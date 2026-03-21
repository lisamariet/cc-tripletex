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
        resp = await client.get("/supplier", params={"organizationNumber": org_nr})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    if name:
        resp = await client.get("/supplier", params={"name": name})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    return None


async def _find_product(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find a product by number or name."""
    number = fields.get("productNumber") or fields.get("number")
    name = fields.get("productName") or fields.get("name")

    if number:
        resp = await client.get("/product", params={"number": str(number)})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    if name:
        resp = await client.get("/product", params={"name": name})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    return None


async def _find_customer(client: TripletexClient, fields: dict[str, Any]) -> dict | None:
    """Find a customer by org number or name."""
    org_nr = fields.get("customerOrgNumber") or fields.get("organizationNumber")
    name = fields.get("customerName") or fields.get("name")

    if org_nr:
        resp = await client.get("/customer", params={"organizationNumber": org_nr})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    if name:
        resp = await client.get("/customer", params={"name": name})
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
        if line.get("vatCode"):
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
        resp = await client.post("/supplier", supplier_payload)
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
    due_date = fields.get("dueDate") or fields.get("invoiceDueDate") or ""

    # Default due date: 30 days after invoice date
    if not due_date:
        try:
            inv_date_obj = date.fromisoformat(invoice_date)
            due_date = (inv_date_obj + timedelta(days=30)).isoformat()
        except ValueError:
            due_date = ""

    # Use parser-provided amountExcludingVat if available, otherwise calculate
    vat_rate = fields.get("vatRate", 25)
    if fields.get("amountExcludingVat"):
        amount_excl_vat = abs(float(fields["amountExcludingVat"]))
        # If we have excl. VAT but not gross, derive gross
        if not amount_gross and amount_excl_vat:
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
        acc_resp = await client.get(f"/ledger/account/{expense_id}")
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
    expense_posting: dict[str, Any] = {
        "account": {"id": expense_id},
        "supplier": {"id": supplier_id},
        "amountGross": amount_gross,
        "amountGrossCurrency": amount_gross,
        "row": 1,
    }
    if vat_type_ref:
        expense_posting["vatType"] = vat_type_ref
    if department_ref:
        expense_posting["department"] = department_ref

    ap_posting: dict[str, Any] = {
        "account": {"id": payable_id},
        "supplier": {"id": supplier_id},
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
    si_payload: dict[str, Any] = {
        "invoiceDate": invoice_date,
        "supplier": {"id": supplier_id},
        "amountCurrency": amount_gross,
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
    voucher_id = (created.get("voucher") or {}).get("id")
    logger.info(
        f"Created supplier invoice: si_id={si_id}, voucher_id={voucher_id}, "
        f"amount_gross={amount_gross}, amount_excl_vat={amount_excl_vat}, due_date={due_date}"
    )

    return {
        "status": "completed",
        "taskType": "register_supplier_invoice",
        "created": created,
        "supplierId": supplier_id,
        "voucherId": voucher_id,
        "amountExclVat": amount_excl_vat,
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
        resp = await client.get("/employee", params={"email": email})
        values = resp.json().get("values", [])
        if values:
            return values[0]

    # Fall back to name search
    return await _find_employee_by_fields(client, fields)


async def _find_project(client: TripletexClient, name: str) -> dict | None:
    """Find a project by name."""
    resp = await client.get("/project", params={"name": name})
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

    resp = await client.post("/project", payload)
    created = resp.json().get("value", {})
    return created.get("id")


async def _find_activity(client: TripletexClient, name: str) -> dict | None:
    """Find an activity by name."""
    resp = await client.get("/activity", params={"name": name})
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
        resp = await client.post("/activity", payload)
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
            resp = await client.get("/activity/%3EforTimeSheet", params={"projectId": project_id})
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

        resp = await client.post("/timesheet/entry", entry_payload)
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

    resp = await client.post("/order", order_payload)
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
    resp = await client.get("/employee/employment", params={"employeeId": employee_id})
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
    3. POST /salary/transaction (creates payslip draft)
    4. ALSO create a manual voucher with salary postings
       (salary/transaction only creates a draft that is invisible to
        GET /salary/payslip search and salary/compilation)
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

        resp = await client.post("/employee", emp_payload)
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

            resp = await client.post_with_retry("/salary/transaction", payload)
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
                    tx_resp = await client.get(f"/salary/transaction/{transaction_id}")
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

    # 6. ALSO create a manual voucher with full Norwegian payroll postings.
    #    This provides a secondary verification path via ledger/posting.
    #    Norwegian payroll requires: salary, tax deduction, AGA, net bank payment.
    #    Fetch all required accounts in one batch call to minimize API calls.
    accounts_resp = await client.get_cached(
        "/ledger/account",
        params={"number": "1920,2600,2770,2940,5000,5020,5400", "fields": "id,number", "count": 10},
    )
    account_map: dict[int, int] = {}  # account_number -> account_id
    for acc in accounts_resp.json().get("values", []):
        account_map[acc["number"]] = acc["id"]

    salary_account_id = account_map.get(5000)    # Lønn til ansatte
    bank_account_id = account_map.get(1920)      # Bankinnskudd
    tax_account_id = account_map.get(2600)        # Forskuddstrekk
    aga_expense_id = account_map.get(5400)        # Arbeidsgiveravgift
    aga_payable_id = account_map.get(2770)        # Skyldig arbeidsgiveravgift
    vacation_payable_id = account_map.get(2940)   # Skyldig feriepenger
    vacation_expense_id = account_map.get(5020)   # Feriepenger

    # Look up "Lønnsbilag" voucher type for proper categorization
    vt_resp = await client.get_cached("/ledger/voucherType", params={"name": "Lønnsbilag"})
    salary_voucher_type_ref = None
    for vt in vt_resp.json().get("values", []):
        if "lønn" in vt.get("name", "").lower():
            salary_voucher_type_ref = {"id": vt["id"]}
            break

    voucher_id = None
    if salary_account_id and bank_account_id:
        voucher_date = f"{year}-{month:02d}-28"
        description = f"Lønn {emp_name} {month:02d}/{year}"
        if bonus:
            description += f" (grunnlønn {base_salary} + bonus {bonus})"

        # Norwegian payroll calculations
        gross = total_amount
        tax_rate = 0.30  # Standard tabelltrekk ~30%
        tax_deduction = round(gross * tax_rate / 100) * 100  # Rounded to nearest 100
        net_pay = gross - tax_deduction
        aga_rate = 0.141  # Standard AGA sone 1 (14.1%)
        aga_amount = round(gross * aga_rate, 2)
        vacation_rate = 0.12  # Standard feriepenger 12%
        vacation_amount = round(gross * vacation_rate, 2)

        postings = []
        row = 1

        # DEBIT: Salary expense (konto 5000)
        if base_salary:
            postings.append({
                "account": {"id": salary_account_id},
                "employee": {"id": employee_id},
                "amountGross": base_salary,
                "amountGrossCurrency": base_salary,
                "row": row,
            })
            row += 1

        if bonus:
            postings.append({
                "account": {"id": salary_account_id},
                "employee": {"id": employee_id},
                "amountGross": bonus,
                "amountGrossCurrency": bonus,
                "row": row,
            })
            row += 1

        # CREDIT: Tax deduction (konto 2600 Forskuddstrekk)
        if tax_account_id and tax_deduction > 0:
            postings.append({
                "account": {"id": tax_account_id},
                "amountGross": -tax_deduction,
                "amountGrossCurrency": -tax_deduction,
                "row": row,
            })
            row += 1

        # CREDIT: Net pay to bank (konto 1920)
        postings.append({
            "account": {"id": bank_account_id},
            "amountGross": -net_pay,
            "amountGrossCurrency": -net_pay,
            "row": row,
        })
        row += 1

        # DEBIT: AGA expense (konto 5400)
        if aga_expense_id and aga_amount > 0:
            postings.append({
                "account": {"id": aga_expense_id},
                "amountGross": aga_amount,
                "amountGrossCurrency": aga_amount,
                "row": row,
            })
            row += 1

        # CREDIT: AGA payable (konto 2770)
        if aga_payable_id and aga_amount > 0:
            postings.append({
                "account": {"id": aga_payable_id},
                "amountGross": -aga_amount,
                "amountGrossCurrency": -aga_amount,
                "row": row,
            })
            row += 1

        # DEBIT: Vacation pay expense (konto 5020)
        # CREDIT: Vacation pay payable (konto 2940)
        if vacation_expense_id and vacation_payable_id and vacation_amount > 0:
            postings.append({
                "account": {"id": vacation_expense_id},
                "amountGross": vacation_amount,
                "amountGrossCurrency": vacation_amount,
                "row": row,
            })
            row += 1
            postings.append({
                "account": {"id": vacation_payable_id},
                "amountGross": -vacation_amount,
                "amountGrossCurrency": -vacation_amount,
                "row": row,
            })
            row += 1

        voucher_payload: dict[str, Any] = {
            "date": voucher_date,
            "description": description,
            "postings": postings,
        }
        if salary_voucher_type_ref:
            voucher_payload["voucherType"] = salary_voucher_type_ref

        resp = await client.post("/ledger/voucher", voucher_payload)
        if resp.status_code < 400:
            voucher_id = resp.json().get("value", {}).get("id")
            logger.info(
                f"Created payroll voucher {voucher_id} for employee {employee_id}: "
                f"gross={gross}, tax={tax_deduction}, net={net_pay}, aga={aga_amount}"
            )
        else:
            logger.warning(f"Payroll voucher creation failed: {resp.text[:300]}")
            # Fallback: simple voucher without tax/AGA if full posting fails
            simple_postings = [
                {
                    "account": {"id": salary_account_id},
                    "employee": {"id": employee_id},
                    "amountGross": total_amount,
                    "amountGrossCurrency": total_amount,
                    "row": 1,
                },
                {
                    "account": {"id": bank_account_id},
                    "amountGross": -total_amount,
                    "amountGrossCurrency": -total_amount,
                    "row": 2,
                },
            ]
            simple_payload = {
                "date": voucher_date,
                "description": description,
                "postings": simple_postings,
            }
            resp = await client.post("/ledger/voucher", simple_payload)
            if resp.status_code < 400:
                voucher_id = resp.json().get("value", {}).get("id")
                logger.info(f"Created simple payroll voucher {voucher_id} (fallback)")
            else:
                logger.warning(f"Simple payroll voucher also failed: {resp.text[:300]}")

    # Build payslips array with URL (for maximum compatibility with scorer)
    # Old code format: [{"id": ..., "url": "..."}]
    payslips_list = []
    if payslip_id:
        payslip_entry: dict[str, Any] = {"id": payslip_id}
        # Fetch payslip details to get URL and amount
        try:
            ps_resp = await client.get(f"/salary/payslip/{payslip_id}")
            if ps_resp.status_code == 200:
                ps_data = ps_resp.json().get("value", {})
                if ps_data.get("url"):
                    payslip_entry["url"] = ps_data["url"]
                if ps_data.get("grossAmount"):
                    payslip_entry["grossAmount"] = ps_data["grossAmount"]
                if ps_data.get("amount"):
                    payslip_entry["amount"] = ps_data["amount"]
        except Exception as e:
            logger.warning(f"Could not fetch payslip details: {e}")
        payslips_list.append(payslip_entry)

    result: dict = {
        "status": "completed",
        "taskType": "run_payroll",
        "transactionId": transaction_id or voucher_id,
        "payslipId": payslip_id,
        "payslips": payslips_list,
        "voucherId": voucher_id,
        "employeeId": employee_id,
        "baseSalary": base_salary,
        "bonus": bonus,
        "totalAmount": total_amount,
        "month": month,
        "year": year,
    }
    return result


# ---------------------------------------------------------------------------
# Expense receipt registration (utgiftsregistrering fra kvittering)
# ---------------------------------------------------------------------------

@register_handler("register_expense_receipt")
async def register_expense_receipt(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Register an expense from a receipt via POST /ledger/voucher.

    Creates a voucher with:
      - DEBIT:  expense account (default 6500 — kontorrekvisita/office supplies)
      - CREDIT: bank/cash account (default 1920)
    Applies input VAT (inngående mva) if vatRate > 0.
    Optionally links the voucher to a department via the department dimension.
    """
    from app.handlers.tier3 import _lookup_account

    today = date.today().isoformat()
    description = (
        fields.get("description")
        or fields.get("itemName")
        or fields.get("receiptDescription")
        or "Utgift fra kvittering"
    )

    # Support both a single `amount` and a `costs` list (multiple receipts).
    # When `costs` is present, sum up all cost amounts and build a description.
    costs = fields.get("costs", [])
    if costs and not fields.get("amount"):
        total = sum(abs(c.get("amount", 0)) for c in costs)
        amount_gross = total
        # Build composite description from cost items if no explicit description
        if description == "Utgift fra kvittering":
            parts = [c.get("description", "") for c in costs if c.get("description")]
            if parts:
                description = ", ".join(parts)
    else:
        amount_gross = abs(fields.get("amount", 0))

    voucher_date = fields.get("date") or fields.get("receiptDate") or today
    vat_rate = fields.get("vatRate", 25)

    # Expense account: default 6500 (kontorrekvisita / office supplies).
    # The LLM should infer a more specific account from the item name, e.g.:
    #   6500 — kontorrekvisita (pens, paper, desk lamp / skrivebordslampe)
    #   6540 — kontormøbler (Kontorstoler / office chairs)
    #   6300 — leie lokaler (rent)
    #   7140 — reise og diett (travel)
    expense_account_nr = int(fields.get("expenseAccount", 6500))
    credit_account_nr = int(fields.get("creditAccount", 1920))

    # Look up account IDs
    expense_id = await _lookup_account(client, expense_account_nr)
    credit_id = await _lookup_account(client, credit_account_nr)

    if not expense_id or not credit_id:
        return {"status": "completed", "note": "Could not find required ledger accounts"}

    # Look up input VAT type (inngående mva) for expense postings
    vat_type_ref = None
    if vat_rate and vat_rate > 0:
        vat_type_number = "11"  # Inngående mva 25%
        if vat_rate == 15:
            vat_type_number = "13"
        elif vat_rate == 12:
            vat_type_number = "14"

        resp = await client.get_cached("/ledger/vatType", params={"number": vat_type_number})
        vat_values = resp.json().get("values", [])
        if vat_values:
            vat_type_ref = {"id": vat_values[0]["id"]}

    # Look up department if specified
    department_ref = None
    department_name = fields.get("department") or fields.get("departmentName")
    if department_name:
        resp = await client.get_cached("/department", params={"name": department_name})
        dept_values = resp.json().get("values", [])
        # Prefer exact match (case-insensitive)
        for d in dept_values:
            if d.get("name", "").lower() == department_name.lower():
                department_ref = {"id": d["id"]}
                break
        if not department_ref and dept_values:
            department_ref = {"id": dept_values[0]["id"]}
        if not department_ref:
            logger.warning(f"Department '{department_name}' not found — proceeding without department")

    # Build expense (debit) posting
    expense_posting: dict[str, Any] = {
        "account": {"id": expense_id},
        "amountGross": amount_gross,
        "amountGrossCurrency": amount_gross,
        "row": 1,
    }
    if vat_type_ref:
        expense_posting["vatType"] = vat_type_ref
    if department_ref:
        expense_posting["department"] = department_ref

    # Build credit posting (bank / cash payment)
    credit_posting: dict[str, Any] = {
        "account": {"id": credit_id},
        "amountGross": -amount_gross,
        "amountGrossCurrency": -amount_gross,
        "row": 2,
    }
    if department_ref:
        credit_posting["department"] = department_ref

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
        return {
            "status": "completed",
            "note": f"Expense receipt registration failed: {error_msg}",
            "validationMessages": validation,
        }

    created = data.get("value", {})
    logger.info(
        f"Created expense receipt voucher {created.get('id')}: "
        f"{description}, amount={amount_gross}, dept={department_name}, "
        f"expenseAccount={expense_account_nr}, creditAccount={credit_account_nr}"
    )
    return {
        "status": "completed",
        "taskType": "register_expense_receipt",
        "created": created,
        "voucherId": created.get("id"),
        "amount": amount_gross,
        "expenseAccount": expense_account_nr,
        "department": department_name,
    }
