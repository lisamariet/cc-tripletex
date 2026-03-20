"""Tier 2 handlers — invoice operations (×2 points)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

# Valid Norwegian bank account numbers (pass mod-11 check)
_BANK_ACCOUNT_NUMBER = "12345678903"
_BANK_ACCOUNT_NUMBER_ALT = "60110000009"


async def _is_bank_account_ready(client: TripletexClient) -> bool:
    """Check if the company has a bank account configured for invoicing."""
    resp = await client.get("/invoice/settings", params={"fields": "bankAccountReady"})
    if resp.status_code == 200:
        value = resp.json().get("value", {})
        return bool(value.get("bankAccountReady"))
    return False


async def _try_update_existing_account(client: TripletexClient) -> bool:
    """Try to set bankAccountNumber on existing ledger account 1920 via PUT.

    Returns True if successful.
    """
    resp = await client.get(
        "/ledger/account",
        params={"number": "1920", "fields": "id,bankAccountNumber,isBankAccount,isInvoiceAccount"},
    )
    accounts = resp.json().get("values", [])
    if not accounts:
        logger.warning("Ledger account 1920 not found")
        return False

    acct = accounts[0]
    if acct.get("bankAccountNumber"):
        logger.info("Ledger account 1920 already has bankAccountNumber set")
        return True

    acct_id = acct["id"]
    full_resp = await client.get(f"/ledger/account/{acct_id}")
    full_acct = full_resp.json().get("value", {})
    if not full_acct:
        return False

    full_acct["bankAccountNumber"] = _BANK_ACCOUNT_NUMBER
    full_acct["isBankAccount"] = True
    full_acct["isInvoiceAccount"] = True

    resp = await client.put(f"/ledger/account/{acct_id}", full_acct)
    if resp.status_code < 400:
        logger.info("Set bankAccountNumber on ledger account 1920 via PUT")
        return True

    logger.warning(f"PUT /ledger/account/{acct_id} failed ({resp.status_code}): {resp.text[:300]}")
    return False


async def _try_create_bank_account(client: TripletexClient) -> bool:
    """Fallback: create a new ledger account with bank details via POST.

    Tries account numbers 1921-1929 until one succeeds.
    Returns True if successful.
    """
    for num in range(1921, 1930):
        resp = await client.post("/ledger/account", {
            "number": num,
            "name": f"Bankkonto {num}",
            "type": "ASSETS",
            "isBankAccount": True,
            "isInvoiceAccount": True,
            "bankAccountNumber": _BANK_ACCOUNT_NUMBER_ALT,
            "currency": {"id": 1},
            "bankAccountCountry": {"id": 161},
        })
        if resp.status_code < 400:
            logger.info(f"Created new bank account on ledger account {num}")
            return True
        logger.debug(f"POST /ledger/account {num} failed: {resp.text[:200]}")

    logger.warning("Failed to create any bank account (1921-1929)")
    return False


async def _ensure_bank_account(client: TripletexClient) -> None:
    """Ensure the company has a bank account configured for invoicing.

    Checks the actual invoice settings (bankAccountReady) as source of truth.
    If not ready, tries multiple approaches:
      1. PUT bankAccountNumber on existing ledger account 1920
      2. POST a new ledger account with bank details (1921-1929)
    """
    if await _is_bank_account_ready(client):
        return

    logger.info("bankAccountReady is False — setting up bank account for invoicing")

    # Strategy 1: update existing account 1920
    if await _try_update_existing_account(client):
        if await _is_bank_account_ready(client):
            return
        logger.warning("Updated account 1920 but bankAccountReady still False")

    # Strategy 2: create a new bank account
    if await _try_create_bank_account(client):
        if await _is_bank_account_ready(client):
            return
        logger.warning("Created bank account but bankAccountReady still False")

    logger.error("Could not ensure bank account — invoice creation may fail")


async def _find_or_create_customer(client: TripletexClient, fields: dict[str, Any]) -> int | None:
    """Find customer by name/orgNr or create one. Returns customer ID or None."""
    name = fields.get("customerName", "")
    org_nr = fields.get("customerOrgNumber")

    if org_nr:
        resp = await client.get("/customer", params={"organizationNumber": org_nr, "fields": "id,name,organizationNumber"})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    if name:
        resp = await client.get("/customer", params={"name": name, "fields": "id,name,organizationNumber"})
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


async def _create_customer_directly(client: TripletexClient, fields: dict[str, Any]) -> int | None:
    """Create customer directly without searching first. Use in fresh sandbox (create_invoice)."""
    name = fields.get("customerName", "") or "Unknown Customer"
    org_nr = fields.get("customerOrgNumber")
    payload: dict[str, Any] = {"name": name, "isCustomer": True}
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
        resp = await client.get("/customer", params={"organizationNumber": org_nr, "fields": "id,name,organizationNumber"})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    if name:
        resp = await client.get("/customer", params={"name": name, "fields": "id,name,organizationNumber"})
        values = resp.json().get("values", [])
        if values:
            return values[0]["id"]

    return None


async def _find_invoice(client: TripletexClient, fields: dict[str, Any], customer_id: int | None = None) -> dict | None:
    """Find an invoice by customerId and optionally invoiceNumber/amount. Returns invoice dict or None.

    When multiple invoices match, try to pick the one whose amountExcludingVat
    is closest to the amount mentioned in the prompt.
    """
    search_params: dict[str, Any] = {
        "invoiceDateFrom": "2000-01-01",
        "invoiceDateTo": date.today().isoformat(),
        "fields": "id,amount,amountCurrency,amountOutstanding,amountExcludingVat,amountExcludingVatCurrency",
    }

    if customer_id:
        search_params["customerId"] = customer_id

    # Only use invoiceNumber if it looks like a number
    inv_num = fields.get("invoiceNumber")
    if inv_num and str(inv_num).isdigit():
        search_params["invoiceNumber"] = inv_num

    resp = await client.get("/invoice", params=search_params)
    invoices = resp.json().get("values", [])
    if not invoices:
        return None

    # If only one invoice, return it
    if len(invoices) == 1:
        return invoices[0]

    # Multiple invoices — try to match by amount (excl. VAT) from the prompt
    target_amount = fields.get("amount")
    if target_amount:
        target = abs(target_amount)
        # Try matching on amountExcludingVat first, then amountCurrency
        best = None
        best_diff = float("inf")
        for inv in invoices:
            excl_vat = inv.get("amountExcludingVat") or inv.get("amountExcludingVatCurrency") or 0
            diff = abs(excl_vat - target)
            if diff < best_diff:
                best_diff = diff
                best = inv
            # Also check gross amount (in case prompt gave incl. VAT amount)
            gross = inv.get("amountCurrency") or inv.get("amount") or 0
            diff_gross = abs(gross - target)
            if diff_gross < best_diff:
                best_diff = diff_gross
                best = inv
        if best:
            return best

    return invoices[0]


async def _ensure_invoice_exists(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find an existing invoice or create one from scratch (customer → order → invoice).

    On a fresh sandbox there are no invoices, so we must create the full chain.
    Returns the invoice dict or None on failure.
    """
    await _ensure_bank_account(client)

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
                # Use number-based reference — id-based fails in sandbox
                order_line["vatType"] = {"number": str(line["vatCode"])}
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

    # Fetch full invoice to get computed amounts (amount, amountExcludingVat, etc.)
    detail_resp = await client.get(f"/invoice/{invoice_id}")
    full_invoice = detail_resp.json().get("value")
    return full_invoice if full_invoice else invoice_data


