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


async def _get_cost_categories(client: TripletexClient) -> list[dict[str, Any]]:
    """Get all available cost categories."""
    resp = await client.get_cached("/travelExpense/costCategory", params={"fields": "id,description", "count": 100})
    return resp.json().get("values", [])


# Mapping from cost description keywords to Tripletex costCategory descriptions.
# Keys are lowercase substrings to search for in cost description,
# values are lowercase substrings to match against category description.
_COST_CATEGORY_KEYWORDS: list[tuple[list[str], str]] = [
    # flybuss/flytog BEFORE fly to avoid false positive
    (["flybuss", "airport bus"], "flybuss"),
    (["flytog", "airport train", "flytoget"], "flytog"),
    (["fly", "flight", "flug", "vuelo", "voo", "vol", "avion", "avião"], "fly"),
    (["taxi", "cab", "drosje", "táxi"], "taxi"),
    (["hotell", "hotel", "hôtel", "overnatting", "accommodation", "unterkunft", "alojamiento", "hébergement"], "hotell"),
    (["tog", "train", "tren", "zug", "trem"], "tog"),
    (["buss", "bus", "autobus", "ônibus"], "buss"),
    (["parkering", "parking", "parken"], "parkering"),
    (["drivstoff", "fuel", "bensin", "diesel", "kraftstoff", "combustible", "carburant"], "drivstoff"),
    (["ferge", "ferry", "fähre", "transbordador"], "ferge"),
    (["mat", "food", "essen", "comida", "nourriture", "måltid", "meal"], "mat"),
    (["representasjon", "representation", "entertainment"], "representasjon"),
    (["bom", "toll", "maut", "peaje", "péage"], "bom"),
    (["t-bane", "metro", "subway", "u-bahn"], "metro"),
    (["trikk", "tram", "straßenbahn", "tranvía", "tramway"], "trikk"),
    (["leie", "rental", "hire", "miet"], "leiebil"),
    (["kontor", "office", "büro", "oficina"], "kontorrekvisita"),
]


def _match_cost_category(description: str, categories: list[dict[str, Any]]) -> int | None:
    """Match a cost description to the best costCategory.

    Returns category ID or None if no match found.
    """
    desc_lower = description.lower()

    for keywords, cat_keyword in _COST_CATEGORY_KEYWORDS:
        if any(kw in desc_lower for kw in keywords):
            # Find the category whose description contains cat_keyword
            for cat in categories:
                cat_desc = cat.get("description", "").lower()
                if cat_keyword in cat_desc:
                    return cat["id"]

    return None


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


def _rate_category_valid_for_date(cat: dict[str, Any], travel_date: datetime) -> bool:
    """Return True if this rate category is valid for the given travel date."""
    from_str = cat.get("fromDate")
    to_str = cat.get("toDate")
    try:
        if from_str and datetime.strptime(from_str, "%Y-%m-%d") > travel_date:
            return False
        if to_str and datetime.strptime(to_str, "%Y-%m-%d") < travel_date:
            return False
    except (ValueError, TypeError):
        pass
    return True


async def _get_per_diem_rate_categories_ranked(
    client: TripletexClient,
    is_day_trip: bool = False,
    travel_date: datetime | None = None,
) -> list[int]:
    """Return a ranked list of candidate per diem rate category IDs.

    Filters on domestic + correct trip type, then date-validity, then sorts by
    highest ID (newest). Returns all valid candidates so callers can try each
    one if earlier choices trigger a date-mismatch validation error.
    """
    if travel_date is None:
        travel_date = datetime.now()

    try:
        resp = await client.get_cached(
            "/travelExpense/rateCategory",
            params={"type": "PER_DIEM", "count": 1000},
        )
        cats = resp.json().get("values", [])
        if not cats:
            return []

        # Primary filter: domestic + trip-type match
        matching = []
        for cat in cats:
            name = cat.get("name", "").lower()
            if "innland" not in name:
                continue
            if is_day_trip:
                if "dagsreise" in name and "over 12" in name:
                    matching.append(cat)
            else:
                if "overnatting" in name and "over 12" in name:
                    matching.append(cat)

        if not matching:
            # Fallback: any domestic category
            matching = [c for c in cats if "innland" in c.get("name", "").lower()]

        if not matching:
            matching = cats

        # Prefer date-valid categories, but keep all as fallback
        date_valid = [c for c in matching if _rate_category_valid_for_date(c, travel_date)]
        candidates = date_valid if date_valid else matching

        # Sort by highest id (newest) first
        candidates.sort(key=lambda c: c["id"], reverse=True)
        ids = [c["id"] for c in candidates]

        logger.info(
            f"Rate category candidates (date={travel_date.date()}): "
            f"{[(c['id'], c.get('name')) for c in candidates[:3]]}"
        )
        return ids

    except Exception as e:
        logger.warning(f"Failed to get per diem rate categories: {e}")
    return []


