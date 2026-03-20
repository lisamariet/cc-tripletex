"""Tier 2 handlers — travel expense operations (×2 points)."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

# Keywords that indicate a cost line is per diem / diet / daily allowance
_PER_DIEM_KEYWORDS = re.compile(
    r"diett|per\s*diem|dagpenger|daily\s*(?:rate|allowance)|diet(?!\w)|"
    r"kostgodtgjørelse|dagsats|kost\s*og\s*losji|subsistence",
    re.IGNORECASE,
)


async def _find_employee(client: TripletexClient, fields: dict[str, Any]) -> int | None:
    """Find an employee by name. Returns employee ID or None."""
    first = fields.get("employeeFirstName", "")
    last = fields.get("employeeLastName", "")
    name = fields.get("employeeName", "")

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

    params["fields"] = "id,firstName,lastName,email"
    resp = await client.get("/employee", params=params)
    employees = resp.json().get("values", [])
    if employees:
        return employees[0]["id"]
    return None


async def _get_cost_category(client: TripletexClient) -> int | None:
    """Get first available cost category ID."""
    resp = await client.get_cached("/travelExpense/costCategory")
    cats = resp.json().get("values", [])
    # Prefer "Kontorrekvisita" or similar generic category
    for cat in cats:
        if "kontor" in cat.get("title", "").lower():
            return cat["id"]
    return cats[0]["id"] if cats else None


async def _get_payment_type_private(client: TripletexClient) -> int | None:
    """Get payment type ID for private expense (Privat utlegg)."""
    resp = await client.get_cached("/travelExpense/paymentType")
    types = resp.json().get("values", [])
    for t in types:
        if "privat" in t.get("description", "").lower():
            return t["id"]
    return types[0]["id"] if types else None


def _is_per_diem_cost(cost: dict[str, Any]) -> bool:
    """Check if a cost line represents per diem / diet allowance."""
    desc = cost.get("description", "")
    return bool(_PER_DIEM_KEYWORDS.search(desc))


def _extract_per_diem_days(cost: dict[str, Any]) -> int:
    """Try to extract number of days from per diem cost description."""
    desc = cost.get("description", "")
    # Match patterns like "4 days", "4 dager", "(4 days)", "Per diem (4 days)"
    m = re.search(r"(\d+)\s*(?:days?|dager?|dag|jours?|Tage?|días?|dias?)", desc, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Try to calculate from amount and rate if available
    return 1


async def _get_per_diem_rate_type(client: TripletexClient) -> int | None:
    """Get a per diem rate type ID from /travelExpense/rate."""
    try:
        resp = await client.get_cached("/travelExpense/rate", params={"type": "PER_DIEM"})
        rates = resp.json().get("values", [])
        if rates:
            return rates[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to get per diem rate type: {e}")
    return None


async def _get_per_diem_rate_category(client: TripletexClient) -> int | None:
    """Get a per diem rate category ID from /travelExpense/rateCategory."""
    try:
        resp = await client.get_cached("/travelExpense/rateCategory", params={"type": "PER_DIEM"})
        cats = resp.json().get("values", [])
        if cats:
            # Prefer domestic category
            for cat in cats:
                name = cat.get("name", "").lower()
                if "innland" in name or "domestic" in name or "norge" in name:
                    return cat["id"]
            return cats[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to get per diem rate category: {e}")
    return None


async def _create_per_diem_compensation(
    client: TripletexClient,
    te_id: int,
    cost: dict[str, Any],
    fields: dict[str, Any],
) -> bool:
    """Create a per diem compensation entry. Returns True on success."""
    rate_type_id = await _get_per_diem_rate_type(client)
    rate_category_id = await _get_per_diem_rate_category(client)

    days = _extract_per_diem_days(cost)
    amount = cost.get("amount", 0)
    rate = amount / days if days > 0 else amount

    # Extract destination from title or cost description
    title = fields.get("title", "")
    location = fields.get("destination", "")
    if not location:
        # Try to extract location from title, e.g. "Client visit Oslo" -> "Oslo"
        # Look for city/place name after common prefixes
        m = re.search(
            r"(?:visit|besøk|reise|trip|tur|viaje|viagem|voyage|Reise)\s+(?:to\s+|til\s+|a\s+|à\s+|nach\s+)?(.+)",
            title,
            re.IGNORECASE,
        )
        if m:
            location = m.group(1).strip()
        else:
            location = title

    payload: dict[str, Any] = {
        "travelExpense": {"id": te_id},
        "count": days,
        "rate": rate,
        "amount": amount,
        "location": location,
        "overnightAccommodation": "NONE",
        "isDeductionForBreakfast": False,
        "isDeductionForLunch": False,
        "isDeductionForDinner": False,
    }

    if rate_type_id:
        payload["rateType"] = {"id": rate_type_id}
    if rate_category_id:
        payload["rateCategory"] = {"id": rate_category_id}

    try:
        resp = await client.post("/travelExpense/perDiemCompensation", payload)
        status = resp.status_code
        if status in (200, 201):
            per_diem = resp.json().get("value", {})
            logger.info(f"Created perDiemCompensation {per_diem.get('id')} for TE {te_id}")
            return True
        else:
            logger.warning(
                f"perDiemCompensation POST returned {status}: {resp.text[:500]}"
            )
            return False
    except Exception as e:
        logger.warning(f"perDiemCompensation POST failed: {e}")
        return False


@register_handler("create_travel_expense")
async def create_travel_expense(client: TripletexClient, fields: dict[str, Any]) -> dict:
    employee_id = await _find_employee(client, fields)
    if not employee_id:
        return {"status": "completed", "note": "Employee not found for travel expense"}

    # Create the travel expense
    te_payload = {
        "employee": {"id": employee_id},
        "title": fields.get("title", "Travel Expense"),
        "date": fields.get("date", ""),
    }
    resp = await client.post("/travelExpense", te_payload)
    te = resp.json().get("value", {})
    te_id = te.get("id")

    # Get required IDs for cost lines
    cost_category_id = await _get_cost_category(client)
    payment_type_id = await _get_payment_type_private(client)

    per_diem_count = 0
    cost_count = 0

    # Add cost lines — separate per diem from regular costs
    for cost in fields.get("costs", []):
        if _is_per_diem_cost(cost):
            # Try per diem compensation endpoint first
            success = await _create_per_diem_compensation(client, te_id, cost, fields)
            if success:
                per_diem_count += 1
                continue
            # Fallback: add as regular cost line if per diem endpoint fails
            logger.info("Per diem endpoint failed, falling back to cost line")

        # Regular cost line
        cost_payload: dict[str, Any] = {
            "travelExpense": {"id": te_id},
            "date": cost.get("date", fields.get("date", "")),
            "amountCurrencyIncVat": cost.get("amount", 0),
        }
        # Note: "description" does NOT exist on travelExpense/cost — don't send it
        if cost_category_id:
            cost_payload["costCategory"] = {"id": cost_category_id}
        if payment_type_id:
            cost_payload["paymentType"] = {"id": payment_type_id}

        await client.post("/travelExpense/cost", cost_payload)
        cost_count += 1

    logger.info(
        f"Created travel expense {te_id} with {cost_count} cost lines "
        f"and {per_diem_count} perDiemCompensations"
    )
    return {"status": "completed", "taskType": "create_travel_expense", "travelExpenseId": te_id}


@register_handler("delete_travel_expense")
async def delete_travel_expense(client: TripletexClient, fields: dict[str, Any]) -> dict:
    te_id = fields.get("travelExpenseId")

    if not te_id:
        params: dict[str, Any] = {}
        employee_id = await _find_employee(client, fields)
        if employee_id:
            params["employeeId"] = employee_id

        resp = await client.get("/travelExpense", params=params)
        expenses = resp.json().get("values", [])

        title = fields.get("travelExpenseTitle", "")
        if title and expenses:
            expenses = [e for e in expenses if title.lower() in e.get("title", "").lower()]

        if not expenses:
            return {"status": "completed", "note": "Travel expense not found"}
        te_id = expenses[0]["id"]

    await client.delete(f"/travelExpense/{te_id}")
    logger.info(f"Deleted travel expense {te_id}")
    return {"status": "completed", "taskType": "delete_travel_expense", "deletedId": te_id}


@register_handler("update_employee")
async def update_employee(client: TripletexClient, fields: dict[str, Any]) -> dict:
    employee_id = await _find_employee(client, fields)
    if not employee_id:
        return {"status": "completed", "note": "Employee not found"}

    # Fetch current data
    resp = await client.get(f"/employee/{employee_id}")
    employee = resp.json().get("value", {})

    # dateOfBirth is required for PUT even if GET returns null
    if not employee.get("dateOfBirth"):
        employee["dateOfBirth"] = "1990-01-01"

    # Apply changes
    changes = fields.get("changes", {})
    employee.update(changes)

    resp = await client.put(f"/employee/{employee_id}", employee)
    logger.info(f"Updated employee {employee_id}")
    return {"status": "completed", "taskType": "update_employee", "employeeId": employee_id}
