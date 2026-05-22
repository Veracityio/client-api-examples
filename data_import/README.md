# Data Import

Importing data into Veracity is a two-phase process:

1. **Create a workbook** — define the template (file + mapping rules) that describes how
   a source file's columns map to Veracity fields. Done once per workbook, updated when
   the schema changes. See [`create_workbook.py`](./create_workbook.py).
2. **Upload data** — push actual records (loans, …) through a published workbook. Done
   every time you have a new file to import.
   See [`upload_data.py`](./upload_data.py).

All Veracity endpoints below require the standard `Authorization` + `x-api-key` headers
(see [`../auth`](../auth)).

---

## Phase 1 — Create a workbook

Four sequential calls: upload the template file, register mapping rules, publish the
version.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  1. POST /data-services/imports/workbooks/upload                         │
│       → { expiration, url, workbookName }                                │
│                                                                          │
│  2. PUT  <presigned url>                                                 │
│       headers:                                                           │
│         Content-Type: application/octet-stream                           │
│         x-amz-server-side-encryption: AES256                             │
│       body: the template file bytes                                      │
│                                                                          │
│  3. POST /data-services/imports/workbook/{workbookName}/mappings         │
│       ?workbookVersion=1                                                 │
│       body: { mappings: ["SET @x = @y", ...] }                           │
│                                                                          │
│  4. POST /data-services/imports/workbooks/{workbookName}/publish         │
│       ?workbookVersion=1                                                 │
│       → { workbookName, workbookVersion, isPublished: true }             │
└──────────────────────────────────────────────────────────────────────────┘
```

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/data-services/imports/workbooks/upload` | Initiate upload, receive presigned PUT URL |
| `POST` | `/data-services/imports/workbook/{workbook_name}/mappings` | Store mapping rules for a workbook version |
| `POST` | `/data-services/imports/workbooks/{workbook_name}/publish` | Publish a workbook version |

### Step 1 — Initiate template upload

`POST /data-services/imports/workbooks/upload`

```json
{
  "workbookName": "MainPosition",
  "fileName": "MainPositionSubset.xlsx",
  "fileSize": 1048576,
  "dataKind": "Loan",
  "vendorName": null,
  "simpleUpload": true
}
```

| Field | Required | Description |
| --- | --- | --- |
| `workbookName` | yes | Logical name to register this workbook under |
| `fileName` | yes | Original filename, including extension (`.xlsx` or `.csv`) |
| `fileSize` | yes (for `simpleUpload: false`) | Size in bytes |
| `dataKind` | yes | Model type: `Loan`, `Exception`, `Remittance`, etc. |
| `vendorName` | no | External vendor name, or `null` |
| `simpleUpload` | no (defaults `true`) | When `true`, returns a single presigned PUT URL. When `false`, returns multipart upload metadata |
| `normalizeColumnNames` | no (defaults `true`) | Lowercase column names, replace spaces with underscores |

Response:

```json
{
  "expiration": 3600,
  "url": "https://s3.amazonaws.com/bucket/.../MainPositionSubset.xlsx?X-Amz-Signature=...",
  "workbookName": "MainPosition"
}
```

### Step 2 — Upload to S3

PUT the raw template file bytes directly to the presigned URL. Two S3 headers are
required:

```
Content-Type: application/octet-stream
x-amz-server-side-encryption: AES256
```

The presigned URL carries its own signature; do **not** send the Veracity auth headers
to S3. A 200 response means the upload succeeded.

### Step 3 — Set mappings

`POST /data-services/imports/workbook/{workbook_name}/mappings?workbookVersion=1`

```json
{
  "mappings": [
    "SET @tenant_loan_id = @lms_loan_id",
    "SET @seller_name = @seller_code",
    "SET @origination_dt = @orig_date"
  ]
}
```

The right-hand side references a source column from your file; the left-hand side names
a Veracity field.

| Param | Required | Description |
| --- | --- | --- |
| `workbookVersion` (query) | no (defaults `"1"`) | Workbook version to attach mappings to |

The API stores mappings in blocks of up to **3000 per request**. For larger mapping sets,
call the endpoint multiple times — each call appends a new block.

Response:

```json
{
  "workbook_name": "MainPosition",
  "workbook_version": "1",
  "block_number": "1",
  "mappings_received": 382
}
```

### Step 4 — Publish

`POST /data-services/imports/workbooks/{workbook_name}/publish?workbookVersion=1`

No request body. Locks in the template file + mappings combination as ready-to-use for
data uploads.

| Param | Required | Description |
| --- | --- | --- |
| `workbookVersion` (query) | no (defaults `"1"`) | Workbook version to publish |

Response:

```json
{
  "workbookName": "MainPosition",
  "workbookVersion": "1",
  "isPublished": true
}
```

### Example

[`create_workbook.py`](./create_workbook.py) — end-to-end (upload → mappings → publish),
configured via global constants at the top of the file. Mapping rules are pulled from
[`../mappings.py`](../mappings.py).

