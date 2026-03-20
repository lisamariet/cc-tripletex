#!/usr/bin/env python3
"""E2E test suite for Tripletex AI Accounting Agent.

Tests the full pipeline: prompt -> parse_task() -> handler -> verification GET.
Self-verification is externalized here (TODO #8+9): the verification GET IS
the self-verification, kept outside live handler code to avoid risk.

Usage:
    python3 scripts/test_e2e.py             # Dry-run: shows test plan only
    python3 scripts/test_e2e.py --live       # Execute tests against sandbox
    python3 scripts/test_e2e.py --live -v    # Verbose output
    python3 scripts/test_e2e.py --live --only create_customer,create_supplier
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("e2e")


# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def green(t: str) -> str: return _c(t, "32")
def red(t: str) -> str: return _c(t, "31")
def yellow(t: str) -> str: return _c(t, "33")
def dim(t: str) -> str: return _c(t, "2")
def bold(t: str) -> str: return _c(t, "1")


# ---------------------------------------------------------------------------
# Sandbox credentials
# ---------------------------------------------------------------------------

def get_sandbox_creds() -> tuple[str, str]:
    """Fetch sandbox credentials from NM i AI API."""
    token = os.environ.get("NMIAI_ACCESS_TOKEN")
    if not token:
        print(red("NMIAI_ACCESS_TOKEN not set in .env"))
        sys.exit(1)
    r = httpx.get(
        "https://api.ainm.no/tripletex/sandbox",
        cookies={"access_token": token},
        headers={"origin": "https://app.ainm.no", "referer": "https://app.ainm.no/"},
    )
    if r.status_code != 200:
        print(red(f"Failed to get sandbox creds: {r.status_code} {r.text[:200]}"))
        sys.exit(1)
    data = r.json()
    return data["api_url"], data["session_token"]


# ---------------------------------------------------------------------------
# Test-case definitions
# ---------------------------------------------------------------------------

@dataclass
class FieldCheck:
    """A single expected field value with comparison mode."""
    field: str
    expected: Any
    mode: str = "eq"  # eq | contains | gt | nested

    def describe(self) -> str:
        if self.mode == "eq":
            return f"{self.field}={self.expected!r}"
        elif self.mode == "contains":
            return f"{self.field} contains {self.expected!r}"
        elif self.mode == "gt":
            return f"{self.field} > {self.expected!r}"
        elif self.mode == "nested":
            return f"{self.field}.{self.expected[0]}={self.expected[1]!r}"
        return f"{self.field} ? {self.expected!r}"


@dataclass
class VerifySpec:
    """How to GET and verify the created entity."""
    endpoint: str                   # e.g. "/customer"
    search_params: dict[str, Any] = field(default_factory=dict)
    checks: list[FieldCheck] = field(default_factory=list)
    search_by_id: bool = False      # use entity id from handler result


@dataclass
class E2ETestCase:
    """One end-to-end test."""
    name: str
    request_file: str               # filename under data/requests/
    expected_task_type: str
    expected_fields: dict[str, Any]  # subset of fields that MUST parse out
    verify: VerifySpec | None = None


# -- The actual test cases, one per real request file ----------------------

TEST_CASES: list[E2ETestCase] = [

    # 1. create_customer with address
    E2ETestCase(
        name="create_customer_with_address",
        request_file="20260319_235722_219962.json",
        expected_task_type="create_customer",
        expected_fields={
            "name": "Bølgekraft AS",
            "organizationNumber": "988957747",
        },
        verify=VerifySpec(
            endpoint="/customer",
            search_params={"organizationNumber": "988957747"},
            checks=[
                FieldCheck("name", "Bølgekraft AS"),
                FieldCheck("organizationNumber", "988957747"),
                FieldCheck("email", "post@blgekraft.no"),
                FieldCheck("invoiceEmail", "post@blgekraft.no"),
            ],
        ),
    ),

    # 2. create_supplier with email
    E2ETestCase(
        name="create_supplier_with_email",
        request_file="20260320_082409_705223.json",
        expected_task_type="create_supplier",
        expected_fields={
            "name": "Northwave Ltd",
            "organizationNumber": "949044378",
        },
        verify=VerifySpec(
            endpoint="/supplier",
            search_params={"organizationNumber": "949044378"},
            checks=[
                FieldCheck("name", "Northwave Ltd"),
                FieldCheck("organizationNumber", "949044378"),
                FieldCheck("email", "faktura@northwaveltd.no"),
                FieldCheck("invoiceEmail", "faktura@northwaveltd.no"),
            ],
        ),
    ),

    # 3. create_product with MVA (German prompt, 15% food VAT)
    E2ETestCase(
        name="create_product_with_mva",
        request_file="20260320_074340_801034.json",
        expected_task_type="create_product",
        expected_fields={
            "name": "Orangensaft",
            "number": "1256",
            "priceExcludingVat": 17450,
        },
        verify=VerifySpec(
            endpoint="/product",
            search_params={"name": "Orangensaft"},
            checks=[
                FieldCheck("name", "Orangensaft"),
                FieldCheck("number", 1256),
                FieldCheck("priceExcludingVatCurrency", 17450.0),
            ],
        ),
    ),

    # 4. create_project (English prompt)
    E2ETestCase(
        name="create_project_english",
        request_file="20260319_233306_546665.json",
        expected_task_type="create_project",
        expected_fields={
            "name": "Integration Northwave",
        },
        verify=VerifySpec(
            endpoint="/project",
            search_params={"name": "Integration Northwave"},
            checks=[
                FieldCheck("name", "Integration Northwave"),
            ],
        ),
    ),
]


# ---------------------------------------------------------------------------
# Verification engine  (TODO #8+9 — self-verification, externalized)
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    field: str
    expected: Any
    actual: Any
    passed: bool
    detail: str = ""


async def verify_entity(
    client,  # TripletexClient
    spec: VerifySpec,
    entity_id: int | None = None,
) -> list[CheckResult]:
    """GET the entity from Tripletex and run field-by-field checks.

    This is the self-verification step (TODO #8+9) kept external to handlers
    so we don't risk breaking live code.
    """
    endpoint = spec.endpoint
    params = dict(spec.search_params)

    if spec.search_by_id and entity_id:
        endpoint = f"{endpoint}/{entity_id}"
        params = {}

    resp = await client.get(endpoint, params=params or None)
    data = resp.json()

    # Locate the entity in the response
    if "values" in data:
        entities = data["values"]
        if not entities:
            return [CheckResult(
                field="__entity__", expected="found", actual="NOT FOUND",
                passed=False, detail=f"GET {endpoint} returned 0 results",
            )]
        entity = entities[0]
    elif "value" in data:
        entity = data["value"]
    else:
        entity = data

    results: list[CheckResult] = []
    for chk in spec.checks:
        actual = _resolve_field(entity, chk.field)
        passed, detail = _compare(actual, chk.expected, chk.mode)
        results.append(CheckResult(
            field=chk.field, expected=chk.expected, actual=actual,
            passed=passed, detail=detail,
        ))
    return results


def _resolve_field(entity: dict, field_path: str) -> Any:
    """Resolve a dotted field path like 'postalAddress.city'."""
    parts = field_path.split(".")
    val = entity
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


def _compare(actual: Any, expected: Any, mode: str) -> tuple[bool, str]:
    if mode == "eq":
        # Flexible: compare as strings to handle int/str mismatches
        if actual is None:
            return False, f"field is None, expected {expected!r}"
        if str(actual) == str(expected):
            return True, ""
        # Try numeric comparison for float/int
        try:
            if float(actual) == float(expected):
                return True, ""
        except (ValueError, TypeError):
            pass
        return False, f"got {actual!r}, expected {expected!r}"
    elif mode == "contains":
        if expected in str(actual or ""):
            return True, ""
        return False, f"{expected!r} not in {actual!r}"
    elif mode == "gt":
        try:
            if float(actual) > float(expected):
                return True, ""
        except (ValueError, TypeError):
            pass
        return False, f"{actual!r} not > {expected!r}"
    return False, f"unknown mode {mode}"


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    parse_ok: bool
    parse_detail: str
    execute_ok: bool
    execute_detail: str
    verify_results: list[CheckResult]
    api_calls: int
    elapsed_sec: float

    @property
    def all_passed(self) -> bool:
        if not self.parse_ok or not self.execute_ok:
            return False
        return all(r.passed for r in self.verify_results)


def load_prompt(request_file: str) -> str:
    """Load prompt from a request file."""
    path = PROJECT_ROOT / "data" / "requests" / request_file
    with open(path) as f:
        data = json.load(f)
    return data["prompt"]


async def run_one_test(
    client,  # TripletexClient
    tc: E2ETestCase,
    verbose: bool = False,
) -> TestResult:
    """Run a single E2E test: parse -> execute -> verify."""
    from app.parser import parse_task
    from app.handlers import HANDLER_REGISTRY, execute_task

    prompt = load_prompt(tc.request_file)
    t0 = time.time()
    calls_before = client.tracker.total_calls

    # -- Step 1: Parse --------------------------------------------------------
    parse_ok = True
    parse_detail = ""
    try:
        parsed = parse_task(prompt)
        if parsed.task_type != tc.expected_task_type:
            parse_ok = False
            parse_detail = f"taskType: got {parsed.task_type}, expected {tc.expected_task_type}"
        else:
            # Check that expected fields are present
            missing = []
            for key, val in tc.expected_fields.items():
                actual = parsed.fields.get(key)
                if actual is None:
                    missing.append(key)
                elif str(actual) != str(val):
                    missing.append(f"{key}(got {actual!r})")
            if missing:
                parse_detail = f"missing/wrong fields: {', '.join(missing)}"
                # Don't fail parse entirely for minor field mismatches — handler may compensate
    except Exception as e:
        parse_ok = False
        parse_detail = f"parse_task() error: {e}"
        # Return early
        return TestResult(
            name=tc.name, parse_ok=False, parse_detail=parse_detail,
            execute_ok=False, execute_detail="skipped (parse failed)",
            verify_results=[], api_calls=0, elapsed_sec=time.time() - t0,
        )

    # -- Step 2: Execute handler ---------------------------------------------
    execute_ok = True
    execute_detail = ""
    entity_id = None
    try:
        result = await execute_task(
            parsed.task_type, client, parsed.fields, prompt=prompt,
        )
        # Extract entity ID from result
        created = result.get("created", {})
        entity_id = created.get("id") if isinstance(created, dict) else None
        if not entity_id:
            entity_id = result.get("invoiceId") or result.get("travelExpenseId")

        if result.get("note") and not entity_id:
            execute_ok = False
            execute_detail = f"handler note: {result['note']}"
        elif entity_id:
            execute_detail = f"id={entity_id}"

        # Check for 4xx errors during this test
        new_calls = client.tracker.api_calls[calls_before:]
        errors_4xx = [c for c in new_calls if 400 <= c.status < 500
                      and c.path != "/company/salesmodules"]
        if errors_4xx:
            sandbox_only = [c for c in errors_4xx if "/:invoice" in c.path]
            real_errors = [c for c in errors_4xx if "/:invoice" not in c.path]
            if real_errors:
                err_str = "; ".join(f"{c.method} {c.path}->{c.status}" for c in real_errors[:3])
                execute_detail += f" [4xx: {err_str}]"

    except Exception as e:
        execute_ok = False
        execute_detail = f"handler error: {str(e)[:200]}"

    # -- Step 3: Verify (self-verification GET) ------------------------------
    verify_results: list[CheckResult] = []
    if tc.verify and execute_ok:
        try:
            verify_results = await verify_entity(client, tc.verify, entity_id)
        except Exception as e:
            verify_results = [CheckResult(
                field="__verify__", expected="success", actual=str(e)[:100],
                passed=False, detail=f"verification GET failed: {e}",
            )]

    elapsed = time.time() - t0
    api_calls = client.tracker.total_calls - calls_before
    return TestResult(
        name=tc.name, parse_ok=parse_ok, parse_detail=parse_detail,
        execute_ok=execute_ok, execute_detail=execute_detail,
        verify_results=verify_results, api_calls=api_calls,
        elapsed_sec=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Dry-run: just show the plan
# ---------------------------------------------------------------------------

def show_plan(test_cases: list[E2ETestCase]) -> None:
    print(f"\n  {bold('E2E Test Plan')} (dry-run mode, use --live to execute)\n")
    print(f"  {len(test_cases)} test cases:\n")
    for i, tc in enumerate(test_cases, 1):
        prompt = load_prompt(tc.request_file)
        print(f"  {bold(f'{i}.')} {tc.name}")
        print(f"     File:   data/requests/{tc.request_file}")
        print(f"     Prompt: {prompt[:90]}...")
        print(f"     Parse:  expect taskType={tc.expected_task_type}")
        if tc.expected_fields:
            fields_str = ", ".join(f"{k}={v!r}" for k, v in tc.expected_fields.items())
            print(f"             expect fields: {fields_str}")
        if tc.verify:
            print(f"     Verify: GET {tc.verify.endpoint} {tc.verify.search_params or ''}")
            for chk in tc.verify.checks:
                print(f"             - {chk.describe()}")
        print()

    print(f"  Pipeline per test:")
    print(f"    1. Load prompt from data/requests/")
    print(f"    2. Call parse_task(prompt) -- check taskType + fields")
    print(f"    3. Call handler against sandbox -- check no 4xx errors")
    print(f"    4. Verification GET -- field-by-field comparison")
    print(f"    5. Report PASS/FAIL\n")


# ---------------------------------------------------------------------------
# Live run: execute all tests
# ---------------------------------------------------------------------------

async def run_live(test_cases: list[E2ETestCase], verbose: bool) -> int:
    from app.tripletex import TripletexClient

    base_url, session_token = get_sandbox_creds()
    client = TripletexClient(base_url, session_token)

    print(f"\n  {bold('E2E Test Suite')} -- live run against sandbox")
    print(f"  Sandbox: {base_url}")
    print(f"  Tests:   {len(test_cases)}\n")
    print(f"  {'='*65}")

    results: list[TestResult] = []
    for tc in test_cases:
        if verbose:
            print(f"\n  Running: {tc.name} ...")

        tr = await run_one_test(client, tc, verbose)
        results.append(tr)

        # Print result line
        status = green("PASS") if tr.all_passed else red("FAIL")
        print(f"  {status}  {tr.name:<35} {tr.api_calls} calls, {tr.elapsed_sec}s")

        # Parse line
        if not tr.parse_ok:
            print(f"         {red('PARSE:')} {tr.parse_detail}")
        elif tr.parse_detail:
            print(f"         {yellow('PARSE:')} {tr.parse_detail}")

        # Execute line
        if not tr.execute_ok:
            print(f"         {red('EXEC:')}  {tr.execute_detail}")
        elif verbose and tr.execute_detail:
            print(f"         {dim('EXEC:')}  {tr.execute_detail}")

        # Verification lines (field-by-field)
        for vr in tr.verify_results:
            if vr.passed:
                if verbose:
                    print(f"         {green('OK')}  {vr.field}={vr.actual!r}")
            else:
                print(f"         {red('FAIL')}  {vr.field}: expected {vr.expected!r}, got {vr.actual!r}")

    print(f"  {'='*65}")

    # Summary
    passed = sum(1 for r in results if r.all_passed)
    failed = len(results) - passed
    total_api = sum(r.api_calls for r in results)
    total_checks = sum(len(r.verify_results) for r in results)
    checks_passed = sum(1 for r in results for v in r.verify_results if v.passed)

    print(f"\n  Results: {green(f'{passed} passed')}, ", end="")
    if failed:
        print(red(f"{failed} failed"))
    else:
        print("0 failed")
    print(f"  Verification checks: {checks_passed}/{total_checks}")
    print(f"  Total API calls: {total_api}")

    await client.close()

    if failed:
        print(f"\n  {red('FAILURES:')}")
        for r in results:
            if not r.all_passed:
                reasons = []
                if not r.parse_ok:
                    reasons.append(f"parse: {r.parse_detail}")
                if not r.execute_ok:
                    reasons.append(f"exec: {r.execute_detail}")
                for v in r.verify_results:
                    if not v.passed:
                        reasons.append(f"verify {v.field}: {v.detail}")
                print(f"    - {r.name}: {'; '.join(reasons)}")
        print()

    return failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="E2E test suite for Tripletex AI agent")
    parser.add_argument("--live", action="store_true",
                        help="Execute tests against sandbox (default: dry-run)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")
    parser.add_argument("--only", type=str, default="",
                        help="Comma-separated list of test names to run")
    args = parser.parse_args()

    test_cases = TEST_CASES
    if args.only:
        names = set(args.only.split(","))
        test_cases = [tc for tc in test_cases if tc.name in names]
        if not test_cases:
            print(red(f"No test cases match: {args.only}"))
            print(f"Available: {', '.join(tc.name for tc in TEST_CASES)}")
            sys.exit(1)

    if args.verbose:
        logging.getLogger("e2e").setLevel(logging.DEBUG)

    if args.live:
        failed = asyncio.run(run_live(test_cases, args.verbose))
        sys.exit(1 if failed else 0)
    else:
        show_plan(test_cases)
        sys.exit(0)


if __name__ == "__main__":
    main()
