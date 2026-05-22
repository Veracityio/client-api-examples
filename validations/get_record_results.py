"""Fetch the per-rule outcomes for a single record under a specific execution.

Endpoint:
    GET {VERACITY_BASE_URL}/validations/record-executions/detail
        ?record_pk={pk}&record_sk={sk}&execution_id={id}

The record_pk / record_sk values come from the OpenSearch document ID of the underlying
record. For a Loan with veracity_loan_id "abc-123" on data source "final", that's:
    record_pk = "loan::abc-123::"
    record_sk = "loan::abc-123::final"

Run:
    export VALIDATIONS_EXECUTION_ID=019577a5-c8f5-7b9e-8b3a-1c2d3e4f5a6b
    export VALIDATIONS_RECORD_PK="loan::abc-123::"
    export VALIDATIONS_RECORD_SK="loan::abc-123::final"
    python get_record_results.py
"""

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
