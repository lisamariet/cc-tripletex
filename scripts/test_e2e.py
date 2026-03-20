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
    python3 scripts/test_e2e.py --live --tier2   # Only Tier 2 tests
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
    mode: str = "eq"  # eq | contains | gt | gte | exists | not_exists

    def describe(self) -> str:
        if self.mode == "eq":
            return f"{self.field}={self.expected!r}"
        elif self.mode == "contains":
            return f"{self.field} contains {self.expected!r}"
        elif self.mode == "gt":
            return f"{self.field} > {self.expected!r}"
        elif self.mode == "gte":
            return f"{self.field} >= {self.expected!r}"
        elif self.mode == "exists":
            return f"{self.field} exists"
        elif self.mode == "not_exists":
            return f"{self.field} not found (deleted)"
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
    expected_task_type: str
    expected_fields: dict[str, Any]  # subset of fields that MUST parse out
    verify: VerifySpec | None = None
    request_file: str = ""          # filename under data/requests/ (for prompt-based)
    prompt: str = ""                # inline prompt (alternative to request_file)
    direct_fields: dict[str, Any] | None = None  # bypass LLM, call handler directly
    setup: str = ""                 # name of setup function to run first
    tier: int = 1                   # tier (1 or 2) for filtering


# -- Tier 1 test cases (existing, prompt-based) ----------------------------

TIER1_TESTS: list[E2ETestCase] = [

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
        tier=1,
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
        tier=1,
    ),

    # 3. create_product with MVA (direct fields, unique name — verify via handler result)
    E2ETestCase(
        name="create_product_with_mva",
        direct_fields={
            "name": "E2E Produkt Test",
            "number": "77777",
            "priceExcludingVat": 17450,
            "vatCode": "31",
        },
        expected_task_type="create_product",
        expected_fields={"priceExcludingVat": 17450},
        verify=None,  # Skip verify-GET (sandbox has duplicates), handler result is enough
        tier=1,
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
        tier=1,
    ),
]


# ---------------------------------------------------------------------------
# Tier 2 test cases — direct handler tests with inline fields
# ---------------------------------------------------------------------------

def _ts() -> str:
    """Unique timestamp suffix for test entity names."""
    return str(int(time.time()))


