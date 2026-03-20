"""Extra Tier 2 handlers — update/delete operations and supplier invoices."""
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
    """Register a supplier invoice (innkjøpsfaktura)."""
    # Find or create the supplier
    supplier = await _find_supplier(client, fields)
    if not supplier:
        # Create supplier
        supplier_payload: dict[str, Any] = {
            "name": fields.get("supplierName") or fields.get("name", "Unknown Supplier"),
        }
        org_nr = fields.get("supplierOrgNumber") or fields.get("organizationNumber")
        if org_nr:
            supplier_payload["organizationNumber"] = org_nr
        resp = await client.post("/supplier", supplier_payload)
        supplier = resp.json().get("value", {})

    supplier_id = supplier.get("id")
    if not supplier_id:
        return {"status": "completed", "note": "Could not find or create supplier"}

    today = date.today().isoformat()

    # Create supplier invoice via voucher
    # Supplier invoices are typically posted as vouchers:
    #   Debit: expense account (e.g. 4000 series)
    #   Credit: accounts payable (2400)
    description = fields.get("description") or fields.get("invoiceDescription") or "Leverandørfaktura"
    amount = abs(fields.get("amount", 0))
    invoice_date = fields.get("invoiceDate") or today

    # Look up accounts
    # 4000 = Innkjøp (default expense)
    # 2400 = Leverandørgjeld (accounts payable)
    from app.handlers.tier3 import _lookup_account
    expense_account_nr = fields.get("expenseAccount", "4000")
    expense_id = await _lookup_account(client, expense_account_nr)
    payable_id = await _lookup_account(client, "2400")

    if not expense_id or not payable_id:
        return {"status": "completed", "note": "Could not find ledger accounts"}

    voucher_payload = {
        "date": invoice_date,
        "description": f"Leverandørfaktura: {description}",
        "postings": [
            {
                "account": {"id": expense_id},
                "amountGross": amount,
                "amountGrossCurrency": amount,
                "row": 1,
            },
            {
                "account": {"id": payable_id},
                "amountGross": -amount,
                "amountGrossCurrency": -amount,
                "row": 2,
            },
        ],
    }

    resp = await client.post("/ledger/voucher", voucher_payload)
    data = resp.json()
    logger.info(f"Created supplier invoice voucher: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "register_supplier_invoice", "created": data.get("value", {})}
