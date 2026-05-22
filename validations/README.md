# Validations

The validations API lets you run rule-set-based checks against records (loans, trades,
collateral, remittances, …) and retrieve per-record results. The high-level flow:

1. **Pick which records to validate** — typically by running an OpenSearch query against
   the loan index (same DSL as `query_loans.py`) to collect a list of `veracity_loan_id`
   values.
2. **Run** a validation — POST a request specifying which rule sets to apply and which
   records (`recordFilter.ids`) to apply them to. You get back an `Execution` with an
   `executionId`.
3. **Poll** the execution until status is `completed`.
4. **List** per-loan summaries for the execution (pass / fail / skip counts).
5. **Drill into** any loan with failures to see the per-rule outcomes.

For this demo we use the **`kkr-validations`** rule set
(`42054406-1bac-4e20-a6d5-6f7c22f59fa3`), which is seeded into anubis from
[`germinate/fixtures/anubis/kkr/rule_sets.json`](../../services/germinate/fixtures/anubis/kkr/rule_sets.json)
and contains ~100 KKR-specific rules.

[`run_validation.py`](./run_validation.py) walks all five steps in a single run, so
there is no need to copy IDs between scripts.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/validations/executions/{model_type}/run` | Kick off a validation run |
| `GET` | `/validations/executions/{model_type}/{execution_id}` | Read an execution (poll for status + counts) |
| `GET` | `/validations/record-executions` | List per-loan summaries for an execution |
| `GET` | `/validations/record-executions/detail` | Per-rule outcomes for a single loan |
| `GET` | `/validations/rule-sets/{model_type}` | List available rule sets |

`{model_type}` is one of: `Loan`, `Trade`, `Collateral`, `Remittance`, `RemittanceTransaction`.

## Request: run a validation

`POST /validations/executions/Loan/run`

```json
{
  "modelType": "Loan",
  "name": "KKR loan validations — public API demo",
  "description": "Kicked off from api_docs/validations/run_validation.py",
  "ruleSetIds": ["42054406-1bac-4e20-a6d5-6f7c22f59fa3"],
  "ruleSetCollectionIds": [],
  "recordFilter": {
    "data_source": "final",
    "ids": [],
    "filter_groups": []
  },
  "runReason": "manual",
  "emailNotifications": []
}
```

Notes:
- At least one of `ruleSetIds` or `ruleSetCollectionIds` is required.
- `recordFilter` accepts the same filter-group DSL as the search endpoints
  (see [`../search/README.md`](../search/README.md)). It also accepts a plain list of record
  `ids` to target a specific set of records. An empty filter + empty `ids` runs against
  every loan in the data source.
- For `Loan` and `Remittance` model types, `data_source` is required
  (e.g. `final` for loans, `daily` for remittances).

## Response: `Execution`

```json
{
  "executionId": "019577a5-c8f5-7b9e-8b3a-1c2d3e4f5a6b",
  "name": "KKR loan validations — public API demo",
  "description": "Kicked off from api_docs/validations/run_validation.py",
  "modelType": "Loan",
  "ruleSetIds": ["42054406-1bac-4e20-a6d5-6f7c22f59fa3"],
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

Poll `GET /validations/executions/Loan/{execution_id}` to watch progress.

## Example KKR rules

A handful of the rules that will fire from the `kkr-validations` rule set:

| Rule | Validates |
| --- | --- |
| `qualifying_fico` range | Origination FICO is between 300 and 850 (when present) |
| `qualifying_fico` required by desk | Origination FICO is required unless `desk` is `RPL` or `NPL` |
| MI data consistency | When `has_pmi_flg` is false, `mi_data.mi_coverage` / `mi_company` / `mi_type` must all be null |
| Total borrower count | `total_borrowers_ct` must be present and `> 0` |
| Rate drift on static loans | For non-`NPL`/non-`RPL`, non-modified, non-ARM, non-step loans, the absolute difference between current and origination rate must not exceed 0.125% |

Each rule references real KKR fields from the position mappings — the same fields you
see in [`../mappings.py`](../mappings.py).

## Request: list all loan results for an execution

`GET /validations/record-executions?execution_id={id}&limit={n}`

Returns one summary row per loan that was validated under the execution, with the
pass/fail/skip counts at the rule level. This is the same listing yoshi shows on the
execution detail page.

```json
{
  "count": 9,
  "items": [
    {
      "execution_id": "019577a5-c8f5-7b9e-8b3a-1c2d3e4f5a6b",
      "model_type": "Loan",
      "record_pk": "loan::abc-123::",
      "record_sk": "loan::abc-123::final",
      "total_rule_count": 101,
      "passed_rule_count": 92,
      "failed_rule_count": 8,
      "skipped_rule_count": 1
    }
  ],
  "last_evaluated_key": null
}
```

| Query param | Required | Description |
| --- | --- | --- |
| `execution_id` | no | Filter to one execution. Omit to list across all executions. |
| `record_pk` / `record_sk` | no | Narrow to a single record's results. |
| `limit` | no | Page size cap. |

> **Heads up:** both this listing endpoint and the `/detail` endpoint below read from
> Parquet on S3 (partitioned by `execution_id`). If you pass an execution_id that the
> backend never ran — or one whose Parquet hasn't landed yet — you'll get a
> `_duckdb.IOException` about "No files found". Always use an `execution_id` that came
> back from a real `run_validation.py` run.

## Request: drill into a single loan's per-rule outcomes

`GET /validations/record-executions/detail?record_pk={pk}&record_sk={sk}&execution_id={id}`

Returns the full per-rule outcomes (passed / failed / skipped lists with the rule
definition, message, priority, and the model fields the rule referenced) for a single
loan under a specific execution. Use this to inspect WHY a loan with failures in the
listing above failed.

```json
{
  "execution_id": "019577a5-c8f5-7b9e-8b3a-1c2d3e4f5a6b",
  "model_type": "Loan",
  "record_pk": "loan::abc-123::",
  "record_sk": "loan::abc-123::final",
  "total_rule_count": 101,
  "passed_rule_count": 92,
  "failed_rule_count": 8,
  "skipped_rule_count": 1,
  "failed_rules": [
    {
      "rule_id": "ba7f251d-5d66-46ec-b50a-0defde163a00",
      "rule_set_id": "42054406-1bac-4e20-a6d5-6f7c22f59fa3",
      "rule_set_name": "kkr-validations",
      "validation_rule": "IF @qualifying_fico IS NULL OR (@qualifying_fico >= 300 AND @qualifying_fico <= 850) THEN 'pass' ELSE 'fail'",
      "message": "Origination FICO must be between 300 and 850",
      "outcome": "failed",
      "priority": "High",
      "variables": ["qualifying_fico"]
    }
  ],
  "passed_rules": [],
  "skipped_rules": []
}
```

## Example: end-to-end

[`run_validation.py`](./run_validation.py) walks every step in a single run — it picks
the loans to validate with the same filter shape as `search/query_loans.py`, kicks off
the `kkr-validations` rule set, polls until done, lists per-loan summaries, and drills
into the worst-failing loan to dump every failed rule.

```python
"""Run the KKR loan validations rule set end-to-end against a filtered subset of loans."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
MODEL_TYPE = "Loan"
DATA_SOURCE = "final"
RULE_SET_ID = "42054406-1bac-4e20-a6d5-6f7c22f59fa3"   # kkr-validations
POLL_INTERVAL_SECONDS = 3
RESULTS_LIMIT = 100

LOAN_FILTER = {
    "filter_groups": [
        {
            "filters": [
                {"field": "desk", "value": "RPL"},
            ]
        }
    ],
}
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    token = get_service_access_token()
    headers = auth_headers(token)

    # Step 1: find the loans the filter matches
    search_body = {
        **LOAN_FILTER,
        "fields": ["veracity_loan_id", "tenant_loan_id"],
        "size": 1000,
        "page": 0,
    }
    search_url = f"{base_url}/loan-services/loans/search"
    search_resp = requests.post(search_url, json=search_body, headers=headers, timeout=60)
    search_resp.raise_for_status()
    search_response = search_resp.json()

    loan_ids = [hit["veracity_loan_id"] for hit in search_response["results"]]
    print(f"\nMatched {len(loan_ids)} loan(s)")
    if not loan_ids:
        sys.exit("filter matched zero loans — nothing to validate")

    # Step 2: kick off the validation
    run_body = {
        "modelType": MODEL_TYPE,
        "name": "KKR loan validations — public API demo",
        "description": "Kicked off from api_docs/validations/run_validation.py",
        "ruleSetIds": [RULE_SET_ID],
        "ruleSetCollectionIds": [],
        "recordFilter": {
            "data_source": DATA_SOURCE,
            "ids": loan_ids,
            "filter_groups": [],
        },
        "runReason": "manual",
        "emailNotifications": [],
    }
    run_url = f"{base_url}/validations/executions/{MODEL_TYPE}/run"
    run_resp = requests.post(run_url, json=run_body, headers=headers, timeout=60)
    run_resp.raise_for_status()
    execution = run_resp.json()
    execution_id = execution["executionId"]

    # Step 3: poll until terminal
    poll_url = f"{base_url}/validations/executions/{MODEL_TYPE}/{execution_id}"
    while True:
        execution = requests.get(poll_url, headers=headers, timeout=30).json()
        if execution["status"] in ("completed", "failed"):
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    # Step 4: list per-loan summaries
    results_url = f"{base_url}/validations/record-executions"
    results = requests.get(
        results_url,
        params={"execution_id": execution_id, "limit": RESULTS_LIMIT},
        headers=headers,
        timeout=30,
    ).json()
    items = sorted(results["items"], key=lambda r: r["failed_rule_count"], reverse=True)

    # Step 5: drill into the worst-failing loan
    detail = None
    if items and items[0]["failed_rule_count"] > 0:
        worst = items[0]
        detail_url = f"{base_url}/validations/record-executions/detail"
        detail = requests.get(
            detail_url,
            params={
                "record_pk": worst["record_pk"],
                "record_sk": worst["record_sk"],
                "execution_id": execution_id,
            },
            headers=headers,
            timeout=30,
        ).json()

    save_output(__file__, {
        "matchedLoans": loan_ids,
        "execution": execution,
        "results": results,
        "worstLoanDetail": detail,
    })


if __name__ == "__main__":
    main()
```
