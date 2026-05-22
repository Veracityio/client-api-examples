"""Shared helpers used by every example script in this directory tree.

Provides:
    - env(name): read a required environment variable or sys.exit with a clear error
    - auth_headers(token): build the Authorization header every request requires
    - dump(label, payload): pretty-print a labelled JSON block
    - save_output(path, payload): write a captured response next to the script that produced it

The reusable service-account token fetcher lives in ``auth/service_account.py``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # read api_docs/.env, if present


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"missing required environment variable: {name}")
    return value


def auth_headers(token: str) -> dict[str, str]:
    """Build the headers required for every authenticated request.

    Two pieces of authentication are needed on every call:
      - ``Authorization: Bearer <token>`` — proves who you are (the service account).
      - ``x-api-key: <api_key>``         — proves you're allowed to talk to the gateway
                                           at all (AWS API Gateway usage plan).

    Service-account tokens carry tenant claims, so no explicit tenant header is needed.
    """
    return {
        "Authorization": f"Bearer {token}",
        "x-api-key": env("API_KEY"),
        "Content-Type": "application/json",
    }


def dump(label: str, payload: Any) -> None:
    """Pretty-print a labelled JSON block to stdout."""
    print(f"\n=== {label} ===")
    print(json.dumps(payload, indent=2, default=str))


def save_output(script_path: str, payload: Any) -> None:
    """Save a captured response next to the running script as ``<script>.output.json``."""
    out_path = Path(script_path).with_suffix(".output.json")
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved response to {out_path}")