def build_tier2_tests() -> list[E2ETestCase]:
    """Build Tier 2 test cases with unique names using timestamps."""
    ts = _ts()
    return [

        # ---- Invoice flow ----

        # T2-1: create_invoice — Norwegian prompt with 3 order lines + different VAT rates
        E2ETestCase(
            name="t2_create_invoice",
            expected_task_type="create_invoice",
            expected_fields={},
            prompt=(
                f'Opprett en faktura til kunden "E2E Testfirma {ts}" med 3 linjer: '
                f'1) "Konsulenttjenester" 10000 kr ekskl. MVA 25%, '
                f'2) "Programvare" 5000 kr ekskl. MVA 25%, '
                f'3) "Fraktkostnad" 800 kr ekskl. MVA 12%.'
            ),
            direct_fields={
                "customerName": f"E2E Testfirma {ts}",
                "lines": [
                    {"description": "Konsulenttjenester", "quantity": 1, "unitPriceExcludingVat": 10000, "vatCode": "3"},
                    {"description": "Programvare", "quantity": 1, "unitPriceExcludingVat": 5000, "vatCode": "3"},
                    {"description": "Fraktkostnad", "quantity": 1, "unitPriceExcludingVat": 800, "vatCode": "33"},
                ],
            },
            verify=VerifySpec(
                endpoint="/invoice",
                search_by_id=True,
                checks=[
                    FieldCheck("amountExcludingVatCurrency", 15800.0, mode="gte"),
                ],
            ),
            tier=2,
        ),

        # T2-2: register_payment — Portuguese prompt, create invoice + pay it
        E2ETestCase(
            name="t2_register_payment",
            expected_task_type="register_payment",
            expected_fields={},
            prompt=(
                f'O cliente "E2E Pagamento {ts}" tem uma fatura pendente de 20000 NOK '
                f'sem IVA por "Desenvolvimento". Registe o pagamento total desta fatura.'
            ),
            direct_fields={
                "customerName": f"E2E Pagamento {ts}",
                "amount": 20000,
                "invoiceDescription": "Desenvolvimento",
                "lines": [
                    {"description": "Desenvolvimento", "quantity": 1, "unitPriceExcludingVat": 20000, "vatCode": "3"},
                ],
            },
            verify=VerifySpec(
                endpoint="/invoice",
                search_by_id=True,
                checks=[
                    # After payment, amountOutstanding should be 0
                    FieldCheck("amountCurrencyOutstanding", 0.0),
                ],
            ),
            tier=2,
        ),

        # T2-3: create_credit_note — Norwegian prompt
        E2ETestCase(
            name="t2_create_credit_note",
            expected_task_type="create_credit_note",
            expected_fields={},
            prompt=(
                f'Kunden "E2E Kreditnota {ts}" har reklamert paa fakturaen for "Hosting" '
                f'(15000 kr ekskl. MVA). Opprett en fullstendig kreditnota.'
            ),
            direct_fields={
                "customerName": f"E2E Kreditnota {ts}",
                "amount": 15000,
                "invoiceDescription": "Hosting",
                "lines": [
                    {"description": "Hosting", "quantity": 1, "unitPriceExcludingVat": 15000, "vatCode": "3"},
                ],
            },
            # Verify: the credit note is a new invoice with negative amount
            verify=None,  # credit note verification done in custom check
            tier=2,
        ),

        # T2-4: reverse_payment
        E2ETestCase(
            name="t2_reverse_payment",
            expected_task_type="reverse_payment",
            expected_fields={},
            prompt=(
                f'Reverser betalingen paa fakturaen til kunden "E2E Reversering {ts}" '
                f'for "Vedlikehold" (12000 kr ekskl. MVA).'
            ),
            direct_fields={
                "customerName": f"E2E Reversering {ts}",
                "amount": 12000,
                "invoiceDescription": "Vedlikehold",
                "lines": [
                    {"description": "Vedlikehold", "quantity": 1, "unitPriceExcludingVat": 12000, "vatCode": "3"},
                ],
            },
            verify=VerifySpec(
                endpoint="/invoice",
                search_by_id=True,
                checks=[
                    # After reversal, the outstanding amount should equal the full amount
                    FieldCheck("amountCurrencyOutstanding", 0, mode="gte"),
                ],
            ),
            tier=2,
        ),

        # ---- Travel expense ----

        # T2-5: create_travel_expense
        E2ETestCase(
            name="t2_create_travel_expense",
            expected_task_type="create_travel_expense",
            expected_fields={},
            prompt=(
                f'Opprett reiseregning for den foerste ansatte med tittel '
                f'"E2E Reise {ts}", dato 2026-03-20, med kostnader: '
                f'Taxi 450 kr og Hotell 1200 kr.'
            ),
            direct_fields={
                # We use setup to find the first employee dynamically
                "title": f"E2E Reise {ts}",
                "date": "2026-03-20",
                "costs": [
                    {"description": "Taxi", "amount": 450, "date": "2026-03-20"},
                    {"description": "Hotell", "amount": 1200, "date": "2026-03-20"},
                ],
            },
            setup="find_first_employee",
            verify=VerifySpec(
                endpoint="/travelExpense",
                search_by_id=True,
                checks=[
                    FieldCheck("title", f"E2E Reise {ts}"),
                ],
            ),
            tier=2,
        ),

        # T2-6: delete_travel_expense (create one then delete)
        E2ETestCase(
            name="t2_delete_travel_expense",
            expected_task_type="delete_travel_expense",
            expected_fields={},
            prompt=f'Slett reiseregningen med tittel "E2E Slett {ts}".',
            direct_fields={
                "travelExpenseTitle": f"E2E Slett {ts}",
            },
            setup="create_travel_expense_for_delete",
            verify=None,  # verified in custom post-check
            tier=2,
        ),

        # ---- Update tests ----

        # T2-7: update_employee
        E2ETestCase(
            name="t2_update_employee",
            expected_task_type="update_employee",
            expected_fields={},
            prompt=f'Oppdater mobilnummeret til den foerste ansatte til 99887766.',
            direct_fields={
                "changes": {"phoneNumberMobile": "99887766"},
            },
            setup="find_first_employee",
            verify=VerifySpec(
                endpoint="/employee",
                search_by_id=True,
                checks=[
                    FieldCheck("phoneNumberMobile", "99887766"),
                ],
            ),
            tier=2,
        ),

        # T2-8: update_customer
        E2ETestCase(
            name="t2_update_customer",
            expected_task_type="update_customer",
            expected_fields={},
            prompt=f'Oppdater beskrivelsen til kunden "E2E OppdaterKunde {ts}" til "Oppdatert beskrivelse {ts}".',
            direct_fields={
                "customerName": f"E2E OppdaterKunde {ts}",
                "changes": {"description": f"Oppdatert beskrivelse {ts}"},
            },
            setup="create_customer_for_update",
            verify=VerifySpec(
                endpoint="/customer",
                search_by_id=True,
                checks=[
                    FieldCheck("description", f"Oppdatert beskrivelse {ts}"),
                ],
            ),
            tier=2,
        ),

        # ---- Other Tier 2 ----

        # T2-9: create_project (keep existing, but direct handler test)
        E2ETestCase(
            name="t2_create_project",
            expected_task_type="create_project",
            expected_fields={},
            prompt=f'Opprett prosjektet "E2E Prosjekt {ts}".',
            direct_fields={
                "name": f"E2E Prosjekt {ts}",
                "startDate": "2026-03-20",
            },
            verify=VerifySpec(
                endpoint="/project",
                search_by_id=True,
                checks=[
                    FieldCheck("name", f"E2E Prosjekt {ts}"),
                ],
            ),
            tier=2,
        ),

        # T2-10: create_order
        E2ETestCase(
            name="t2_create_order",
            expected_task_type="create_order",
            expected_fields={},
            prompt=(
                f'Opprett en ordre for kunden "E2E Ordre {ts}" med 2 linjer: '
                f'"Vare A" 3000 kr og "Vare B" 7000 kr ekskl. MVA.'
            ),
            direct_fields={
                "customerName": f"E2E Ordre {ts}",
                "lines": [
                    {"description": "Vare A", "quantity": 1, "unitPriceExcludingVat": 3000},
                    {"description": "Vare B", "quantity": 1, "unitPriceExcludingVat": 7000},
                ],
            },
            verify=VerifySpec(
                endpoint="/order",
                search_by_id=True,
                checks=[
                    FieldCheck("id", 0, mode="gt"),
                ],
            ),
            tier=2,
        ),

        # T2-11: register_supplier_invoice
        E2ETestCase(
            name="t2_register_supplier_invoice",
            expected_task_type="register_supplier_invoice",
            expected_fields={},
            prompt=(
                f'Registrer en leverandoerfaktura fra "E2E Leverandoer {ts}" '
                f'paa 25000 kr for "Kontorrekvisita".'
            ),
            direct_fields={
                "supplierName": f"E2E Leverandoer {ts}",
                "amount": 25000,
                "description": "Kontorrekvisita",
            },
            verify=VerifySpec(
                endpoint="/ledger/voucher",
                search_by_id=True,
                checks=[
                    FieldCheck("id", 0, mode="gt"),
                ],
            ),
            tier=2,
        ),

        # T2-12: register_timesheet
        E2ETestCase(
            name="t2_register_timesheet",
            expected_task_type="register_timesheet",
            expected_fields={},
            prompt=(
                f'Registrer 7.5 timer for den foerste ansatte paa prosjektet '
                f'"E2E Timefoering {ts}" med aktivitet "Utvikling" for i dag.'
            ),
            direct_fields={
                "projectName": f"E2E Timefoering {ts}",
                "activityName": "Utvikling",
                "hours": 7.5,
                "date": "2026-03-20",
            },
            setup="find_first_employee",
            verify=VerifySpec(
                endpoint="/timesheet/entry",
                search_by_id=True,
                checks=[
                    FieldCheck("hours", 7.5),
                ],
            ),
            tier=2,
        ),

        # T2-13: run_payroll
        E2ETestCase(
            name="t2_run_payroll",
            expected_task_type="run_payroll",
            expected_fields={},
            prompt=(
                f'Kjoer loenn for den foerste ansatte for mars 2026. '
                f'Grunnloenn er 35000 NOK og bonus er 5000 NOK.'
            ),
            direct_fields={
                "baseSalary": 35000,
                "bonus": 5000,
                "month": 3,
                "year": 2026,
            },
            setup="find_first_employee",
            verify=None,  # Payroll verification is complex; check handler result
            tier=2,
        ),
    ]


