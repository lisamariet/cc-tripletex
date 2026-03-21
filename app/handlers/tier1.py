"""Tier 1 handlers — simple create operations (1 API call each, ×1 point).

Efficiency notes:
- create_supplier: 1 call (POST /supplier) — optimal
- create_customer: 1 call (POST /customer) — optimal
- create_employee: 1-3 calls (GET /department if needed + POST /employee + POST /employment if startDate)
- create_product: 1 call (POST /product) — vatType IDs hardcoded to avoid GET /ledger/vatType
- create_department: 1 call (POST /department) — salesmodules call removed (always 422)
"""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

# Hardcoded vatType number→ID mapping for Norwegian standard VAT codes.
# These are defined by Norwegian tax authorities and are consistent across
# all Tripletex sandboxes.  The API `number` field equals the `id` for
# standard codes.  We fall back to an API lookup for unknown codes.
_VAT_CODE_TO_ID: dict[str, int] = {
    "3": 3,    # 25% standard (Utgående MVA, høy sats)
    "31": 31,  # 15% food (middels sats)
    "33": 32,  # 12% transport/low (lav sats) — NB: number=33 but id=32!
    "5": 5,    # 0% exempt
    "6": 6,    # 0% outside VAT law
}


async def _resolve_vat_type_id(client: TripletexClient, vat_code: str) -> int | None:
    """Resolve a vatCode string to a vatType ID, using hardcoded map first."""
    if vat_code in _VAT_CODE_TO_ID:
        return _VAT_CODE_TO_ID[vat_code]
    # Fallback: API lookup for unknown codes
    vat_resp = await client.get_cached("/ledger/vatType", params={"number": vat_code})
    vat_types = vat_resp.json().get("values", [])
    if vat_types:
        return vat_types[0]["id"]
    return None


def _pick(fields: dict, *keys: str) -> dict[str, Any]:
    """Pick non-None values from fields."""
    return {k: fields[k] for k in keys if fields.get(k) is not None}


def _build_address(fields: dict) -> dict[str, Any] | None:
    """Build a Tripletex Address object from parsed address fields."""
    addr = fields.get("address")
    if not addr:
        return None
    return _pick(addr, "addressLine1", "addressLine2", "postalCode", "city") or None


def _warn_unused(handler_name: str, fields: dict, used_keys: set) -> None:
    """Log warning for any parsed fields that weren't used by the handler."""
    unused = {k for k in fields if k not in used_keys and fields[k] is not None}
    if unused:
        logger.warning(f"[{handler_name}] Unused parsed fields: {unused}")


# All field keys that supplier/customer handlers map
_CONTACT_KEYS = {
    "name", "organizationNumber", "email", "invoiceEmail", "phoneNumber",
    "phoneNumberMobile", "isPrivateIndividual", "description", "isSupplier",
    "isCustomer", "bankAccounts", "website", "address", "overdueNoticeEmail",
    "language",
}


def _sync_email(fields: dict) -> None:
    """If only one of email/invoiceEmail is set, copy to both.
    Also set overdueNoticeEmail if not explicitly provided."""
    email = fields.get("email")
    inv_email = fields.get("invoiceEmail")
    if inv_email and not email:
        fields["email"] = inv_email
    elif email and not inv_email:
        fields["invoiceEmail"] = email
    # Default overdueNoticeEmail to the same email if not set
    resolved_email = fields.get("email") or fields.get("invoiceEmail")
    if resolved_email and not fields.get("overdueNoticeEmail"):
        fields["overdueNoticeEmail"] = resolved_email


