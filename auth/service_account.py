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
