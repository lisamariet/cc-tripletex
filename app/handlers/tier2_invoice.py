"""Tier 2 handlers — invoice operations (×2 points)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


async def _find_or_create_customer(client: TripletexClient, fields: dict[str, Any]) -> int:
    """Find customer by name/orgNr or create one. Returns customer ID."""
    name = fields.get("customerName", "")
    org_nr = fields.get("customerOrgNumber")

    # Search by org number first (more specific)
    if org_nr:
        resp = await client.get("/customer", params={"organizationNumber": org_nr, "isCustomer": True})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    # Search by name
    if name:
        resp = await client.get("/customer", params={"name": name, "isCustomer": True})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    # Create customer
    payload = {"name": name or "Unknown Customer", "isCustomer": True}
    if org_nr:
        payload["organizationNumber"] = org_nr
    resp = await client.post("/customer", payload)
    return resp.json().get("value", {}).get("id")


@register_handler("create_invoice")
async def create_invoice(client: TripletexClient, fields: dict[str, Any]) -> dict:
    customer_id = await _find_or_create_customer(client, fields)

    # Build order lines
    order_lines = []
    for line in fields.get("lines", []):
        order_line = {
            "description": line.get("description", ""),
            "count": line.get("quantity", 1),
            "unitPriceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
        }
        if line.get("vatCode"):
            vat_resp = await client.get("/ledger/vatType", params={"number": line["vatCode"]})
            vat_types = vat_resp.json().get("values", [])
            if vat_types:
                order_line["vatType"] = {"id": vat_types[0]["id"]}
        order_lines.append(order_line)

    # Create order
    order_payload = {
        "customer": {"id": customer_id},
        "orderDate": fields.get("invoiceDate", ""),
        "deliveryDate": fields.get("invoiceDate", ""),
        "orderLines": order_lines,
    }
    resp = await client.post("/order", order_payload)
    order = resp.json().get("value", {})
    order_id = order.get("id")

    # Invoice the order
    resp = await client.put(f"/order/{order_id}/:invoice", {
        "invoiceDate": fields.get("invoiceDate", ""),
        "sendToCustomer": False,
    })
    invoice_data = resp.json()
    logger.info(f"Created invoice from order {order_id}")
    return {"status": "completed", "taskType": "create_invoice", "created": invoice_data.get("value", {})}


@register_handler("register_payment")
async def register_payment(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Find the invoice
    search_params: dict[str, Any] = {}
    if fields.get("invoiceNumber"):
        search_params["invoiceNumber"] = fields["invoiceNumber"]
    if fields.get("customerName"):
        search_params["customerName"] = fields["customerName"]
    if fields.get("customerOrgNumber"):
        # First find customer
        cust_resp = await client.get("/customer", params={"organizationNumber": fields["customerOrgNumber"]})
        customers = cust_resp.json().get("values", [])
        if customers:
            search_params["customerId"] = customers[0]["id"]

    resp = await client.get("/invoice", params=search_params)
    invoices = resp.json().get("values", [])
    if not invoices:
        logger.error("No invoice found for payment registration")
        return {"status": "completed", "note": "No matching invoice found"}

    invoice = invoices[0]
    invoice_id = invoice.get("id")

    # Register payment
    payment_payload = {
        "amount": fields.get("amount", invoice.get("amount", 0)),
        "paymentDate": fields.get("paymentDate", ""),
    }
    if fields.get("paymentType"):
        payment_payload["paymentTypeId"] = fields["paymentType"]

    resp = await client.put(f"/invoice/{invoice_id}/:payment", payment_payload)
    logger.info(f"Registered payment on invoice {invoice_id}")
    return {"status": "completed", "taskType": "register_payment", "invoiceId": invoice_id}


@register_handler("create_credit_note")
async def create_credit_note(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Find the invoice
    search_params: dict[str, Any] = {}
    if fields.get("invoiceNumber"):
        search_params["invoiceNumber"] = fields["invoiceNumber"]
    if fields.get("customerOrgNumber"):
        cust_resp = await client.get("/customer", params={"organizationNumber": fields["customerOrgNumber"]})
        customers = cust_resp.json().get("values", [])
        if customers:
            search_params["customerId"] = customers[0]["id"]

    resp = await client.get("/invoice", params=search_params)
    invoices = resp.json().get("values", [])
    if not invoices:
        return {"status": "completed", "note": "No matching invoice found for credit note"}

    invoice_id = invoices[0].get("id")
    credit_payload = {}
    if fields.get("comment"):
        credit_payload["comment"] = fields["comment"]

    resp = await client.put(f"/invoice/{invoice_id}/:createCreditNote", credit_payload)
    logger.info(f"Created credit note for invoice {invoice_id}")
    return {"status": "completed", "taskType": "create_credit_note", "invoiceId": invoice_id}


@register_handler("update_customer")
async def update_customer(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Find the customer
    params: dict[str, Any] = {}
    if fields.get("customerOrgNumber"):
        params["organizationNumber"] = fields["customerOrgNumber"]
    elif fields.get("customerName"):
        params["name"] = fields["customerName"]

    resp = await client.get("/customer", params=params)
    customers = resp.json().get("values", [])
    if not customers:
        return {"status": "completed", "note": "Customer not found"}

    customer = customers[0]
    customer_id = customer.get("id")

    # Apply changes
    changes = fields.get("changes", {})
    customer.update(changes)

    resp = await client.put(f"/customer/{customer_id}", customer)
    logger.info(f"Updated customer {customer_id}")
    return {"status": "completed", "taskType": "update_customer", "customerId": customer_id}
