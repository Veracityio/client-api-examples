"""Query loan exceptions, grouped by category with summed amounts.

Endpoint:
    POST {VERACITY_BASE_URL}/loan-assets/loan-exceptions

The request body is an OpenSearchQueryBody (see ../README.md for the full DSL). This
example skips returning individual hits and instead asks for exceptions grouped by
category, with a count and a summed exception amount per bucket.

Run:
    python query_exceptions.py
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
                    {"field": "status", "value": "open"},
                ]
            }
        ],
        "groupby": [
            {"data_type": "string", "field": "category", "size": 50}
        ],
        "metrics": [
            {"field": "amount", "metric": "sum", "name": "total_amount"},
            {"field": "amount", "metric": "avg", "name": "avg_amount"},
        ],
        "include_hits": False,
    }

    url = f"{base_url}/loan-assets/loan-exceptions"
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