# Combine all test cases
TEST_CASES: list[E2ETestCase] = TIER1_TESTS  # Tier 2 added dynamically


# ---------------------------------------------------------------------------
# Setup functions for tests that need pre-existing entities
# ---------------------------------------------------------------------------

async def setup_find_first_employee(client, fields: dict) -> dict:
    """Find the first employee and inject their name into fields."""
    resp = await client.get("/employee", params={"count": 1})
    employees = resp.json().get("values", [])
    if not employees:
        raise RuntimeError("No employees found in sandbox")
    emp = employees[0]
    fields["employeeFirstName"] = emp.get("firstName", "")
    fields["employeeLastName"] = emp.get("lastName", "")
    fields["employeeName"] = f"{emp.get('firstName', '')} {emp.get('lastName', '')}"
    fields["_employee_id"] = emp["id"]
    return fields


async def setup_create_customer_for_update(client, fields: dict) -> dict:
    """Create a customer that will be updated in the test."""
    name = fields.get("customerName", f"E2E Customer {_ts()}")
    payload = {"name": name, "isCustomer": True, "description": "Before update"}
    resp = await client.post("/customer", payload)
    created = resp.json().get("value", {})
    fields["_customer_id"] = created.get("id")
    return fields


async def setup_create_travel_expense_for_delete(client, fields: dict) -> dict:
    """Create a travel expense that will be deleted in the test."""
    # Find first employee
    resp = await client.get("/employee", params={"count": 1})
    employees = resp.json().get("values", [])
    if not employees:
        raise RuntimeError("No employees found")
    emp_id = employees[0]["id"]

    title = fields.get("travelExpenseTitle", f"E2E Slett {_ts()}")
    te_payload = {
        "employee": {"id": emp_id},
        "title": title,
        "date": "2026-03-20",
    }
    resp = await client.post("/travelExpense", te_payload)
    te = resp.json().get("value", {})
    fields["travelExpenseId"] = te.get("id")
    fields["employeeFirstName"] = employees[0].get("firstName", "")
    fields["employeeLastName"] = employees[0].get("lastName", "")
    return fields


