"""Query KKR loans via the OpenSearch-backed search endpoint.

Endpoint:
    POST {VERACITY_BASE_SERVICE_URL}/loan-services/loans/search

The request body is an OpenSearchQueryBody (see ../README.md for the full DSL). This
example filters loans on the KKR-specific `desk` field, sorts by original loan balance
(largest first), and projects a focused set of fields per hit.

The field names below come from the KKR position mappings in api_docs/mappings.py — the
left-hand-side of each `SET` statement is a queryable field once data has been imported
via create_workbook.py + upload_data.py.

Run:
    python query_loans.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    token = get_service_access_token()

    query_body = {
        "filter_groups": [
            {
                "filters": [
                    {"field": "desk", "value": "RPL"},
                ]
            }
        ],
        "sort": "-orig_bal",
        "size": 25,
        "page": 0,
        "fields": [
            "tenant_loan_id",
            "seller_name",
            "desk",
            "sub_desk",
            "position_status",
            "orig_bal",
            "settle_dt",
            "property_info.0.property_state",
        ],
    }

    url = f"{base_url}/loan-services/loans/search"
    dump(f"POST {url}", query_body)

    response = requests.post(
        url,
        json=query_body,
        headers=auth_headers(token),
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()

    dump("Response", body)
    save_output(__file__, body)


if __name__ == "__main__":
    main()
