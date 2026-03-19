#!/usr/bin/env python3
"""Test all handlers against Tripletex sandbox to verify API field names work.

Usage:
    python3 scripts/test_handlers.py --base-url URL --token TOKEN
    python3 scripts/test_handlers.py  # reads from latest GCS request log
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tripletex import TripletexClient

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# Test data for each handler — minimal payloads to verify field names
TEST_CASES: list[dict] = [
    {
        "name": "create_supplier",
        "handler": "create_supplier",
        "fields": {
            "name": "Test Leverandør AS",
            "organizationNumber": "999888777",
            "email": "test@leverandor.no",
        },
        "verify_path": "/supplier",
        "verify_field": "name",
    },
    {
        "name": "create_customer",
        "handler": "create_customer",
        "fields": {
            "name": "Test Kunde AS",
            "organizationNumber": "888777666",
            "email": "test@kunde.no",
        },
        "verify_path": "/customer",
        "verify_field": "name",
    },
    {
        "name": "create_employee",
        "handler": "create_employee",
        "fields": {
            "firstName": "Test",
            "lastName": "Testansatt",
            "email": f"test.ansatt.{int(__import__('time').time())}@example.org",
        },
        "verify_path": "/employee",
        "verify_field": "firstName",
    },
    {
        "name": "create_product",
        "handler": "create_product",
        "fields": {
            "name": "Testprodukt",
            "number": str(int(__import__('time').time()) % 100000),
            "priceExcludingVat": 1000,
            "vatCode": "3",
        },
        "verify_path": "/product",
        "verify_field": "name",
    },
    {
        "name": "create_department",
        "handler": "create_department",
        "fields": {
            "name": "Testavdeling",
        },
        "verify_path": "/department",
        "verify_field": "name",
    },
]

TIER2_TEST_CASES: list[dict] = [
    {
        "name": "create_project",
        "handler": "create_project",
        "fields": {
            "name": "Testprosjekt",
            "customerName": "Test Kunde AS",
        },
        "verify_path": "/project",
        "verify_field": "name",
    },
]


def color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def green(text: str) -> str:
    return color(text, "32")

def red(text: str) -> str:
    return color(text, "31")

def yellow(text: str) -> str:
    return color(text, "33")


async def run_test(client: TripletexClient, test: dict) -> tuple[str, bool, str]:
    """Run a single handler test. Returns (name, passed, detail)."""
    from app.handlers import HANDLER_REGISTRY

    handler = HANDLER_REGISTRY.get(test["handler"])
    if not handler:
        return test["name"], False, "Handler not registered"

    try:
        result = await handler(client, test["fields"])
        status = result.get("status", "")
        created = result.get("created", {})

        # Check if something was actually created
        if created and created.get("id"):
            return test["name"], True, f"ID={created['id']}"
        elif "note" in result:
            return test["name"], False, f"Note: {result['note']}"
        else:
            # Check tracker for 4xx errors
            last_call = client.tracker.api_calls[-1] if client.tracker.api_calls else None
            if last_call and 400 <= last_call.status < 500:
                return test["name"], False, f"API error {last_call.status}: check field names"
            return test["name"], True, "Completed (no ID returned)"

    except Exception as e:
        return test["name"], False, str(e)[:200]


async def main_async(base_url: str, token: str, include_tier2: bool = False) -> int:
    client = TripletexClient(base_url, token)

    tests = TEST_CASES.copy()
    if include_tier2:
        tests.extend(TIER2_TEST_CASES)

    print(f"\nTesting {len(tests)} handlers against {base_url}\n")
    print("-" * 60)

    passed = 0
    failed = 0

    for test in tests:
        name, ok, detail = await run_test(client, test)
        if ok:
            print(f"  {green('PASS')}  {name}: {detail}")
            passed += 1
        else:
            print(f"  {red('FAIL')}  {name}: {detail}")
            failed += 1

    print("-" * 60)

    # Show API call summary
    print(f"\nAPI-kall: {client.tracker.total_calls}")
    print(f"4xx-feil: {client.tracker.error_count_4xx}")
    for call in client.tracker.api_calls:
        status_color = green if call.status < 400 else red
        print(f"  {call.method:6} {call.path:40} {status_color(str(call.status))} ({call.duration_ms:.0f}ms)")

    print(f"\nResultat: {green(f'{passed} passed')}, {red(f'{failed} failed') if failed else f'{failed} failed'}")

    await client.close()
    return failed


def main():
    parser = argparse.ArgumentParser(description="Test handlers against Tripletex sandbox")
    parser.add_argument("--base-url", default="https://kkpqfuj-amager.tripletex.dev/v2",
                        help="Tripletex API base URL")
    parser.add_argument("--token", default=None, help="Session token")
    parser.add_argument("--tier2", action="store_true", help="Include Tier 2 tests")
    parser.add_argument("--from-gcs", action="store_true",
                        help="Use credentials from latest GCS request log")
    args = parser.parse_args()

    token = args.token
    base_url = args.base_url

    if not token and args.from_gcs:
        import subprocess
        result = subprocess.run(
            ["gsutil", "ls", "gs://tripletex-agent-requests/requests/"],
            capture_output=True, text=True
        )
        files = sorted(result.stdout.strip().split("\n"))
        if files:
            latest = files[-1]
            print(f"Using credentials from: {latest}")
            result = subprocess.run(["gsutil", "cat", latest], capture_output=True, text=True)
            data = json.loads(result.stdout)
            creds = data.get("tripletex_credentials", {})
            token = creds.get("session_token", "")
            base_url = creds.get("base_url", base_url)

    if not token:
        print("Error: Trenger --token eller --from-gcs")
        print("  python3 scripts/test_handlers.py --token <session_token>")
        print("  python3 scripts/test_handlers.py --from-gcs")
        sys.exit(1)

    failed = asyncio.run(main_async(base_url, token, include_tier2=args.tier2))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
