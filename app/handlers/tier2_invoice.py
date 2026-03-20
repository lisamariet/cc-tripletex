"""Tier 2 handlers — invoice operations (×2 points)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


async def _find_or_create_customer(client: TripletexClient, fields: dict[str, Any]) -> int | None:
    """Find customer by name/orgNr or create one. Returns customer ID or None."""
    name = fields.get("customerName", "")
    org_nr = fields.get("customerOrgNumber")

    if org_nr:
        resp = await client.get("/customer", params={"organizationNumber": org_nr})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    if name:
        resp = await client.get("/customer", params={"name": name})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    # Create customer
    payload: dict[str, Any] = {"name": name or "Unknown Customer", "isCustomer": True}
    if org_nr:
        payload["organizationNumber"] = org_nr
    resp = await client.post("/customer", payload)
    value = resp.json().get("value", {})
    return value.get("id") if value else None


async def _find_customer_id(client: TripletexClient, fields: dict[str, Any]) -> int | None:
    """Find customer by orgNr or name. Returns ID or None. Does NOT create."""
    org_nr = fields.get("customerOrgNumber")
    name = fields.get("customerName")

    if org_nr:
        resp = await client.get("/customer", params={"organizationNumber": org_nr})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    if name:
        resp = await client.get("/customer", params={"name": name})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    return None


async def _find_invoice(client: TripletexClient, fields: dict[str, Any], customer_id: int | None = None) -> dict | None:
    """Find an invoice by customerId and optionally invoiceNumber. Returns invoice dict or None."""
    search_params: dict[str, Any] = {
        "invoiceDateFrom": "2000-01-01",
        "invoiceDateTo": date.today().isoformat(),
    }

    if customer_id:
        search_params["customerId"] = customer_id

    # Only use invoiceNumber if it looks like a number
    inv_num = fields.get("invoiceNumber")
    if inv_num and str(inv_num).isdigit():
        search_params["invoiceNumber"] = inv_num

    resp = await client.get("/invoice", params=search_params)
    invoices = resp.json().get("values", [])
    return invoices[0] if invoices else None


async def _ensure_invoice_exists(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find an existing invoice or create one from scratch (customer → order → invoice).

    On a fresh sandbox there are no invoices, so we must create the full chain.
    Returns the invoice dict or None on failure.
    """
    # Try to find existing invoice first
    customer_id = await _find_customer_id(client, fields)
    invoice = await _find_invoice(client, fields, customer_id)
    if invoice:
        return invoice

    # No invoice found — create the full chain
    customer_id = await _find_or_create_customer(client, fields)
    if not customer_id:
        return None

    today = date.today().isoformat()

    # Build order lines from fields
    order_lines = []
    if fields.get("lines"):
        for line in fields["lines"]:
            order_line: dict[str, Any] = {
                "count": line.get("quantity", 1),
                "unitPriceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
            }
            if line.get("description"):
                order_line["description"] = line["description"]
            if line.get("vatCode"):
                vat_resp = await client.get("/ledger/vatType", params={"number": line["vatCode"]})
                vat_types = vat_resp.json().get("values", [])
                if vat_types:
                    order_line["vatType"] = {"id": vat_types[0]["id"]}
            order_lines.append(order_line)
    elif fields.get("amount"):
        # Single line from amount + description
        description = fields.get("invoiceDescription") or fields.get("description") or "Invoice"
        order_lines.append({
            "count": 1,
            "unitPriceExcludingVatCurrency": abs(fields["amount"]),
            "description": description,
        })
    else:
        return None

    # Create order
    order_payload = {
        "customer": {"id": customer_id},
        "orderDate": today,
        "deliveryDate": today,
        "orderLines": order_lines,
    }
    resp = await client.post("/order", order_payload)
    order = resp.json().get("value", {})
    order_id = order.get("id")
    if not order_id:
        logger.error("Failed to create order for invoice pipeline")
        return None

    # Invoice the order
    resp = await client.put(f"/order/{order_id}/:invoice", params={
        "invoiceDate": today,
        "sendToCustomer": False,
    })
    invoice_data = resp.json().get("value", {})
    invoice_id = invoice_data.get("id")
    if not invoice_id:
        logger.error("Failed to invoice order in pipeline")
        return None

    logger.info(f"Created invoice {invoice_id} from order {order_id} in pipeline")
    return invoice_data


async def _get_bank_payment_type_id(client: TripletexClient) -> int | None:
    """Get the bank payment type ID."""
    payment_type_resp = await client.get("/invoice/paymentType")
    payment_types = payment_type_resp.json().get("values", [])
    for pt in payment_types:
        if "bank" in pt.get("description", "").lower():
            return pt["id"]
    return payment_types[0]["id"] if payment_types else None


