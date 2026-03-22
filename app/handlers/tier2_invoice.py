"""Tier 2 handlers — invoice operations (×2 points)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.handlers import register_handler
from app.handlers.tier1 import _resolve_vat_type_id
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

# Valid Norwegian bank account numbers (pass mod-11 check)
_BANK_ACCOUNT_NUMBER = "12345678903"
_BANK_ACCOUNT_NUMBER_ALT = "60110000009"


async def _is_bank_account_ready(client: TripletexClient) -> tuple[bool, bool]:
    """Check if the company has a bank account configured for invoicing.

    Returns (ready, token_ok) — token_ok=False means 403 (token is invalid,
    no point retrying any API calls).
    """
    resp = await client.get("/invoice/settings", params={"fields": "bankAccountReady"})
    if resp.status_code == 403:
        return False, False
    if resp.status_code == 200:
        value = resp.json().get("value", {})
        return bool(value.get("bankAccountReady")), True
    return False, True


async def _try_update_existing_account(client: TripletexClient) -> bool:
    """Try to set bankAccountNumber on existing ledger account 1920 via PUT.

    Returns True if successful.
    """
    resp = await client.get_cached(
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
    full_resp = await client.get_cached(f"/ledger/account/{acct_id}")
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

    Tries account numbers 1921-1923 until one succeeds (limit to 3 to avoid
    excessive 4xx noise when the sandbox already has these accounts).
    Returns True if successful.
    """
    for num in range(1921, 1924):
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

    logger.warning("Failed to create any bank account (1921-1923)")
    return False


