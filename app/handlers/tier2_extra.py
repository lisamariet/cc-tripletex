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
    # Find or create customer
    from app.handlers.tier2_invoice import _find_or_create_customer
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
        order_lines.append(order_line)

    order_payload = {
        "customer": {"id": customer_id},
        "orderDate": fields.get("orderDate") or today,
        "deliveryDate": fields.get("deliveryDate") or today,
        "orderLines": order_lines,
    }
    resp = await client.post("/order", order_payload)
    data = resp.json()
    logger.info(f"Created order: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_order", "created": data.get("value", {})}


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


async def _find_or_create_project(client: TripletexClient, name: str) -> int | None:
    """Find project by name or create a new one. Returns project ID."""
    project = await _find_project(client, name)
    if project:
        return project["id"]

    # Need a project manager — use the first employee
    resp = await client.get("/employee", params={"count": 1})
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
    """Register a timesheet entry (hours) for an employee on a project/activity."""
    # 1. Find employee
    employee = await _find_employee(client, fields)
    if not employee:
        return {"status": "completed", "note": "Employee not found"}
    employee_id = employee["id"]

    # 2. Find or create project
    project_name = fields.get("projectName") or fields.get("project")
    if not project_name:
        return {"status": "completed", "note": "Project name is required"}
    project_id = await _find_or_create_project(client, project_name)
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
    return {
        "status": "completed",
        "taskType": "register_timesheet",
        "created": created,
    }


# ---------------------------------------------------------------------------
# Payroll / salary (lønnskjøring)
# ---------------------------------------------------------------------------

async def _ensure_division(client: TripletexClient) -> int | None:
    """Get or create a default division for salary processing. Returns division ID."""
    resp = await client.get("/division", params={"count": 1})
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
        # Check if division is set
        if not employment.get("division"):
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


async def _get_salary_type_id(client: TripletexClient, number: str) -> int | None:
    """Look up a salary type by its number (e.g. '2000' for Fastlønn). Returns ID."""
    resp = await client.get_cached("/salary/type", params={"number": number})
    values = resp.json().get("values", [])
    if values:
        return values[0]["id"]
    return None


@register_handler("run_payroll")
async def run_payroll(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Run payroll for an employee: create a salary transaction with payslip.

    Tripletex salary/transaction API structure:
      POST /salary/transaction
      {
        "year": int,
        "month": int,
        "payslips": [
          {
            "employee": {"id": int},
            "specifications": [
              {"salaryType": {"id": int}, "rate": number, "count": number, "amount": number}
            ]
          }
        ]
      }
    Note: Do NOT put "date", "year", "month", or "employee" inside payslip or specification objects.
    """
    # 1. Find the employee
    employee = await _find_employee(client, fields)
    if not employee:
        return {"status": "completed", "note": "Employee not found"}
    employee_id = employee["id"]
    logger.info(f"Found employee {employee_id}: {employee.get('firstName')} {employee.get('lastName')}")

    # 2. Ensure employee has dateOfBirth (required for employment creation)
    if not employee.get("dateOfBirth"):
        try:
            update_payload = {
                "id": employee_id,
                "version": employee.get("version", 0),
                "firstName": employee.get("firstName", ""),
                "lastName": employee.get("lastName", ""),
                "dateOfBirth": "1990-01-01",
            }
            resp = await client.put(f"/employee/{employee_id}", update_payload)
            if resp.status_code < 400:
                employee = resp.json().get("value", employee)
                logger.info(f"Set dateOfBirth on employee {employee_id}")
        except Exception as e:
            logger.warning(f"Could not set dateOfBirth: {e}")

    # 3. Ensure a division exists
    division_id = await _ensure_division(client)
    if not division_id:
        return {"status": "completed", "note": "Could not find or create division for salary processing"}

    # 4. Ensure employment with division
    employment_id = await _ensure_employment_with_division(client, employee_id, division_id)
    if not employment_id:
        return {"status": "completed", "note": "Could not set up employment record for employee"}

    # 5. Get salary type IDs
    fastlonn_id = await _get_salary_type_id(client, "2000")  # Fastlønn (base salary)
    bonus_type_id = await _get_salary_type_id(client, "2002")  # Bonus
    if not fastlonn_id:
        return {"status": "completed", "note": "Could not find salary type for base salary (Fastlønn/2000)"}

    # 6. Determine month/year and amounts
    today = date.today()
    month = fields.get("month") or today.month
    year = fields.get("year") or today.year
    base_salary = fields.get("baseSalary", 0)
    bonus = fields.get("bonus", 0)

    # 7. Build salary specifications (only salaryType, rate, count, amount)
    specifications = []

    if base_salary:
        specifications.append({
            "salaryType": {"id": fastlonn_id},
            "rate": base_salary,
            "count": 1,
            "amount": base_salary,
        })

    if bonus and bonus_type_id:
        specifications.append({
            "salaryType": {"id": bonus_type_id},
            "rate": bonus,
            "count": 1,
            "amount": bonus,
        })

    if not specifications:
        return {"status": "completed", "note": "No salary amounts specified"}

    # 8. Create salary transaction with payslip
    #    Top-level: year, month, payslips[]
    #    Payslip: employee, specifications[]
    #    Specification: salaryType, rate, count, amount
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

    resp = await client.post("/salary/transaction", payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"Salary transaction failed: {error_msg} — {validation}")
        return {
            "status": "completed",
            "note": f"Salary transaction failed: {error_msg}",
            "validationMessages": validation,
        }

    created = data.get("value", {})
    transaction_id = created.get("id")
    payslips = created.get("payslips", [])
    logger.info(
        f"Created salary transaction {transaction_id} for employee {employee_id}: "
        f"baseSalary={base_salary}, bonus={bonus}, month={month}/{year}"
    )

    return {
        "status": "completed",
        "taskType": "run_payroll",
        "transactionId": transaction_id,
        "payslips": payslips,
        "employeeId": employee_id,
        "baseSalary": base_salary,
        "bonus": bonus,
        "month": month,
        "year": year,
    }
