#!/usr/bin/env python3
"""Pre-deploy tests: verify all handlers work against Tripletex sandbox.

Run this BEFORE every deploy to catch field name errors, missing required fields, etc.
Exit code 0 = all passed, 1 = failures found.

Usage:
    python3 scripts/pre_deploy_test.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def green(t: str) -> str: return color(t, "32")
def red(t: str) -> str: return color(t, "31")
def yellow(t: str) -> str: return color(t, "33")


def get_sandbox_creds() -> tuple[str, str]:
    """Fetch sandbox credentials from NM i AI API."""
    token = os.environ.get("NMIAI_ACCESS_TOKEN")
    if not token:
        print(red("NMIAI_ACCESS_TOKEN not found in .env"))
        sys.exit(1)

    r = httpx.get("https://api.ainm.no/tripletex/sandbox",
                  cookies={"access_token": token},
                  headers={"origin": "https://app.ainm.no", "referer": "https://app.ainm.no/"})
    if r.status_code != 200:
        print(red(f"Failed to get sandbox creds: {r.status_code}"))
        sys.exit(1)

    data = r.json()
    return data["api_url"], data["session_token"]


# Test cases: (name, handler_name, fields, expect_created)
TESTS = [
    # --- Tier 1 ---
    ("create_supplier", "create_supplier", {
        "name": f"PreDeploy Supplier {int(time.time())}",
        "organizationNumber": "999000111",
        "email": "test@supplier.no",
        "address": {"addressLine1": "Testgata 1", "postalCode": "0001", "city": "Oslo"},
    }, True),

    ("create_customer", "create_customer", {
        "name": f"PreDeploy Customer {int(time.time())}",
        "organizationNumber": "999000222",
        "email": "test@customer.no",
        "phoneNumberMobile": "99887766",
        "address": {"addressLine1": "Kundegata 2", "postalCode": "0002", "city": "Bergen"},
    }, True),

    ("create_employee", "create_employee", {
        "firstName": "PreDeploy",
        "lastName": f"Test{int(time.time()) % 10000}",
        "email": f"predeploy.{int(time.time())}@example.org",
        "dateOfBirth": "1990-05-15",
        # Note: startDate should NOT be sent to /employee — it goes on Employment
    }, True),

    ("create_product", "create_product", {
        "name": f"PreDeploy Product {int(time.time())}",
        "number": str(int(time.time()) % 100000),
        "priceExcludingVat": 500,
        "vatCode": "3",
    }, True),

    ("create_department", "create_department", {
        "name": f"PreDeploy Dept {int(time.time())}",
    }, True),

    # --- Tier 2 ---
    ("create_invoice", "create_invoice", {
        "customerName": f"Invoice Test Customer {int(time.time())}",
        "lines": [{"description": "Test service", "quantity": 1, "unitPriceExcludingVat": 1000}],
    }, True),

    ("create_project", "create_project", {
        "name": f"PreDeploy Project {int(time.time())}",
        "customerName": f"PreDeploy Customer {int(time.time())}",
    }, True),

    ("create_travel_expense", "create_travel_expense", {
        "employeeName": "PreDeploy",
        "title": f"PreDeploy Travel {int(time.time())}",
        "date": "2026-03-20",
        "costs": [{"description": "Test cost", "amount": 100}],
    }, False),  # Returns travelExpenseId, not "created"

    ("update_employee", "update_employee", {
        "employeeFirstName": "PreDeploy",
        "changes": {"phoneNumberMobile": "11223344"},
    }, False),  # Returns employeeId

    ("update_customer", "update_customer", {
        "customerOrgNumber": "999000222",
        "changes": {"description": "Updated by pre-deploy test"},
    }, False),  # Returns customerId
]


async def run_test(client, handler, fields: dict) -> tuple[bool, str]:
    """Run a handler and check if it succeeds (no 4xx errors)."""
    from app.tripletex import TripletexClient

    try:
        calls_before = len(client.tracker.api_calls)
        result = await handler(client, fields)

        # Only check errors from THIS test's calls
        new_calls = client.tracker.api_calls[calls_before:]
        recent_errors = [c for c in new_calls if 400 <= c.status < 500
                        and c.path != "/company/salesmodules"]  # Ignore salesmodules 422

        if recent_errors:
            # Allow known sandbox-only failures (no bank account blocks :invoice)
            sandbox_only = [c for c in recent_errors if "/:invoice" in c.path]
            real_errors = [c for c in recent_errors if "/:invoice" not in c.path]
            if real_errors:
                err_details = "; ".join(f"{c.method} {c.path} → {c.status}" for c in real_errors)
                return False, f"4xx errors: {err_details}"
            elif sandbox_only:
                return True, "OK (sandbox: no bank account for :invoice)"

        # Check if something was created
        if result.get("created") and result["created"].get("id"):
            return True, f"ID={result['created']['id']}"
        elif result.get("travelExpenseId"):
            return True, f"TE={result['travelExpenseId']}"
        elif result.get("employeeId"):
            return True, f"Emp={result['employeeId']}"
        elif result.get("customerId"):
            return True, f"Cust={result['customerId']}"
        elif result.get("note"):
            return False, f"Note: {result['note']}"
        else:
            return True, "OK"

    except Exception as e:
        return False, str(e)[:200]


async def main_async() -> int:
    from app.tripletex import TripletexClient
    from app.handlers import HANDLER_REGISTRY

    base_url, token = get_sandbox_creds()
    client = TripletexClient(base_url, token)

    print(f"\n  Pre-deploy test mot {base_url}")
    print(f"  {len(TESTS)} tester, {len(HANDLER_REGISTRY)} handlers registrert\n")
    print(f"  {'='*55}")

    passed = 0
    failed = 0
    errors: list[str] = []

    for test_name, handler_name, fields, _ in TESTS:
        handler = HANDLER_REGISTRY.get(handler_name)
        if not handler:
            print(f"  {red('SKIP')}  {test_name}: handler ikke registrert")
            failed += 1
            errors.append(f"{test_name}: handler not registered")
            continue

        ok, detail = await run_test(client, handler, fields)
        if ok:
            print(f"  {green('PASS')}  {test_name}: {detail}")
            passed += 1
        else:
            print(f"  {red('FAIL')}  {test_name}: {detail}")
            failed += 1
            errors.append(f"{test_name}: {detail}")

    print(f"  {'='*55}")

    # API call summary
    total_calls = client.tracker.total_calls
    total_4xx = client.tracker.error_count_4xx
    print(f"\n  API-kall: {total_calls}, 4xx: {total_4xx}")

    await client.close()

    print(f"\n  Resultat: {green(f'{passed} passed')}, ", end="")
    if failed:
        print(f"{red(f'{failed} failed')}")
        print(f"\n  {red('DEPLOY BLOKKERT — fiks feilene først!')}\n")
        for e in errors:
            print(f"    - {e}")
    else:
        print(f"0 failed")
        print(f"\n  {green('Klar for deploy!')}\n")

    return failed


def main():
    failed = asyncio.run(main_async())
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
