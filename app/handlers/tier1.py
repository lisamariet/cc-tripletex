"""Tier 1 handlers — simple create operations (1 API call each, ×1 point)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


def _pick(fields: dict, *keys: str) -> dict[str, Any]:
    """Pick non-None values from fields."""
    return {k: fields[k] for k in keys if fields.get(k) is not None}


@register_handler("create_supplier")
async def create_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict:
    payload = {"name": fields["name"]}
    payload.update(_pick(fields, "organizationNumber", "email", "invoiceEmail",
                         "phoneNumber", "isPrivateIndividual", "description", "bankAccount"))

    resp = await client.post("/supplier", payload)
    data = resp.json()
    logger.info(f"Created supplier: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_supplier", "created": data.get("value", {})}


@register_handler("create_customer")
async def create_customer(client: TripletexClient, fields: dict[str, Any]) -> dict:
    payload = {"name": fields["name"], "isCustomer": True}
    payload.update(_pick(fields, "organizationNumber", "email", "invoiceEmail",
                         "phoneNumber", "isPrivateIndividual", "description", "isSupplier"))

    resp = await client.post("/customer", payload)
    data = resp.json()
    logger.info(f"Created customer: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_customer", "created": data.get("value", {})}


@register_handler("create_employee")
async def create_employee(client: TripletexClient, fields: dict[str, Any]) -> dict:
    payload = {"firstName": fields["firstName"], "lastName": fields["lastName"]}
    payload.update(_pick(fields, "email", "phoneNumberMobile", "dateOfBirth", "startDate"))

    # userType is required — default to STANDARD
    payload["userType"] = fields.get("userType", "STANDARD")

    # department is required — use provided or fetch first available
    if fields.get("departmentId"):
        payload["department"] = {"id": fields["departmentId"]}
    else:
        dept_resp = await client.get("/department", params={"count": 1})
        depts = dept_resp.json().get("values", [])
        if depts:
            payload["department"] = {"id": depts[0]["id"]}

    if fields.get("address"):
        addr = fields["address"]
        payload["address"] = _pick(addr, "addressLine1", "postalCode", "city", "country")

    resp = await client.post("/employee", payload)
    data = resp.json()
    employee_id = data.get("value", {}).get("id")
    logger.info(f"Created employee: {employee_id}")
    return {"status": "completed", "taskType": "create_employee", "created": data.get("value", {})}


@register_handler("create_product")
async def create_product(client: TripletexClient, fields: dict[str, Any]) -> dict:
    payload = {"name": fields["name"]}
    payload.update(_pick(fields, "number", "description", "isInactive"))

    # Map price fields to correct Tripletex API names
    if fields.get("priceExcludingVat") is not None:
        payload["priceExcludingVatCurrency"] = fields["priceExcludingVat"]
    if fields.get("priceIncludingVat") is not None:
        payload["priceIncludingVatCurrency"] = fields["priceIncludingVat"]

    # If vatCode specified, look up the vatType
    if fields.get("vatCode"):
        vat_resp = await client.get("/ledger/vatType", params={"number": fields["vatCode"]})
        vat_data = vat_resp.json()
        vat_types = vat_data.get("values", [])
        if vat_types:
            payload["vatType"] = {"id": vat_types[0]["id"]}

    resp = await client.post("/product", payload)
    data = resp.json()
    logger.info(f"Created product: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_product", "created": data.get("value", {})}


@register_handler("create_department")
async def create_department(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # First enable the department module
    try:
        await client.post("/company/salesmodules", [{"name": "department", "enabled": True}])
    except Exception:
        logger.warning("Could not enable department module — may already be active")

    payload = {"name": fields["name"]}
    if fields.get("departmentNumber"):
        payload["departmentNumber"] = fields["departmentNumber"]

    resp = await client.post("/department", payload)
    data = resp.json()
    logger.info(f"Created department: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_department", "created": data.get("value", {})}
