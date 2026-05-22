"""Upload a data file against an existing published workbook.

A data upload pushes actual records (loans, …) through the workbook's mapping rules.
The workbook must already be published — see create_workbook.py for that flow.

Flow:
    1. POST {base_url}/data-services/imports/data
       → returns a presigned PUT URL plus a runId for tracking
    2. PUT  <presigned url> with the file body
       headers:
         Content-Type: application/octet-stream
         x-amz-server-side-encryption: AES256

Processing status is visible in the Veracity UI after the upload returns.

Configure the upload by editing the GLOBAL CONFIG block below, then:

    python data_import/upload_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
# Edit these per-upload. Everything else (credentials, base URL) comes from environment
# variables loaded from api_docs/.env.

FILE_PATH = "MainPositionSubset.xlsx"  # at the root of api_docs/
WORKBOOK_NAME = "MainPositionLateNight"  # Must reference a workbook published via create_workbook.py
WORKBOOK_VERSION = "1"  # Published workbook version
DATA_SOURCE = "final"  # e.g. "final" for loans, "daily" for remittances
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
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

    initiate = requests.post(
        initiate_url, json=initiate_body, headers=headers, timeout=60
    )
    initiate.raise_for_status()
    initiate_response = initiate.json()
    dump("Initiate response", initiate_response)

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
    print("Upload accepted. Track processing status in the Veracity UI.")

    save_output(__file__, initiate_response)


if __name__ == "__main__":
    main()
