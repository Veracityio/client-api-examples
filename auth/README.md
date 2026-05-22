# Authentication

All Veracity API requests authenticate with a **service-account access token**.

Service-account credentials (`client_id` + `client_secret`) are created and managed through
the Veracity control plane. Once you have them, you exchange them for a short-lived bearer
token (~1 hour TTL) by `POST`ing to `/pub/tokens/service-account`.

## Required headers

Every authenticated request requires two headers:

```
Authorization: Bearer <access_token>
x-api-key: <api_key>
```

- `Authorization` proves who you are (the service account).
- `x-api-key` is the AWS API Gateway usage-plan key — it's required for the request to
  reach our services at all. The token-exchange call itself (`/pub/tokens/service-account`)
  is the one exception: it does not require `x-api-key`.

The service-account token carries the tenant claim, so no explicit tenant header is needed.

## Required environment variables

```bash
VERACITY_BASE_URL=https://core-beta.veracityloan.ai
VERACITY_BASE_SERVICE_URL=https://core-service-beta.veracityloan.ai
CLIENT_ID=...
CLIENT_SECRET=...
API_KEY=...
```

These may be set in your shell or placed in `api_docs/.env` (auto-loaded by every script).

Two hosts are involved:
- **`VERACITY_BASE_URL`** — the auth host. Only the token-exchange call below talks to it.
- **`VERACITY_BASE_SERVICE_URL`** — the API host. Every example script in `search/`,
  `data_import/`, and `validations/` reads this one for its API calls.

The `CLIENT_ID`, `CLIENT_SECRET`, and `API_KEY` values were delivered to you in a 1Password
note. Treat all three as sensitive — never check them into source control, never paste them
into chat, and rotate them through the Veracity control plane if they're ever exposed.

## Obtaining a token

`POST {VERACITY_BASE_URL}/pub/tokens/service-account`

Request body:

```json
{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret"
}
```

Response:

```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

When the token expires, simply call the endpoint again.

## Reusable helper

[`service_account.py`](./service_account.py) exposes a single `get_service_access_token()`
function that every other example script in this directory tree imports to obtain a token
before making API calls.

```python
"""Obtain an access token using a service account (client credentials).

Use this for unattended integrations — scheduled jobs, server-to-server pipelines, anything
that runs without a human in the loop.

Service-account credentials are created and managed through the Veracity control plane.

The ``get_service_access_token`` function is reusable — every other example script in this
directory tree imports it to obtain a token before making API calls.

Run:
    python service_account.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

# Make the api_docs/ root importable so ``from _shared import ...`` works whether this
# script is run directly (``python auth/service_account.py``) or imported by another
# example script in a sibling directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import dump, env, save_output


def get_service_access_token() -> str:
    """Exchange a service-account client_id/secret pair for a bearer access token.

    The returned token is valid for ~1 hour. Callers should request a new token rather
    than trying to refresh — there is no refresh-token flow for service accounts.
    """
    # Pulled from the environment (or api_docs/.env, which _shared auto-loads):
    #   VERACITY_BASE_URL          the auth host (e.g. https://core-beta.veracityloan.ai).
    #                              Token exchange happens here ONLY — every subsequent
    #                              API call goes to VERACITY_BASE_SERVICE_URL instead.
    #   CLIENT_ID                  your service account's client id
    #   CLIENT_SECRET              your service account's client secret
    base_url = env("VERACITY_BASE_URL")
    client_id = env("CLIENT_ID")
    client_secret = env("CLIENT_SECRET")

    # The /pub/tokens/service-account endpoint takes a JSON body with the credential
    # pair and returns a JWT plus metadata. It does NOT require an Authorization
    # header itself — the credentials in the body ARE the authentication. It also does
    # NOT require the x-api-key header (that's only on the core-service-* host).
    request_body = {
        "client_id": client_id,
        "client_secret": client_secret,
    }

    # Print the request for visibility — but redact the secret so it doesn't end up
    # in terminal scrollback or screen captures.
    dump(
        f"POST {base_url}/pub/tokens/service-account",
        request_body | {"client_secret": "***"},
    )

    response = requests.post(
        f"{base_url}/pub/tokens/service-account",
        json=request_body,
        timeout=30,
    )
    # 4xx (bad credentials) or 5xx (service down) will raise here. In a real
    # integration you would catch this and surface a more actionable error to the caller.
    response.raise_for_status()
    body = response.json()

    # Show the full response shape (access_token, token_type, expires_in, tenant_name,
    # service_account_id, …) so readers can see exactly what comes back.
    dump("Response", body)

    # Persist the response to auth/service_account.output.json so the docs in this
    # repository carry a real captured example rather than a hand-written stub.
    save_output(__file__, body)

    # Callers (query_loans.py, run_validation.py, …) only need the access_token —
    # they pass it straight into auth_headers().
    return body["access_token"]


if __name__ == "__main__":
    get_service_access_token()
```

## Using the token in other scripts

```python
from auth.service_account import get_service_access_token
from _shared import auth_headers

token = get_service_access_token()
headers = auth_headers(token)
```
