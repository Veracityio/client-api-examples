"""Pull every loan-level result for a validation execution, then drill into the worst.

Steps walked here:
    4. GET  {base_url}/validations/record-executions?execution_id={id}
       → one summary row per validated loan (pass/fail/skip counts)
    5. GET  {base_url}/validations/record-executions/detail
       → for the loan with the most failed rules, list every failed rule with its DSL,
         message, priority, and the model fields (variables) the rule referenced
    6. POST {base_url}/loan-services/loans/search
       → look up the actual loan-side values for every variable referenced by any of
         the failed rules, and attach them back onto each rule. This mirrors what
         yoshi does on its rule-detail view: showing "rule X failed because @y was Z."

The execution_id is read from the sibling run_validation.output.json so there's nothing
for the operator to choose. Run run_validation.py first.

Run:
    python validations/get_loan_results.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import auth_headers, dump, env, save_output
from auth.service_account import get_service_access_token

# ─── GLOBAL CONFIG ────────────────────────────────────────────────────────────
LIMIT = 100  # max records to return from the listing — bump for larger executions
# ──────────────────────────────────────────────────────────────────────────────


def load_execution_id() -> str:
    """Pull the executionId from the sibling run_validation.output.json."""
    output_path = Path(__file__).with_name("run_validation.output.json")
    if not output_path.exists():
        sys.exit(
            f"{output_path.name} not found — run validations/run_validation.py first "
            "so it can capture an executionId."
        )
    data = json.loads(output_path.read_text())
    execution_id = data.get("execution", {}).get("executionId")
    if not execution_id:
        sys.exit(
            f"{output_path.name} does not contain execution.executionId — re-run "
            "validations/run_validation.py to refresh it."
        )
    return execution_id


def get_nested(doc: dict, dotted_path: str) -> Any:
    """Walk a dotted path through a nested dict/list document and return the leaf value.

    Handles intermediate dicts and lists. Numeric path segments index into lists
    (e.g. ``property_info.0.property_state``). Returns None if any segment is missing.
    """
    current: Any = doc
    for part in dotted_path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def main() -> None:
    base_url = env("VERACITY_BASE_SERVICE_URL")
    execution_id = load_execution_id()
    token = get_service_access_token()
    headers = auth_headers(token)

    # ─── Step 4: list every loan-level result ───────────────────────────────────
    results_url = f"{base_url}/validations/record-executions"
    results_params = {"execution_id": execution_id, "limit": LIMIT}
    dump(f"GET {results_url}", results_params)

    results_resp = requests.get(results_url, params=results_params, headers=headers, timeout=30)
    results_resp.raise_for_status()
    results = results_resp.json()

    items = sorted(results["items"], key=lambda r: r["failed_rule_count"], reverse=True)
    print(f"\n{results['count']} loan(s) under execution {execution_id}\n")
    print(f"  {'record_pk':<40}  {'total':>6}  {'passed':>6}  {'failed':>6}  {'skipped':>7}")
    print(f"  {'-' * 40}  {'-' * 6}  {'-' * 6}  {'-' * 6}  {'-' * 7}")
    for r in items:
        print(
            f"  {r['record_pk']:<40}  "
            f"{r['total_rule_count']:>6}  "
            f"{r['passed_rule_count']:>6}  "
            f"{r['failed_rule_count']:>6}  "
            f"{r['skipped_rule_count']:>7}"
        )

    detail: dict | None = None
    if not items or items[0]["failed_rule_count"] == 0:
        print("\nNo loan had any failed rules — skipping drill-down and enrichment.")
        save_output(__file__, {"results": results, "worstLoanDetail": None})
        return

    worst = items[0]

    # ─── Step 5: drill into the worst-failing loan ──────────────────────────────
    detail_url = f"{base_url}/validations/record-executions/detail"
    detail_params = {
        "record_pk": worst["record_pk"],
        "record_sk": worst["record_sk"],
        "execution_id": execution_id,
    }
    dump(f"GET {detail_url}", detail_params)

    detail_resp = requests.get(detail_url, params=detail_params, headers=headers, timeout=30)
    detail_resp.raise_for_status()
    detail = detail_resp.json()

    # ─── Step 6: enrich each failed rule with the loan's actual field values ────
    # The /detail response only tells us WHICH fields each rule referenced (the
    # `variables` array). To answer WHY a rule failed, we also need each field's
    # current value on the loan. We hit the loan search API once with `ids` scoped
    # to just this loan and `fields` set to every variable any failed rule mentions.
    all_vars = sorted({v for r in detail["failed_rules"] for v in r["variables"]})
    loan_doc: dict = {}
    if all_vars:
        opensearch_id = f"{worst['record_pk']}|||{worst['record_sk']}"
        enrich_url = f"{base_url}/loan-services/loans/search"
        enrich_body = {
            "ids": [opensearch_id],
            "fields": all_vars,
            "size": 1,
        }
        dump(f"POST {enrich_url}", enrich_body)
        enrich_resp = requests.post(enrich_url, json=enrich_body, headers=headers, timeout=30)
        enrich_resp.raise_for_status()
        enrich_response = enrich_resp.json()
        if enrich_response["results"]:
            loan_doc = enrich_response["results"][0]

    for r in detail["failed_rules"]:
        r["values"] = {v: get_nested(loan_doc, v) for v in r["variables"]}

    # ─── Print the enriched failure breakdown ──────────────────────────────────
    print(f"\nFailed rules for {worst['record_pk']} ({len(detail['failed_rules'])}):")
    for r in detail["failed_rules"]:
        print(f"\n  rule_id:         {r['rule_id']}")
        print(f"  rule_set_name:   {r['rule_set_name']}")
        print(f"  priority:        {r['priority']}")
        print(f"  message:         {r['message']}")
        print(f"  validation_rule: {r['validation_rule']}")
        print(f"  variables:       {r['variables']}")
        print(f"  values:          {r['values']}")

    save_output(__file__, {
        "results": results,
        "worstLoanDetail": detail,
    })


if __name__ == "__main__":
    main()
