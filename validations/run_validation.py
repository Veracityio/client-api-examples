"""Kick off the KKR loan validations rule set against a filtered subset of loans.

Steps walked here:
    1. POST {base_url}/loan-services/loans/search
       → use the same filter shape as search/query_loans.py to pick which loans to validate
    2. POST {base_url}/validations/executions/Loan/run
       → kick off the rule set against just those loans
    3. GET  {base_url}/validations/executions/Loan/{execution_id}
       → poll until status is "completed" or "failed"

The matched loan IDs and the final execution (including its executionId) are saved to
run_validation.output.json. Run get_loan_results.py next to see the per-loan outcomes.

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

MODEL_TYPE = "Loan"  # which Veracity model to validate
DATA_SOURCE = "final"  # required for Loan / Remittance
RULE_SET_ID = "42054406-1bac-4e20-a6d5-6f7c22f59fa3"  # kkr-validations
POLL_INTERVAL_SECONDS = 3

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
        "size": 25,
        "page": 0,
    }
    search_url = f"{base_url}/loan-services/loans/search"
    dump(f"POST {search_url}", search_body)

    search_resp = requests.post(
        search_url, json=search_body, headers=headers, timeout=60
    )
    search_resp.raise_for_status()
    search_response = search_resp.json()

    loan_ids = [hit["veracity_loan_id"] for hit in search_response["results"]]
    print(f"\nMatched {len(loan_ids)} loan(s):")
    for hit in search_response["results"]:
        print(
            f"  veracity_loan_id={hit['veracity_loan_id']}  tenant_loan_id={hit.get('tenant_loan_id')}"
        )

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
    save_output(
        __file__,
        {
            "matchedLoans": loan_ids,
            "execution": execution,
        },
    )

    print("\nDone. Next: python validations/get_loan_results.py")


if __name__ == "__main__":
    main()
