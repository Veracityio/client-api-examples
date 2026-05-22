"""Create a workbook end-to-end: upload the template file, set mappings, publish.

A workbook is the template that translates a source file's columns into Veracity fields.
Once a workbook is published, it can be referenced by data uploads (see upload_data.py).

Flow:
    1. POST {base_url}/data-services/imports/workbooks/upload
       → returns a presigned PUT URL for the workbook template file
    2. PUT  <presigned url> with the file body
       headers:
         Content-Type: application/octet-stream
         x-amz-server-side-encryption: AES256
    3. POST {base_url}/data-services/imports/workbook/{workbookName}/mappings
       → store the mapping rules that translate source columns to Veracity fields
    4. POST {base_url}/data-services/imports/workbooks/{workbookName}/publish
       → mark the workbook version as ready for data uploads

Configure the workbook by editing the GLOBAL CONFIG block below, then:

    python data_import/create_workbook.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token
from mappings import main_position_mappings

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
# Edit these per-workbook. Everything else (credentials, base URL) comes from environment
# variables loaded from api_docs/.env.

FILE_PATH = "MainPositionSubset.xlsx"  # at the root of api_docs/
WORKBOOK_NAME = "MainPosition1"  # Logical name to register this workbook under
WORKBOOK_VERSION = "1"  # Version to write — leave at "1" for a new workbook
DATA_KIND = "Loan"  # ModelType: Loan | Exception | Remittance | ...
VENDOR_NAME = None  # Optional: name of the external vendor, or None
MAPPINGS = main_position_mappings  # SET statements from api_docs/mappings.py
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    file_path = Path(FILE_PATH)
    file_size = file_path.stat().st_size

    # Exchange CLIENT_ID / CLIENT_SECRET for a bearer token. The returned auth_headers
    # carry both Authorization and the API Gateway x-api-key header.
    token = get_service_access_token()
    headers = auth_headers(token)

    # ─── Step 1: ask Veracity for a presigned S3 PUT URL ────────────────────────
    initiate_body = {
        "workbookName": WORKBOOK_NAME,
        "fileName": file_path.name,
        "fileSize": file_size,
        "dataKind": DATA_KIND,
        "vendorName": VENDOR_NAME,
        # simpleUpload defaults to true server-side; we include it here for clarity.
        "simpleUpload": True,
    }

    initiate_url = f"{base_url}/data-services/imports/workbooks/upload"
    dump(f"POST {initiate_url}", initiate_body)

    initiate = requests.post(
        initiate_url, json=initiate_body, headers=headers, timeout=60
    )
    initiate.raise_for_status()
    initiate_response = initiate.json()
    dump("Initiate response", initiate_response)

    # ─── Step 2: PUT the file body directly to S3 ───────────────────────────────
    # The presigned URL does NOT take the Veracity auth headers — it carries its own
    # signature in the query string. But the bucket policy requires the SSE header and
    # we send a generic binary Content-Type.
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

    # ─── Step 3: store the mapping rules ────────────────────────────────────────
    # The mappings translate source columns (right-hand side of each `SET`) into Veracity
    # fields (left-hand side). The API accepts up to 3000 mappings per request.
    mappings_url = f"{base_url}/data-services/imports/workbook/{WORKBOOK_NAME}/mappings"
    dump(
        f"POST {mappings_url}?workbookVersion={WORKBOOK_VERSION}",
        {"mappings": f"<{len(MAPPINGS)} SET statements>"},
    )

    mappings_resp = requests.post(
        mappings_url,
        params={"workbookVersion": WORKBOOK_VERSION},
        json={"mappings": MAPPINGS},
        headers=headers,
        timeout=60,
    )
    mappings_resp.raise_for_status()
    mappings_response = mappings_resp.json()
    dump("Mappings response", mappings_response)

    # ─── Step 4: publish the workbook version ───────────────────────────────────
    # Until the workbook is published, it cannot be used to import data. Publishing
    # locks in the file + mappings combination as ready-to-use.
    publish_url = f"{base_url}/data-services/imports/workbooks/{WORKBOOK_NAME}/publish"
    dump(f"POST {publish_url}?workbookVersion={WORKBOOK_VERSION}", {})

    publish_resp = requests.post(
        publish_url,
        params={"workbookVersion": WORKBOOK_VERSION},
        headers=headers,
        timeout=60,
    )
    publish_resp.raise_for_status()
    publish_response = publish_resp.json()
    dump("Publish response", publish_response)

    save_output(
        __file__,
        {
            "initiate": initiate_response,
            "mappings": mappings_response,
            "publish": publish_response,
        },
    )


if __name__ == "__main__":
    main()
