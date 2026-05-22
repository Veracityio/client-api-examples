"""Upload a data file against an existing published workbook.

A data upload pushes actual records (loans, exceptions, …) through the workbook's mapping
rules. The workbook must already be published — see create_workbook.py for that flow.

Flow:
    1. POST {base_url}/data-services/imports/data
       → returns a presigned PUT URL plus a runId for tracking
    2. PUT  <presigned url> with the file body
       headers:
         Content-Type: application/octet-stream
         x-amz-server-side-encryption: AES256
    3. GET  {base_url}/data-services/imports/data/{runId}/status
       → poll every few seconds until status is "Completed" or "Failed"
    4. GET  {base_url}/data-services/imports/data/{runId}/metadata
       → final row counts, step timings
    5. GET  {base_url}/data-services/imports/data/{runId}/results/file
       → presigned download URL for the consolidated mapped results CSV

Configure the upload by editing the GLOBAL CONFIG block below, then:

    python data_import/upload_data.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
# Edit these per-upload. Everything else (credentials, base URL) comes from environment
# variables loaded from api_docs/.env.

FILE_PATH = "MainPositionSubset.xlsx"  # at the root of api_docs/
WORKBOOK_NAME = "MainPosition"    # Must reference a workbook published via create_workbook.py
WORKBOOK_VERSION = "1"            # Published workbook version
DATA_SOURCE = "final"             # e.g. "final" for loans, "daily" for remittances
POLL_INTERVAL_SECONDS = 3         # How often to poll the status endpoint
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    base_url = env("VERACITY_BASE_URL")
    file_path = Path(FILE_PATH)
    file_size = file_path.stat().st_size

    token = get_service_access_token()
    headers = auth_headers(token)

    # ─── Step 1: initiate the data upload ───────────────────────────────────────
    # The `workbooks` array lets you fan one upload out across multiple workbook
    # templates if needed. The common case is a single entry, as shown here.
    initiate_body = {
        "workbooks": [
            {
                "workbookName": WORKBOOK_NAME,
                "workbookVersion": WORKBOOK_VERSION,
                "dataSource": DATA_SOURCE,
            }
        ],
        "fileName": file_path.name,
        "fileSize": file_size,
        "simpleUpload": True,
    }

    initiate_url = f"{base_url}/data-services/imports/data"
    dump(f"POST {initiate_url}", initiate_body)

    initiate = requests.post(initiate_url, json=initiate_body, headers=headers, timeout=60)
    initiate.raise_for_status()
    initiate_response = initiate.json()
    dump("Initiate response", initiate_response)

    run_id = initiate_response["runId"]

    # ─── Step 2: PUT the file body directly to S3 ───────────────────────────────
    s3_headers = {
        "Content-Type": "application/octet-stream",
        "x-amz-server-side-encryption": "AES256",
    }
    presigned_url = initiate_response["url"]
    print(f"\nPUT {presigned_url[:80]}...  ({file_size} bytes)")

    with file_path.open("rb") as f:
        put = requests.put(presigned_url, data=f, headers=s3_headers, timeout=300)
    put.raise_for_status()
    print(f"S3 PUT returned {put.status_code}")

    # ─── Step 3: poll for completion ────────────────────────────────────────────
    # The pipeline runs asynchronously after the file lands in S3. Status values are
    # Pending, Processing, Completed, or Failed. There is no webhook.
    status_url = f"{base_url}/data-services/imports/data/{run_id}/status"
    print(f"\nPolling {status_url}")

    while True:
        status_resp = requests.get(status_url, headers=headers, timeout=30)
        status_resp.raise_for_status()
        status = status_resp.json()
        print(f"  status = {status['status']}")
        if status["status"] in ("Completed", "Failed"):
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    if status["status"] != "Completed":
        sys.exit(f"data upload failed: {status}")

    # ─── Step 4: fetch the full metadata ────────────────────────────────────────
    # Step timings, row counts, success vs failure breakdown, etc.
    metadata_url = f"{base_url}/data-services/imports/data/{run_id}/metadata"
    metadata = requests.get(metadata_url, headers=headers, timeout=30).json()
    dump("Metadata", metadata)

    # ─── Step 5: get a presigned download URL for the consolidated results ──────
    results_url = f"{base_url}/data-services/imports/data/{run_id}/results/file"
    results = requests.get(results_url, headers=headers, timeout=30).json()
    dump("Results download URL", results)

    save_output(__file__, {
        "runId": run_id,
        "initiate": initiate_response,
        "finalStatus": status,
        "metadata": metadata,
        "resultsFile": results,
    })


if __name__ == "__main__":
    main()
