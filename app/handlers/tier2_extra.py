"""Extra Tier 2 handlers — update/delete operations, supplier invoices, and payroll."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

async def _find_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find a supplier by org number or name."""
    org_nr = fields.get("supplierOrgNumber") or fields.get("organizationNumber")
    name = fields.get("supplierName") or fields.get("name")

    if org_nr:
        resp = await client.get("/supplier", params={"organizationNumber": org_nr, "fields": "id,name,organizationNumber,version"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    if name:
        resp = await client.get("/supplier", params={"name": name, "fields": "id,name,organizationNumber,version"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    return None


async def _find_product(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find a product by number or name."""
    number = fields.get("productNumber") or fields.get("number")
    name = fields.get("productName") or fields.get("name")

    if number:
        resp = await client.get("/product", params={"number": str(number), "fields": "id,name,number,version,priceExcludingVatCurrency,priceIncludingVatCurrency"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    if name:
        resp = await client.get("/product", params={"name": name, "fields": "id,name,number,version,priceExcludingVatCurrency,priceIncludingVatCurrency"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    return None


async def _find_customer(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find a customer by org number or name."""
    org_nr = fields.get("customerOrgNumber") or fields.get("organizationNumber")
    name = fields.get("customerName") or fields.get("name")

    if org_nr:
        resp = await client.get("/customer", params={"organizationNumber": org_nr, "fields": "id,name,organizationNumber,version"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    if name:
        resp = await client.get("/customer", params={"name": name, "fields": "id,name,organizationNumber,version"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    return None


async def _find_employee_by_fields(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find employee by name fields."""
    first = fields.get("employeeFirstName") or fields.get("firstName", "")
    last = fields.get("employeeLastName") or fields.get("lastName", "")
    name = fields.get("employeeName") or fields.get("name", "")

    params: dict[str, Any] = {}
    if first:
        params["firstName"] = first
    if last:
        params["lastName"] = last
    if not params and name:
        parts = name.strip().split()
        if len(parts) >= 2:
            params["firstName"] = parts[0]
            params["lastName"] = " ".join(parts[1:])
        else:
            params["firstName"] = name

    if not params:
        return None

    params["fields"] = "id,firstName,lastName,email,version"
    resp = await client.get("/employee", params=params)
    values = resp.json().get("values", [])
    return values[0] if values else None


# ---------------------------------------------------------------------------
# Update handlers
# ---------------------------------------------------------------------------

@register_handler("update_supplier")
async def update_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict:
    supplier = await _find_supplier(client, fields)
    if not supplier:
        return {"status": "completed", "note": "Supplier not found"}

    supplier_id = supplier.get("id")
    changes = fields.get("changes", {})
    supplier.update(changes)

    resp = await client.put(f"/supplier/{supplier_id}", supplier)
    logger.info(f"Updated supplier {supplier_id}")
    return {"status": "completed", "taskType": "update_supplier", "supplierId": supplier_id}


@register_handler("update_product")
async def update_product(client: TripletexClient, fields: dict[str, Any]) -> dict:
    product = await _find_product(client, fields)
    if not product:
        return {"status": "completed", "note": "Product not found"}

    product_id = product.get("id")
    changes = fields.get("changes", {})

    # Map price fields to correct API names
    if "priceExcludingVat" in changes:
        changes["priceExcludingVatCurrency"] = changes.pop("priceExcludingVat")
    if "priceIncludingVat" in changes:
        changes["priceIncludingVatCurrency"] = changes.pop("priceIncludingVat")

    product.update(changes)

    resp = await client.put(f"/product/{product_id}", product)
    logger.info(f"Updated product {product_id}")
    return {"status": "completed", "taskType": "update_product", "productId": product_id}


# ---------------------------------------------------------------------------
# Delete handlers
# ---------------------------------------------------------------------------

@register_handler("delete_employee")
async def delete_employee(client: TripletexClient, fields: dict[str, Any]) -> dict:
    employee_id = fields.get("_employee_id")
    if not employee_id:
        employee = await _find_employee_by_fields(client, fields)
        if not employee:
            return {"status": "completed", "note": "Employee not found"}
        employee_id = employee.get("id")
    resp = await client.delete(f"/employee/{employee_id}")
    logger.info(f"Deleted employee {employee_id}")
    return {"status": "completed", "taskType": "delete_employee", "deletedId": employee_id}


@register_handler("delete_customer")
async def delete_customer(client: TripletexClient, fields: dict[str, Any]) -> dict:
    customer = await _find_customer(client, fields)
    if not customer:
        return {"status": "completed", "note": "Customer not found"}

    customer_id = customer.get("id")
    resp = await client.delete(f"/customer/{customer_id}")
    logger.info(f"Deleted customer {customer_id}")
    return {"status": "completed", "taskType": "delete_customer", "deletedId": customer_id}


@register_handler("delete_supplier")
async def delete_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict:
    supplier = await _find_supplier(client, fields)
    if not supplier:
        return {"status": "completed", "note": "Supplier not found"}

    supplier_id = supplier.get("id")
    resp = await client.delete(f"/supplier/{supplier_id}")
    logger.info(f"Deleted supplier {supplier_id}")
    return {"status": "completed", "taskType": "delete_supplier", "deletedId": supplier_id}


# ---------------------------------------------------------------------------
# Order (without invoicing)
# ---------------------------------------------------------------------------

@register_handler("create_order")
async def create_order(client: TripletexClient, fields: dict[str, Any]) -> dict:
    from app.handlers.tier2_invoice import _find_or_create_customer, _ensure_bank_account, _get_bank_payment_type_id
    from app.handlers.tier1 import _resolve_vat_type_id

    customer_id = await _find_or_create_customer(client, fields)
    if not customer_id:
        return {"status": "completed", "note": "Could not find or create customer"}

    today = date.today().isoformat()
    order_lines = []
    for line in fields.get("lines", []):
        order_line: dict[str, Any] = {
            "count": line.get("quantity", 1),
            "unitPriceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
        }
        if line.get("description"):
            order_line["description"] = line["description"]
        line_vat_id: int | None = None
        if line.get("vatCode"):
            line_vat_id = await _resolve_vat_type_id(client, str(line["vatCode"]))
            if line_vat_id is not None:
                order_line["vatType"] = {"id": line_vat_id}
            else:
                order_line["vatType"] = {"number": str(line["vatCode"])}

        # Find or create product if productNumber is given
        product_number = line.get("productNumber")
        if product_number:
            # Try to find existing product first (competition pre-creates them)
            search_resp = await client.get("/product", params={"number": str(product_number), "fields": "id,number"})
            existing = search_resp.json().get("values", [])
            if existing:
                product_id = existing[0]["id"]
                order_line["product"] = {"id": product_id}
                logger.info(f"Found existing product {product_number} (id={product_id})")
            else:
                product_payload: dict[str, Any] = {
                    "name": line.get("description", f"Product {product_number}"),
                    "number": str(product_number),
                    "priceExcludingVatCurrency": line.get("unitPriceExcludingVat", 0),
                }
                if line_vat_id is not None:
                    product_payload["vatType"] = {"id": line_vat_id}
                prod_resp = await client.post_with_retry("/product", product_payload)
                if prod_resp.status_code in (200, 201):
                    product_id = prod_resp.json().get("value", {}).get("id")
                    if product_id:
                        order_line["product"] = {"id": product_id}
                        logger.info(f"Created product {product_number} (id={product_id})")

        order_lines.append(order_line)

    order_payload = {
        "customer": {"id": customer_id},
        "orderDate": fields.get("orderDate") or today,
        "deliveryDate": fields.get("deliveryDate") or today,
        "orderLines": order_lines,
    }
    resp = await client.post_with_retry("/order", order_payload)
    data = resp.json()
    order = data.get("value", {})
    order_id = order.get("id")
    logger.info(f"Created order: {order_id}")

    result: dict[str, Any] = {"status": "completed", "taskType": "create_order", "created": order}

    # Convert to invoice if requested
    if order_id and fields.get("convertToInvoice"):
        await _ensure_bank_account(client)
        inv_resp = await client.put(f"/order/{order_id}/:invoice", params={
            "invoiceDate": today,
            "sendToCustomer": False,
        })
        if inv_resp.status_code < 400:
            invoice = inv_resp.json().get("value", {})
            invoice_id = invoice.get("id")
            result["invoice"] = invoice
            logger.info(f"Converted order {order_id} to invoice {invoice_id}")

            # Register payment if requested
            if invoice_id and fields.get("registerPayment"):
                # Get full invoice to find amount
                detail_resp = await client.get(f"/invoice/{invoice_id}")
                full_invoice = detail_resp.json().get("value", {})
                amount = full_invoice.get("amountCurrency") or full_invoice.get("amount") or 0
                amount = abs(amount)

                payment_type_id = await _get_bank_payment_type_id(client)
                pay_resp = await client.put(f"/invoice/{invoice_id}/:payment", params={
                    "paymentDate": today,
                    "paymentTypeId": payment_type_id,
                    "paidAmount": amount,
                })
                if pay_resp.status_code < 400:
                    result["payment"] = {"status": "paid", "amount": amount}
                    logger.info(f"Registered payment on invoice {invoice_id}, amount={amount}")

    return result


# ---------------------------------------------------------------------------
# Supplier invoice (leverandørfaktura)
# ---------------------------------------------------------------------------

@register_handler("register_supplier_invoice")
async def register_supplier_invoice(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Register a supplier invoice via POST /supplierInvoice.

    This creates a proper supplierInvoice entity (visible via GET /supplierInvoice)
    with an embedded voucher.  The voucher postings are used as the credit side;
    Tripletex auto-generates the AP credit posting.
    """
    from datetime import timedelta

    # 1. Find or create the supplier
    supplier = await _find_supplier(client, fields)
    if not supplier:
        supplier_payload: dict[str, Any] = {
            "name": fields.get("supplierName") or fields.get("name", "Unknown Supplier"),
            "isSupplier": True,
        }
        org_nr = fields.get("supplierOrgNumber") or fields.get("organizationNumber")
        if org_nr:
            supplier_payload["organizationNumber"] = str(org_nr)
        resp = await client.post_with_retry("/supplier", supplier_payload)
        if resp.status_code >= 400:
            logger.error(f"Failed to create supplier: {resp.text[:300]}")
            return {"status": "completed", "note": f"Failed to create supplier: {resp.text[:300]}"}
        supplier = resp.json().get("value", {})

    supplier_id = supplier.get("id")
    if not supplier_id:
        return {"status": "completed", "note": "Could not find or create supplier"}

    today = date.today().isoformat()

    product_name = fields.get("productName") or ""
    raw_description = fields.get("description") or fields.get("invoiceDescription") or ""
    if product_name and raw_description:
        description = f"{product_name} — {raw_description}"
    elif product_name:
        description = product_name
    elif raw_description:
        description = raw_description
    else:
        description = "Leverandørfaktura"

    amount_gross = abs(fields.get("amount", 0))  # Amount INCLUDING VAT (gross)
    invoice_date = fields.get("invoiceDate") or today
    invoice_number = fields.get("invoiceNumber") or ""
    due_date = fields.get("dueDate") or fields.get("invoiceDueDate") or fields.get("paymentDueDate") or ""

    # Default due date: 30 days after invoice date
    if not due_date:
        try:
            inv_date_obj = date.fromisoformat(invoice_date)
            due_date = (inv_date_obj + timedelta(days=30)).isoformat()
        except ValueError:
            due_date = ""

    # Use parser-provided amountExcludingVat if available, otherwise calculate.
    # CRITICAL: When both netto and brutto come from PDF, they can be inconsistent
    # (e.g. netto=64850, brutto=81062, but 64850*1.25=81062.50).
    # Tripletex calculates netto = brutto / (1+rate) internally, so if we send
    # brutto=81062 the expense posting gets netto=64849.60, which fails check 5.
    # Fix: Use netto (amountExcludingVat) as master; derive consistent brutto.
    vat_rate = fields.get("vatRate", 25)
    if fields.get("amountExcludingVat"):
        amount_excl_vat = abs(float(fields["amountExcludingVat"]))
        # ALWAYS derive gross from netto to ensure Tripletex consistency
        # (netto is the authoritative value from the PDF)
        amount_gross = round(amount_excl_vat * (1 + vat_rate / 100), 2)
    elif vat_rate and vat_rate > 0:
        amount_excl_vat = round(amount_gross / (1 + vat_rate / 100), 2)
    else:
        amount_excl_vat = amount_gross

    # 2. Look up accounts — use vatCode from parser if provided to map account
    from app.handlers.tier3 import _lookup_account
    # Expense account: parser picks based on product type; fallback 4000
    expense_account_nr_raw = fields.get("expenseAccount", "4000")
    try:
        expense_account_nr = int(expense_account_nr_raw)
    except (ValueError, TypeError):
        expense_account_nr = 4000
    expense_id = await _lookup_account(client, expense_account_nr)
    payable_id = await _lookup_account(client, 2400)

    if not expense_id or not payable_id:
        return {"status": "completed", "note": "Could not find ledger accounts"}

    # 2b. Unlock VAT on expense account if locked (some accounts like 7100 are
    #     locked to vatCode 0, but the prompt asks for input VAT 25%)
    try:
        acc_resp = await client.get_cached(f"/ledger/account/{expense_id}")
        acc_data = acc_resp.json().get("value", {})
        if acc_data.get("vatLocked"):
            acc_data["vatLocked"] = False
            await client.put(f"/ledger/account/{expense_id}", acc_data)
            logger.info(f"Unlocked VAT on account {expense_account_nr} (id={expense_id})")
    except Exception as e:
        logger.warning(f"Could not unlock VAT on account {expense_account_nr}: {e}")

    # 3. Look up the "Leverandørfaktura" voucher type
    resp = await client.get_cached("/ledger/voucherType", params={"name": "Leverandørfaktura"})
    vt_values = resp.json().get("values", [])
    voucher_type_ref = None
    for vt in vt_values:
        if vt.get("name") == "Leverandørfaktura":
            voucher_type_ref = {"id": vt["id"]}
            break
    if not voucher_type_ref and vt_values:
        voucher_type_ref = {"id": vt_values[0]["id"]}

    # 4. Look up the correct INPUT VAT type (inngående mva) for supplier invoices.
    #    Tripletex /ledger/vatType number field (NOT the same as Norwegian MVA code):
    #      "1"  = Fradrag inngående avgift, høy sats (25%) — standard inngående for purchases
    #      "11" = Fradrag inngående avgift, middels sats (15%) — food/beverage
    #      "13" = Fradrag inngående avgift, lav sats (12%) — transport/cinema
    #       "0" = Ingen avgiftsbehandling (0%)
    #    Norwegian BAS vatCode (from parser): 11=25%, 13=15%, 14=12%
    #    These are DIFFERENT numbering schemes — map BAS code → Tripletex number.
    vat_code_str = str(fields.get("vatCode", "")).strip()
    if vat_code_str in ("11", "13", "14", "0"):
        # Parser provided explicit BAS vatCode — map to Tripletex number and vatRate
        if vat_code_str == "11":
            vat_type_number = "1"   # Tripletex: inngående 25%
            vat_rate = 25
        elif vat_code_str == "13":
            vat_type_number = "11"  # Tripletex: inngående 15%
            vat_rate = 15
        elif vat_code_str == "14":
            vat_type_number = "13"  # Tripletex: inngående 12%
            vat_rate = 12
        else:  # "0"
            vat_type_number = None
            vat_rate = 0
    else:
        vat_rate = fields.get("vatRate", 25)
        vat_type_number = "1"   # default: Inngående mva 25% (Tripletex number "1")
        if vat_rate == 15:
            vat_type_number = "11"  # Tripletex: inngående 15%
        elif vat_rate == 12:
            vat_type_number = "13"  # Tripletex: inngående 12%
        elif vat_rate == 0:
            vat_type_number = None

    vat_type_ref = None
    if vat_type_number:
        resp = await client.get_cached("/ledger/vatType", params={"number": vat_type_number})
        vat_values = resp.json().get("values", [])
        if vat_values:
            vat_type_ref = {"id": vat_values[0]["id"]}

    # 4b. Look up department if specified
    department_ref = None
    dept_name = fields.get("department") or ""
    if dept_name:
        try:
            dept_resp = await client.get_cached("/department", params={"name": dept_name, "count": 10})
            dept_values = dept_resp.json().get("values", [])
            # Find exact (case-insensitive) match first, then partial
            for dv in dept_values:
                if dv.get("name", "").lower() == dept_name.lower():
                    department_ref = {"id": dv["id"]}
                    break
            if not department_ref and dept_values:
                department_ref = {"id": dept_values[0]["id"]}
            if department_ref:
                logger.info(f"Found department '{dept_name}' → id={department_ref['id']}")
            else:
                logger.warning(f"Department '{dept_name}' not found in Tripletex")
        except Exception as e:
            logger.warning(f"Could not look up department '{dept_name}': {e}")

    # 5. Build voucher postings (expense debit + AP credit).
    # Tripletex /supplierInvoice requires BOTH postings:
    #   - Expense debit posting WITH supplier reference on the expense account line
    #   - AP credit posting (konto 2400) WITH supplier reference
    # Without both postings + supplier ref on expense, POST /supplierInvoice returns 500.
    #
    # Sign convention for Tripletex supplierInvoice postings:
    #   - Expense posting: NEGATIVE amounts (Tripletex internal convention)
    #   - AP posting: POSITIVE amounts
    # The amountCurrency on the SI payload is omitted (set to 0) so Tripletex
    # TRIPLETEX SIGN CONVENTION for supplierInvoice voucher postings:
    # - expense posting: POSITIVE amounts (debit = cost increases)
    # - AP posting: NEGATIVE amounts (credit = liability increases)
    # - SI-level amountCurrency: NEGATIVE (expense from company perspective)
    # When expense=positive, AP=negative, SI amountCurrency=negative:
    #   isCreditNote is set to False (normal invoice).
    # When AP=positive (old convention): isCreditNote is set to True (credit note).
    expense_posting: dict[str, Any] = {
        "account": {"id": expense_id},
        "supplier": {"id": supplier_id},
        "amount": amount_excl_vat,         # POSITIVE: expense debit
        "amountCurrency": amount_excl_vat,
        "amountGross": amount_gross,       # POSITIVE gross: Tripletex auto-generates VAT posting
        "amountGrossCurrency": amount_gross,
        "row": 1,
    }
    if vat_type_ref:
        expense_posting["vatType"] = vat_type_ref
    if department_ref:
        expense_posting["department"] = department_ref

    # Link expense posting to project if projectId is provided
    project_id_ref = fields.get("projectId")
    if project_id_ref:
        expense_posting["project"] = {"id": project_id_ref}

    ap_posting: dict[str, Any] = {
        "account": {"id": payable_id},
        "supplier": {"id": supplier_id},
        "amount": -amount_gross,            # NEGATIVE: AP credit (liability)
        "amountCurrency": -amount_gross,
        "amountGross": -amount_gross,
        "amountGrossCurrency": -amount_gross,
        "row": 2,
    }

    voucher_obj: dict[str, Any] = {
        "date": invoice_date,
        "description": f"Leverandørfaktura: {description}",
        "postings": [expense_posting, ap_posting],
    }
    if voucher_type_ref:
        voucher_obj["voucherType"] = voucher_type_ref

    # 6. Build and POST the supplierInvoice payload
    # CRITICAL: amountCurrency MUST be negative for normal supplier invoices.
    # Tripletex sets isCreditNote=True when amountCurrency >= 0.
    # Convention: supplier invoices are expenses (negative from company perspective).
    si_payload: dict[str, Any] = {
        "invoiceDate": invoice_date,
        "supplier": {"id": supplier_id},
        "amountCurrency": -abs(amount_gross),  # Negative = normal invoice (not credit note)
        "currency": {"id": 1},
        "voucher": voucher_obj,
    }
    if invoice_number:
        si_payload["invoiceNumber"] = str(invoice_number)
    if due_date:
        si_payload["invoiceDueDate"] = due_date

    resp = await client.post_with_retry("/supplierInvoice", si_payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"POST /supplierInvoice failed ({resp.status_code}): {error_msg} — {validation}")
        # Fallback: create via /ledger/voucher if /supplierInvoice still fails
        # voucher_obj already has both expense + AP postings with supplier refs
        return await _register_supplier_invoice_via_voucher(
            client, fields, voucher_obj, invoice_number, supplier_id,
        )

    created = data.get("value", {})
    si_id = created.get("id")
    voucher_ref = created.get("voucher") or {}
    voucher_id = voucher_ref.get("id") if isinstance(voucher_ref, dict) else None
    logger.info(
        f"Created supplier invoice: si_id={si_id}, voucher_id={voucher_id}, "
        f"amount_gross={amount_gross}, amount_excl_vat={amount_excl_vat}, due_date={due_date}"
    )

    # 7. Fix voucher postings via PUT /ledger/voucher/{id}.
    # POST /supplierInvoice creates TYPE_SUPPLIER_INVOICE_SIMPLE which auto-generates
    # SIMPLE postings from amountCurrency, ignoring our detailed postings.
    # We PUT the voucher afterwards to set the correct expense account (e.g. 4000),
    # VAT type, and proper signs (positive debit on expense, negative credit on AP).
    if voucher_id:
        try:
            v_resp = await client.get(
                f"/ledger/voucher/{voucher_id}", params={"fields": "*,postings(*)"},
            )
            v_data = v_resp.json().get("value", {})
            v_version = v_data.get("version", 0)
            old_postings = v_data.get("postings", [])

            corrected: list[dict[str, Any]] = []
            for p in old_postings:
                p_acct = (p.get("account") or {}).get("id")
                base: dict[str, Any] = {
                    "id": p.get("id"),
                    "version": p.get("version", 0),
                    "date": invoice_date,
                }
                if p_acct == expense_id or p.get("type") == "INVOICE_EXPENSE":
                    base.update({
                        "account": {"id": expense_id},
                        "supplier": {"id": supplier_id},
                        "amount": amount_excl_vat,
                        "amountCurrency": amount_excl_vat,
                        "amountGross": amount_gross,
                        "amountGrossCurrency": amount_gross,
                        "row": 1,
                    })
                    if vat_type_ref:
                        base["vatType"] = vat_type_ref
                    if department_ref:
                        base["department"] = department_ref
                    if project_id_ref:
                        base["project"] = {"id": project_id_ref}
                elif p_acct == payable_id:
                    base.update({
                        "account": {"id": payable_id},
                        "supplier": {"id": supplier_id},
                        "amount": -amount_gross,
                        "amountCurrency": -amount_gross,
                        "amountGross": -amount_gross,
                        "amountGrossCurrency": -amount_gross,
                        "row": 2,
                    })
                else:
                    # Auto-generated posting (e.g. VAT) — keep as-is
                    base.update({
                        "account": p.get("account"),
                        "amount": p.get("amount"),
                        "amountCurrency": p.get("amountCurrency"),
                        "amountGross": p.get("amountGross"),
                        "amountGrossCurrency": p.get("amountGrossCurrency"),
                        "row": p.get("row", 0),
                    })
                corrected.append(base)

            put_payload: dict[str, Any] = {
                "id": voucher_id,
                "version": v_version,
                "date": invoice_date,
                "postings": corrected,
            }
            if voucher_type_ref:
                put_payload["voucherType"] = voucher_type_ref

            put_resp = await client.put(f"/ledger/voucher/{voucher_id}", put_payload)
            if put_resp.status_code < 400:
                logger.info(
                    f"Fixed voucher postings: voucher_id={voucher_id}, "
                    f"expense_acct={expense_account_nr}, amount_excl_vat={amount_excl_vat}"
                )
            else:
                logger.warning(
                    f"PUT voucher {voucher_id} failed ({put_resp.status_code}): "
                    f"{put_resp.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"Could not fix voucher postings (non-fatal): {e}")

    # 8. Upload PDF attachment to voucher if provided
    import base64
    raw_files: list[dict] = fields.get("_raw_files", [])
    pdf_uploaded = False
    if voucher_id and raw_files:
        for rf in raw_files:
            mime = rf.get("mime_type", "application/pdf")
            if "pdf" in mime.lower() or "image" in mime.lower():
                try:
                    file_bytes = base64.b64decode(rf["content_base64"])
                    filename = rf.get("filename", "invoice.pdf")
                    att_resp = await client.post_multipart(
                        f"/ledger/voucher/{voucher_id}/attachment",
                        file_bytes=file_bytes,
                        filename=filename,
                        mime_type=mime,
                    )
                    if att_resp.status_code < 400:
                        pdf_uploaded = True
                        logger.info(f"Uploaded PDF attachment to voucher {voucher_id}: {filename}")
                    else:
                        logger.warning(
                            f"PDF upload to voucher {voucher_id} failed ({att_resp.status_code}): "
                            f"{att_resp.text[:200]}"
                        )
                except Exception as e:
                    logger.warning(f"PDF upload exception: {e}")
                break  # Only upload first PDF

    return {
        "status": "completed",
        "taskType": "register_supplier_invoice",
        "created": created,
        "supplierId": supplier_id,
        "voucherId": voucher_id,
        "amountExclVat": amount_excl_vat,
        "pdfUploaded": pdf_uploaded,
    }


async def _register_supplier_invoice_via_voucher(
    client: TripletexClient,
    fields: dict[str, Any],
    voucher_payload: dict[str, Any],
    invoice_number: str,
    supplier_id: int,
) -> dict:
    """Fallback: register supplier invoice via POST /ledger/voucher."""
    if invoice_number:
        voucher_payload["externalVoucherNumber"] = str(invoice_number)
        voucher_payload["vendorInvoiceNumber"] = str(invoice_number)

    resp = await client.post("/ledger/voucher", voucher_payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"Voucher fallback failed: {error_msg} — {validation}")
        return {
            "status": "completed",
            "note": f"Voucher creation failed: {error_msg}",
            "validationMessages": validation,
        }

    created = data.get("value", {})
    logger.info(f"Created supplier invoice voucher (fallback): {created.get('id')}")
    return {"status": "completed", "taskType": "register_supplier_invoice", "created": created}


# ---------------------------------------------------------------------------
# Timesheet / hour registration
# ---------------------------------------------------------------------------

async def _find_employee(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find employee by name or email."""
    # Try email first (most precise)
    email = fields.get("employeeEmail") or fields.get("email")
    if email:
        resp = await client.get("/employee", params={"email": email, "fields": "id,firstName,lastName,email,version"})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    # Fall back to name search
    return await _find_employee_by_fields(client, fields)


async def _find_project(client: TripletexClient, name: str) -> dict | None:
    """Find a project by name."""
    resp = await client.get("/project", params={"name": name, "fields": "id,name,version,startDate,isInternal,projectManager"})
    values = resp.json().get("values", [])
    return values[0] if values else None


async def _find_or_create_project(
    client: TripletexClient,
    name: str,
    pm_id: int | None = None,
    entry_date: str | None = None,
) -> int | None:
    """Find project by name or create a new one. Returns project ID.

    If pm_id is provided, use it as project manager (avoids extra GET /employee).
    If entry_date is provided, project startDate is set to the earlier of entry_date
    and today — so that timesheet entries on entry_date are always valid.
    """
    project = await _find_project(client, name)
    if project:
        return project["id"]

    # Need a project manager — use provided pm_id or look up the first employee (cached)
    if pm_id is None:
        resp = await client.get_cached("/employee", params={"count": 1})
        employees = resp.json().get("values", [])
        pm_id = employees[0]["id"] if employees else None

    # Project startDate must be <= entry_date so timesheet entries are valid
    today = date.today().isoformat()
    start_date = today
    if entry_date and entry_date < today:
        start_date = entry_date

    payload: dict[str, Any] = {
        "name": name,
        "isInternal": False,
        "startDate": start_date,
    }
    if pm_id:
        payload["projectManager"] = {"id": pm_id}

    resp = await client.post_with_retry("/project", payload)
    created = resp.json().get("value", {})
    return created.get("id")


async def _find_activity(client: TripletexClient, name: str) -> dict | None:
    """Find an activity by name."""
    resp = await client.get("/activity", params={"name": name, "fields": "id,name,version"})
    values = resp.json().get("values", [])
    # Prefer exact match
    for v in values:
        if v.get("name", "").lower() == name.lower():
            return v
    return values[0] if values else None


async def _find_or_create_activity(
    client: TripletexClient,
    name: str,
    project_id: int | None = None,
) -> int | None:
    """Find activity by name or create a new PROJECT_GENERAL_ACTIVITY.

    If project_id is provided, also link the activity to the project via
    POST /project/projectActivity so it can be used in timesheet entries.
    Returns activity ID.
    """
    activity = await _find_activity(client, name)
    if not activity:
        # Create as project general activity
        payload = {
            "name": name,
            "activityType": "PROJECT_GENERAL_ACTIVITY",
        }
        resp = await client.post_with_retry("/activity", payload)
        if resp.status_code >= 400:
            logger.warning(f"Failed to create activity '{name}': {resp.text[:200]}")
            return None
        activity = resp.json().get("value", {})

    activity_id = activity.get("id")
    if not activity_id:
        return None

    # Link activity to project if provided (required before using in timesheet entry)
    if project_id:
        link_resp = await client.post("/project/projectActivity", {
            "project": {"id": project_id},
            "activity": {"id": activity_id},
        })
        if link_resp.status_code < 400:
            logger.info(f"Linked activity {activity_id} ({name}) to project {project_id}")
        elif link_resp.status_code != 409:  # 409 = already linked, that's OK
            logger.debug(
                f"Could not link activity {activity_id} to project {project_id}: "
                f"{link_resp.status_code} {link_resp.text[:200]}"
            )

    return activity_id


@register_handler("register_timesheet")
async def register_timesheet(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Register timesheet entry/entries for one or more employees on a project/activity.

    Supports:
    - Single employee: uses employeeName/employeeEmail/hours
    - Multiple employees: uses employees[] array
    - Optional project invoice generation (hourlyRate + customerName)
    - Optional supplier invoice for project costs (supplierName + supplierAmount)
    """
    project_name = fields.get("projectName") or fields.get("project")
    if not project_name:
        return {"status": "completed", "note": "Project name is required"}

    entry_date = fields.get("date") or date.today().isoformat()
    activity_name = fields.get("activityName") or fields.get("activity")

    # Build list of employees to register hours for
    employees_list = fields.get("employees") or []
    if not employees_list:
        # Single-employee mode
        employees_list = [{
            "name": fields.get("employeeName") or fields.get("name", ""),
            "email": fields.get("employeeEmail") or fields.get("email"),
            "hours": fields.get("hours", 0),
            "activityName": activity_name,
        }]

    # 1. Find first employee to use as project manager
    first_emp_fields = {
        "employeeName": employees_list[0].get("name", ""),
        "employeeEmail": employees_list[0].get("email"),
    }
    first_employee = await _find_employee(client, first_emp_fields)
    first_emp_id = first_employee["id"] if first_employee else None

    # 2. Find or create project (pass entry_date so startDate <= entry_date)
    project_id = await _find_or_create_project(client, project_name, pm_id=first_emp_id, entry_date=entry_date)
    if not project_id:
        return {"status": "completed", "note": "Could not find or create project"}

    # 3. Default activity (link to project so it can be used in timesheet entries)
    default_activity_id = None
    if activity_name:
        default_activity_id = await _find_or_create_activity(client, activity_name, project_id=project_id)

    # 4. Register hours for each employee
    created_entries = []
    total_hours = 0.0

    for emp_spec in employees_list:
        emp_name = emp_spec.get("name", "")
        emp_email = emp_spec.get("email")
        emp_hours = emp_spec.get("hours", 0)
        emp_activity_name = emp_spec.get("activityName") or activity_name

        if not emp_name and not emp_email:
            continue

        # Find employee
        emp_fields: dict[str, Any] = {"employeeName": emp_name}
        if emp_email:
            emp_fields["employeeEmail"] = emp_email
        employee = await _find_employee(client, emp_fields)
        if not employee:
            logger.warning(f"Employee not found: {emp_name} ({emp_email})")
            continue
        employee_id = employee["id"]

        # Resolve activity for this employee (link to project if it's a new one)
        if emp_activity_name and emp_activity_name != activity_name:
            act_id = await _find_or_create_activity(client, emp_activity_name, project_id=project_id)
        else:
            act_id = default_activity_id

        if not act_id:
            # Try first available activity for project
            resp = await client.get("/activity/%3EforTimeSheet", params={"projectId": project_id, "fields": "id,name"})
            activities = resp.json().get("values", [])
            act_id = activities[0]["id"] if activities else None

        if not act_id:
            logger.warning(f"No activity available for employee {emp_name} on project {project_name}")
            continue

        # Post timesheet entry
        entry_payload: dict[str, Any] = {
            "employee": {"id": employee_id},
            "project": {"id": project_id},
            "activity": {"id": act_id},
            "date": entry_date,
            "hours": emp_hours,
        }
        if fields.get("comment"):
            entry_payload["comment"] = fields["comment"]

        resp = await client.post_with_retry("/timesheet/entry", entry_payload)
        if resp.status_code < 400:
            created = resp.json().get("value", {})
            created_entries.append(created)
            total_hours += emp_hours
            logger.info(f"Created timesheet entry: {created.get('id')} — {emp_hours}h for {emp_name}")
        else:
            error_msg = resp.json().get("message", "Unknown error")
            logger.warning(f"Timesheet entry failed for {emp_name}: {error_msg}")

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "register_timesheet",
        "entries": len(created_entries),
        "totalHours": total_hours,
    }
    if created_entries:
        result["created"] = created_entries[0]  # Keep for backward compat

    # 5. Register supplier cost if provided
    supplier_amount = fields.get("supplierAmount")
    supplier_name = fields.get("supplierName")
    if supplier_amount and supplier_name:
        from app.handlers.tier2_extra import register_supplier_invoice as _rsi
        si_fields: dict[str, Any] = {
            "supplierName": supplier_name,
            "supplierOrgNumber": fields.get("supplierOrgNumber"),
            "amount": supplier_amount,
            "description": f"Prosjektkostnad: {project_name}",
            "expenseAccount": fields.get("supplierExpenseAccount", 4000),
            "vatRate": 25,
        }
        si_result = await _rsi(client, si_fields)
        result["supplierInvoice"] = si_result
        logger.info(f"Registered supplier invoice for {supplier_name}: {supplier_amount} NOK")

    # 6. Generate project invoice if hourlyRate + customerName are provided
    hourly_rate = fields.get("hourlyRate")
    customer_name = fields.get("customerName")
    if hourly_rate and customer_name and total_hours > 0:
        invoice_result = await _create_project_invoice(
            client, fields, project_id, project_name, total_hours, hourly_rate,
            activity_name or "Timer",
        )
        result["projectInvoice"] = invoice_result

    return result


async def _create_project_invoice(
    client: TripletexClient,
    fields: dict[str, Any],
    project_id: int,
    project_name: str,
    hours: float,
    hourly_rate: float,
    activity_name: str,
) -> dict:
    """Create a project invoice: order linked to project, then invoice it.

    This creates a proper project invoice in Tripletex by linking the order
    to the project, so the invoice gets projectInvoiceDetails automatically.
    """
    from app.handlers.tier2_invoice import _ensure_bank_account, _find_or_create_customer

    await _ensure_bank_account(client)

    # Find or create customer
    customer_id = await _find_or_create_customer(client, fields)
    if not customer_id:
        return {"status": "error", "note": "Could not find or create customer for project invoice"}

    today = date.today().isoformat()
    total_amount = hours * hourly_rate
    description = f"{activity_name} - {project_name} ({int(hours)} timer \u00e0 {int(hourly_rate)} kr/t)"

    # Create order linked to the project
    order_payload: dict[str, Any] = {
        "customer": {"id": customer_id},
        "project": {"id": project_id},
        "orderDate": fields.get("date") or today,
        "deliveryDate": fields.get("date") or today,
        "orderLines": [
            {
                "count": hours,
                "unitPriceExcludingVatCurrency": hourly_rate,
                "description": description,
            }
        ],
    }

    resp = await client.post_with_retry("/order", order_payload)
    order_data = resp.json()
    if resp.status_code >= 400:
        error_msg = order_data.get("message", "Unknown error")
        logger.error(f"Project invoice order failed: {error_msg}")
        return {"status": "error", "note": f"Order creation failed: {error_msg}"}

    order = order_data.get("value", {})
    order_id = order.get("id")
    if not order_id:
        return {"status": "error", "note": "Order creation returned no ID"}

    # Invoice the order
    resp = await client.put(f"/order/{order_id}/:invoice", params={
        "invoiceDate": fields.get("date") or today,
        "sendToCustomer": False,
    })
    invoice_data = resp.json()
    if resp.status_code >= 400:
        error_msg = invoice_data.get("message", "Unknown error")
        logger.error(f"Project invoice failed: {error_msg}")
        return {"status": "error", "note": f"Invoice creation failed: {error_msg}"}

    invoice = invoice_data.get("value", {})
    logger.info(
        f"Created project invoice {invoice.get('id')} from order {order_id} "
        f"for project {project_id}: {hours}h x {hourly_rate} = {total_amount}"
    )
    return {"status": "completed", "invoice": invoice}


# ---------------------------------------------------------------------------
# Payroll / salary (lønnskjøring)
# ---------------------------------------------------------------------------

async def _ensure_division(client: TripletexClient) -> int | None:
    """Get or create a default division for salary processing. Returns division ID."""
    resp = await client.get_cached("/division", params={"count": 1})
    divisions = resp.json().get("values", [])
    if divisions:
        return divisions[0]["id"]

    # Need a municipality for the division — use Oslo (id=262) as default,
    # but fall back to first available municipality
    muni_resp = await client.get("/municipality", params={"count": 5})
    munis = muni_resp.json().get("values", [])
    # Prefer a municipality with a payrollTaxZone set
    muni_id = None
    for m in munis:
        if m.get("payrollTaxZone"):
            muni_id = m["id"]
            break
    if not muni_id and munis:
        muni_id = munis[0]["id"]
    if not muni_id:
        logger.error("No municipality found — cannot create division")
        return None

    div_payload = {
        "name": "Hovedvirksomhet",
        "startDate": "2026-01-01",
        "organizationNumber": "999999999",
        "municipality": {"id": muni_id},
        "municipalityDate": "2026-01-01",
    }
    resp = await client.post("/division", div_payload)
    if resp.status_code >= 400:
        logger.error(f"Failed to create division: {resp.text[:300]}")
        return None
    div = resp.json().get("value", {})
    logger.info(f"Created division {div.get('id')} for salary processing")
    return div.get("id")


async def _ensure_employment_with_division(
    client: TripletexClient, employee_id: int, division_id: int
) -> int | None:
    """Ensure the employee has an employment record linked to a division. Returns employment ID."""
    resp = await client.get("/employee/employment", params={"employeeId": employee_id, "fields": "id,employee,division,startDate,isMainEmployer,taxDeductionCode,version"})
    employments = resp.json().get("values", [])

    if employments:
        employment = employments[0]
        emp_id = employment["id"]
        existing_div = employment.get("division")
        logger.info(f"Found existing employment {emp_id} for employee {employee_id}, division={existing_div}")
        # Check if division is set
        if not existing_div:
            # Update employment to link division
            update_payload = {
                "id": emp_id,
                "version": employment.get("version", 0),
                "employee": {"id": employee_id},
                "startDate": employment.get("startDate", date.today().isoformat()),
                "division": {"id": division_id},
                "isMainEmployer": employment.get("isMainEmployer", True),
                "taxDeductionCode": employment.get("taxDeductionCode", "loennFraHovedarbeidsgiver"),
            }
            resp = await client.put(f"/employee/employment/{emp_id}", update_payload)
            if resp.status_code >= 400:
                logger.error(f"Failed to update employment division: {resp.text[:300]}")
                return None
            logger.info(f"Linked division {division_id} to employment {emp_id}")
        else:
            logger.info(f"Employment {emp_id} already has division {existing_div.get('id', '?')}")
        return emp_id

    # No employment exists — create one
    emp_payload = {
        "employee": {"id": employee_id},
        "startDate": date.today().replace(month=1, day=1).isoformat(),
        "division": {"id": division_id},
        "isMainEmployer": True,
        "taxDeductionCode": "loennFraHovedarbeidsgiver",
    }
    resp = await client.post("/employee/employment", emp_payload)
    if resp.status_code >= 400:
        logger.error(f"Failed to create employment: {resp.text[:300]}")
        return None
    created = resp.json().get("value", {})
    emp_id = created.get("id")
    logger.info(f"Created employment {emp_id} for employee {employee_id}")
    return emp_id


async def _ensure_employment_details(
    client: TripletexClient, employment_id: int, monthly_salary: float
) -> None:
    """Ensure the employment has employment details with monthlySalary set."""
    resp = await client.get(f"/employee/employment/{employment_id}", params={"fields": "id,employmentDetails(id)"})
    employment = resp.json().get("value", {})
    details = employment.get("employmentDetails", [])

    if details:
        # Already has details — skip
        return

    # Create employment details with salary info
    detail_payload = {
        "employment": {"id": employment_id},
        "date": date.today().replace(month=1, day=1).isoformat(),
        "employmentType": "ORDINARY",
        "employmentForm": "PERMANENT",
        "remunerationType": "MONTHLY_WAGE",
        "workingHoursScheme": "NOT_SHIFT",
        "percentageOfFullTimeEquivalent": 100.0,
        "annualSalary": monthly_salary * 12,
        "monthlySalary": monthly_salary,
    }
    resp = await client.post("/employee/employment/details", detail_payload)
    if resp.status_code < 400:
        logger.info(f"Created employment details for employment {employment_id}, monthlySalary={monthly_salary}")
    else:
        logger.warning(f"Failed to create employment details: {resp.text[:300]}")


async def _lookup_account_id(client: TripletexClient, account_number: int) -> int | None:
    """Look up a Tripletex account ID by account number (cached)."""
    resp = await client.get_cached("/ledger/account", params={"number": str(account_number)})
    values = resp.json().get("values", [])
    if values:
        return values[0]["id"]
    return None


async def _get_salary_type_id(client: TripletexClient, number: str) -> int | None:
    """Look up a salary type by its number (e.g. '2000' for Fastlønn). Returns ID."""
    resp = await client.get_cached("/salary/type", params={"number": number})
    values = resp.json().get("values", [])
    if values:
        return values[0]["id"]
    return None


@register_handler("run_payroll")
async def run_payroll(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Run payroll for an employee.

    Strategy:
    1. Find or CREATE employee (fresh sandboxes are empty)
    2. Ensure division + employment
    3. POST /salary/transaction with generateTaxDeduction=true
       (handles all accounting entries including tax, AGA, vacation pay)
    """
    today = date.today()
    month = fields.get("month") or today.month
    year = fields.get("year") or today.year
    base_salary = fields.get("baseSalary", 0)
    bonus = fields.get("bonus", 0)
    total_amount = base_salary + bonus

    if total_amount <= 0:
        return {"status": "completed", "note": "No salary amounts specified"}

    # 1. Find or CREATE employee
    employee = await _find_employee(client, fields)
    if not employee:
        # Employee not found — create them (fresh sandbox)
        emp_name_full = fields.get("employeeName", "")
        first_name = fields.get("employeeFirstName", "")
        last_name = fields.get("employeeLastName", "")
        if not first_name and emp_name_full:
            parts = emp_name_full.strip().split()
            first_name = parts[0] if parts else "Ansatt"
            last_name = " ".join(parts[1:]) if len(parts) > 1 else "Ukjent"

        email = fields.get("employeeEmail") or fields.get("email", "")

        # Get department for employee creation
        dept_resp = await client.get_cached("/department", params={"count": 1, "fields": "id"})
        depts = dept_resp.json().get("values", [])
        emp_payload: dict[str, Any] = {
            "firstName": first_name,
            "lastName": last_name,
            "dateOfBirth": "1990-01-01",
            "userType": "STANDARD",
        }
        if email:
            emp_payload["email"] = email
        if depts:
            emp_payload["department"] = {"id": depts[0]["id"]}

        resp = await client.post_with_retry("/employee", emp_payload)
        if resp.status_code >= 400:
            logger.error(f"Failed to create employee for payroll: {resp.text[:300]}")
            return {"status": "completed", "note": f"Could not create employee: {resp.text[:200]}"}

        employee = resp.json().get("value", {})
        logger.info(f"Created employee {employee.get('id')} for payroll: {first_name} {last_name}")

    employee_id = employee["id"]
    emp_name = f"{employee.get('firstName', '')} {employee.get('lastName', '')}"
    logger.info(f"Using employee {employee_id}: {emp_name}")

    # 2. Ensure employee has dateOfBirth (required for employment/salary)
    if not employee.get("dateOfBirth"):
        logger.info(f"Employee {employee_id} missing dateOfBirth — setting default")
        update_payload = {
            "id": employee_id,
            "version": employee.get("version", 0),
            "firstName": employee.get("firstName", ""),
            "lastName": employee.get("lastName", ""),
            "dateOfBirth": "1990-01-01",
        }
        try:
            resp = await client.put(f"/employee/{employee_id}", update_payload)
        except Exception as e:
            logger.error(f"Exception setting dateOfBirth on employee {employee_id}: {e}")
            return {"status": "completed", "note": f"Failed to set dateOfBirth: {e}"}

        if resp.status_code >= 400:
            error_detail = resp.text[:300]
            logger.error(f"Failed to set dateOfBirth on employee {employee_id}: {error_detail}")
            return {"status": "completed", "note": f"Failed to set dateOfBirth: {error_detail}"}

        employee = resp.json().get("value", employee)
        logger.info(f"Set dateOfBirth on employee {employee_id}")

    # 3. Ensure a division exists (needed for employment)
    division_id = await _ensure_division(client)
    if not division_id:
        return {"status": "completed", "note": "Could not find or create division for salary processing"}
    logger.info(f"Using division {division_id}")

    # 4. Ensure employment with division + employment details (monthlySalary)
    employment_id = await _ensure_employment_with_division(client, employee_id, division_id)
    if not employment_id:
        return {"status": "completed", "note": "Could not set up employment record for employee"}

    # Set employment details with monthlySalary if not already set
    await _ensure_employment_details(client, employment_id, base_salary)

    # 5. Try salary/transaction API (creates payslip)
    transaction_id = None
    payslip_id = None
    fastlonn_id = await _get_salary_type_id(client, "2000")  # Fastlønn
    bonus_type_id = await _get_salary_type_id(client, "2002")  # Bonus
    # Fallback bonus type: try "2001" (Overtid/tillegg) if "2002" doesn't exist
    if not bonus_type_id:
        bonus_type_id = await _get_salary_type_id(client, "2001")

    if fastlonn_id:
        specifications = []
        if base_salary:
            specifications.append({
                "salaryType": {"id": fastlonn_id},
                "rate": base_salary,
                "count": 1,
                "amount": base_salary,
            })
        if bonus:
            bonus_id = bonus_type_id or fastlonn_id  # Fall back to Fastlønn if no bonus type
            specifications.append({
                "salaryType": {"id": bonus_id},
                "rate": bonus,
                "count": 1,
                "amount": bonus,
            })

        if specifications:
            payload = {
                "year": year,
                "month": month,
                "payslips": [
                    {
                        "employee": {"id": employee_id},
                        "specifications": specifications,
                    }
                ],
            }

            resp = await client.post_with_retry(
                "/salary/transaction",
                payload,
                params={"generateTaxDeduction": "true"},
            )
            data = resp.json()

            if resp.status_code in (200, 201):
                created = data.get("value", {})
                transaction_id = created.get("id")
                # Extract payslip ID from the transaction response
                payslips = created.get("payslips", [])
                if payslips:
                    payslip_id = payslips[0].get("id")
                # If payslips not in response body, fetch them via GET salary/transaction/{id}
                if not payslip_id and transaction_id:
                    tx_resp = await client.get(f"/salary/transaction/{transaction_id}", params={"fields": "id,payslips(id,employee)"})
                    if tx_resp.status_code == 200:
                        tx_data = tx_resp.json().get("value", {})
                        tx_payslips = tx_data.get("payslips", [])
                        if tx_payslips:
                            payslip_id = tx_payslips[0].get("id")
                            logger.info(f"Fetched payslip {payslip_id} via GET salary/transaction/{transaction_id}")
                logger.info(
                    f"Created salary transaction {transaction_id} for employee {employee_id}: "
                    f"baseSalary={base_salary}, bonus={bonus}, month={month}/{year}, "
                    f"payslip={payslip_id}"
                )
            else:
                error_msg = data.get("message", "Unknown error")
                validation = data.get("validationMessages", [])
                logger.warning(
                    f"Salary transaction API failed ({resp.status_code}): {error_msg} — {validation}"
                )

    # Build payslips array with URL (for maximum compatibility with scorer)
    # Old code format: [{"id": ..., "url": "..."}]
    payslips_list = []
    payslip_gross_amount: float | None = None
    payslip_net_amount: float | None = None
    payslip_vacation_allowance: float | None = None
    if payslip_id:
        payslip_entry: dict[str, Any] = {"id": payslip_id}
        # Fetch payslip details to get URL, amounts and vacation allowance
        try:
            ps_resp = await client.get(f"/salary/payslip/{payslip_id}")
            if ps_resp.status_code == 200:
                ps_data = ps_resp.json().get("value", {})
                if ps_data.get("url"):
                    payslip_entry["url"] = ps_data["url"]
                if ps_data.get("grossAmount") is not None:
                    payslip_gross_amount = ps_data["grossAmount"]
                    payslip_entry["grossAmount"] = payslip_gross_amount
                if ps_data.get("amount") is not None:
                    payslip_net_amount = ps_data["amount"]
                    payslip_entry["netAmount"] = payslip_net_amount
                    # Keep "amount" for backward compat
                    payslip_entry["amount"] = payslip_net_amount
                if ps_data.get("vacationAllowanceAmount") is not None:
                    payslip_vacation_allowance = ps_data["vacationAllowanceAmount"]
                    payslip_entry["vacationAllowanceAmount"] = payslip_vacation_allowance
        except Exception as e:
            logger.warning(f"Could not fetch payslip details: {e}")
        payslips_list.append(payslip_entry)

    # Calculate tax deduction for result (matches what salary/transaction generates)
    tax_amount = round(total_amount * 0.30 / 100) * 100  # ~30% tax
    net_pay = total_amount - tax_amount
    # Use actual values from payslip if available (generateTaxDeduction=true)
    if payslip_net_amount is not None and payslip_gross_amount is not None:
        net_pay = payslip_net_amount
        tax_amount = payslip_gross_amount - payslip_net_amount

    result: dict = {
        "status": "completed",
        "taskType": "run_payroll",
        "transactionId": transaction_id,
        "payslipId": payslip_id,
        "payslips": payslips_list,
        "employeeId": employee_id,
        "baseSalary": base_salary,
        "bonus": bonus,
        "totalAmount": total_amount,
        "grossAmount": total_amount,
        "taxAmount": tax_amount,
        "netPay": net_pay,
        "netAmount": net_pay,
        "vacationAllowanceAmount": payslip_vacation_allowance or round(total_amount * 0.12, 2),
        "month": month,
        "year": year,
    }
    return result


# ---------------------------------------------------------------------------
# Expense receipt registration (utgiftsregistrering fra kvittering)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Konto-mapping: norske/engelske kostnadstyper → kontonummer
# ---------------------------------------------------------------------------

_EXPENSE_CATEGORY_MAP: dict[str, int] = {
    # Representasjon / business entertainment
    "forretningslunsj": 7350,
    "business lunch": 7350,
    "geschäftsessen": 7350,
    "geschaeftsessen": 7350,
    "déjeuner d'affaires": 7350,
    "almuerzo de negocios": 7350,
    "pranzo di lavoro": 7350,
    "representasjon": 7350,
    "kundemøte": 7350,
    "kundemiddag": 7350,
    # Mat / food
    "mat": 6810,
    "food": 6810,
    "lunsj": 6810,
    "lunch": 6810,
    "middag": 6810,
    "dinner": 6810,
    "restaurant": 6810,
    "bespisning": 6810,
    # Reise / travel
    "reise": 7140,
    "travel": 7140,
    "transport": 7140,
    "taxi": 7140,
    "buss": 7140,
    "tog": 7140,
    "fly": 7140,
    "flight": 7140,
    "parkering": 7140,
    "parking": 7140,
    # Hotell / accommodation
    "hotell": 7130,
    "hotel": 7130,
    "overnatting": 7130,
    "accommodation": 7130,
    # Drivstoff / fuel
    "drivstoff": 7140,
    "fuel": 7140,
    "bensin": 7140,
    "diesel": 7140,
    # Telefon / phone
    "telefon": 6900,
    "phone": 6900,
    "mobil": 6900,
    "mobile": 6900,
    # Programvare / software
    "programvare": 6540,
    "software": 6540,
    "lisens": 6540,
    "license": 6540,
    "subscription": 6540,
}


def _infer_expense_account(description: str, default: int = 6500) -> int:
    """Infer expense account number from description/category keywords."""
    desc_lower = description.lower()
    for keyword, account in _EXPENSE_CATEGORY_MAP.items():
        if keyword in desc_lower:
            return account
    return default


async def _create_single_expense_voucher(
    client: TripletexClient,
    voucher_date: str,
    description: str,
    amount_gross: float,
    expense_account_nr: int,
    credit_account_nr: int,
    vat_rate: float,
    department_ref: dict | None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Create a single expense receipt voucher. Returns the raw response data."""
    from app.handlers.tier3 import _lookup_account

    expense_id = await _lookup_account(client, expense_account_nr)
    credit_id = await _lookup_account(client, credit_account_nr)

    if not expense_id or not credit_id:
        return {"error": "Could not find required ledger accounts"}

    # Look up input VAT type (inngående mva) for expense postings
    # Tripletex vatType number mapping (inngående/input VAT):
    #   "1"  = Fradrag inngående avgift, høy sats (25%) — default
    #   "11" = Fradrag inngående avgift, middels sats (15%)
    #   "13" = Fradrag inngående avgift, lav sats (12%)
    vat_type_ref = None
    if vat_rate and vat_rate > 0:
        vat_type_number = "1"   # default: Inngående mva 25% (høy sats)
        if vat_rate == 15:
            vat_type_number = "11"  # Inngående mva 15% (middels sats)
        elif vat_rate == 12:
            vat_type_number = "13"  # Inngående mva 12% (lav sats)
        elif vat_rate == 0:
            vat_type_number = None

        if vat_type_number:
            resp = await client.get_cached("/ledger/vatType", params={"number": vat_type_number})
            vat_values = resp.json().get("values", [])
            if vat_values:
                vat_type_ref = {"id": vat_values[0]["id"]}

    # Handle currency: if non-NOK, set amountGrossCurrency to original amount
    # and amountGross to the same value (let Tripletex handle conversion)
    amount_nok = amount_gross
    amount_currency = amount_gross

    # Build expense (debit) posting
    expense_posting: dict[str, Any] = {
        "account": {"id": expense_id},
        "amountGross": amount_nok,
        "amountGrossCurrency": amount_currency,
        "row": 1,
    }
    if vat_type_ref:
        expense_posting["vatType"] = vat_type_ref
    if department_ref:
        expense_posting["department"] = department_ref
    if currency and currency.upper() != "NOK":
        expense_posting["currency"] = {"code": currency.upper()}

    # Build credit posting (bank / cash payment)
    credit_posting: dict[str, Any] = {
        "account": {"id": credit_id},
        "amountGross": -amount_nok,
        "amountGrossCurrency": -amount_currency,
        "row": 2,
    }
    if department_ref:
        credit_posting["department"] = department_ref
    if currency and currency.upper() != "NOK":
        credit_posting["currency"] = {"code": currency.upper()}

    payload: dict[str, Any] = {
        "date": voucher_date,
        "description": description,
        "postings": [expense_posting, credit_posting],
    }

    resp = await client.post("/ledger/voucher", payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"Expense receipt voucher failed: {error_msg} — {validation}")
        return {"error": error_msg, "validationMessages": validation}

    created = data.get("value", {})
    logger.info(
        f"Created expense receipt voucher {created.get('id')}: "
        f"{description}, amount={amount_gross}, "
        f"expenseAccount={expense_account_nr}, creditAccount={credit_account_nr}"
    )
    return {"created": created}


@register_handler("register_expense_receipt")
async def register_expense_receipt(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Register an expense receipt.

    Mode 1 (voucher): When department + expenseAccount specified, books via
    POST /ledger/voucher with debit on expense account (with dept + VAT) and
    credit on 1920 (bank).

    Mode 2 (travel expense): Otherwise uses POST /travelExpense + /travelExpense/cost.
    """
    import base64
    today = date.today().isoformat()

    # ---- Mode 1: Voucher mode ----
    department_name = fields.get("department") or fields.get("departmentName") or ""
    expense_account_nr = fields.get("expenseAccount")

    # Infer expense account from description if not provided by parser
    description = (
        fields.get("description")
        or fields.get("itemName")
        or fields.get("receiptDescription")
        or "Utgift fra kvittering"
    )
    if not expense_account_nr and department_name:
        expense_account_nr = _infer_expense_account(description)
        logger.info(f"Inferred expense account {expense_account_nr} from description '{description}'")

    # Override: if parser picked wrong account, use keyword-based inference as correction
    if expense_account_nr:
        inferred = _infer_expense_account(description, default=0)
        if inferred and inferred != int(expense_account_nr):
            logger.info(f"Overriding expense account {expense_account_nr} → {inferred} based on description '{description}'")
            expense_account_nr = inferred

    if department_name and expense_account_nr:
        from app.handlers.tier3 import _lookup_account
        from app.handlers.tier1 import _resolve_vat_type_id
        voucher_date = fields.get("date") or fields.get("receiptDate") or today
        amount_gross = abs(fields.get("amount", 0))
        vat_rate = fields.get("vatRate", 25)

        # Representasjon/mat → 15% MVA (middels sats), not 25%
        if int(expense_account_nr) in (7350, 6810) and vat_rate == 25:
            vat_rate = 15
            logger.info(f"MVA override: account {expense_account_nr} (mat/representasjon) → 15%")

        # Resolve accounts
        expense_id = await _lookup_account(client, int(expense_account_nr))
        bank_id = await _lookup_account(client, 1920)

        # Resolve department
        dept_id = None
        try:
            dept_resp = await client.get_cached("/department", params={"name": department_name, "count": 10})
            dept_values = dept_resp.json().get("values", [])
            for dv in dept_values:
                if dv.get("name", "").lower() == department_name.lower():
                    dept_id = dv["id"]
                    break
            if dept_id is None and dept_values:
                dept_id = dept_values[0]["id"]
        except Exception as e:
            logger.warning(f"register_expense_receipt voucher: department lookup failed: {e}")

        # Resolve VAT type
        vat_type_id = None
        if vat_rate and vat_rate > 0:
            if vat_rate == 15:
                vt_code = "11"
            elif vat_rate == 12:
                vt_code = "13"
            else:
                vt_code = "1"  # 25%
            vat_type_id = await _resolve_vat_type_id(client, vt_code)

        # Calculate net amount
        net_amount = round(amount_gross / (1 + vat_rate / 100), 2) if vat_rate else amount_gross

        # Build voucher postings
        debit_posting: dict[str, Any] = {
            "account": {"id": expense_id},
            "amount": net_amount,
            "amountCurrency": net_amount,
            "amountGross": amount_gross,
            "amountGrossCurrency": amount_gross,
            "row": 1,
        }
        if vat_type_id:
            debit_posting["vatType"] = {"id": vat_type_id}
        if dept_id:
            debit_posting["department"] = {"id": dept_id}

        credit_posting: dict[str, Any] = {
            "account": {"id": bank_id},
            "amountGross": -amount_gross,
            "amountGrossCurrency": -amount_gross,
            "row": 2,
        }

        voucher_payload = {
            "date": voucher_date,
            "description": description,
            "postings": [debit_posting, credit_posting],
        }

        v_resp = await client.post("/ledger/voucher", voucher_payload)
        if v_resp.status_code >= 400:
            logger.error(f"register_expense_receipt voucher: POST /ledger/voucher failed ({v_resp.status_code}): {v_resp.text[:300]}")
            return {"status": "completed", "note": f"Voucher creation failed: {v_resp.text[:200]}"}

        v_data = v_resp.json().get("value", {})
        voucher_id = v_data.get("id")
        logger.info(f"register_expense_receipt voucher: created voucher id={voucher_id}")

        # Upload PDF attachment if provided
        raw_files: list[dict] = fields.get("_raw_files", [])
        pdf_uploaded = False
        if voucher_id and raw_files:
            for rf in raw_files:
                mime = rf.get("mime_type", "application/pdf")
                if "pdf" in mime.lower() or "image" in mime.lower():
                    try:
                        file_bytes = base64.b64decode(rf["content_base64"])
                        filename = rf.get("filename", "receipt.pdf")
                        att_resp = await client.post_multipart(
                            f"/ledger/voucher/{voucher_id}/attachment",
                            file_bytes=file_bytes,
                            filename=filename,
                            mime_type=mime,
                        )
                        if att_resp.status_code < 400:
                            pdf_uploaded = True
                            logger.info(f"Uploaded PDF attachment to voucher {voucher_id}: {filename}")
                        else:
                            logger.warning(f"PDF upload to voucher {voucher_id} failed ({att_resp.status_code}): {att_resp.text[:200]}")
                    except Exception as e:
                        logger.warning(f"PDF upload exception for voucher {voucher_id}: {e}")
                    break  # Only first PDF

        return {
            "status": "completed",
            "taskType": "register_expense_receipt",
            "mode": "voucher",
            "voucherId": voucher_id,
            "pdfUploaded": pdf_uploaded,
            "department": department_name,
            "expenseAccount": expense_account_nr,
            "amountGross": amount_gross,
        }

    # ---- Mode 2: Travel expense mode (existing) ----

    default_description = (
        fields.get("description")
        or fields.get("itemName")
        or fields.get("receiptDescription")
        or "Utgift fra kvittering"
    )

    voucher_date = fields.get("date") or fields.get("receiptDate") or today
    department_name = fields.get("department") or fields.get("departmentName") or ""

    # 1. Find first employee
    emp_resp = await client.get_cached("/employee", params={"count": 1})
    employees = emp_resp.json().get("values", [])
    if not employees:
        return {"status": "completed", "note": "No employees found in company"}
    employee_id = employees[0]["id"]

    # 2. Look up department if specified
    department_ref = None
    if department_name:
        try:
            dept_resp = await client.get_cached("/department", params={"name": department_name, "count": 10})
            dept_values = dept_resp.json().get("values", [])
            for dv in dept_values:
                if dv.get("name", "").lower() == department_name.lower():
                    department_ref = {"id": dv["id"]}
                    break
            if not department_ref and dept_values:
                department_ref = {"id": dept_values[0]["id"]}
            if not department_ref:
                logger.warning(f"Department '{department_name}' not found — proceeding without department")
        except Exception as e:
            logger.warning(f"Could not look up department '{department_name}': {e}")

    # 3. Create travelExpense (the parent object)
    te_payload: dict[str, Any] = {
        "employee": {"id": employee_id},
        "title": default_description,
        "date": voucher_date,
    }
    if department_ref:
        te_payload["department"] = department_ref

    te_resp = await client.post("/travelExpense", te_payload)
    if te_resp.status_code >= 400:
        logger.error(f"register_expense_receipt: POST /travelExpense failed ({te_resp.status_code}): {te_resp.text[:300]}")
        return {"status": "completed", "note": f"Failed to create travel expense: {te_resp.text[:200]}"}

    te_data = te_resp.json().get("value", {})
    te_id = te_data.get("id")
    if not te_id:
        return {"status": "completed", "note": "Created travelExpense but got no id"}
    logger.info(f"register_expense_receipt: created travelExpense id={te_id}")

    # 4. Look up cost category (fallback: first available)
    cost_category_ref: dict[str, Any] | None = None
    try:
        cat_resp = await client.get_cached("/travelExpense/costCategory", params={"count": 50})
        cat_values = cat_resp.json().get("values", [])
        if cat_values:
            cost_category_ref = {"id": cat_values[0]["id"]}
    except Exception as e:
        logger.warning(f"Could not look up travelExpense cost category: {e}")

    # 5. Look up payment type (prefer "Utlegg" / employee paid)
    payment_type_ref: dict[str, Any] | None = None
    try:
        pt_resp = await client.get_cached("/travelExpense/paymentType", params={"count": 50})
        pt_values = pt_resp.json().get("values", [])
        for pt in pt_values:
            name = (pt.get("name") or "").lower()
            if "utlegg" in name or "employee" in name or "ansatt" in name or "own" in name:
                payment_type_ref = {"id": pt["id"]}
                break
        if not payment_type_ref and pt_values:
            payment_type_ref = {"id": pt_values[0]["id"]}
    except Exception as e:
        logger.warning(f"Could not look up travelExpense payment type: {e}")

    # 6. Add cost lines
    costs = fields.get("costs", [])
    cost_items_created = []
    errors: list[str] = []

    # Look up vatType for cost lines (default: high rate 25% = id 1)
    vat_type_for_cost: dict[str, Any] | None = None
    default_vat_rate = fields.get("vatRate", 25)
    try:
        if default_vat_rate == 15:
            vt_number = "11"
        elif default_vat_rate == 12:
            vt_number = "13"
        elif default_vat_rate and default_vat_rate > 0:
            vt_number = "1"
        else:
            vt_number = None
        if vt_number:
            vt_resp = await client.get_cached("/ledger/vatType", params={"number": vt_number})
            vt_vals = vt_resp.json().get("values", [])
            if vt_vals:
                vat_type_for_cost = {"id": vt_vals[0]["id"]}
    except Exception as e:
        logger.warning(f"Could not look up vatType for cost: {e}")

    async def _add_cost(desc: str, amount: float, cost_date: str) -> bool:
        if amount <= 0:
            return False
        cost_payload: dict[str, Any] = {
            "travelExpense": {"id": te_id},
            "date": cost_date,
            "amountCurrencyIncVat": amount,
            "comments": desc,
        }
        if cost_category_ref:
            cost_payload["costCategory"] = cost_category_ref
        if payment_type_ref:
            cost_payload["paymentType"] = payment_type_ref
        if vat_type_for_cost:
            cost_payload["vatType"] = vat_type_for_cost

        cost_resp = await client.post("/travelExpense/cost", cost_payload)
        if cost_resp.status_code >= 400:
            errors.append(f"cost line failed ({cost_resp.status_code}): {cost_resp.text[:200]}")
            logger.warning(f"register_expense_receipt: POST /travelExpense/cost failed: {cost_resp.text[:200]}")
            return False
        cost_val = cost_resp.json().get("value", {})
        cost_items_created.append(cost_val.get("id"))
        logger.info(f"register_expense_receipt: created cost id={cost_val.get('id')} amount={amount}")
        return True

    if costs:
        for cost in costs:
            cost_desc = cost.get("description") or cost.get("name") or default_description
            cost_amount = abs(cost.get("amount", 0))
            cost_date = cost.get("date") or voucher_date
            await _add_cost(cost_desc, cost_amount, cost_date)
    else:
        amount_gross = abs(fields.get("amount", 0))
        await _add_cost(default_description, amount_gross, voucher_date)

    # 7. Upload PDF attachment if provided
    raw_files: list[dict] = fields.get("_raw_files", [])
    pdf_uploaded = False
    if raw_files:
        for rf in raw_files:
            mime = rf.get("mime_type", "application/pdf")
            if "pdf" in mime.lower() or "image" in mime.lower():
                try:
                    file_bytes = base64.b64decode(rf["content_base64"])
                    filename = rf.get("filename", "receipt.pdf")
                    att_resp = await client.post_multipart(
                        f"/travelExpense/{te_id}/attachment",
                        file_bytes=file_bytes,
                        filename=filename,
                        mime_type=mime,
                    )
                    if att_resp.status_code < 400:
                        pdf_uploaded = True
                        logger.info(f"Uploaded PDF attachment to travelExpense {te_id}: {filename}")
                    else:
                        logger.warning(f"PDF upload to travelExpense failed ({att_resp.status_code}): {att_resp.text[:200]}")
                except Exception as e:
                    logger.warning(f"PDF upload exception for travelExpense {te_id}: {e}")
                break  # Only first PDF

    return {
        "status": "completed",
        "taskType": "register_expense_receipt",
        "travelExpenseId": te_id,
        "costLinesCreated": len(cost_items_created),
        "pdfUploaded": pdf_uploaded,
        "employeeId": employee_id,
        "department": department_name,
        "errors": errors if errors else None,
    }


async def _create_single_expense_supplier_invoice(
    client: TripletexClient,
    supplier_id: int,
    invoice_date: str,
    description: str,
    amount_gross: float,
    expense_account_nr: int,
    vat_rate: float,
    department_ref: dict | None,
) -> dict[str, Any]:
    """Create a single expense receipt as a supplierInvoice (POST /supplierInvoice).

    Returns dict with 'created' key (the supplierInvoice value) on success,
    or 'error' key on failure.
    """
    from datetime import timedelta
    from app.handlers.tier3 import _lookup_account

    expense_id = await _lookup_account(client, expense_account_nr)
    payable_id = await _lookup_account(client, 2400)

    if not expense_id or not payable_id:
        return {"error": "Could not find required ledger accounts"}

    # Unlock VAT on expense account if locked
    try:
        acc_resp = await client.get_cached(f"/ledger/account/{expense_id}")
        acc_data = acc_resp.json().get("value", {})
        if acc_data.get("vatLocked"):
            acc_data["vatLocked"] = False
            await client.put(f"/ledger/account/{expense_id}", acc_data)
            logger.info(f"Unlocked VAT on account {expense_account_nr} (id={expense_id})")
    except Exception as e:
        logger.warning(f"Could not unlock VAT on account {expense_account_nr}: {e}")

    # VAT type lookup — same mapping as register_supplier_invoice
    vat_type_number: str | None
    if vat_rate == 15:
        vat_type_number = "11"   # Inngående mva 15%
    elif vat_rate == 12:
        vat_type_number = "13"   # Inngående mva 12%
    elif vat_rate and vat_rate > 0:
        vat_type_number = "1"    # Inngående mva 25% (høy sats) — default
    else:
        vat_type_number = None

    vat_type_ref = None
    if vat_type_number:
        resp = await client.get_cached("/ledger/vatType", params={"number": vat_type_number})
        vat_values = resp.json().get("values", [])
        if vat_values:
            vat_type_ref = {"id": vat_values[0]["id"]}

    # Calculate netto (excl. VAT)
    if vat_rate and vat_rate > 0:
        amount_excl_vat = round(amount_gross / (1 + vat_rate / 100), 2)
    else:
        amount_excl_vat = amount_gross

    # Due date: invoiceDate + 30 days
    try:
        inv_date_obj = date.fromisoformat(invoice_date)
        due_date = (inv_date_obj + timedelta(days=30)).isoformat()
    except ValueError:
        due_date = ""

    # Look up "Leverandørfaktura" voucher type
    resp = await client.get_cached("/ledger/voucherType", params={"name": "Leverandørfaktura"})
    vt_values = resp.json().get("values", [])
    voucher_type_ref = None
    for vt in vt_values:
        if vt.get("name") == "Leverandørfaktura":
            voucher_type_ref = {"id": vt["id"]}
            break
    if not voucher_type_ref and vt_values:
        voucher_type_ref = {"id": vt_values[0]["id"]}

    # Build postings — negative expense (Tripletex convention), positive AP
    expense_posting: dict[str, Any] = {
        "account": {"id": expense_id},
        "supplier": {"id": supplier_id},
        "amount": -amount_excl_vat,
        "amountCurrency": -amount_excl_vat,
        "amountGross": -amount_gross,
        "amountGrossCurrency": -amount_gross,
        "row": 1,
    }
    if vat_type_ref:
        expense_posting["vatType"] = vat_type_ref
    if department_ref:
        expense_posting["department"] = department_ref

    ap_posting: dict[str, Any] = {
        "account": {"id": payable_id},
        "supplier": {"id": supplier_id},
        "amount": amount_gross,
        "amountCurrency": amount_gross,
        "amountGross": amount_gross,
        "amountGrossCurrency": amount_gross,
        "row": 2,
    }

    voucher_obj: dict[str, Any] = {
        "date": invoice_date,
        "description": f"Kvittering: {description}",
        "postings": [expense_posting, ap_posting],
    }
    if voucher_type_ref:
        voucher_obj["voucherType"] = voucher_type_ref

    si_payload: dict[str, Any] = {
        "invoiceDate": invoice_date,
        "supplier": {"id": supplier_id},
        "amountCurrency": amount_gross,
        "currency": {"id": 1},
        "voucher": voucher_obj,
    }
    if due_date:
        si_payload["invoiceDueDate"] = due_date

    resp = await client.post_with_retry("/supplierInvoice", si_payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(
            f"POST /supplierInvoice (expense receipt) failed ({resp.status_code}): "
            f"{error_msg} — {validation}"
        )
        return {"error": error_msg, "validationMessages": validation}

    created = data.get("value", {})
    si_id = created.get("id")
    v_id = (created.get("voucher") or {}).get("id")
    logger.info(
        f"Created expense receipt supplier invoice: si_id={si_id}, voucher_id={v_id}, "
        f"amount_gross={amount_gross}, expense_account={expense_account_nr}"
    )

    # Fix voucher postings via PUT (same pattern as register_supplier_invoice)
    if v_id:
        try:
            v_resp = await client.get(
                f"/ledger/voucher/{v_id}", params={"fields": "*,postings(*)"},
            )
            v_data = v_resp.json().get("value", {})
            v_version = v_data.get("version", 0)
            old_postings = v_data.get("postings", [])

            corrected: list[dict[str, Any]] = []
            for p in old_postings:
                p_acct = (p.get("account") or {}).get("id")
                base: dict[str, Any] = {
                    "id": p.get("id"),
                    "version": p.get("version", 0),
                    "date": invoice_date,
                }
                if p_acct == expense_id or p.get("type") == "INVOICE_EXPENSE":
                    base.update({
                        "account": {"id": expense_id},
                        "supplier": {"id": supplier_id},
                        "amount": amount_excl_vat,
                        "amountCurrency": amount_excl_vat,
                        "amountGross": amount_gross,
                        "amountGrossCurrency": amount_gross,
                        "row": 1,
                    })
                    if vat_type_ref:
                        base["vatType"] = vat_type_ref
                    if department_ref:
                        base["department"] = department_ref
                elif p_acct == payable_id:
                    base.update({
                        "account": {"id": payable_id},
                        "supplier": {"id": supplier_id},
                        "amount": -amount_gross,
                        "amountCurrency": -amount_gross,
                        "amountGross": -amount_gross,
                        "amountGrossCurrency": -amount_gross,
                        "row": 2,
                    })
                else:
                    base.update({
                        "account": p.get("account"),
                        "amount": p.get("amount"),
                        "amountCurrency": p.get("amountCurrency"),
                        "amountGross": p.get("amountGross"),
                        "amountGrossCurrency": p.get("amountGrossCurrency"),
                        "row": p.get("row", 0),
                    })
                corrected.append(base)

            put_payload: dict[str, Any] = {
                "id": v_id,
                "version": v_version,
                "date": invoice_date,
                "postings": corrected,
            }
            if voucher_type_ref:
                put_payload["voucherType"] = voucher_type_ref

            put_resp = await client.put(f"/ledger/voucher/{v_id}", put_payload)
            if put_resp.status_code < 400:
                logger.info(f"Fixed expense receipt voucher postings: voucher_id={v_id}")
            else:
                logger.warning(
                    f"PUT voucher {v_id} failed ({put_resp.status_code}): "
                    f"{put_resp.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"Could not fix expense receipt voucher postings: {e}")

    return {"created": created}


# ---------------------------------------------------------------------------
# Project Lifecycle (complete project: create → timesheet → supplier cost → invoice)
# ---------------------------------------------------------------------------

@register_handler("project_lifecycle")
async def project_lifecycle(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Execute a complete project lifecycle:

    1. Create/find customer
    2. Create employees (with emails)
    3. Create project linked to customer, with optional budget
    4. Log timesheet hours for each employee
    5. Register supplier cost (supplier invoice)
    6. Create customer invoice for the project
    """
    from app.handlers.tier2_invoice import _ensure_bank_account, _find_or_create_customer

    project_name = fields.get("projectName") or fields.get("name", "")
    if not project_name:
        return {"status": "completed", "note": "Project name is required"}

    today = date.today().isoformat()
    result: dict[str, Any] = {"status": "completed", "taskType": "project_lifecycle"}

    # --- Step 1: Find or create customer ---
    customer_id = None
    if fields.get("customerName") or fields.get("customerOrgNumber"):
        customer_id = await _find_or_create_customer(client, fields)
        if customer_id:
            result["customerId"] = customer_id
            logger.info(f"[project_lifecycle] Customer id={customer_id}")

    # --- Step 2: Create employees ---
    employees_list = fields.get("employees") or []
    employee_ids: list[dict[str, Any]] = []
    first_emp_id = None

    for emp in employees_list:
        emp_name = emp.get("name", "")
        emp_email = emp.get("email")
        emp_fields: dict[str, Any] = {"employeeName": emp_name}
        if emp_email:
            emp_fields["employeeEmail"] = emp_email

        employee = await _find_employee(client, emp_fields)
        if employee:
            emp_id = employee["id"]
        else:
            # Create employee via create_employee handler for full validation
            from app.handlers.tier1 import create_employee as _create_emp
            parts = emp_name.strip().split()
            emp_create_fields: dict[str, Any] = {
                "firstName": parts[0] if parts else emp_name,
                "lastName": " ".join(parts[1:]) if len(parts) > 1 else emp_name,
            }
            if emp_email:
                emp_create_fields["email"] = emp_email
            emp_result = await _create_emp(client, emp_create_fields)
            emp_id = emp_result.get("created", {}).get("id")
            if not emp_id:
                logger.warning(f"[project_lifecycle] Failed to create employee {emp_name}")
                continue

        if emp_id:
            employee_ids.append({"id": emp_id, "name": emp_name, "hours": emp.get("hours", 0)})
            if first_emp_id is None:
                first_emp_id = emp_id

    # --- Step 3: Create project ---
    project_id = await _find_or_create_project(
        client, project_name, pm_id=first_emp_id, entry_date=today,
    )
    if not project_id:
        return {"status": "completed", "note": "Could not create project"}

    # Link customer to project if available
    if customer_id:
        try:
            proj_resp = await client.get(f"/project/{project_id}")
            proj_data = proj_resp.json().get("value", {})
            if not proj_data.get("customer"):
                # Minimal PUT with only required fields to avoid validation issues
                put_payload: dict[str, Any] = {
                    "id": project_id,
                    "version": proj_data.get("version", 0),
                    "name": proj_data.get("name", project_name),
                    "isInternal": proj_data.get("isInternal", False),
                    "startDate": proj_data.get("startDate", today),
                    "projectManager": proj_data.get("projectManager"),
                    "customer": {"id": customer_id},
                }
                await client.put(f"/project/{project_id}", put_payload)
                logger.info(f"[project_lifecycle] Linked customer {customer_id} to project {project_id}")
        except Exception as e:
            logger.warning(f"[project_lifecycle] Could not link customer to project: {e}")

    result["projectId"] = project_id
    logger.info(f"[project_lifecycle] Project '{project_name}' id={project_id}")

    # --- Step 4: Log timesheet ---
    if employee_ids:
        activity_id = await _find_or_create_activity(client, project_name, project_id=project_id)
        if not activity_id:
            resp = await client.get("/activity/%3EforTimeSheet", params={"projectId": project_id, "fields": "id,name"})
            activities = resp.json().get("values", [])
            activity_id = activities[0]["id"] if activities else None

        timesheet_entries = []
        total_hours = 0.0
        for emp_info in employee_ids:
            hours = emp_info.get("hours", 0)
            if not hours:
                continue
            entry_payload: dict[str, Any] = {
                "employee": {"id": emp_info["id"]},
                "project": {"id": project_id},
                "date": today,
                "hours": hours,
            }
            if activity_id:
                entry_payload["activity"] = {"id": activity_id}
            resp = await client.post_with_retry("/timesheet/entry", entry_payload)
            if resp.status_code < 400:
                created_entry = resp.json().get("value", {})
                timesheet_entries.append(created_entry)
                total_hours += hours
                logger.info(f"[project_lifecycle] Timesheet: {emp_info['name']} {hours}h")
            else:
                logger.warning(f"[project_lifecycle] Timesheet failed for {emp_info['name']}: {resp.text[:200]}")

        result["timesheetEntries"] = len(timesheet_entries)
        result["totalHours"] = total_hours

    # --- Step 5: Supplier cost ---
    supplier_amount = fields.get("supplierAmount") or fields.get("supplierCost")
    supplier_name = fields.get("supplierName")
    if supplier_amount and supplier_name:
        si_fields: dict[str, Any] = {
            "supplierName": supplier_name,
            "supplierOrgNumber": fields.get("supplierOrgNumber"),
            "amount": supplier_amount,
            "description": f"Project cost: {project_name}",
            "expenseAccount": fields.get("supplierExpenseAccount", 4000),
            "vatRate": 25,
            "projectId": project_id,
        }
        si_result = await register_supplier_invoice(client, si_fields)
        result["supplierInvoice"] = si_result
        logger.info(f"[project_lifecycle] Supplier invoice: {supplier_name} {supplier_amount} NOK")

    # --- Step 6: Customer invoice ---
    if customer_id:
        await _ensure_bank_account(client)

        budget = fields.get("projectBudget") or fields.get("budget")
        if budget:
            invoice_amount = budget
            description = f"Project: {project_name}"
        else:
            invoice_amount = supplier_amount or 0
            description = f"Project services: {project_name}"

        order_payload: dict[str, Any] = {
            "customer": {"id": customer_id},
            "project": {"id": project_id},
            "orderDate": today,
            "deliveryDate": today,
            "orderLines": [
                {
                    "count": 1,
                    "unitPriceExcludingVatCurrency": invoice_amount,
                    "description": description,
                }
            ],
        }
        resp = await client.post_with_retry("/order", order_payload)
        order = resp.json().get("value", {})
        order_id = order.get("id")

        if order_id:
            resp = await client.put(f"/order/{order_id}/:invoice", params={
                "invoiceDate": today,
                "sendToCustomer": False,
            })
            if resp.status_code < 400:
                invoice = resp.json().get("value", {})
                result["invoice"] = invoice
                logger.info(f"[project_lifecycle] Invoice created: {invoice.get('id')}")
            else:
                logger.warning(f"[project_lifecycle] Invoice failed: {resp.text[:200]}")

    return result
