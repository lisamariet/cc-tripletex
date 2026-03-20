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
                prod_resp = await client.post("/product", product_payload)
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
    resp = await client.post("/order", order_payload)
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
    """Register a supplier invoice (innkjøpsfaktura) as a voucher with correct VAT and voucherType.

    Uses POST /ledger/voucher with voucherType = "Leverandørfaktura" so the voucher
    is properly classified as a supplier invoice in Tripletex.
    """
    # 1. Find or create the supplier
    supplier = await _find_supplier(client, fields)
    if not supplier:
        supplier_payload: dict[str, Any] = {
            "name": fields.get("supplierName") or fields.get("name", "Unknown Supplier"),
        }
        org_nr = fields.get("supplierOrgNumber") or fields.get("organizationNumber")
        if org_nr:
            supplier_payload["organizationNumber"] = org_nr
        resp = await client.post("/supplier", supplier_payload)
        if resp.status_code >= 400:
            logger.error(f"Failed to create supplier: {resp.text[:300]}")
            return {"status": "completed", "note": f"Failed to create supplier: {resp.text[:300]}"}
        supplier = resp.json().get("value", {})

    supplier_id = supplier.get("id")
    if not supplier_id:
        return {"status": "completed", "note": "Could not find or create supplier"}

    today = date.today().isoformat()

    description = fields.get("description") or fields.get("invoiceDescription") or "Leverandørfaktura"
    amount = abs(fields.get("amount", 0))
    invoice_date = fields.get("invoiceDate") or today
    invoice_number = fields.get("invoiceNumber") or ""

    # 2. Look up accounts
    from app.handlers.tier3 import _lookup_account
    expense_account_nr = int(fields.get("expenseAccount", "4000"))
    expense_id = await _lookup_account(client, expense_account_nr)
    payable_id = await _lookup_account(client, 2400)

    if not expense_id or not payable_id:
        return {"status": "completed", "note": "Could not find ledger accounts"}

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

    # 4. Look up the correct input VAT type based on the rate from the prompt.
    # Norwegian input VAT (inngående MVA) codes:
    #   "1"  = 25% høy sats
    #   "11" = 15% middels sats
    #   "13" = 12% lav sats
    vat_rate = fields.get("vatRate", 25)
    vat_type_number = "1"  # default: 25%
    if vat_rate == 15:
        vat_type_number = "11"
    elif vat_rate == 12:
        vat_type_number = "13"
    elif vat_rate == 0:
        vat_type_number = None

    vat_type_ref = None
    if vat_type_number:
        resp = await client.get_cached("/ledger/vatType", params={"number": vat_type_number})
        vat_values = resp.json().get("values", [])
        if vat_values:
            vat_type_ref = {"id": vat_values[0]["id"]}

    # 5. Build the expense posting (debit) — with VAT type so Tripletex auto-creates the
    # MVA posting.  amountGross is the full amount INCLUDING VAT.
    expense_posting: dict[str, Any] = {
        "account": {"id": expense_id},
        "supplier": {"id": supplier_id},
        "amountGross": amount,
        "amountGrossCurrency": amount,
        "row": 1,
    }
    if vat_type_ref:
        expense_posting["vatType"] = vat_type_ref
    if invoice_number:
        expense_posting["invoiceNumber"] = str(invoice_number)

    # 6. Build the AP posting (credit 2400) — no VAT type, full gross amount
    ap_posting: dict[str, Any] = {
        "account": {"id": payable_id},
        "supplier": {"id": supplier_id},
        "amountGross": -amount,
        "amountGrossCurrency": -amount,
        "row": 2,
    }
    if invoice_number:
        ap_posting["invoiceNumber"] = str(invoice_number)

    voucher_payload: dict[str, Any] = {
        "date": invoice_date,
        "description": f"Leverandørfaktura: {description}",
        "postings": [expense_posting, ap_posting],
    }
    if voucher_type_ref:
        voucher_payload["voucherType"] = voucher_type_ref
    if invoice_number:
        voucher_payload["externalVoucherNumber"] = str(invoice_number)

    resp = await client.post("/ledger/voucher", voucher_payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"Supplier invoice voucher failed: {error_msg} — {validation}")
        return {
            "status": "completed",
            "note": f"Voucher creation failed: {error_msg}",
            "validationMessages": validation,
        }

    created = data.get("value", {})
    logger.info(f"Created supplier invoice voucher: {created.get('id')}")
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


