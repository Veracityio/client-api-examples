"""Run the KKR loan validations rule set end-to-end against a filtered subset of loans.

This script walks the entire validation lifecycle in a single run:

    1. POST {base_url}/loan-services/loans/search
       → use a filter (same DSL as search/query_loans.py) to pick which loans to validate
    2. POST {base_url}/validations/executions/Loan/run
       → kick off the rule set against just those loans
    3. GET  {base_url}/validations/executions/Loan/{execution_id}
       → poll until status is "completed" or "failed"
    4. GET  {base_url}/validations/record-executions?execution_id={id}
       → list every loan that was validated with its pass/fail/skip counts
    5. GET  {base_url}/validations/record-executions/detail
       → drill into the loan with the most failures and dump every failed rule

The rule set ID below is `kkr-validations` — KKR's seeded rule set in anubis, defined in
germinate at fixtures/anubis/kkr/rule_sets.json and fixtures/anubis/kkr/rules.json. It
evaluates ~100 KKR-specific rules (FICO ranges, desk-based exemptions, MI consistency,
rate drift on static loans, etc.).

Configure by editing the GLOBAL CONFIG block below, then:

    python validations/run_validation.py
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
# Edit these per-run. Everything else (credentials, base URL) comes from environment
# variables loaded from api_docs/.env.

MODEL_TYPE = "Loan"                                              # which Veracity model to validate
DATA_SOURCE = "final"                                            # required for Loan / Remittance
RULE_SET_ID = "42054406-1bac-4e20-a6d5-6f7c22f59fa3"             # kkr-validations
POLL_INTERVAL_SECONDS = 3
RESULTS_LIMIT = 100                                              # max loans to list under the execution

# Same OpenSearch filter shape used in search/query_loans.py — pick which loans to
# validate. Leave `filter_groups` empty to validate every loan in the data source.
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

    # ─── Step 1: find the loans the filter matches ──────────────────────────────
    search_body = {
        **LOAN_FILTER,
        "fields": ["veracity_loan_id", "tenant_loan_id"],
        "size": 1000,
        "page": 0,
    }
    search_url = f"{base_url}/loan-services/loans/search"
    dump(f"POST {search_url}", search_body)

    search_resp = requests.post(search_url, json=search_body, headers=headers, timeout=60)
    search_resp.raise_for_status()
    search_response = search_resp.json()

    loan_ids = [hit["veracity_loan_id"] for hit in search_response["results"]]
    print(f"\nMatched {len(loan_ids)} loan(s):")
    for hit in search_response["results"]:
        print(f"  veracity_loan_id={hit['veracity_loan_id']}  tenant_loan_id={hit.get('tenant_loan_id')}")

    if not loan_ids:
        sys.exit("filter matched zero loans — nothing to validate")

    # ─── Step 2: kick off the validation against those loans ────────────────────
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
    dump(f"POST {run_url}", run_body)
    run_resp = requests.post(run_url, json=run_body, headers=headers, timeout=60)
    run_resp.raise_for_status()
    execution = run_resp.json()
    dump("Initial execution", execution)
    execution_id = execution["executionId"]

    # ─── Step 3: poll until terminal ────────────────────────────────────────────
    poll_url = f"{base_url}/validations/executions/{MODEL_TYPE}/{execution_id}"
    print(f"\nPolling {poll_url}")
    while True:
        execution = requests.get(poll_url, headers=headers, timeout=30).json()
        print(
            f"  status={execution['status']:>10}  "
            f"processed={execution['recordsProcessedCount']:>5}  "
            f"failures={execution['failureCount']:>5}"
        )
        if execution["status"] in ("completed", "failed"):
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    dump("Final execution", execution)

    # ─── Step 4: list every loan-level result ───────────────────────────────────
    results_url = f"{base_url}/validations/record-executions"
    results_params = {"execution_id": execution_id, "limit": RESULTS_LIMIT}
    dump(f"GET {results_url}", results_params)
    results_resp = requests.get(results_url, params=results_params, headers=headers, timeout=30)
    results_resp.raise_for_status()
    results = results_resp.json()

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

    # ─── Step 5: drill into the worst-failing loan ──────────────────────────────
    worst = max(items, key=lambda r: r["failed_rule_count"], default=None)
    detail: dict | None = None
    if worst and worst["failed_rule_count"] > 0:
        detail_url = f"{base_url}/validations/record-executions/detail"
        detail_params = {
            "record_pk": worst["record_pk"],
            "record_sk": worst["record_sk"],
            "execution_id": execution_id,
        }
        dump(f"GET {detail_url}", detail_params)
        detail_resp = requests.get(detail_url, params=detail_params, headers=headers, timeout=30)
        detail_resp.raise_for_status()
        detail = detail_resp.json()

        print(f"\nFailed rules for {worst['record_pk']} ({len(detail['failed_rules'])}):")
        for r in detail["failed_rules"]:
            print(f"\n  rule_id:         {r['rule_id']}")
            print(f"  rule_set_name:   {r['rule_set_name']}")
            print(f"  priority:        {r['priority']}")
            print(f"  message:         {r['message']}")
            print(f"  validation_rule: {r['validation_rule']}")
            print(f"  variables:       {r['variables']}")
    else:
        print("\nNo loan had any failed rules — skipping per-rule drill-down.")

    save_output(__file__, {
        "matchedLoans": loan_ids,
        "execution": execution,
        "results": results,
        "worstLoanDetail": detail,
    })


if __name__ == "__main__":
    main()
