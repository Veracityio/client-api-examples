# Search (OpenSearch Query DSL)

Many of the public Veracity endpoints — including loan search — accept a common JSON
request body that lets you express filters, sorting, pagination, and aggregations
against the underlying OpenSearch indexes.

This document describes the shape of that request body and the responses it can return.
The DSL is identical regardless of which resource you're querying; only the URL and the
field names available on the documents change.

## Endpoints covered

| Resource | Method | Path |
| --- | --- | --- |
| Loans | `POST` | `{base_url}/loan-services/loans/search` |

Other tenant-facing endpoints that accept the same DSL include collateral, remittances,
and trades — see the Swagger spec for the full list.

## Request body

Every search endpoint accepts the same envelope:

```json
{
  "filter_groups": [],
  "sort": null,
  "size": 100,
  "page": 0,
  "fields": null,
  "ids": null,
  "groupby": null,
  "metrics": null,
  "include_hits": true
}
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `filter_groups` | `FilterGroup[]` | `[]` | One or more filter groups. Groups are AND-combined |
| `sort` | `string \| null` | `null` | Field name to sort by. Prefix with `-` for descending |
| `size` | `int` | `100` | Page size (max results per page) |
| `page` | `int` | `0` | Zero-indexed page number |
| `fields` | `string[] \| null` | `null` | Return only these fields. `null` returns the full document |
| `ids` | `string[] \| null` | `null` | Restrict to these document IDs |
| `groupby` | `GroupBy[] \| null` | `null` | Group results into buckets |
| `metrics` | `MetricAggregation[] \| null` | `null` | Compute metrics over the result set or per bucket |
| `include_hits` | `bool` | `true` | When `false`, skip returning hits — use this for pure aggregation queries |

## Filtering

Filters are organized into groups. Within a group, filters combine using `filter_operator`
(`and` by default, or `or`). Multiple groups always combine with AND logic.

### Operators

| Operator | Meaning |
| --- | --- |
| `equals` (default) | Exact, case-insensitive match |
| `contains` | Case-insensitive wildcard match |
| `lt`, `lte`, `gt`, `gte` | Numeric or date range |
| `is_empty`, `is_not_empty` | Field absence / presence |

### Simple AND

```json
{
  "filter_groups": [
    {
      "filters": [
        { "field": "status", "value": "active" },
        { "field": "state", "value": "CA" }
      ]
    }
  ]
}
```

### OR within a group

```json
{
  "filter_groups": [
    {
      "filter_operator": "or",
      "filters": [
        { "field": "status", "value": "active" },
        { "field": "status", "value": "pending" }
      ]
    }
  ]
}
```

### Combined AND/OR

`(status = active OR status = pending) AND amount >= 100000`

```json
{
  "filter_groups": [
    {
      "filter_operator": "or",
      "filters": [
        { "field": "status", "value": "active" },
        { "field": "status", "value": "pending" }
      ]
    },
    {
      "filters": [
        { "field": "amount", "value": "100000", "operator": "gte" }
      ]
    }
  ]
}
```

### Nested fields

Dotted field names automatically resolve against nested documents — no special syntax
required.

```json
{ "field": "subject_property.state", "value": "CA" }
```

### Filtering by document ID

```json
{ "ids": ["LOAN#123|||DETAIL", "LOAN#456|||DETAIL"] }
```

## Pagination and sorting

```json
{
  "sort": "-created_at",
  "size": 25,
  "page": 2,
  "fields": ["loan_number", "status", "balance"]
}
```

- `sort`: field name; prefix `-` for descending
- `size`: max results per page
- `page`: zero-indexed
- `fields`: source filtering — only these fields are returned per hit

## Aggregations (group by)

Use `groupby` to bucket results. Multiple entries create nested aggregations.

| `data_type` | Buckets by | Key parameters |
| --- | --- | --- |
| `string` | Distinct keyword values | `field`, `size` (default 100) |
| `date` | Date histogram | `field`, `group_type` (`day` / `month` / `year`) |
| `histogram` | Fixed numeric intervals | `field`, `interval` |
| `range` | Custom ranges | `field`, `ranges` |

### Group by string

```json
{
  "groupby": [
    { "data_type": "string", "field": "seller", "size": 500 }
  ],
  "include_hits": false
}
```

### Group by date

```json
{
  "groupby": [
    { "data_type": "date", "field": "created_at", "group_type": "month" }
  ],
  "include_hits": false
}
```

### Group by histogram

```json
{
  "groupby": [
    { "data_type": "histogram", "field": "balance", "interval": 50000 }
  ],
  "include_hits": false
}
```

### Group by range

```json
{
  "groupby": [
    {
      "data_type": "range",
      "field": "balance",
      "ranges": [
        { "to": 100000 },
        { "from": 100000, "to": 500000 },
        { "from": 500000 }
      ]
    }
  ],
  "include_hits": false
}
```

## Metrics

Available metric types: `sum`, `avg`, `min`, `max`, `count`.

Metrics may be used **with or without** `groupby`:
- Without `groupby` — computed across all matching documents
- With `groupby` — computed per bucket (at every nesting level)

```json
{
  "groupby": [{ "data_type": "string", "field": "seller" }],
  "metrics": [
    { "field": "balance", "metric": "sum", "name": "total_balance" },
    { "field": "balance", "metric": "avg", "name": "avg_balance" },
    { "field": "rate", "metric": "min", "name": "min_rate" }
  ],
  "include_hits": false
}
```

If `name` is omitted, it defaults to `{field}_{metric}` (e.g. `balance_sum`).

## Response shapes

Responses are discriminated by `response_type`. There are three shapes.

### `hits` — standard search results

Returned when there is no `groupby` and no top-level `metrics`.

```json
{
  "response_type": "hits",
  "total": 2,
  "results": [
    {
      "opensearch_id": "LOAN#123|||DETAIL",
      "opensearch_score": 1.0,
      "loan_number": "L-000123",
      "status": "active",
      "balance": 250000,
      "state": "CA"
    },
    {
      "opensearch_id": "LOAN#456|||DETAIL",
      "opensearch_score": 0.8,
      "loan_number": "L-000456",
      "status": "active",
      "balance": 175000,
      "state": "TX"
    }
  ]
}
```

### `grouped` — bucketed aggregation results

Returned when `groupby` is specified.

```json
{
  "response_type": "grouped",
  "total": 500,
  "group_fields": ["seller"],
  "results": [
    {
      "key": "Acme Lending",
      "doc_count": 312,
      "metrics": {
        "total_balance": { "agg_type": "sum", "value": 78000000.0 },
        "avg_balance":   { "agg_type": "avg", "value": 250000.0 }
      },
      "children": []
    }
  ]
}
```

Nested `groupby` populates `children`:

```json
{
  "response_type": "grouped",
  "total": 500,
  "group_fields": ["seller", "created_at"],
  "results": [
    {
      "key": "Acme Lending",
      "doc_count": 312,
      "metrics": { "total_balance": { "agg_type": "sum", "value": 78000000.0 } },
      "children": [
        { "key": "2024-01", "doc_count": 95,  "metrics": { }, "children": [] },
        { "key": "2024-02", "doc_count": 217, "metrics": { }, "children": [] }
      ]
    }
  ]
}
```

### `metric` — metrics-only

Returned when `metrics` are specified without `groupby`.

```json
{
  "response_type": "metric",
  "total": 500,
  "results": {
    "total_balance": { "agg_type": "sum",   "value": 125000000.0 },
    "avg_balance":   { "agg_type": "avg",   "value": 250000.0 },
    "min_rate":      { "agg_type": "min",   "value": 3.25 }
  }
}
```

## Example: query KKR loans

[`query_loans.py`](./query_loans.py) — filters KKR loans on the `desk` field, sorts by
original balance (largest first), and projects a focused set of fields per hit. The
field names come from the KKR position mappings in [`../mappings.py`](../mappings.py).

```python
"""Query KKR loans via the OpenSearch-backed search endpoint.

Endpoint:
    POST {VERACITY_BASE_SERVICE_URL}/loan-services/loans/search
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
```