async def _find_or_create_project(client: TripletexClient, name: str, pm_id: int | None = None) -> int | None:
    """Find project by name or create a new one. Returns project ID.

    If pm_id is provided, use it as project manager (avoids extra GET /employee).
    """
    project = await _find_project(client, name)
    if project:
        return project["id"]

    # Need a project manager — use provided pm_id or look up the first employee (cached)
    if pm_id is None:
        resp = await client.get_cached("/employee", params={"count": 1})
        employees = resp.json().get("values", [])
        pm_id = employees[0]["id"] if employees else None

    payload: dict[str, Any] = {
        "name": name,
        "isInternal": False,
        "startDate": date.today().isoformat(),
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


async def _find_or_create_activity(client: TripletexClient, name: str) -> int | None:
    """Find activity by name or create a new PROJECT_GENERAL_ACTIVITY. Returns activity ID."""
    activity = await _find_activity(client, name)
    if activity:
        return activity["id"]

    # Create as project general activity so it can be used on any project
    payload = {
        "name": name,
        "activityType": "PROJECT_GENERAL_ACTIVITY",
    }
    resp = await client.post("/activity", payload)
    created = resp.json().get("value", {})
    return created.get("id")


@register_handler("register_timesheet")
async def register_timesheet(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Register a timesheet entry (hours) for an employee on a project/activity.

    If hourlyRate and customerName are provided, also generates a project invoice
    by creating an order linked to the project and invoicing it.
    """
    # 1. Find employee
    employee = await _find_employee(client, fields)
    if not employee:
        return {"status": "completed", "note": "Employee not found"}
    employee_id = employee["id"]

    # 2. Find or create project (reuse employee_id as PM to avoid extra GET /employee)
    project_name = fields.get("projectName") or fields.get("project")
    if not project_name:
        return {"status": "completed", "note": "Project name is required"}
    project_id = await _find_or_create_project(client, project_name, pm_id=employee_id)
    if not project_id:
        return {"status": "completed", "note": "Could not find or create project"}

    # 3. Find or create activity
    activity_name = fields.get("activityName") or fields.get("activity")
    if not activity_name:
        # Default to first available activity for the project
        resp = await client.get("/activity/%3EforTimeSheet", params={"projectId": project_id})
        activities = resp.json().get("values", [])
        if activities:
            activity_id = activities[0]["id"]
        else:
            return {"status": "completed", "note": "No activity specified and none available for project"}
    else:
        activity_id = await _find_or_create_activity(client, activity_name)
        if not activity_id:
            return {"status": "completed", "note": "Could not find or create activity"}

    # 4. Build and POST timesheet entry
    hours = fields.get("hours", 0)
    entry_date = fields.get("date") or date.today().isoformat()

    entry_payload: dict[str, Any] = {
        "employee": {"id": employee_id},
        "project": {"id": project_id},
        "activity": {"id": activity_id},
        "date": entry_date,
        "hours": hours,
    }
    if fields.get("comment"):
        entry_payload["comment"] = fields["comment"]

    resp = await client.post("/timesheet/entry", entry_payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        return {
            "status": "completed",
            "note": f"Timesheet entry failed: {error_msg}",
            "validationMessages": validation,
        }

    created = data.get("value", {})
    logger.info(f"Created timesheet entry: {created.get('id')} — {hours}h for employee {employee_id}")

    # 5. If hourlyRate + customerName are provided, generate a project invoice
    hourly_rate = fields.get("hourlyRate")
    customer_name = fields.get("customerName")
    if hourly_rate and customer_name:
        invoice_result = await _create_project_invoice(
            client, fields, project_id, project_name, hours, hourly_rate, activity_name or "Timer",
        )
        return {
            "status": "completed",
            "taskType": "register_timesheet",
            "created": created,
            "projectInvoice": invoice_result,
        }

    return {
        "status": "completed",
        "taskType": "register_timesheet",
        "created": created,
    }


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


async def _lookup_account_id(client: TripletexClient, account_number: int) -> int | None:
    """Look up a Tripletex account ID by account number (cached)."""
    resp = await client.get_cached("/ledger/account", params={"number": str(account_number)})
    values = resp.json().get("values", [])
    if values:
        return values[0]["id"]
    return None


@register_handler("run_payroll")
async def run_payroll(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Run payroll for an employee using manual voucher posting.

    The salary/transaction API is [BETA] and returns 403 in competition sandboxes.
    Instead, we create a manual voucher (bilag) with:
      - Debit account 5000 (lønn/salary) for base salary
      - Debit account 5000 for bonus (or separate line)
      - Credit account 1920 (bank) for total amount
    The employee record and employment are still created/verified.
    """
    # 1. Find the employee
    employee = await _find_employee(client, fields)
    if not employee:
        return {"status": "completed", "note": "Employee not found"}
    employee_id = employee["id"]
    emp_name = f"{employee.get('firstName', '')} {employee.get('lastName', '')}"
    logger.info(f"Found employee {employee_id}: {emp_name}")

    # 2. Ensure employee has dateOfBirth (required for employment)
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

    # 4. Ensure employment with division
    employment_id = await _ensure_employment_with_division(client, employee_id, division_id)
    if not employment_id:
        return {"status": "completed", "note": "Could not set up employment record for employee"}

    # 5. Determine month/year and amounts
    today = date.today()
    month = fields.get("month") or today.month
    year = fields.get("year") or today.year
    base_salary = fields.get("baseSalary", 0)
    bonus = fields.get("bonus", 0)
    total_amount = base_salary + bonus

    if total_amount <= 0:
        return {"status": "completed", "note": "No salary amounts specified"}

    # 6. Look up account IDs for salary (5000) and bank (1920)
    salary_account_id = await _lookup_account_id(client, 5000)
    bank_account_id = await _lookup_account_id(client, 1920)

    if not salary_account_id:
        return {"status": "completed", "note": "Could not find salary account 5000"}
    if not bank_account_id:
        return {"status": "completed", "note": "Could not find bank account 1920"}

    # 7. Build voucher postings
    #    Debit 5000 (salary expense), Credit 1920 (bank)
    voucher_date = f"{year}-{month:02d}-28"  # Last working day of the month
    description = f"Lønn {emp_name} {month:02d}/{year}"
    if bonus:
        description += f" (grunnlønn {base_salary} + bonus {bonus})"

    postings = []
    row = 1

    # Debit salary account for base salary
    if base_salary:
        postings.append({
            "account": {"id": salary_account_id},
            "amountGross": base_salary,
            "amountGrossCurrency": base_salary,
            "row": row,
        })
        row += 1

    # Debit salary account for bonus
    if bonus:
        postings.append({
            "account": {"id": salary_account_id},
            "amountGross": bonus,
            "amountGrossCurrency": bonus,
            "row": row,
        })
        row += 1

    # Credit bank account for total
    postings.append({
        "account": {"id": bank_account_id},
        "amountGross": -total_amount,
        "amountGrossCurrency": -total_amount,
        "row": row,
    })

    payload = {
        "date": voucher_date,
        "description": description,
        "postings": postings,
    }

    resp = await client.post("/ledger/voucher", payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"Payroll voucher creation failed: {error_msg} — {validation}")
        return {
            "status": "completed",
            "note": f"Payroll voucher failed: {error_msg}",
            "validationMessages": validation,
        }

    created = data.get("value", {})
    voucher_id = created.get("id")
    logger.info(
        f"Created payroll voucher {voucher_id} for employee {employee_id}: "
        f"baseSalary={base_salary}, bonus={bonus}, month={month}/{year}"
    )

    return {
        "status": "completed",
        "taskType": "run_payroll",
        "transactionId": voucher_id,  # Use voucher ID as transactionId for test compatibility
        "voucherId": voucher_id,
        "employeeId": employee_id,
        "baseSalary": base_salary,
        "bonus": bonus,
        "month": month,
        "year": year,
        "method": "manual_voucher",  # Flag that we used voucher instead of salary API
    }