```python
"""Create a workbook end-to-end: upload the template file, set mappings, publish."""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token
from mappings import main_position_mappings

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
FILE_PATH = "MainPositionSubset.xlsx"
WORKBOOK_NAME = "MainPosition"
WORKBOOK_VERSION = "1"
DATA_KIND = "Loan"
VENDOR_NAME = None
MAPPINGS = main_position_mappings
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    file_path = Path(FILE_PATH)
    file_size = file_path.stat().st_size

    token = get_service_access_token()
    headers = auth_headers(token)

    # Step 1: initiate template upload
    initiate_body = {
        "workbookName": WORKBOOK_NAME,
        "fileName": file_path.name,
        "fileSize": file_size,
        "dataKind": DATA_KIND,
        "vendorName": VENDOR_NAME,
        "simpleUpload": True,
    }
    initiate_url = f"{base_url}/data-services/imports/workbooks/upload"
    initiate = requests.post(initiate_url, json=initiate_body, headers=headers, timeout=60)
    initiate.raise_for_status()
    initiate_response = initiate.json()
    dump("Initiate response", initiate_response)

    # Step 2: PUT to S3
    s3_headers = {
        "Content-Type": "application/octet-stream",
        "x-amz-server-side-encryption": "AES256",
    }
    with file_path.open("rb") as f:
        put = requests.put(initiate_response["url"], data=f, headers=s3_headers, timeout=300)
    put.raise_for_status()

    # Step 3: set mappings
    mappings_url = f"{base_url}/data-services/imports/workbook/{WORKBOOK_NAME}/mappings"
    mappings_resp = requests.post(
        mappings_url,
        params={"workbookVersion": WORKBOOK_VERSION},
        json={"mappings": MAPPINGS},
        headers=headers,
        timeout=60,
    )
    mappings_resp.raise_for_status()
    dump("Mappings response", mappings_resp.json())

    # Step 4: publish
    publish_url = f"{base_url}/data-services/imports/workbooks/{WORKBOOK_NAME}/publish"
    publish_resp = requests.post(
        publish_url,
        params={"workbookVersion": WORKBOOK_VERSION},
        headers=headers,
        timeout=60,
    )
    publish_resp.raise_for_status()
    dump("Publish response", publish_resp.json())

    save_output(__file__, {
        "initiate": initiate_response,
        "mappings": mappings_resp.json(),
        "publish": publish_resp.json(),
    })


if __name__ == "__main__":
    main()
```

---

## Phase 2 — Upload data

Once a workbook is published, you can push data files at it. The pipeline runs
asynchronously: the file lands in S3 and the backend takes over. Track processing
status in the Veracity UI.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  1. POST /data-services/imports/data                                     │
│       → { multipart, expiration, runId, url }                            │
│                                                                          │
│  2. PUT  <presigned url>                                                 │
│       headers:                                                           │
│         Content-Type: application/octet-stream                           │
│         x-amz-server-side-encryption: AES256                             │
│       body: the data file bytes                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/data-services/imports/data` | Initiate data upload, receive presigned PUT URL + `runId` |

### Step 1 — Initiate data upload

`POST /data-services/imports/data`

```json
{
  "workbooks": [
    { "workbookName": "MainPosition", "workbookVersion": "1", "dataSource": "final" }
  ],
  "fileName": "loans.xlsx",
  "fileSize": 1048576,
  "simpleUpload": true
}
```

| Field | Required | Description |
| --- | --- | --- |
| `workbooks` | yes | One or more workbook references this file should be mapped against |
| `workbooks[].workbookName` | yes | Name of a published workbook |
| `workbooks[].workbookVersion` | no (defaults `"1"`) | Published version |
| `workbooks[].dataSource` | yes | e.g. `final` for loans, `daily` for remittances |
| `fileName` | yes | Original filename, including extension |
| `fileSize` | yes (for `simpleUpload: false`) | Size in bytes |
| `simpleUpload` | no (defaults `true`) | When `false`, returns multipart upload metadata |

Response:

```json
{
  "multipart": false,
  "expiration": 3600,
  "runId": "run-abc123",
  "url": "https://s3.amazonaws.com/.../loans.xlsx?X-Amz-Signature=..."
}
```

Keep the `runId` — every subsequent call uses it as the path parameter.

### Step 2 — Upload to S3

Same S3 PUT pattern as the workbook upload — two required headers, no Veracity auth:

```
Content-Type: application/octet-stream
x-amz-server-side-encryption: AES256
```

Once S3 returns 200, the upload has been handed off to the pipeline. Track processing
status from the Veracity UI.

### Example

[`upload_data.py`](./upload_data.py) — initiate + S3 PUT, configured via global
constants at the top of the file.

```python
"""Upload a data file against an existing published workbook."""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
FILE_PATH = "MainPositionSubset.xlsx"
WORKBOOK_NAME = "MainPosition"
WORKBOOK_VERSION = "1"
DATA_SOURCE = "final"
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    file_path = Path(FILE_PATH)
    file_size = file_path.stat().st_size

    token = get_service_access_token()
    headers = auth_headers(token)

    # Step 1: initiate data upload
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
    initiate = requests.post(initiate_url, json=initiate_body, headers=headers, timeout=60)
    initiate.raise_for_status()
    initiate_response = initiate.json()
    dump("Initiate response", initiate_response)

    # Step 2: PUT to S3
    s3_headers = {
        "Content-Type": "application/octet-stream",
        "x-amz-server-side-encryption": "AES256",
    }
    with file_path.open("rb") as f:
        put = requests.put(initiate_response["url"], data=f, headers=s3_headers, timeout=300)
    put.raise_for_status()

    save_output(__file__, initiate_response)


if __name__ == "__main__":
    main()
```

---

## For large files

For files large enough that a single PUT isn't practical, pass `simpleUpload: false` on
either initiate call. The response will instead carry `uploadId`, `partSize`, `numParts`,
and per-part presigned URLs, and you'll need a second call to either
`/data-services/imports/workbooks/upload/complete` (workbook templates) or
`/data-services/imports/data/complete` (data files) with the `{PartNumber, ETag}` list
after PUT-ing each chunk. Ask us if you need to walk through that flow.