async def _get_bank_payment_type_id(client: TripletexClient) -> int | None:
    """Get the bank payment type ID."""
    payment_type_resp = await client.get_cached("/invoice/paymentType")
    payment_types = payment_type_resp.json().get("values", [])
    for pt in payment_types:
        if "bank" in pt.get("description", "").lower():
            return pt["id"]
    return payment_types[0]["id"] if payment_types else None


@register_handler("create_invoice")
async def create_invoice(client: TripletexClient, fields: dict[str, Any]) -> dict:
    await _ensure_bank_account(client)

    # Fresh sandbox: POST customer directly — no existing customers to search for
    customer_id = await _create_customer_directly(client, fields)
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
            # Use number-based reference — id-based fails in sandbox
            order_line["vatType"] = {"number": str(line["vatCode"])}
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

    # If the invoice dict doesn't already have amount fields, fetch full details
    if not invoice.get("amountCurrency") and not invoice.get("amount"):
        detail_resp = await client.get(f"/invoice/{invoice_id}")
        invoice = detail_resp.json().get("value", invoice)

    # Get payment type (bank)
    payment_type_id = await _get_bank_payment_type_id(client)

    # Use the invoice's gross amount (including VAT) for paidAmount.
    # The paidAmount parameter is "in invoice currency" and must cover the full
    # outstanding amount to register a full payment.
    # Use amountOutstanding first (handles partially paid invoices), then gross total.
    # Must check `is not None` because 0.0 is a valid amount (fully paid).
    amount_outstanding = invoice.get("amountOutstanding")
    if amount_outstanding is None:
        amount_outstanding = invoice.get("amountCurrencyOutstanding")
    amount_gross = invoice.get("amountCurrency") or invoice.get("amount") or 0

    # Prefer outstanding amount (it accounts for any prior partial payments).
    # If outstanding is 0 but gross is positive, it means invoice is already paid —
    # use gross in that case (we're registering the payment).
    if amount_outstanding is not None and amount_outstanding != 0:
        amount = amount_outstanding
    elif amount_gross:
        amount = amount_gross
    else:
        # Fallback: parsed excl-VAT amount scaled up by 1.25 (standard 25% MVA)
        parsed_amount = fields.get("amount", 0)
        amount = abs(parsed_amount) * 1.25 if parsed_amount else 0
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

    # If the invoice dict doesn't already have amount fields, fetch full details
    if not invoice.get("amountCurrency") and not invoice.get("amount"):
        detail_resp = await client.get(f"/invoice/{invoice_id}")
        invoice = detail_resp.json().get("value", invoice)

    payment_type_id = await _get_bank_payment_type_id(client)

    # Use the invoice's gross amount (including VAT)
    amount = (
        invoice.get("amountCurrency")
        or invoice.get("amount")
        or 0
    )
    if amount == 0:
        parsed_amount = fields.get("amount", 0)
        amount = abs(parsed_amount) * 1.25 if parsed_amount else 0
    amount = abs(amount)

    payment_date = fields.get("paymentDate") or date.today().isoformat()

    # Check if invoice already has a payment (amountOutstanding == 0 means fully paid)
    outstanding = invoice.get("amountOutstanding") or invoice.get("amountCurrencyOutstanding")
    if outstanding is not None and float(outstanding) == 0:
        # Invoice already paid — just reverse (negative amount)
        logger.info(f"Invoice {invoice_id} already paid, reversing directly")
        resp = await client.put(f"/invoice/{invoice_id}/:payment", params={
            "paymentDate": payment_date,
            "paymentTypeId": payment_type_id,
            "paidAmount": -amount,
        })
    else:
        # Invoice not yet paid — pay first, then reverse
        await client.put(f"/invoice/{invoice_id}/:payment", params={
            "paymentDate": payment_date,
            "paymentTypeId": payment_type_id,
            "paidAmount": amount,
        })
        logger.info(f"Registered initial payment on invoice {invoice_id} before reversal")

        resp = await client.put(f"/invoice/{invoice_id}/:payment", params={
            "paymentDate": payment_date,
            "paymentTypeId": payment_type_id,
            "paidAmount": -amount,
        })

    logger.info(f"Reversed payment on invoice {invoice_id}, amount={-amount}")
    return {"status": "completed", "taskType": "reverse_payment", "invoiceId": invoice_id}


