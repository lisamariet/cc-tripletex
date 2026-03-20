#!/usr/bin/env python3
"""Validate handler payloads against the Tripletex OpenAPI spec.

Statically analyses handler source code to find all client.post() and
client.put() calls, extracts the endpoint paths and payload field names,
and validates them against the OpenAPI spec.

Usage:
    python -m scripts.validate_handlers
    # or
    python scripts/validate_handlers.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.api_validator import (
    get_valid_fields,
    get_schema_name,
    validate_payload,
    get_all_endpoints,
    _schema_lookup,
)


# ---------------------------------------------------------------------------
# AST-based payload extraction
# ---------------------------------------------------------------------------

class PayloadExtractor(ast.NodeVisitor):
    """Walk an AST and extract (endpoint, payload_keys) from client.post/put calls."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.results: list[dict] = []

    def visit_Call(self, node: ast.Call) -> None:
        # Match: client.post("/path", payload) or await client.post("/path", payload)
        # Also: self.post, self.put  (but we focus on client.post/put patterns)
        method_name = None
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
        if method_name not in ("post", "put"):
            self.generic_visit(node)
            return

        http_method = method_name.upper()

        # Extract the path argument (first positional arg or 'path' kwarg)
        path = None
        if node.args:
            path = self._extract_string(node.args[0])

        # Extract payload argument (second positional or 'payload' kwarg)
        payload_node = None
        if len(node.args) >= 2:
            payload_node = node.args[1]
        for kw in node.keywords:
            if kw.arg in ("payload", "json_body"):
                payload_node = kw.value
            if kw.arg == "path" and path is None:
                path = self._extract_string(kw.value)

        if path and payload_node:
            keys = self._extract_dict_keys(payload_node)
            if keys is not None:
                self.results.append({
                    "method": http_method,
                    "path": path,
                    "keys": keys,
                    "line": node.lineno,
                })

        self.generic_visit(node)

    def _extract_string(self, node: ast.expr) -> str | None:
        """Try to extract a string literal from an AST node."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        # Handle f-strings like f"/supplier/{supplier_id}" — extract the base path
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    parts.append("{id}")  # Replace format expressions with {id}
            return "".join(parts)
        return None

    def _extract_dict_keys(self, node: ast.expr) -> set[str] | None:
        """Extract top-level key names from a dict literal or variable assignment."""
        if isinstance(node, ast.Dict):
            keys = set()
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
            return keys if keys else None

        if isinstance(node, ast.Name):
            # Variable reference — we can't resolve it statically in all cases
            # but we track the common pattern of building a dict then passing it
            return None

        return None


def extract_payloads_from_file(filepath: Path) -> list[dict]:
    """Parse a Python file and extract all POST/PUT payload field names."""
    source = filepath.read_text()
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    extractor = PayloadExtractor(str(filepath))
    extractor.visit(tree)
    return extractor.results


# ---------------------------------------------------------------------------
# Known payload mappings (supplement static analysis with manually tracked payloads)
#
# These cover payloads built incrementally (dict literal + .update()) that
# the AST extractor can't fully capture.
# ---------------------------------------------------------------------------

KNOWN_PAYLOADS: list[dict] = [
    # tier1.py — create_supplier
    {
        "handler": "create_supplier",
        "method": "POST",
        "path": "/supplier",
        "keys": {
            "name", "organizationNumber", "email", "invoiceEmail",
            "phoneNumber", "phoneNumberMobile", "isPrivateIndividual",
            "description", "bankAccount", "website", "overdueNoticeEmail",
            "language", "postalAddress", "physicalAddress",
        },
    },
    # tier1.py — create_customer
    {
        "handler": "create_customer",
        "method": "POST",
        "path": "/customer",
        "keys": {
            "name", "isCustomer", "organizationNumber", "email", "invoiceEmail",
            "phoneNumber", "phoneNumberMobile", "isPrivateIndividual",
            "description", "isSupplier", "website", "overdueNoticeEmail",
            "language", "postalAddress", "physicalAddress",
        },
    },
    # tier1.py — create_employee
    {
        "handler": "create_employee",
        "method": "POST",
        "path": "/employee",
        "keys": {
            "firstName", "lastName", "email", "phoneNumberMobile",
            "dateOfBirth", "employeeNumber", "nationalIdentityNumber",
            "bankAccountNumber", "iban", "userType", "department", "address",
        },
    },
    # tier1.py — create_product
    {
        "handler": "create_product",
        "method": "POST",
        "path": "/product",
        "keys": {
            "name", "number", "description", "isInactive",
            "priceExcludingVatCurrency", "priceIncludingVatCurrency",
            "costExcludingVatCurrency", "vatType",
        },
    },
    # tier1.py — create_department
    {
        "handler": "create_department",
        "method": "POST",
        "path": "/department",
        "keys": {"name", "departmentNumber"},
    },
    # tier2_invoice.py — create_invoice order payload
    {
        "handler": "create_invoice (order)",
        "method": "POST",
        "path": "/order",
        "keys": {"customer", "orderDate", "deliveryDate", "orderLines"},
    },
    # tier2_travel.py — create_travel_expense
    {
        "handler": "create_travel_expense",
        "method": "POST",
        "path": "/travelExpense",
        "keys": {"employee", "title", "date"},
    },
    # tier2_travel.py — travel expense cost line
    {
        "handler": "create_travel_expense (cost)",
        "method": "POST",
        "path": "/travelExpense/cost",
        "keys": {
            "travelExpense", "date", "amountCurrencyIncVat",
            "costCategory", "paymentType",
        },
    },
    # tier2_project.py — create_project
    {
        "handler": "create_project",
        "method": "POST",
        "path": "/project",
        "keys": {
            "name", "isInternal", "projectManager", "customer",
            "startDate", "endDate", "isClosed",
        },
    },
    # tier3.py — create_voucher
    {
        "handler": "create_voucher",
        "method": "POST",
        "path": "/ledger/voucher",
        "keys": {"date", "description", "postings"},
    },
    # tier3.py — voucher posting (nested in postings array)
    {
        "handler": "create_voucher (posting)",
        "method": "POST",
        "path": "/ledger/posting",
        "keys": {"account", "amountGross", "amountGrossCurrency", "row", "vatType"},
    },
    # tier2_extra.py — create_order
    {
        "handler": "create_order",
        "method": "POST",
        "path": "/order",
        "keys": {"customer", "orderDate", "deliveryDate", "orderLines"},
    },
    # tier2_extra.py — register_supplier_invoice (voucher)
    {
        "handler": "register_supplier_invoice",
        "method": "POST",
        "path": "/ledger/voucher",
        "keys": {"date", "description", "postings"},
    },
    # tier2_extra.py — timesheet entry
    {
        "handler": "register_timesheet",
        "method": "POST",
        "path": "/timesheet/entry",
        "keys": {"employee", "project", "activity", "date", "hours", "comment"},
    },
    # tier2_extra.py — salary transaction
    {
        "handler": "run_payroll",
        "method": "POST",
        "path": "/ledger/voucher",
        "keys": {"date", "description", "postings"},
    },
    # tier2_extra.py — employment
    {
        "handler": "ensure_employment",
        "method": "POST",
        "path": "/employee/employment",
        "keys": {
            "employee", "startDate", "division",
            "isMainEmployer", "taxDeductionCode",
        },
    },
    # tier2_extra.py — division
    {
        "handler": "ensure_division",
        "method": "POST",
        "path": "/division",
        "keys": {
            "name", "startDate", "organizationNumber",
            "municipality", "municipalityDate",
        },
    },
    # tier2_extra.py — activity
    {
        "handler": "find_or_create_activity",
        "method": "POST",
        "path": "/activity",
        "keys": {"name", "activityType"},
    },
]


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate_all() -> list[dict]:
    """Run validation on all known handler payloads and return issues."""
    issues: list[dict] = []

    # 1. Validate known (manually tracked) payloads
    for entry in KNOWN_PAYLOADS:
        method = entry["method"]
        path = entry["path"]
        handler = entry.get("handler", "?")
        keys = entry["keys"]

        # Build a dummy payload dict for validation
        dummy = {k: "dummy" for k in keys}
        errors = validate_payload(method, path, dummy)
        if errors:
            issues.append({
                "source": f"known:{handler}",
                "method": method,
                "path": path,
                "errors": errors,
            })

    # 2. AST-based extraction from handler files
    handlers_dir = PROJECT_ROOT / "app" / "handlers"
    for py_file in sorted(handlers_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        payloads = extract_payloads_from_file(py_file)
        for p in payloads:
            dummy = {k: "dummy" for k in p["keys"]}
            errors = validate_payload(p["method"], p["path"], dummy)
            if errors:
                issues.append({
                    "source": f"{py_file.name}:{p['line']}",
                    "method": p["method"],
                    "path": p["path"],
                    "errors": errors,
                })

    return issues


def main() -> None:
    print("=" * 72)
    print("Tripletex Handler Payload Validator")
    print(f"OpenAPI endpoints indexed: {len(_schema_lookup)}")
    print("=" * 72)
    print()

    issues = validate_all()

    if not issues:
        print("All handler payloads are valid against the OpenAPI spec.")
        return

    total_errors = 0
    for issue in issues:
        print(f"--- {issue['source']}  {issue['method']} {issue['path']} ---")
        for err in issue["errors"]:
            print(f"  {err}")
            total_errors += 1
        print()

    print(f"Found {total_errors} field issue(s) across {len(issues)} endpoint call(s).")
    sys.exit(1)


if __name__ == "__main__":
    main()
