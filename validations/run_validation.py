"""Kick off a Loan validation run, then poll until it completes.

Endpoints:
    POST {VERACITY_BASE_URL}/validations/executions/Loan/run
    GET  {VERACITY_BASE_URL}/validations/executions/Loan/{execution_id}

Set VALIDATIONS_RULE_SET_ID to a rule set you have access to. Optionally narrow the
target record set by setting VALIDATIONS_LOAN_IDS to a comma-separated list of loan IDs.

Run:
    export VALIDATIONS_RULE_SET_ID=rs-abc123
    export VALIDATIONS_LOAN_IDS=loan-1,loan-2     # optional
    python run_validation.py
"""

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
        time.sleep(3)

    dump("Final execution", execution)
    save_output(__file__, execution)


if __name__ == "__main__":
    main()