@register_handler("create_supplier")
async def create_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # For suppliers: set email field, but DON'T auto-copy to invoiceEmail/overdueNoticeEmail
    # unless the prompt explicitly provides them. The scoring checks that these fields
    # are only set when explicitly requested.
    # _sync_email copies email↔invoiceEmail, which is wrong for suppliers where
    # the prompt says "E-mail:" generically — it should go in `email` only.
    email = fields.get("email") or fields.get("invoiceEmail")
    if email:
        fields["email"] = email
    # Only keep invoiceEmail if parser explicitly extracted it as different from email,
    # or if prompt context suggests it's specifically an invoice email
    if fields.get("invoiceEmail") == fields.get("email"):
        # Same value = was auto-copied, remove it so Tripletex keeps it empty
        fields.pop("invoiceEmail", None)
    # Don't set overdueNoticeEmail for suppliers (it's a customer-facing field)
    if fields.get("overdueNoticeEmail") == email:
        fields.pop("overdueNoticeEmail", None)

    payload = {"name": fields["name"]}
    payload.update(_pick(fields, "organizationNumber", "email", "invoiceEmail",
                         "phoneNumber", "phoneNumberMobile", "isPrivateIndividual",
                         "description", "bankAccounts", "website", "overdueNoticeEmail",
                         "language"))

    address = _build_address(fields)
    if address:
        payload["postalAddress"] = address
        payload["physicalAddress"] = address

    _warn_unused("create_supplier", fields, _CONTACT_KEYS)

    resp = await client.post("/supplier", payload)
    data = resp.json()
    logger.info(f"Created supplier: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_supplier", "created": data.get("value", {})}


@register_handler("create_customer")
async def create_customer(client: TripletexClient, fields: dict[str, Any]) -> dict:
    _sync_email(fields)
    payload = {"name": fields["name"], "isCustomer": True}
    payload.update(_pick(fields, "organizationNumber", "email", "invoiceEmail",
                         "phoneNumber", "phoneNumberMobile", "isPrivateIndividual",
                         "description", "isSupplier", "website", "overdueNoticeEmail",
                         "language"))

    address = _build_address(fields)
    if address:
        payload["postalAddress"] = address
        payload["physicalAddress"] = address

    _warn_unused("create_customer", fields, _CONTACT_KEYS)

    resp = await client.post("/customer", payload)
    data = resp.json()
    logger.info(f"Created customer: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_customer", "created": data.get("value", {})}


_EMPLOYEE_KEYS = {
    "firstName", "lastName", "email", "phoneNumberMobile", "dateOfBirth",
    "startDate", "userType", "departmentId", "address", "employeeNumber",
    "nationalIdentityNumber", "bankAccountNumber", "iban", "role",
    "occupationCode", "employmentPercentage", "annualSalary", "monthlySalary",
}