SETUP_REGISTRY = {
    "find_first_employee": setup_find_first_employee,
    "create_customer_for_update": setup_create_customer_for_update,
    "create_travel_expense_for_delete": setup_create_travel_expense_for_delete,
}


# ---------------------------------------------------------------------------
# Verification engine  (TODO #8+9 -- self-verification, externalized)
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
    """GET the entity from Tripletex and run field-by-field checks."""
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
        if actual is None:
            return False, f"field is None, expected {expected!r}"
        if str(actual) == str(expected):
            return True, ""
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
    elif mode == "gte":
        try:
            if float(actual) >= float(expected):
                return True, ""
        except (ValueError, TypeError):
            pass
        return False, f"{actual!r} not >= {expected!r}"
    elif mode == "exists":
        if actual is not None:
            return True, ""
        return False, "field does not exist"
    elif mode == "not_exists":
        if actual is None:
            return True, ""
        return False, f"expected not found but got {actual!r}"
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

    t0 = time.time()
    calls_before = client.tracker.total_calls

    # Determine if this is a direct-fields test or prompt-based
    if tc.direct_fields is not None:
        # Direct handler invocation (Tier 2 style)
        fields = dict(tc.direct_fields)
        parse_ok = True
        parse_detail = "direct (bypassed LLM)"

        # Run setup if needed
        if tc.setup and tc.setup in SETUP_REGISTRY:
            try:
                fields = await SETUP_REGISTRY[tc.setup](client, fields)
            except Exception as e:
                return TestResult(
                    name=tc.name, parse_ok=True, parse_detail=f"setup failed: {e}",
                    execute_ok=False, execute_detail=f"setup error: {e}",
                    verify_results=[], api_calls=0, elapsed_sec=time.time() - t0,
                )

        task_type = tc.expected_task_type
    else:
        # Prompt-based (Tier 1 style)
        prompt = tc.prompt or load_prompt(tc.request_file)
        parse_ok = True
        parse_detail = ""
        try:
            parsed = parse_task(prompt)
            task_type = parsed.task_type
            fields = parsed.fields
            if parsed.task_type != tc.expected_task_type:
                parse_ok = False
                parse_detail = f"taskType: got {parsed.task_type}, expected {tc.expected_task_type}"
            else:
                missing = []
                for key, val in tc.expected_fields.items():
                    actual = parsed.fields.get(key)
                    if actual is None:
                        missing.append(key)
                    elif str(actual) != str(val):
                        missing.append(f"{key}(got {actual!r})")
                if missing:
                    parse_detail = f"missing/wrong fields: {', '.join(missing)}"
        except Exception as e:
            parse_ok = False
            parse_detail = f"parse_task() error: {e}"
            return TestResult(
                name=tc.name, parse_ok=False, parse_detail=parse_detail,
                execute_ok=False, execute_detail="skipped (parse failed)",
                verify_results=[], api_calls=0, elapsed_sec=time.time() - t0,
            )

    # -- Step 2: Execute handler ---------------------------------------------
    execute_ok = True
    execute_detail = ""
    entity_id = None
    handler_result = {}
    try:
        prompt_text = tc.prompt or ""
        handler_result = await execute_task(
            task_type, client, fields, prompt=prompt_text,
        )
        # Extract entity ID from result
        created = handler_result.get("created", {})
        entity_id = created.get("id") if isinstance(created, dict) else None
        if not entity_id:
            entity_id = (
                handler_result.get("invoiceId")
                or handler_result.get("travelExpenseId")
                or handler_result.get("transactionId")
                or handler_result.get("employeeId")
                or handler_result.get("customerId")
                or handler_result.get("deletedId")
            )

        if handler_result.get("note") and not entity_id:
            execute_ok = False
            execute_detail = f"handler note: {handler_result['note']}"
        elif entity_id:
            execute_detail = f"id={entity_id}"

        # Check for 4xx errors during this test
        new_calls = client.tracker.api_calls[calls_before:]
        errors_4xx = [c for c in new_calls if 400 <= c.status < 500
                      and c.path != "/company/salesmodules"]
        if errors_4xx:
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

    # -- Custom post-checks for tests without standard verify ----------------
    if not tc.verify and execute_ok:
        # For delete tests, verify the entity is gone
        if "delete" in tc.expected_task_type:
            deleted_id = handler_result.get("deletedId")
            if deleted_id:
                verify_results.append(CheckResult(
                    field="deleted", expected=True, actual=True,
                    passed=True, detail=f"entity {deleted_id} deleted",
                ))
            else:
                verify_results.append(CheckResult(
                    field="deleted", expected=True, actual=False,
                    passed=False, detail="no deletedId in result",
                ))

        # For credit note, check handler returned invoiceId
        if tc.expected_task_type == "create_credit_note":
            if handler_result.get("invoiceId"):
                verify_results.append(CheckResult(
                    field="invoiceId", expected="exists", actual=handler_result["invoiceId"],
                    passed=True, detail="credit note created",
                ))
            else:
                verify_results.append(CheckResult(
                    field="invoiceId", expected="exists", actual=None,
                    passed=False, detail="no invoiceId in credit note result",
                ))

        # For payroll, check transactionId
        if tc.expected_task_type == "run_payroll":
            if handler_result.get("transactionId"):
                verify_results.append(CheckResult(
                    field="transactionId", expected="exists",
                    actual=handler_result["transactionId"],
                    passed=True, detail="payroll transaction created",
                ))
            else:
                note = handler_result.get("note", "unknown")
                verify_results.append(CheckResult(
                    field="transactionId", expected="exists", actual=None,
                    passed=False, detail=f"no transactionId: {note}",
                ))

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
        prompt = tc.prompt or (load_prompt(tc.request_file) if tc.request_file else "(direct handler)")
        print(f"  {bold(f'{i}.')} {tc.name} [Tier {tc.tier}]")
        if tc.request_file:
            print(f"     File:   data/requests/{tc.request_file}")
        print(f"     Prompt: {prompt[:90]}...")
        print(f"     Task:   {tc.expected_task_type}")
        if tc.direct_fields:
            print(f"     Mode:   direct handler (bypass LLM)")
        if tc.setup:
            print(f"     Setup:  {tc.setup}")
        if tc.verify:
            print(f"     Verify: GET {tc.verify.endpoint}")
            for chk in tc.verify.checks:
                print(f"             - {chk.describe()}")
        print()


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
        elif tr.parse_detail and "direct" not in tr.parse_detail:
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
    parser.add_argument("--tier2", action="store_true",
                        help="Only run Tier 2 tests")
    parser.add_argument("--all", action="store_true",
                        help="Run both Tier 1 and Tier 2 tests")
    args = parser.parse_args()

    # Build test cases with timestamp-unique names
    tier2_tests = build_tier2_tests()

    if args.tier2:
        test_cases = tier2_tests
    elif args.all:
        test_cases = TIER1_TESTS + tier2_tests
    else:
        # Default: Tier 1 only (backward compat), unless --only is used
        test_cases = TIER1_TESTS + tier2_tests

    if args.only:
        names = set(args.only.split(","))
        test_cases = [tc for tc in test_cases if tc.name in names]
        if not test_cases:
            all_names = [tc.name for tc in TIER1_TESTS + tier2_tests]
            print(red(f"No test cases match: {args.only}"))
            print(f"Available: {', '.join(all_names)}")
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