@register_handler("create_credit_note")
async def create_credit_note(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Ensure invoice exists (create customer → order → invoice if needed)
    invoice = await _ensure_invoice_exists(client, fields)

    if not invoice:
        return {"status": "completed", "note": "No matching invoice found and could not create one"}

    invoice_id = invoice.get("id")
    today = date.today().isoformat()
    credit_params: dict[str, Any] = {
        "date": fields.get("creditNoteDate") or today,
        "sendToCustomer": False,
    }
    if fields.get("comment"):
        credit_params["comment"] = fields["comment"]

    # :createCreditNote uses query params, not JSON body
    resp = await client.put(f"/invoice/{invoice_id}/:createCreditNote", params=credit_params)
    logger.info(f"Created credit note for invoice {invoice_id}")
    return {"status": "completed", "taskType": "create_credit_note", "invoiceId": invoice_id}


@register_handler("create_invoice_from_pdf")
async def create_invoice_from_pdf(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Create an invoice from PDF-extracted data. The parser extracts fields from the PDF."""
    # Same as create_invoice — the parser already extracted data from the PDF
    return await create_invoice(client, fields)


@register_handler("update_customer")
async def update_customer(client: TripletexClient, fields: dict[str, Any]) -> dict:
    params: dict[str, Any] = {}
    if fields.get("customerOrgNumber"):
        params["organizationNumber"] = fields["customerOrgNumber"]
    elif fields.get("customerName"):
        params["name"] = fields["customerName"]

    # Don't restrict fields here — we need the full object for PUT update
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