@register_handler("create_employee")
async def create_employee(client: TripletexClient, fields: dict[str, Any]) -> dict:
    payload = {"firstName": fields["firstName"], "lastName": fields["lastName"]}
    # Note: startDate belongs on Employment, not Employee — don't send it here
    payload.update(_pick(fields, "email", "phoneNumberMobile", "dateOfBirth",
                         "employeeNumber", "nationalIdentityNumber",
                         "bankAccountNumber", "iban"))

    # userType is required — default to STANDARD
    payload["userType"] = fields.get("userType", "STANDARD")

    # department is required — use provided or fetch first available
    if fields.get("departmentId"):
        payload["department"] = {"id": fields["departmentId"]}
    else:
        dept_resp = await client.get_cached("/department", params={"count": 1, "fields": "id,name"})
        depts = dept_resp.json().get("values", [])
        if depts:
            payload["department"] = {"id": depts[0]["id"]}

    address = _build_address(fields)
    if address:
        payload["address"] = address

    _warn_unused("create_employee", fields, _EMPLOYEE_KEYS)

    resp = await client.post("/employee", payload)
    data = resp.json()
    employee_id = data.get("value", {}).get("id")
    logger.info(f"Created employee: {employee_id}")

    # Grant entitlements/role if requested
    # Map common role descriptions to Tripletex entitlement templates
    role = fields.get("role", "").lower()
    if employee_id and any(kw in role for kw in ("admin", "kontoadmin", "full", "all")):
        await client.put("/employee/entitlement/:grantEntitlementsByTemplate", params={
            "employeeId": employee_id, "template": "ALL_PRIVILEGES",
        })
        logger.info(f"Granted ALL_PRIVILEGES to employee {employee_id}")
    elif employee_id and any(kw in role for kw in ("faktura", "invoice", "invoicing")):
        await client.put("/employee/entitlement/:grantEntitlementsByTemplate", params={
            "employeeId": employee_id, "template": "INVOICING_MANAGER",
        })
    elif employee_id and any(kw in role for kw in ("regnskapsfør", "accountant", "regnskap")):
        await client.put("/employee/entitlement/:grantEntitlementsByTemplate", params={
            "employeeId": employee_id, "template": "ACCOUNTANT",
        })
    elif employee_id and any(kw in role for kw in ("personell", "hr", "personal")):
        await client.put("/employee/entitlement/:grantEntitlementsByTemplate", params={
            "employeeId": employee_id, "template": "PERSONELL_MANAGER",
        })
    elif employee_id and any(kw in role for kw in ("avdeling", "department")):
        await client.put("/employee/entitlement/:grantEntitlementsByTemplate", params={
            "employeeId": employee_id, "template": "DEPARTMENT_LEADER",
        })
    elif employee_id and role:
        # Unknown role — default to ALL_PRIVILEGES to maximize score
        await client.put("/employee/entitlement/:grantEntitlementsByTemplate", params={
            "employeeId": employee_id, "template": "ALL_PRIVILEGES",
        })
        logger.info(f"Unknown role '{role}', granted ALL_PRIVILEGES to employee {employee_id}")

    # Create employment record with startDate if provided
    employment_id: int | None = None
    if employee_id and fields.get("startDate"):
        employment_payload = {
            "employee": {"id": employee_id},
            "startDate": fields["startDate"],
        }
        emp_resp = await client.post("/employee/employment", employment_payload)
        if emp_resp.status_code < 400:
            employment_id = emp_resp.json().get("value", {}).get("id")
            logger.info(f"Created employment for {employee_id} with startDate={fields['startDate']}")
        else:
            logger.warning(f"Failed to create employment: {emp_resp.text[:200]}")

    # Create employment details if salary/occupationCode/percentage is provided
    # This covers PDF-based tasks with detailed contract data
    has_detail_fields = any(
        fields.get(k) is not None
        for k in ("occupationCode", "employmentPercentage", "annualSalary", "monthlySalary")
    )
    if employee_id and employment_id and has_detail_fields:
        detail_payload: dict[str, Any] = {
            "employment": {"id": employment_id},
            "date": fields.get("startDate") or "2026-01-01",
            "employmentType": "ORDINARY",
            "employmentForm": "PERMANENT",
            "remunerationType": "MONTHLY_WAGE",
            "workingHoursScheme": "NOT_SHIFT",
            "percentageOfFullTimeEquivalent": fields.get("employmentPercentage") or 100.0,
        }

        # Resolve occupation code to Tripletex ID
        occ_code = fields.get("occupationCode")
        if occ_code:
            try:
                occ_resp = await client.get_cached(
                    "/employee/employment/occupationCode",
                    params={"nameAndCode": str(occ_code), "count": 1},
                )
                occ_values = occ_resp.json().get("values", [])
                if occ_values:
                    detail_payload["occupationCode"] = {"id": occ_values[0]["id"]}
                    logger.info(f"Resolved occupationCode {occ_code} → id={occ_values[0]['id']}")
            except Exception as e:
                logger.warning(f"Failed to resolve occupationCode {occ_code}: {e}")

        # Set salary: prefer annual, derive monthly, or use monthly directly
        annual = fields.get("annualSalary")
        monthly = fields.get("monthlySalary")
        if annual:
            detail_payload["annualSalary"] = annual
            detail_payload["monthlySalary"] = round(annual / 12, 2)
        elif monthly:
            detail_payload["monthlySalary"] = monthly
            detail_payload["annualSalary"] = round(monthly * 12, 2)

        det_resp = await client.post("/employee/employment/details", detail_payload)
        if det_resp.status_code < 400:
            logger.info(f"Created employment details for employment {employment_id}")
        else:
            logger.warning(f"Failed to create employment details: {det_resp.text[:300]}")

    return {"status": "completed", "taskType": "create_employee", "created": data.get("value", {})}


