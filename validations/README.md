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
6. **Enrich** each failed rule with the loan's actual values for the model fields the
   rule referenced (so you can answer "why did this rule fail?" — not just "which
   rule").

For this demo we use the **`kkr-validations`** rule set
(`42054406-1bac-4e20-a6d5-6f7c22f59fa3`), which is seeded into anubis from
[`germinate/fixtures/anubis/kkr/rule_sets.json`](../../services/germinate/fixtures/anubis/kkr/rule_sets.json)
and contains ~100 KKR-specific rules.

Two scripts walk the flow:

```
run_validation.py        (steps 1-3: query → run → poll)
    └── run_validation.output.json    ← captures executionId
         │
         ▼
get_loan_results.py      (steps 4-6: list summaries → drill into worst → enrich w/ loan values)
    └── get_loan_results.output.json
```

`get_loan_results.py` reads the executionId from `run_validation.output.json` and
auto-picks the loan with the most failed rules to drill into — no IDs to copy by hand.

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
      "record_sk": "loan::final::",
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
  "record_sk": "loan::final::",
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

## Enriching failed rules with loan values

The `/detail` response tells you WHICH model fields each rule referenced (`variables`),
but not what those fields were actually set to on the loan. Yoshi solves this on the
rule-detail view by hitting the loan search API a second time, scoped to that one loan,
with `fields` set to every variable any failed rule mentioned.

The two API calls look like this:

```
GET /validations/record-executions/detail?record_pk=...&record_sk=...&execution_id=...
   → response.failed_rules[*].variables  e.g. ["qualifying_fico", "desk"]

POST /loan-services/loans/search
   {
     "ids": ["<record_pk>|||<record_sk>"],
     "fields": ["qualifying_fico", "desk"],
     "size": 1
   }
   → response.results[0]  e.g. { "qualifying_fico": null, "desk": "Investor" }
```

The OpenSearch document id is the concatenation `{record_pk}|||{record_sk}` (with three
pipes as the separator), so you can target exactly the loan you just drilled into.

`get_loan_results.py` collects the union of every failed rule's `variables`, fires that
search once, and then attaches a `values` object onto each failed rule by walking the
dotted path into the returned loan document:

```json
{
  "rule_id": "ba7f251d-…",
  "validation_rule": "IF @qualifying_fico IS NULL OR (@qualifying_fico >= 300 AND @qualifying_fico <= 850) THEN 'pass' ELSE 'fail'",
  "message": "Origination FICO must be between 300 and 850",
  "variables": ["qualifying_fico"],
  "values": { "qualifying_fico": null }
}
```

Dotted variable names (e.g. `mi_data.mi_coverage`, `property_info.0.property_state`)
traverse nested objects and array indices in the loan document.

## Example: query loans + run validation + poll

[`run_validation.py`](./run_validation.py) — picks the loans to validate with the same
OpenSearch filter shape as `search/query_loans.py`, then runs the `kkr-validations`
rule set against just those loans and polls until done. The matched loan IDs and the
final execution (including its `executionId`) are saved to `run_validation.output.json`.

```python
"""Kick off the KKR loan validations rule set against a filtered subset of loans."""

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
    loan_ids = [hit["veracity_loan_id"] for hit in search_resp.json()["results"]]
    print(f"\nMatched {len(loan_ids)} loan(s)")
    if not loan_ids:
        sys.exit("filter matched zero loans — nothing to validate")

    # Step 2: kick off the validation
    run_body = {
        "modelType": MODEL_TYPE,
        "name": "KKR loan validations — public API demo",
        "ruleSetIds": [RULE_SET_ID],
        "ruleSetCollectionIds": [],
        "recordFilter": {"data_source": DATA_SOURCE, "ids": loan_ids, "filter_groups": []},
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

    save_output(__file__, {"matchedLoans": loan_ids, "execution": execution})


if __name__ == "__main__":
    main()
```

## Example: list loan results + drill into the worst + enrich with loan values

[`get_loan_results.py`](./get_loan_results.py) — reads the executionId from
`run_validation.output.json`, lists every loan's pass/fail/skip counts, drills into the
loan with the most failed rules, then asks the loan search API for the actual values of
every model field any failed rule referenced and attaches those values back onto each
rule.

```python
"""Pull every loan-level result for a validation execution, then drill into the worst."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
LIMIT = 100
# ──────────────────────────────────────────────────────────────────────────────


def load_execution_id() -> str:
    output_path = Path(__file__).with_name("run_validation.output.json")
    if not output_path.exists():
        sys.exit(
            f"{output_path.name} not found — run validations/run_validation.py first."
        )
    data = json.loads(output_path.read_text())
    execution_id = data.get("execution", {}).get("executionId")
    if not execution_id:
        sys.exit(f"{output_path.name} does not contain execution.executionId.")
    return execution_id


def get_nested(doc: dict, dotted_path: str) -> Any:
    """Walk a dotted path through a nested dict/list document; None if any segment is missing."""
    current: Any = doc
    for part in dotted_path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    execution_id = load_execution_id()
    token = get_service_access_token()
    headers = auth_headers(token)

    # Step 4: list every loan-level result
    results_url = f"{base_url}/validations/record-executions"
    results = requests.get(
        results_url,
        params={"execution_id": execution_id, "limit": LIMIT},
        headers=headers,
        timeout=30,
    ).json()

    items = sorted(results["items"], key=lambda r: r["failed_rule_count"], reverse=True)
    print(f"\n{results['count']} loan(s) under execution {execution_id}\n")
    print(f"  {'record_pk':<40}  {'total':>6}  {'passed':>6}  {'failed':>6}  {'skipped':>7}")
    print(f"  {'-' * 40}  {'-' * 6}  {'-' * 6}  {'-' * 6}  {'-' * 7}")
    for r in items:
        print(
            f"  {r['record_pk']:<40}  "
            f"{r['total_rule_count']:>6}  "
            f"{r['passed_rule_count']:>6}  "
            f"{r['failed_rule_count']:>6}  "
            f"{r['skipped_rule_count']:>7}"
        )

    detail = None
    if items and items[0]["failed_rule_count"] > 0:
        worst = items[0]

        # Step 5: drill into the worst-failing loan
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

        # Step 6: enrich each failed rule with the loan's actual field values
        all_vars = sorted({v for r in detail["failed_rules"] for v in r["variables"]})
        loan_doc: dict = {}
        if all_vars:
            enrich_resp = requests.post(
                f"{base_url}/loan-services/loans/search",
                json={
                    "ids": [f"{worst['record_pk']}|||{worst['record_sk']}"],
                    "fields": all_vars,
                    "size": 1,
                },
                headers=headers,
                timeout=30,
            ).json()
            if enrich_resp["results"]:
                loan_doc = enrich_resp["results"][0]

        for r in detail["failed_rules"]:
            r["values"] = {v: get_nested(loan_doc, v) for v in r["variables"]}

        print(f"\nFailed rules for {worst['record_pk']} ({len(detail['failed_rules'])}):")
        for r in detail["failed_rules"]:
            print(f"\n  rule_id:         {r['rule_id']}")
            print(f"  rule_set_name:   {r['rule_set_name']}")
            print(f"  priority:        {r['priority']}")
            print(f"  message:         {r['message']}")
            print(f"  validation_rule: {r['validation_rule']}")
            print(f"  variables:       {r['variables']}")
            print(f"  values:          {r['values']}")

    save_output(__file__, {"results": results, "worstLoanDetail": detail})


if __name__ == "__main__":
    main()
```