@register_handler("create_invoice")
async def create_invoice(client: TripletexClient, fields: dict[str, Any]) -> dict:
    customer_id = await _find_or_create_customer(client, fields)
    if not customer_id:
        return {"status": "completed", "note": "Could not find or create customer"}

    # Build order lines
    order_lines = []
    for line in fields.get("lines", []):
        order_line: dict[str, Any] = {
            "count": line.get("quantity", 1),
            "unitPriceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
        }
        if line.get("description"):
            order_line["description"] = line["description"]
        if line.get("vatCode"):
            vat_resp = await client.get("/ledger/vatType", params={"number": line["vatCode"]})
            vat_types = vat_resp.json().get("values", [])
            if vat_types:
                order_line["vatType"] = {"id": vat_types[0]["id"]}
        order_lines.append(order_line)

    # Create order — orderDate and deliveryDate are required
    today = date.today().isoformat()
    order_date = fields.get("invoiceDate") or today
    order_payload = {
        "customer": {"id": customer_id},
        "orderDate": order_date,
        "deliveryDate": order_date,
        "orderLines": order_lines,
    }
    resp = await client.post("/order", order_payload)
    order = resp.json().get("value", {})
    order_id = order.get("id")

    if not order_id:
        return {"status": "completed", "note": "Failed to create order"}

    # Invoice the order — :invoice uses query params, not JSON body
    invoice_params: dict[str, Any] = {
        "invoiceDate": order_date,
        "sendToCustomer": False,
    }
    if fields.get("dueDate"):
        invoice_params["invoiceDueDate"] = fields["dueDate"]

    resp = await client.put(f"/order/{order_id}/:invoice", params=invoice_params)
    invoice_data = resp.json()
    logger.info(f"Created invoice from order {order_id}")
    return {"status": "completed", "taskType": "create_invoice", "created": invoice_data.get("value", {})}


@register_handler("register_payment")
async def register_payment(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Ensure invoice exists (create customer → order → invoice if needed)
    invoice = await _ensure_invoice_exists(client, fields)

    if not invoice:
        logger.error("No invoice found or created for payment")
        return {"status": "completed", "note": "No matching invoice found and could not create one"}

    invoice_id = invoice.get("id")

    # Get payment type (bank)
    payment_type_id = await _get_bank_payment_type_id(client)

    # Use amount from fields, or fall back to invoice amount
    amount = fields.get("amount")
    if amount is None or amount == 0:
        amount = invoice.get("amount", 0)
    # Ensure positive amount for payment
    amount = abs(amount)

    payment_date = fields.get("paymentDate") or date.today().isoformat()

    resp = await client.put(f"/invoice/{invoice_id}/:payment", params={
        "paymentDate": payment_date,
        "paymentTypeId": payment_type_id,
        "paidAmount": amount,
    })
    logger.info(f"Registered payment on invoice {invoice_id}, amount={amount}")
    return {"status": "completed", "taskType": "register_payment", "invoiceId": invoice_id}


@register_handler("reverse_payment")
async def reverse_payment(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Reverse a payment on an invoice — creates invoice, pays it, then reverses."""
    # Ensure invoice exists (create customer → order → invoice if needed)
    invoice = await _ensure_invoice_exists(client, fields)

    if not invoice:
        return {"status": "completed", "note": "No matching invoice found and could not create one"}

    invoice_id = invoice.get("id")
    payment_type_id = await _get_bank_payment_type_id(client)

    amount = fields.get("amount")
    if amount is None or amount == 0:
        amount = invoice.get("amount", 0)

    payment_date = fields.get("paymentDate") or date.today().isoformat()

    # First register the initial payment (positive amount)
    await client.put(f"/invoice/{invoice_id}/:payment", params={
        "paymentDate": payment_date,
        "paymentTypeId": payment_type_id,
        "paidAmount": abs(amount),
    })
    logger.info(f"Registered initial payment on invoice {invoice_id} before reversal")

    # Now reverse with negative amount
    resp = await client.put(f"/invoice/{invoice_id}/:payment", params={
        "paymentDate": payment_date,
        "paymentTypeId": payment_type_id,
        "paidAmount": -abs(amount),
    })
    logger.info(f"Reversed payment on invoice {invoice_id}, amount={-abs(amount)}")
    return {"status": "completed", "taskType": "reverse_payment", "invoiceId": invoice_id}


@register_handler("create_credit_note")
async def create_credit_note(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Ensure invoice exists (create customer → order → invoice if needed)
    invoice = await _ensure_invoice_exists(client, fields)

    if not invoice:
        return {"status": "completed", "note": "No matching invoice found and could not create one"}

    invoice_id = invoice.get("id")
    credit_params: dict[str, Any] = {}
    if fields.get("comment"):
        credit_params["comment"] = fields["comment"]

    # :createCreditNote uses query params, not JSON body
    resp = await client.put(f"/invoice/{invoice_id}/:createCreditNote", params=credit_params)
    logger.info(f"Created credit note for invoice {invoice_id}")
    return {"status": "completed", "taskType": "create_credit_note", "invoiceId": invoice_id}


@register_handler("update_customer")
async def update_customer(client: TripletexClient, fields: dict[str, Any]) -> dict:
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

    changes = fields.get("changes", {})
    customer.update(changes)

    resp = await client.put(f"/customer/{customer_id}", customer)
    logger.info(f"Updated customer {customer_id}")
    return {"status": "completed", "taskType": "update_customer", "customerId": customer_id}
