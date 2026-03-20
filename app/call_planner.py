"""API call planner — hardcoded optimal call sequences for known task types.

This module defines the minimal, optimal sequence of API calls for each task type,
based on experience and knowledge of the Tripletex API. No LLM is used here.

The plan can be used for:
  1. Documentation: see exactly which calls each handler makes
  2. Future optimization: compare actual calls vs. planned calls
  3. Debugging: identify unnecessary calls
"""
from __future__ import annotations

from typing import Any


def plan_api_calls(task_type: str, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the optimal sequence of API calls for a given task type.

    Each call is a dict with:
      - method: HTTP method (GET, POST, PUT, DELETE)
      - path: API path
      - description: what this call does
      - conditional: bool, True if this call may be skipped
      - payload_fields: list of field names used (for POST/PUT)
      - params: dict of query params (for GET)
    """
    planner = _PLANNERS.get(task_type)
    if planner:
        return planner(fields)
    return []


# ---------------------------------------------------------------------------
# Individual planners
# ---------------------------------------------------------------------------

def _plan_create_supplier(fields: dict) -> list[dict]:
    return [
        {"method": "POST", "path": "/supplier", "description": "Create supplier",
         "payload_fields": ["name", "organizationNumber", "email", "invoiceEmail"],
         "conditional": False},
    ]


def _plan_create_customer(fields: dict) -> list[dict]:
    return [
        {"method": "POST", "path": "/customer", "description": "Create customer",
         "payload_fields": ["name", "organizationNumber", "email", "invoiceEmail", "isCustomer"],
         "conditional": False},
    ]


def _plan_create_employee(fields: dict) -> list[dict]:
    calls = []
    if not fields.get("departmentId"):
        calls.append(
            {"method": "GET", "path": "/department", "description": "Find default department (cached)",
             "params": {"count": 1, "fields": "id,name"}, "conditional": True},
        )
    calls.append(
        {"method": "POST", "path": "/employee", "description": "Create employee",
         "payload_fields": ["firstName", "lastName", "email", "userType", "department"],
         "conditional": False},
    )
    if fields.get("role"):
        calls.append(
            {"method": "PUT", "path": "/employee/entitlement/:grantEntitlementsByTemplate",
             "description": "Grant role entitlements",
             "params": {"employeeId": "...", "template": "..."},
             "conditional": True},
        )
    if fields.get("startDate"):
        calls.append(
            {"method": "POST", "path": "/employee/employment",
             "description": "Create employment record with startDate",
             "conditional": True},
        )
    return calls


def _plan_create_product(fields: dict) -> list[dict]:
    calls = []
    if fields.get("vatCode") and fields["vatCode"] not in ("3", "31", "33", "5", "6"):
        calls.append(
            {"method": "GET", "path": "/ledger/vatType",
             "description": "Look up VAT type (cached, only for non-standard codes)",
             "conditional": True},
        )
    calls.append(
        {"method": "POST", "path": "/product", "description": "Create product",
         "payload_fields": ["name", "number", "priceExcludingVatCurrency", "vatType"],
         "conditional": False},
    )
    return calls


def _plan_create_department(fields: dict) -> list[dict]:
    return [
        {"method": "POST", "path": "/department", "description": "Create department",
         "payload_fields": ["name", "departmentNumber"], "conditional": False},
    ]


def _plan_create_invoice(fields: dict) -> list[dict]:
    return [
        {"method": "GET", "path": "/invoice/settings", "description": "Check bank account ready (cached)",
         "conditional": False},
        # Bank account setup only if not ready (0-3 extra calls)
        {"method": "POST", "path": "/customer", "description": "Create customer directly",
         "conditional": False},
        {"method": "POST", "path": "/order", "description": "Create order with lines",
         "conditional": False},
        {"method": "PUT", "path": "/order/{id}/:invoice", "description": "Invoice the order",
         "conditional": False},
    ]


def _plan_register_payment(fields: dict) -> list[dict]:
    return [
        # _ensure_invoice_exists: bank account check + find/create customer + order + invoice
        {"method": "GET", "path": "/invoice/settings", "description": "Check bank account (cached)",
         "conditional": False},
        {"method": "POST", "path": "/customer", "description": "Create customer",
         "conditional": False},
        {"method": "POST", "path": "/order", "description": "Create order",
         "conditional": False},
        {"method": "PUT", "path": "/order/{id}/:invoice", "description": "Invoice order",
         "conditional": False},
        {"method": "GET", "path": "/invoice/{id}", "description": "Get invoice details",
         "conditional": False},
        {"method": "GET", "path": "/invoice/paymentType", "description": "Get payment type (cached)",
         "conditional": False},
        {"method": "PUT", "path": "/invoice/{id}/:payment", "description": "Register payment",
         "conditional": False},
    ]


def _plan_reverse_payment(fields: dict) -> list[dict]:
    plan = _plan_register_payment(fields)
    plan.append(
        {"method": "PUT", "path": "/invoice/{id}/:payment",
         "description": "Reverse payment (negative amount)", "conditional": True},
    )
    return plan


def _plan_create_credit_note(fields: dict) -> list[dict]:
    return [
        # _ensure_invoice_exists chain
        {"method": "GET", "path": "/invoice/settings", "description": "Check bank account (cached)",
         "conditional": False},
        {"method": "POST", "path": "/customer", "description": "Create customer",
         "conditional": False},
        {"method": "POST", "path": "/order", "description": "Create order",
         "conditional": False},
        {"method": "PUT", "path": "/order/{id}/:invoice", "description": "Invoice order",
         "conditional": False},
        {"method": "GET", "path": "/invoice/{id}", "description": "Get full invoice",
         "conditional": False},
        {"method": "PUT", "path": "/invoice/{id}/:createCreditNote",
         "description": "Create credit note", "conditional": False},
    ]


def _plan_create_travel_expense(fields: dict) -> list[dict]:
    calls = [
        {"method": "GET", "path": "/employee", "description": "Find employee",
         "conditional": False},
        {"method": "POST", "path": "/travelExpense", "description": "Create travel expense",
         "conditional": False},
        {"method": "GET", "path": "/travelExpense/costCategory",
         "description": "Get cost category (cached)", "conditional": False},
        {"method": "GET", "path": "/travelExpense/paymentType",
         "description": "Get payment type (cached)", "conditional": False},
    ]
    # One POST per cost line
    for i, cost in enumerate(fields.get("costs", [])):
        calls.append(
            {"method": "POST", "path": "/travelExpense/cost",
             "description": f"Add cost line {i+1}", "conditional": False},
        )
    return calls


def _plan_register_timesheet(fields: dict) -> list[dict]:
    calls = [
        {"method": "GET", "path": "/employee", "description": "Find employee",
         "conditional": False},
        {"method": "GET", "path": "/project", "description": "Find project",
         "conditional": False},
        # If project not found: GET /employee (for PM) + POST /project
        {"method": "GET", "path": "/activity", "description": "Find activity",
         "conditional": False},
        # If activity not found: POST /activity
        {"method": "POST", "path": "/timesheet/entry", "description": "Create timesheet entry",
         "conditional": False},
    ]
    return calls


def _plan_create_voucher(fields: dict) -> list[dict]:
    calls = []
    # Account lookups (cached)
    seen_accounts = set()
    for p in fields.get("postings", []):
        for key in ("debitAccount", "creditAccount"):
            acct = p.get(key)
            if acct and acct not in seen_accounts:
                seen_accounts.add(acct)
                calls.append(
                    {"method": "GET", "path": "/ledger/account",
                     "description": f"Look up account {acct} (cached)",
                     "conditional": False},
                )
    calls.append(
        {"method": "POST", "path": "/ledger/voucher", "description": "Create voucher",
         "conditional": False},
    )
    return calls


def _plan_register_supplier_invoice(fields: dict) -> list[dict]:
    return [
        {"method": "GET", "path": "/supplier", "description": "Find supplier",
         "conditional": False},
        # If not found: POST /supplier
        {"method": "GET", "path": "/ledger/account", "description": "Look up expense account (cached)",
         "conditional": False},
        {"method": "GET", "path": "/ledger/account", "description": "Look up AP account 2400 (cached)",
         "conditional": False},
        {"method": "GET", "path": "/ledger/voucherType",
         "description": "Look up Leverandorfaktura type (cached)", "conditional": False},
        {"method": "GET", "path": "/ledger/vatType",
         "description": "Look up input VAT type (cached)", "conditional": False},
        {"method": "POST", "path": "/ledger/voucher", "description": "Create voucher",
         "conditional": False},
    ]


def _plan_run_payroll(fields: dict) -> list[dict]:
    return [
        {"method": "GET", "path": "/employee", "description": "Find employee",
         "conditional": False},
        # dateOfBirth update if missing (conditional)
        {"method": "GET", "path": "/division", "description": "Find division",
         "conditional": False},
        # If no division: GET /municipality + POST /division
        {"method": "GET", "path": "/employee/employment",
         "description": "Check employment", "conditional": False},
        # If no employment: POST /employee/employment
        {"method": "GET", "path": "/ledger/account",
         "description": "Look up salary account 5000 (cached)", "conditional": False},
        {"method": "GET", "path": "/ledger/account",
         "description": "Look up bank account 1920 (cached)", "conditional": False},
        {"method": "POST", "path": "/ledger/voucher",
         "description": "Create payroll voucher (manual posting)", "conditional": False},
    ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PLANNERS: dict[str, Any] = {
    "create_supplier": _plan_create_supplier,
    "create_customer": _plan_create_customer,
    "create_employee": _plan_create_employee,
    "create_product": _plan_create_product,
    "create_department": _plan_create_department,
    "create_invoice": _plan_create_invoice,
    "register_payment": _plan_register_payment,
    "reverse_payment": _plan_reverse_payment,
    "create_credit_note": _plan_create_credit_note,
    "create_travel_expense": _plan_create_travel_expense,
    "register_timesheet": _plan_register_timesheet,
    "create_voucher": _plan_create_voucher,
    "register_supplier_invoice": _plan_register_supplier_invoice,
    "run_payroll": _plan_run_payroll,
}
