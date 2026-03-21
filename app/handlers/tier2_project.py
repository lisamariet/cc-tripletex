"""Tier 2 handlers — project operations (×2 points)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient
from app.handlers.tier2_invoice import _find_or_create_customer, _ensure_bank_account

logger = logging.getLogger(__name__)


@register_handler("create_project")
async def create_project(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Projects need a project manager — find the first employee if not specified
    pm_id = None
    if fields.get("projectManagerName"):
        parts = fields["projectManagerName"].strip().split()
        params: dict[str, Any] = {}
        if len(parts) >= 2:
            params["firstName"] = parts[0]
            params["lastName"] = " ".join(parts[1:])
        else:
            params["firstName"] = parts[0]
        resp = await client.get("/employee", params=params)
        employees = resp.json().get("values", [])
        if employees:
            pm_id = employees[0]["id"]

    if pm_id is None:
        # Use first available employee (cached — same across session)
        resp = await client.get_cached("/employee", params={"count": 1})
        employees = resp.json().get("values", [])
        if employees:
            pm_id = employees[0]["id"]

    project_payload: dict[str, Any] = {
        "name": fields["name"],
        "isInternal": False,
    }

    if pm_id:
        project_payload["projectManager"] = {"id": pm_id}

    if fields.get("customerName") or fields.get("customerOrgNumber"):
        customer_id = await _find_or_create_customer(client, fields)
        project_payload["customer"] = {"id": customer_id}

    # startDate is required by Tripletex — default to today
    from datetime import date
    project_payload["startDate"] = fields.get("startDate") or date.today().isoformat()
    if fields.get("endDate"):
        project_payload["endDate"] = fields["endDate"]
    if fields.get("isClosed") is not None:
        project_payload["isClosed"] = fields["isClosed"]

    resp = await client.post("/project", project_payload)
    data = resp.json()
    logger.info(f"Created project: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_project", "created": data.get("value", {})}


async def _find_project_manager(client: TripletexClient, name: str | None) -> int | None:
    """Find a project manager employee by name, or fall back to first employee."""
    pm_id = None
    if name:
        parts = name.strip().split()
        params: dict[str, Any] = {}
        if len(parts) >= 2:
            params["firstName"] = parts[0]
            params["lastName"] = " ".join(parts[1:])
        else:
            params["firstName"] = parts[0]
        resp = await client.get("/employee", params=params)
        employees = resp.json().get("values", [])
        if employees:
            pm_id = employees[0]["id"]

    if pm_id is None:
        resp = await client.get_cached("/employee", params={"count": 1})
        employees = resp.json().get("values", [])
        if employees:
            pm_id = employees[0]["id"]

    return pm_id


@register_handler("set_project_fixed_price")
async def set_project_fixed_price(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Create a project linked to a customer with a fixed price amount."""
    from datetime import date as date_cls

    project_name = fields.get("projectName") or fields.get("name", "Unnamed Project")
    fixed_price = fields.get("fixedPrice", 0)

    # 1. Find or create customer
    customer_id = await _find_or_create_customer(client, fields)

    # 2. Find project manager
    pm_id = await _find_project_manager(client, fields.get("projectManagerName"))

    # 3. Create project with isFixedPrice=true
    project_payload: dict[str, Any] = {
        "name": project_name,
        "isInternal": False,
        "isFixedPrice": True,
        "fixedprice": fixed_price,
        "startDate": fields.get("startDate") or date_cls.today().isoformat(),
    }

    if pm_id:
        project_payload["projectManager"] = {"id": pm_id}
    if customer_id:
        project_payload["customer"] = {"id": customer_id}
    if fields.get("endDate"):
        project_payload["endDate"] = fields["endDate"]

    resp = await client.post("/project", project_payload)
    data = resp.json()
    project = data.get("value", {})
    project_id = project.get("id")
    logger.info(f"Created fixed-price project: {project_id}")

    # 4. If the fixedprice wasn't set on create (some API versions require PUT), update it
    if project_id and project.get("fixedprice", 0) != fixed_price:
        logger.info(f"Updating fixedprice to {fixed_price} via PUT")
        # Fetch full project to get all required fields for PUT
        get_resp = await client.get(f"/project/{project_id}")
        full_project = get_resp.json().get("value", {})
        if full_project:
            full_project["isFixedPrice"] = True
            full_project["fixedprice"] = fixed_price
            put_resp = await client.put(f"/project/{project_id}", full_project)
            if put_resp.status_code < 400:
                project = put_resp.json().get("value", project)
                logger.info(f"Updated project {project_id} with fixedprice={fixed_price}")
            else:
                logger.warning(f"PUT update failed: {put_resp.status_code} {put_resp.text[:300]}")

    # 5. If invoicePercentage is provided, create a partial invoice
    invoice_percentage = fields.get("invoicePercentage")
    invoice_data = None
    if invoice_percentage and fixed_price and customer_id:
        try:
            percentage = float(invoice_percentage)
            partial_amount = fixed_price * percentage / 100

            # Ensure bank account is configured for invoicing
            await _ensure_bank_account(client)

            today = date_cls.today().isoformat()

            # Create order with 1 line for partial payment, linked to the project
            description = f"Delbetaling {int(percentage)}%" if percentage == int(percentage) else f"Delbetaling {percentage}%"
            order_payload: dict[str, Any] = {
                "customer": {"id": customer_id},
                "orderDate": today,
                "deliveryDate": today,
                "orderLines": [
                    {
                        "count": 1,
                        "unitPriceExcludingVatCurrency": partial_amount,
                        "description": description,
                    }
                ],
            }
            if project_id:
                order_payload["project"] = {"id": project_id}
            order_resp = await client.post("/order", order_payload)
            order = order_resp.json().get("value", {})
            order_id = order.get("id")

            if order_id:
                # Invoice the order
                inv_resp = await client.put(f"/order/{order_id}/:invoice", params={
                    "invoiceDate": today,
                    "sendToCustomer": False,
                })
                invoice_data = inv_resp.json().get("value", {})
                invoice_id = invoice_data.get("id")
                logger.info(f"Created partial invoice {invoice_id} for {percentage}% of fixed price ({partial_amount} NOK)")
            else:
                logger.warning("Failed to create order for partial invoice")
        except Exception as e:
            logger.error(f"Failed to create partial invoice: {e}")

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "set_project_fixed_price",
        "created": project,
    }
    if invoice_data:
        result["invoice"] = invoice_data
    return result