async def _get_per_diem_rate_category(
    client: TripletexClient,
    is_day_trip: bool = False,
    travel_date: datetime | None = None,
) -> int | None:
    """Get the best per diem rate category ID (first from ranked list)."""
    ids = await _get_per_diem_rate_categories_ranked(
        client, is_day_trip=is_day_trip, travel_date=travel_date,
    )
    return ids[0] if ids else None


async def _get_per_diem_rate_type(client: TripletexClient, rate_category_id: int | None) -> int | None:
    """Get a per diem rate type ID from /travelExpense/rate.

    Requires rateCategoryId — without it the endpoint returns 422 "Result set
    too large". Returns None (safe fallback) if the category ID is missing or
    the call fails.
    """
    if not rate_category_id:
        logger.warning("Skipping /travelExpense/rate lookup — no rateCategoryId available")
        return None
    try:
        params: dict[str, Any] = {"count": 1, "rateCategoryId": str(rate_category_id)}
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
    travel_date: datetime | None = None,
) -> bool:
    """Create a per diem compensation entry. Returns True on success.

    Tries each candidate rate category in rank order. If a category causes a
    "dato samsvarer ikke" (date mismatch) validation error, the next candidate
    is tried automatically.
    """
    if travel_date is None:
        travel_date = datetime.now()

    # Get all candidate category IDs ranked by preference
    category_ids = await _get_per_diem_rate_categories_ranked(
        client, is_day_trip=is_day_trip, travel_date=travel_date,
    )

    days = _extract_per_diem_days(cost)
    amount = cost.get("amount", 0)
    location = _extract_destination(fields)

    def _build_payload(rate_category_id: int | None, rate_type_id: int | None) -> dict[str, Any]:
        p: dict[str, Any] = {
            "travelExpense": {"id": te_id},
            "count": days,
            "location": location,
            "overnightAccommodation": "HOTEL" if not is_day_trip else "NONE",
            "isDeductionForBreakfast": False,
            "isDeductionForLunch": False,
            "isDeductionForDinner": False,
        }
        if rate_type_id:
            p["rateType"] = {"id": rate_type_id}
        if rate_category_id:
            p["rateCategory"] = {"id": rate_category_id}
        # Include explicit amount/rate only when Tripletex cannot calculate from rates
        if not rate_type_id:
            rate = amount / days if days > 0 else amount
            p["rate"] = rate
            p["amount"] = amount
        return p

    def _is_date_mismatch(resp_text: str) -> bool:
        return "samsvarer ikke" in resp_text or "dato" in resp_text.lower()

    def _is_missing_dates(resp_text: str) -> bool:
        return "avreisedato" in resp_text.lower() or "returdato" in resp_text.lower()

    # Try up to 3 candidate categories
    for i, cat_id in enumerate(category_ids[:3]):
        rate_type_id = await _get_per_diem_rate_type(client, cat_id)
        payload = _build_payload(cat_id, rate_type_id)

        try:
            resp = await client.post("/travelExpense/perDiemCompensation", payload)
            status = resp.status_code
            if status in (200, 201):
                per_diem = resp.json().get("value", {})
                logger.info(
                    f"Created perDiemCompensation {per_diem.get('id')} "
                    f"for TE {te_id} (category={cat_id}, attempt={i+1})"
                )
                return True

            logger.warning(
                f"perDiemCompensation attempt {i+1} returned {status} "
                f"(category={cat_id}): {resp.text[:300]}"
            )

            if status == 422:
                if _is_date_mismatch(resp.text) and i < 2:
                    logger.info(f"Date mismatch for category {cat_id}, trying next candidate")
                    continue
                if _is_missing_dates(resp.text):
                    # travelDetails not persisted — cannot proceed with per diem
                    logger.warning(
                        "perDiemCompensation requires travelDetails (departure/return dates) "
                        "which were not persisted — falling back to regular cost line"
                    )
                    return False
                # Other 422 — try without rateType/rateCategory as last resort
                if rate_type_id and i == 0:
                    fallback = _build_payload(None, None)
                    resp2 = await client.post("/travelExpense/perDiemCompensation", fallback)
                    if resp2.status_code in (200, 201):
                        per_diem = resp2.json().get("value", {})
                        logger.info(
                            f"Created perDiemCompensation {per_diem.get('id')} "
                            f"(no-rate fallback) for TE {te_id}"
                        )
                        return True
                    logger.warning(
                        f"perDiemCompensation no-rate fallback failed: "
                        f"{resp2.status_code}: {resp2.text[:200]}"
                    )
            return False

        except Exception as e:
            logger.warning(f"perDiemCompensation POST failed (attempt {i+1}): {e}")
            return False

    logger.warning(f"All perDiemCompensation attempts failed for TE {te_id}")
    return False


