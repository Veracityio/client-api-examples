# Validations

The validations API lets you run rule-set-based checks against records (loans, trades,
collateral, remittances, …) and retrieve per-record results. The high-level flow:

1. **Run** a validation — POST a request specifying which rule sets to apply and which
   records to apply them to. You get back an `Execution` with an `executionId`.
2. **Poll** the execution until status is `completed`.
3. **Retrieve** per-record results for any record covered by the execution.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/validations/executions/{model_type}/run` | Kick off a validation run |
| `GET` | `/validations/executions/{model_type}/{execution_id}` | Read an execution (poll for status + counts) |
| `GET` | `/validations/record-executions/detail` | Per-record rule outcomes |
| `GET` | `/validations/rule-sets/{model_type}` | List available rule sets |

`{model_type}` is one of: `Loan`, `Trade`, `Collateral`, `Remittance`, `RemittanceTransaction`.

## Request: run a validation

`POST /validations/executions/{model_type}/run`

```json
{
  "modelType": "Loan",
  "name": "Q2 ad-hoc check",
  "description": "Manual run against CA loans",
  "ruleSetIds": ["rs-abc123"],
  "ruleSetCollectionIds": [],
  "recordFilter": {
    "data_source": "final",
    "ids": [],
    "filter_groups": [
      {
        "filters": [
          { "field": "subject_property.state", "value": "CA" }
        ]
      }
    ]
  },
  "runReason": "manual",
  "emailNotifications": []
}
```

Notes:
- At least one of `ruleSetIds` or `ruleSetCollectionIds` is required.
- `recordFilter` accepts the same filter-group DSL as the search endpoints
  (see [`../search/README.md`](../search/README.md)). It also accepts a plain list of record
  `ids` to target a specific set of records.
- For `Loan` and `Remittance` model types, `data_source` is required
  (e.g. `final` for loans, `daily` for remittances).

## Response: `Execution`

```json
{
  "executionId": "019577a5-c8f5-7b9e-8b3a-1c2d3e4f5a6b",
  "name": "Q2 ad-hoc check",
  "description": "Manual run against CA loans",
  "modelType": "Loan",
  "ruleSetIds": ["rs-abc123"],
  "ruleSetCollectionIds": [],
  "status": "processing",
  "recordsProcessedCount": 0,
  "failureCount": 0,
  "successCount": 0,
  "runReason": "manual",
  "recordFilter": { "...echoed back..." }
}
```

`status` progresses through `pending` → `processing` → `completed` (or `failed`).

Poll `GET /validations/executions/{model_type}/{execution_id}` to watch progress.

## Request: per-record results

`GET /validations/record-executions/detail?record_pk={pk}&record_sk={sk}&execution_id={id}`

Returns the per-rule outcomes for a single record under a specific execution.

```json
{
  "executionId": "019577a5-c8f5-7b9e-8b3a-1c2d3e4f5a6b",
  "modelType": "Loan",
  "recordPk": "loan::abc-123::",
  "recordSk": "loan::abc-123::final",
  "totalRuleCount": 5,
  "passedRuleCount": 4,
  "failedRuleCount": 1,
  "skippedRuleCount": 0,
  "failedRules": [
    {
      "ruleId": "rule-789",
      "ruleSetId": "rs-abc123",
      "ruleSetName": "CA Compliance",
      "validationRule": "IF @borrower_age >= 18 THEN 'pass'",
      "message": "Borrower age below minimum",
      "outcome": "failed",
      "priority": "High",
      "variables": ["borrower_age"]
    }
  ],
  "passedRules": [],
  "skippedRules": []
}
```

## Example: run a validation and poll until complete

[`run_validation.py`](./run_validation.py)

```python
"""Kick off a Loan validation run, then poll until it completes."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token


def main() -> None:
    base_url = env("VERACITY_BASE_URL")
    token = get_service_access_token()
    headers = auth_headers(token)

    rule_set_id = env("VALIDATIONS_RULE_SET_ID")
    loan_ids = [s for s in os.environ.get("VALIDATIONS_LOAN_IDS", "").split(",") if s]

    request_body = {
        "modelType": "Loan",
        "name": "Public API client demo",
        "description": "Kicked off from api_docs/validations/run_validation.py",
        "ruleSetIds": [rule_set_id],
        "ruleSetCollectionIds": [],
        "recordFilter": {
            "data_source": "final",
            "ids": loan_ids,
            "filter_groups": [],
        },
        "runReason": "manual",
        "emailNotifications": [],
    }

    run_url = f"{base_url}/validations/executions/Loan/run"
    dump(f"POST {run_url}", request_body)
    response = requests.post(run_url, json=request_body, headers=headers, timeout=60)
    response.raise_for_status()
    execution = response.json()
    dump("Initial execution", execution)

    execution_id = execution["executionId"]

    # ─── Poll until terminal ──────────────────────────────────────────────
    poll_url = f"{base_url}/validations/executions/Loan/{execution_id}"
    while True:
        execution = requests.get(poll_url, headers=headers, timeout=30).json()
        print(
            f"  status={execution['status']:>10}  "
            f"processed={execution['recordsProcessedCount']:>5}  "
            f"failures={execution['failureCount']:>5}"
        )
        if execution["status"] in ("completed", "failed"):
            break
        time.sleep(3)

    dump("Final execution", execution)
    save_output(__file__, execution)


if __name__ == "__main__":
    main()
```

## Example: fetch per-record results

[`get_record_results.py`](./get_record_results.py)

```python
"""Fetch the per-rule outcomes for a single record under a specific execution."""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token


def main() -> None:
    base_url = env("VERACITY_BASE_URL")
    token = get_service_access_token()
    headers = auth_headers(token)

    params = {
        "record_pk": env("VALIDATIONS_RECORD_PK"),
        "record_sk": env("VALIDATIONS_RECORD_SK"),
        "execution_id": env("VALIDATIONS_EXECUTION_ID"),
    }

    url = f"{base_url}/validations/record-executions/detail"
    dump(f"GET {url}", params)

    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    body = response.json()

    dump("Response", body)
    save_output(__file__, body)


if __name__ == "__main__":
    main()
```