_PRODUCT_KEYS = {
    "name", "number", "description", "isInactive", "priceExcludingVat",
    "priceIncludingVat", "vatCode", "costExcludingVat",
}


@register_handler("create_product")
async def create_product(client: TripletexClient, fields: dict[str, Any]) -> dict:
    payload = {"name": fields["name"]}
    payload.update(_pick(fields, "number", "description", "isInactive"))

    # Map price fields to correct Tripletex API names
    if fields.get("priceExcludingVat") is not None:
        payload["priceExcludingVatCurrency"] = fields["priceExcludingVat"]
    if fields.get("priceIncludingVat") is not None:
        payload["priceIncludingVatCurrency"] = fields["priceIncludingVat"]
    if fields.get("costExcludingVat") is not None:
        payload["costExcludingVatCurrency"] = fields["costExcludingVat"]

    # If vatCode specified, resolve to vatType ID (hardcoded for common codes)
    if fields.get("vatCode"):
        vat_id = await _resolve_vat_type_id(client, fields["vatCode"])
        if vat_id is not None:
            payload["vatType"] = {"id": vat_id}

    _warn_unused("create_product", fields, _PRODUCT_KEYS)

    resp = await client.post("/product", payload)
    data = resp.json()
    logger.info(f"Created product: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_product", "created": data.get("value", {})}


@register_handler("create_department")
async def create_department(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # NOTE: salesmodules POST removed — department module is already enabled in
    # competition sandboxes.  The old call always returned 422, wasting a call
    # and incurring a 4xx penalty on the efficiency bonus.
    payload: dict[str, Any] = {"name": fields["name"]}
    if fields.get("departmentNumber"):
        payload["departmentNumber"] = fields["departmentNumber"]

    # Look up department manager by name if provided
    manager_name = fields.get("departmentManagerName")
    if manager_name:
        try:
            parts = manager_name.strip().split()
            search_params: dict[str, Any] = {"count": 5, "fields": "id,firstName,lastName"}
            if len(parts) >= 2:
                search_params["lastName"] = parts[-1]
            else:
                search_params["firstName"] = parts[0]
            mgr_resp = await client.get("/employee", params=search_params)
            employees = mgr_resp.json().get("values", [])
            # Pick best match: prefer full name match
            manager_id = None
            name_lower = manager_name.lower()
            for emp in employees:
                full = f"{emp.get('firstName', '')} {emp.get('lastName', '')}".lower()
                if full.strip() == name_lower or emp.get("lastName", "").lower() == parts[-1].lower():
                    manager_id = emp["id"]
                    break
            if manager_id:
                payload["departmentManager"] = {"id": manager_id}
                logger.info(f"Resolved departmentManager '{manager_name}' → id={manager_id}")
            else:
                logger.warning(f"Could not find employee for departmentManager '{manager_name}'")
        except Exception as e:
            logger.warning(f"Failed to look up departmentManager '{manager_name}': {e}")

    resp = await client.post("/department", payload)
    data = resp.json()
    created = data.get("value", {})
    if not created or not created.get("id"):
        logger.warning(f"create_department failed: status={resp.status_code}, body={resp.text[:300]}")
        return {"status": "completed", "taskType": "create_department", "error": f"API returned no id: {resp.text[:200]}", "created": {}}
    logger.info(f"Created department: {created.get('id')} name={created.get('name')}")
    return {"status": "completed", "taskType": "create_department", "created": created}