async def _ensure_bank_account(client: TripletexClient) -> None:
    """Ensure the company has a bank account configured for invoicing.

    Checks the actual invoice settings (bankAccountReady) as source of truth.
    If not ready, tries multiple approaches:
      1. PUT bankAccountNumber on existing ledger account 1920
      2. POST a new ledger account with bank details (1921-1923)

    Uses a per-client flag to avoid redundant checks within the same session.
    If the proxy token is already invalid (403 on first check), aborts immediately
    to avoid wasting calls on a doomed request.
    """
    # Skip if we already confirmed bank account is ready in this session
    if getattr(client, '_bank_account_confirmed', False):
        return

    ready, token_ok = await _is_bank_account_ready(client)
    if not token_ok:
        logger.warning("bankAccountReady check returned 403 — token invalid, skipping bank setup")
        return
    if ready:
        client._bank_account_confirmed = True  # type: ignore[attr-defined]
        return

    logger.info("bankAccountReady is False — setting up bank account for invoicing")

    # Strategy 1: update existing account 1920
    if await _try_update_existing_account(client):
        client._bank_account_confirmed = True  # type: ignore[attr-defined]
        return

    # Strategy 2: create a new bank account (limit attempts to reduce 4xx noise)
    if await _try_create_bank_account(client):
        client._bank_account_confirmed = True  # type: ignore[attr-defined]
        return

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

    # Try to find existing invoice first — reuse customer_id for creation if needed
    customer_id = await _find_customer_id(client, fields)
    invoice = await _find_invoice(client, fields, customer_id)
    if invoice:
        return invoice

    # No invoice found — create the full chain.
    # If we already found the customer above, skip the redundant search in _find_or_create_customer.
    if not customer_id:
        customer_id = await _create_customer_directly(client, fields)
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
                vat_id = await _resolve_vat_type_id(client, str(line["vatCode"]))
                if vat_id is not None:
                    order_line["vatType"] = {"id": vat_id}
                else:
                    order_line["vatType"] = {"number": str(line["vatCode"])}
            order_lines.append(order_line)
    elif fields.get("amount") or fields.get("foreignAmount"):
        # Single line from amount + description
        description = fields.get("invoiceDescription") or fields.get("description") or "Invoice"
        # For foreign currency invoices, compute NOK amount = foreignAmount * invoiceExchangeRate
        foreign_amount = fields.get("foreignAmount")
        invoice_rate = fields.get("invoiceExchangeRate")
        if foreign_amount and invoice_rate:
            unit_price = abs(foreign_amount) * invoice_rate
        else:
            unit_price = abs(fields.get("amount", 0))
        order_lines.append({
            "count": 1,
            "unitPriceExcludingVatCurrency": unit_price,
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


async def _create_invoice_chain(client: TripletexClient, fields: dict[str, Any], customer_id: int) -> dict | None:
    """Create order → invoice chain for a known customer. Returns invoice dict or None."""
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
                vat_id = await _resolve_vat_type_id(client, str(line["vatCode"]))
                if vat_id is not None:
                    order_line["vatType"] = {"id": vat_id}
                else:
                    order_line["vatType"] = {"number": str(line["vatCode"])}
            order_lines.append(order_line)
    elif fields.get("amount") or fields.get("foreignAmount"):
        description = fields.get("invoiceDescription") or fields.get("description") or "Invoice"
        foreign_amount = fields.get("foreignAmount")
        invoice_rate = fields.get("invoiceExchangeRate")
        if foreign_amount and invoice_rate:
            unit_price = abs(foreign_amount) * invoice_rate
        else:
            unit_price = abs(fields.get("amount", 0))
        order_lines.append({
            "count": 1,
            "unitPriceExcludingVatCurrency": unit_price,
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

    # Competition pre-creates customer — search first, create only if not found
    customer_id = await _find_or_create_customer(client, fields)
    if not customer_id:
        return {"status": "completed", "note": "Could not find or create customer"}

    # Build order lines — create products if productNumber is specified
    order_lines = []
    for line in fields.get("lines", []):
        order_line: dict[str, Any] = {
            "count": line.get("quantity", 1),
            "unitPriceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
        }
        if line.get("description"):
            order_line["description"] = line["description"]
        if line.get("vatCode"):
            vat_id = await _resolve_vat_type_id(client, str(line["vatCode"]))
            if vat_id is not None:
                order_line["vatType"] = {"id": vat_id}
            else:
                order_line["vatType"] = {"number": str(line["vatCode"])}

        # If productNumber is given, find or create the product and link it
        product_number = line.get("productNumber")
        if product_number:
            # First, try to find existing product by number
            search_resp = await client.get("/product", params={"number": str(product_number), "fields": "id,number"})
            existing = search_resp.json().get("values", [])
            if existing:
                product_id = existing[0]["id"]
                order_line["product"] = {"id": product_id}
                logger.info(f"Found existing product {product_number} (id={product_id})")
            else:
                # Create new product
                product_payload: dict[str, Any] = {
                    "name": line.get("description", f"Product {product_number}"),
                    "number": str(product_number),
                    "priceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
                }
                vat_code = line.get("vatCode", "3")
                vat_id = await _resolve_vat_type_id(client, str(vat_code))
                if vat_id is not None:
                    product_payload["vatType"] = {"id": vat_id}
                prod_resp = await client.post_with_retry("/product", product_payload)
                if prod_resp.status_code in (200, 201):
                    product_id = prod_resp.json().get("value", {}).get("id")
                    if product_id:
                        order_line["product"] = {"id": product_id}
                        logger.info(f"Created product {product_number} (id={product_id})")
                else:
                    logger.warning(f"Failed to create product {product_number}: {prod_resp.text[:200]}")

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
    resp = await client.post_with_retry("/order", order_payload)
    order = resp.json().get("value", {})
    order_id = order.get("id")

    if not order_id:
        return {"status": "completed", "note": "Failed to create order"}

    # Invoice the order — :invoice uses query params, not JSON body
    invoice_params: dict[str, Any] = {
        "invoiceDate": order_date,
        "sendToCustomer": True,
    }
    if fields.get("dueDate"):
        invoice_params["invoiceDueDate"] = fields["dueDate"]

    resp = await client.put(f"/order/{order_id}/:invoice", params=invoice_params)
    invoice_data = resp.json()
    invoice_value = invoice_data.get("value", {})
    invoice_id = invoice_value.get("id")
    logger.info(f"Created invoice {invoice_id} from order {order_id}")

    # Send invoice to customer (backup — sendToCustomer should handle it, but explicit :send ensures it)
    if invoice_id:
        try:
            send_resp = await client.put(f"/invoice/{invoice_id}/:send", params={"sendType": "EMAIL"})
            if send_resp.status_code < 400:
                logger.info(f"Sent invoice {invoice_id} via :send")
            else:
                logger.warning(f"Send invoice {invoice_id} failed ({send_resp.status_code}) — sendToCustomer may have covered it")
        except Exception as e:
            logger.warning(f"Invoice :send exception (non-fatal): {e}")

    return {"status": "completed", "taskType": "create_invoice", "created": invoice_value}


@register_handler("register_payment")
async def register_payment(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Optimised path: try to find existing invoice WITHOUT bank-account setup
    # (bank setup is only needed when CREATING a new invoice).
    # This saves 1-2 API calls when the invoice already exists in the sandbox.
    customer_id = await _find_customer_id(client, fields)
    invoice = await _find_invoice(client, fields, customer_id) if customer_id else None

    if not invoice:
        # Fallback: create full chain (customer → order → invoice) — needs bank account.
        # We pass pre-resolved customer_id to avoid redundant lookups inside _ensure_invoice_exists.
        await _ensure_bank_account(client)
        if not customer_id:
            customer_id = await _create_customer_directly(client, fields)
        if customer_id:
            invoice = await _create_invoice_chain(client, fields, customer_id)

    if not invoice:
        logger.error("No invoice found or created for payment")
        return {"status": "completed", "note": "No matching invoice found and could not create one"}

    invoice_id = invoice.get("id")

    # Use amount fields from the search result directly to avoid an extra GET.
    # _find_invoice already requests amountCurrency, amountOutstanding, etc.
    # Only fetch full details if the search result is missing amountCurrency.
    if not invoice.get("amountCurrency") and not invoice.get("amount"):
        detail_resp = await client.get(f"/invoice/{invoice_id}")
        invoice = detail_resp.json().get("value", invoice)

    # Get payment type (bank)
    payment_type_id = await _get_bank_payment_type_id(client)

    # Use the invoice's gross amount (including VAT) for paidAmount.
    # The paidAmount parameter is "in invoice currency" and must cover the full
    # outstanding amount to register a full payment.
    #
    # NOTE: Tripletex sandbox returns overflow/garbage values for amountOutstanding
    # and amountCurrencyOutstanding (e.g. -41943040000.0).  Use amountCurrency
    # (gross total incl. VAT) as the authoritative source for paidAmount.
    # This is correct for a fresh unpaid invoice where outstanding == gross total.
    # For partially-paid invoices, use amountOutstanding only if it is a
    # sensible positive value (within 2x of gross).
    amount_gross = invoice.get("amountCurrency") or invoice.get("amount") or 0
    amount_gross = abs(amount_gross)

    amount_outstanding_raw = invoice.get("amountOutstanding")
    if amount_outstanding_raw is None:
        amount_outstanding_raw = invoice.get("amountCurrencyOutstanding")

    # Sanity-check: outstanding must be in [0, 2 * gross] to be usable
    if (
        amount_outstanding_raw is not None
        and amount_outstanding_raw >= 0
        and (amount_gross == 0 or amount_outstanding_raw <= amount_gross * 2)
    ):
        amount = amount_outstanding_raw
    elif amount_gross:
        amount = amount_gross
    else:
        # Fallback: parsed excl-VAT amount scaled up by 1.25 (standard 25% MVA)
        parsed_amount = fields.get("amount", 0)
        amount = abs(parsed_amount) * 1.25 if parsed_amount else 0
    # Ensure positive amount for payment
    amount = abs(amount)

    payment_date = fields.get("paymentDate") or date.today().isoformat()

    # Foreign currency handling: use paidAmountCurrency so Tripletex calculates
    # the exchange rate difference (agio/disagio) automatically.
    #
    # paidAmount        = NOK amount (payment-type account currency)
    # paidAmountCurrency = amount in the invoice's own currency (e.g. EUR)
    #
    # When the invoice is in a foreign currency, Tripletex needs both values to
    # determine the realised exchange rate and book agio/disagio internally.
    foreign_currency = fields.get("foreignCurrency")
    foreign_amount = fields.get("foreignAmount")
    invoice_rate = fields.get("invoiceExchangeRate")
    payment_rate = fields.get("paymentExchangeRate")

    payment_params: dict[str, Any] = {
        "paymentDate": payment_date,
        "paymentTypeId": payment_type_id,
    }

    if foreign_currency and foreign_amount and payment_rate:
        # Invoice is in foreign currency.
        # paidAmountCurrency = gross amount in invoice currency (incl. VAT)
        # paidAmount = NOK equivalent at the payment exchange rate
        #
        # We use the invoice's gross amount as paidAmountCurrency when available,
        # because it already includes VAT in the invoice currency.
        # If the invoice was stored in NOK (sandbox quirk), we derive from fields.
        invoice_currency_id = None
        inv_currency = invoice.get("currency") if invoice else None
        if inv_currency:
            invoice_currency_id = inv_currency.get("id")

        if invoice_currency_id and invoice_currency_id != 1:
            # Invoice is properly stored in foreign currency
            paid_amount_currency = amount  # gross in invoice currency
            paid_amount_nok = round(abs(foreign_amount) * payment_rate * 1.25, 2)
        else:
            # Invoice stored in NOK (sandbox creates invoices in NOK).
            # The gross amount on the invoice is already in NOK at invoice rate.
            # We need to tell Tripletex the NOK payment amount at payment rate
            # and the original invoice-currency amount.
            gross_foreign = abs(foreign_amount) * 1.25  # incl 25% VAT
            paid_amount_currency = round(gross_foreign, 2)
            paid_amount_nok = round(abs(foreign_amount) * payment_rate * 1.25, 2)

        payment_params["paidAmount"] = paid_amount_nok
        payment_params["paidAmountCurrency"] = paid_amount_currency
        logger.info(
            f"Foreign currency payment: {foreign_currency} {foreign_amount}, "
            f"rate={payment_rate}, paidAmount(NOK)={paid_amount_nok}, "
            f"paidAmountCurrency={paid_amount_currency}"
        )
    else:
        # Standard NOK invoice — use the invoice amount directly
        payment_params["paidAmount"] = amount

    resp = await client.put(f"/invoice/{invoice_id}/:payment", params=payment_params)
    logger.info(f"Registered payment on invoice {invoice_id}, params={payment_params}")

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "register_payment",
        "invoiceId": invoice_id,
    }

    # Handle foreign currency agio/disagio via manual voucher ONLY as fallback.
    # When paidAmountCurrency is sent, Tripletex should handle agio internally.
    # We only create a manual agio voucher if the :payment call did NOT receive
    # paidAmountCurrency (i.e. we couldn't determine the foreign currency info)
    # or if the invoice was stored in NOK (sandbox quirk) so Tripletex can't
    # compute the exchange difference itself.
    needs_manual_agio = (
        foreign_currency
        and foreign_amount
        and invoice_rate
        and payment_rate
        and invoice_rate != payment_rate
    )
    # If we sent paidAmountCurrency AND the invoice is truly in foreign currency,
    # Tripletex handles agio — skip manual voucher.
    if needs_manual_agio and "paidAmountCurrency" in payment_params:
        invoice_currency_id = None
        inv_currency = invoice.get("currency") if invoice else None
        if inv_currency:
            invoice_currency_id = inv_currency.get("id")
        if invoice_currency_id and invoice_currency_id != 1:
            # Tripletex handles agio automatically for real foreign-currency invoices
            needs_manual_agio = False
            rate_diff = payment_rate - invoice_rate
            agio_amount = round(abs(foreign_amount) * abs(rate_diff), 2)
            result["agioNote"] = (
                f"Tripletex handles agio automatically: ~{agio_amount} NOK "
                f"({'gain' if rate_diff > 0 else 'loss'})"
            )
            logger.info(f"Agio handled by Tripletex via paidAmountCurrency, ~{agio_amount} NOK")

    if needs_manual_agio:
        rate_diff = payment_rate - invoice_rate
        agio_amount = round(abs(foreign_amount) * abs(rate_diff), 2)

        if agio_amount > 0.01:
            is_gain = rate_diff > 0  # gain when payment rate > invoice rate
            # Account 8060 = agio (currency gain), 8160 = disagio (currency loss)
            default_agio_account = 8060 if is_gain else 8160
            agio_account_nr = fields.get("agioAccount") or default_agio_account
            # Accounts receivable (kundefordring) for the counterpart posting
            receivable_account_nr = 1500

            from app.handlers.tier3 import _lookup_account as _la
            receivable_id = await _la(client, receivable_account_nr)
            agio_id = await _la(client, int(agio_account_nr))

            if receivable_id and agio_id:
                # Build customer reference for the 1500 posting (reskontro)
                customer_ref: dict[str, Any] | None = None
                if customer_id:
                    customer_ref = {"id": customer_id}
                elif invoice:
                    cust = invoice.get("customer")
                    if cust and cust.get("id"):
                        customer_ref = {"id": cust["id"]}

                # Disagio loss: DEBIT 8160 (expense), CREDIT 1500 (receivable decreases)
                # Agio gain:    DEBIT 1500 (receivable increases), CREDIT 8060 (income)
                if is_gain:
                    receivable_posting: dict[str, Any] = {
                        "account": {"id": receivable_id}, "amountGross": agio_amount,
                        "amountGrossCurrency": agio_amount, "row": 1,
                    }
                    if customer_ref:
                        receivable_posting["customer"] = customer_ref
                    agio_posting: dict[str, Any] = {
                        "account": {"id": agio_id}, "amountGross": -agio_amount,
                        "amountGrossCurrency": -agio_amount, "row": 2,
                    }
                    postings = [receivable_posting, agio_posting]
                else:
                    agio_posting = {
                        "account": {"id": agio_id}, "amountGross": agio_amount,
                        "amountGrossCurrency": agio_amount, "row": 1,
                    }
                    receivable_posting = {
                        "account": {"id": receivable_id}, "amountGross": -agio_amount,
                        "amountGrossCurrency": -agio_amount, "row": 2,
                    }
                    if customer_ref:
                        receivable_posting["customer"] = customer_ref
                    postings = [agio_posting, receivable_posting]

                agio_voucher = {
                    "date": payment_date,
                    "description": f"Valutadifferanse ({foreign_currency} {foreign_amount:.0f}): "
                                   f"kurs {invoice_rate} → {payment_rate}",
                    "postings": postings,
                }
                agio_resp = await client.post("/ledger/voucher", agio_voucher)
                if agio_resp.status_code < 400:
                    agio_voucher_id = agio_resp.json().get("value", {}).get("id")
                    logger.info(
                        f"Created {'agio' if is_gain else 'disagio'} voucher {agio_voucher_id}: "
                        f"{agio_amount} NOK ({foreign_currency} rate diff {rate_diff})"
                    )
                    result["agioVoucherId"] = agio_voucher_id
                    result["agioAmount"] = agio_amount
                else:
                    logger.warning(f"Agio voucher creation failed: {agio_resp.text[:300]}")

    return result


@register_handler("reverse_payment")
async def reverse_payment(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Reverse a payment on an invoice — creates invoice, pays it, then reverses."""
    # Ensure invoice exists (create customer → order → invoice if needed)
    invoice = await _ensure_invoice_exists(client, fields)

    if not invoice:
        return {"status": "completed", "note": "No matching invoice found and could not create one"}

    invoice_id = invoice.get("id")

    # Always fetch full invoice details to get amountOutstanding reliably
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
    # Note: use `is not None` checks — 0 is falsy in Python but valid here
    outstanding = invoice.get("amountCurrencyOutstanding")
    if outstanding is None:
        outstanding = invoice.get("amountOutstanding")
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