@register_handler("create_travel_expense")
async def create_travel_expense(client: TripletexClient, fields: dict[str, Any]) -> dict:
    employee_id = await _find_employee(client, fields)
    if not employee_id:
        return {"status": "completed", "note": "Employee not found for travel expense"}

    # Determine if any cost line is per diem
    has_per_diem = any(_is_per_diem_cost(c) for c in fields.get("costs", []))

    # Don't send date — let Tripletex default to today.
    # Gemini sometimes hallucinates wrong dates (e.g. 2024 instead of 2026).
    # Tripletex auto-sets today's date when omitted.
    dep_date = datetime.now()  # Used for travelDetails and rateCategory date filtering

    # Calculate per diem days
    total_days = 1
    if has_per_diem:
        total_days = sum(
            _extract_per_diem_days(c)
            for c in fields.get("costs", [])
            if _is_per_diem_cost(c)
        )
        total_days = max(total_days, 1)

    ret_date = dep_date + timedelta(days=total_days)

    destination = _extract_destination(fields)

    # Create the travel expense — omit date (Tripletex defaults to today)
    te_payload: dict[str, Any] = {
        "employee": {"id": employee_id},
        "title": fields.get("title", "Travel Expense"),
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
    all_categories = await _get_cost_categories(client)
    # Fallback: first category if no match found
    fallback_category_id = all_categories[0]["id"] if all_categories else None
    payment_type_id = await _get_payment_type_private(client)

    per_diem_count = 0
    cost_count = 0

    # Add cost lines — separate per diem from regular costs
    for cost in fields.get("costs", []):
        if _is_per_diem_cost(cost):
            # Try per diem compensation endpoint
            success = await _create_per_diem_compensation(
                client, te_id, cost, fields,
                is_day_trip=(total_days <= 1),
                travel_date=dep_date,
            )
            if success:
                per_diem_count += 1
                continue
            # Fallback: add as regular cost line if per diem endpoint fails
            logger.info("Per diem endpoint failed, falling back to cost line")

        # Regular cost line — match costCategory to description
        cost_desc = cost.get("description", "")
        matched_cat_id = _match_cost_category(cost_desc, all_categories)
        category_id = matched_cat_id or fallback_category_id

        cost_date = cost.get("date", dep_date.strftime("%Y-%m-%d"))
        cost_payload: dict[str, Any] = {
            "travelExpense": {"id": te_id},
            "date": cost_date,
            "amountCurrencyIncVat": cost.get("amount", 0),
        }
        # Note: "description" does NOT exist on travelExpense/cost -- don't send it
        if category_id:
            cost_payload["costCategory"] = {"id": category_id}
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

        params["fields"] = "id,title,employee"
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
