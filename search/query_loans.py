"""Query loans via the OpenSearch-backed search endpoint.

Endpoint:
    POST {VERACITY_BASE_URL}/loan-services/loans/search

The request body is an OpenSearchQueryBody (see ../README.md for the full DSL). This
example filters active loans in California with a balance >= $100k, returns the most
recent ones first, and only includes a few fields per hit.

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
    base_url = env("VERACITY_BASE_URL")
    token = get_service_access_token()

    query_body = {
        "filter_groups": [
            {
                "filters": [
                    {"field": "status", "value": "active"},
                    {"field": "subject_property.state", "value": "CA"},
                    {"field": "balance", "value": "100000", "operator": "gte"},
                ]
            }
        ],
        "sort": "-created_at",
        "size": 25,
        "page": 0,
        "fields": ["loan_number", "status", "balance", "subject_property.state", "created_at"],
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
