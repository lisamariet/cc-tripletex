"""Tier 2 handlers — travel expense operations (x2 points)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

# Keywords that indicate a cost line is per diem / diet / daily allowance
_PER_DIEM_KEYWORDS = re.compile(
    r"diett|per\s*diem|dagpenger|daily\s*(?:rate|allowance)|diet(?:as?)?(?!\w)|"
    r"kostgodtgj.relse|dagsats|kost\s*og\s*losji|subsistence|"
    r"tagegeld|tagessatz|indemnit.s?\s*journali.res?|"
    r"traktament|perdiem|dag\s*penger",
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
    # Also German "5 Tage", Spanish "2 dias", French "3 jours"
    m = re.search(r"(\d+)\s*(?:days?|dager?|dag|jours?|Tage?|d[ií]as?)", desc, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Try to calculate from amount and known daily rate (800 NOK)
    amount = cost.get("amount", 0)
    if amount and amount >= 800:
        days = round(amount / 800)
        if days >= 1:
            return days
    return 1


def _extract_destination(fields: dict[str, Any]) -> str:
    """Extract travel destination from fields."""
    destination = fields.get("destination", "")
    if destination:
        return destination
    title = fields.get("title", "")
    # Try to extract location from title, e.g. "Client visit Oslo" -> "Oslo"
    m = re.search(
        r"(?:visit[ea]?|bes.k|reise|trip|tur|viaje|viagem|voyage|Reise|"
        r"konferanse?|conference|Kundenbesuch|Besuch|client)\s+"
        r"(?:to\s+|til\s+|a\s+|.\s+|nach\s+|de\s+|en\s+)?(.+)",
        title,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # If title contains a Norwegian city name, use it
    return title or "Reisemal"


async def _get_per_diem_rate_category(
    client: TripletexClient,
    is_day_trip: bool = False,
) -> int | None:
    """Get the newest per diem rate category ID for domestic overnight travel.

    Tripletex has many duplicate rate categories for different date ranges.
    We need the one with the HIGHEST id (newest) matching the travel date.
    For multi-day trips: "Overnatting over 12 timer - innland"
    For day trips: "Dagsreise over 12 timer - innland"
    """
    try:
        resp = await client.get_cached("/travelExpense/rateCategory",
                                        params={"type": "PER_DIEM", "count": 1000})
        cats = resp.json().get("values", [])
        if not cats:
            return None

        # Filter for domestic categories matching trip type
        matching = []
        for cat in cats:
            name = cat.get("name", "").lower()
            is_domestic = "innland" in name
            if not is_domestic:
                continue
            if is_day_trip:
                # For day trips, prefer "Dagsreise over 12 timer"
                if "dagsreise" in name and "over 12" in name:
                    matching.append(cat)
            else:
                # For overnight trips, prefer "Overnatting over 12 timer"
                if "overnatting" in name and "over 12" in name:
                    matching.append(cat)

        if not matching:
            # Fallback: any domestic category, newest first
            matching = [c for c in cats if "innland" in c.get("name", "").lower()]

        if matching:
            # Return the one with highest id (newest date range)
            matching.sort(key=lambda c: c["id"], reverse=True)
            chosen = matching[0]
            logger.info(f"Selected rateCategory: id={chosen['id']} name={chosen.get('name')}")
            return chosen["id"]

        return cats[-1]["id"]  # Absolute fallback: last in list
    except Exception as e:
        logger.warning(f"Failed to get per diem rate category: {e}")
    return None


async def _get_per_diem_rate_type(client: TripletexClient, rate_category_id: int | None) -> int | None:
    """Get a per diem rate type ID from /travelExpense/rate."""
    try:
        params: dict[str, Any] = {"count": 1}
        if rate_category_id:
            params["rateCategoryId"] = str(rate_category_id)
        resp = await client.get_cached("/travelExpense/rate", params=params)
        if resp.status_code != 200:
            logger.warning(f"GET /travelExpense/rate returned {resp.status_code}")
            return None
        rates = resp.json().get("values", [])
        if rates:
            return rates[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to get per diem rate type: {e}")
    return None


async def _ensure_travel_details(
    client: TripletexClient,
    te_id: int,
    dep_date: datetime,
    ret_date: datetime,
    destination: str,
    purpose: str,
    total_days: int,
) -> bool:
    """Ensure the travel expense has travelDetails set (via PUT if needed).

    Tripletex may ignore travelDetails in POST, so we fetch, check, and PUT.
    """
    # Fetch current TE
    resp = await client.get(f"/travelExpense/{te_id}", params={"fields": "*"})
    if resp.status_code != 200:
        logger.warning(f"GET /travelExpense/{te_id} returned {resp.status_code}")
        return False

    te_data = resp.json().get("value", {})

    # Check if travelDetails already has departure/return dates
    td = te_data.get("travelDetails") or {}
    has_dates = td.get("departureDate") and td.get("returnDate")

    if has_dates:
        logger.info(f"TE {te_id} already has travelDetails with dates")
        return True

    # Need to PUT travelDetails
    travel_details = {
        "departureDate": dep_date.strftime("%Y-%m-%d"),
        "returnDate": ret_date.strftime("%Y-%m-%d"),
        "departureTime": "08:00",
        "returnTime": "18:00",
        "destination": destination,
        "departureFrom": "Kontoret",
        "purpose": purpose,
        "isForeignTravel": False,
        "isDayTrip": total_days <= 1,
        "isCompensationFromRates": True,
    }

    te_data["travelDetails"] = travel_details
    # Remove read-only fields that cause issues on PUT
    for key in ["costs", "perDiemCompensations", "mileageAllowances",
                "accommodationAllowances", "isCompleted", "isApproved",
                "attachment", "documents", "payslip", "isChargeable"]:
        te_data.pop(key, None)

    resp = await client.put(f"/travelExpense/{te_id}", te_data)
    if resp.status_code in (200, 201):
        logger.info(f"PUT travelDetails on TE {te_id} succeeded")
        return True
    else:
        logger.warning(f"PUT travelDetails on TE {te_id} returned {resp.status_code}: {resp.text[:300]}")
        return False


async def _create_per_diem_compensation(
    client: TripletexClient,
    te_id: int,
    cost: dict[str, Any],
    fields: dict[str, Any],
    is_day_trip: bool = False,
) -> bool:
    """Create a per diem compensation entry. Returns True on success."""
    rate_category_id = await _get_per_diem_rate_category(client, is_day_trip=is_day_trip)
    rate_type_id = await _get_per_diem_rate_type(client, rate_category_id)

    days = _extract_per_diem_days(cost)
    amount = cost.get("amount", 0)
    location = _extract_destination(fields)

    payload: dict[str, Any] = {
        "travelExpense": {"id": te_id},
        "count": days,
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

    # Only include amount/rate if we don't have rate type (Tripletex calculates from rates)
    if not rate_type_id:
        rate = amount / days if days > 0 else amount
        payload["rate"] = rate
        payload["amount"] = amount

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
            # Try again without rate fields
            if rate_type_id and status == 422:
                payload.pop("rateType", None)
                payload.pop("rateCategory", None)
                rate = amount / days if days > 0 else amount
                payload["rate"] = rate
                payload["amount"] = amount
                resp2 = await client.post("/travelExpense/perDiemCompensation", payload)
                if resp2.status_code in (200, 201):
                    per_diem = resp2.json().get("value", {})
                    logger.info(f"Created perDiemCompensation {per_diem.get('id')} (retry) for TE {te_id}")
                    return True
                logger.warning(f"perDiemCompensation retry also failed: {resp2.status_code}: {resp2.text[:300]}")
            return False
    except Exception as e:
        logger.warning(f"perDiemCompensation POST failed: {e}")
        return False


@register_handler("create_travel_expense")
async def create_travel_expense(client: TripletexClient, fields: dict[str, Any]) -> dict:
    employee_id = await _find_employee(client, fields)
    if not employee_id:
        return {"status": "completed", "note": "Employee not found for travel expense"}

    # Determine if any cost line is per diem
    has_per_diem = any(_is_per_diem_cost(c) for c in fields.get("costs", []))

    # Always use a date — fall back to today if missing
    travel_date = fields.get("date", "")
    if not travel_date:
        travel_date = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"No date in fields, using today: {travel_date}")

    # Calculate per diem days
    total_days = 1
    if has_per_diem:
        total_days = sum(
            _extract_per_diem_days(c)
            for c in fields.get("costs", [])
            if _is_per_diem_cost(c)
        )
        total_days = max(total_days, 1)

    try:
        dep_date = datetime.strptime(travel_date, "%Y-%m-%d")
    except ValueError:
        dep_date = datetime.now()
    ret_date = dep_date + timedelta(days=total_days)

    destination = _extract_destination(fields)

    # Create the travel expense — always include travelDetails when per diem
    te_payload: dict[str, Any] = {
        "employee": {"id": employee_id},
        "title": fields.get("title", "Travel Expense"),
        "date": travel_date,
    }

    if has_per_diem:
        te_payload["travelDetails"] = {
            "departureDate": dep_date.strftime("%Y-%m-%d"),
            "returnDate": ret_date.strftime("%Y-%m-%d"),
            "departureTime": "08:00",
            "returnTime": "18:00",
            "destination": destination,
            "departureFrom": fields.get("departureFrom", "Kontoret"),
            "purpose": fields.get("title", "Tjenestereise"),
            "isForeignTravel": False,
            "isDayTrip": total_days <= 1,
            "isCompensationFromRates": True,
        }

    resp = await client.post("/travelExpense", te_payload)
    te = resp.json().get("value", {})
    te_id = te.get("id")

    if not te_id:
        logger.error(f"Failed to create travel expense: {resp.text[:500]}")
        return {"status": "completed", "note": "Failed to create travel expense"}

    # If per diem, ensure travelDetails are set (PUT if POST didn't persist them)
    if has_per_diem:
        await _ensure_travel_details(
            client, te_id, dep_date, ret_date,
            destination, fields.get("title", "Tjenestereise"), total_days,
        )

    # Get required IDs for cost lines
    cost_category_id = await _get_cost_category(client)
    payment_type_id = await _get_payment_type_private(client)

    per_diem_count = 0
    cost_count = 0

    # Add cost lines — separate per diem from regular costs
    for cost in fields.get("costs", []):
        if _is_per_diem_cost(cost):
            # Try per diem compensation endpoint
            success = await _create_per_diem_compensation(
                client, te_id, cost, fields, is_day_trip=(total_days <= 1),
            )
            if success:
                per_diem_count += 1
                continue
            # Fallback: add as regular cost line if per diem endpoint fails
            logger.info("Per diem endpoint failed, falling back to cost line")

        # Regular cost line
        cost_date = cost.get("date", travel_date)
        cost_payload: dict[str, Any] = {
            "travelExpense": {"id": te_id},
            "date": cost_date,
            "amountCurrencyIncVat": cost.get("amount", 0),
        }
        # Note: "description" does NOT exist on travelExpense/cost -- don't send it
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
