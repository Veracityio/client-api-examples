# Veracity Public API — Examples & Guides

This directory complements the OpenAPI/Swagger documentation with runnable Python examples
and supplemental guides for the parts of the API that are most commonly used by clients.

All examples use plain [`requests`](https://requests.readthedocs.io/).

## What's here

| Directory | What it covers |
| --- | --- |
| [`auth/`](./auth) | How to obtain an access token using a service account |
| [`search/`](./search) | How to query the search-style endpoints (loans, exceptions, …) using the OpenSearch query DSL |
| [`data_import/`](./data_import) | How to import a workbook of data through Kazooie's chunked upload pipeline |
| [`validations/`](./validations) | How to run rule-set validations and retrieve per-record results |

## Environment

These examples are written against the **beta** environment. Configure them either via
environment variables in your shell or with an `api_docs/.env` file (auto-loaded by every
script):

| Variable | Description | Example |
| --- | --- | --- |
| `VERACITY_BASE_URL` | Public API base URL | `https://core-beta.veracityloan.ai` |
| `CLIENT_ID` | Service-account client id | — |
| `CLIENT_SECRET` | Service-account client secret | — |
| `API_KEY` | AWS API Gateway key (sent as `x-api-key` on every request) | — |

The `CLIENT_ID`, `CLIENT_SECRET`, and `API_KEY` values were delivered to you in a
1Password note. Copy them into the variables above (or into `api_docs/.env`).

Sample `api_docs/.env`:

```bash
VERACITY_BASE_URL=https://core-beta.veracityloan.ai
CLIENT_ID=...
CLIENT_SECRET=...
API_KEY=...
```

## Required headers

Every authenticated request requires two headers:

```
Authorization: Bearer <access_token>
x-api-key: <api_key>
```

- `Authorization` proves who you are (the service account).
- `x-api-key` is the AWS API Gateway usage-plan key — it's required for the request to
  reach our services at all.

The service-account token carries the tenant claim, so no explicit tenant header is needed.

## Running the examples

Each example script is self-contained and runnable:

```bash
cd api_docs
python search/query_loans.py
```

When run, the script prints the request and response, and writes the captured response to a
sibling `*.output.json` file so the canned responses in this repository reflect real beta
data.

## Conventions

- Scripts show the **happy path only** — they do not include retry, backoff, or detailed
  error handling. Real client integrations should add both.
- Every script reads credentials from environment variables — never hard-code them.
- Outputs are pretty-printed JSON for readability.
- Every script imports `get_service_access_token` from `auth/service_account.py` to obtain
  a token before making API calls.
