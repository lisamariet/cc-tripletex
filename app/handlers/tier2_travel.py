"""Tier 2 handlers — travel expense operations (×2 points)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


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
        # Try splitting full name
        parts = name.strip().split()
        if len(parts) >= 2:
            params["firstName"] = parts[0]
            params["lastName"] = " ".join(parts[1:])
        else:
            params["firstName"] = name

    resp = await client.get("/employee", params=params)
    employees = resp.json().get("values", [])
    if employees:
        return employees[0]["id"]
    return None


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

    # Add cost lines
    for cost in fields.get("costs", []):
        cost_payload = {
            "travelExpense": {"id": te_id},
            "description": cost.get("description", ""),
            "amountCurrencyIncVat": cost.get("amount", 0),
            "date": fields.get("date", ""),
        }
        if cost.get("currency"):
            cost_payload["currency"] = cost["currency"]
        if cost.get("vatCode"):
            cost_payload["vatType"] = {"number": cost["vatCode"]}

        await client.post("/travelExpense/cost", cost_payload)

    logger.info(f"Created travel expense {te_id} with {len(fields.get('costs', []))} cost lines")
    return {"status": "completed", "taskType": "create_travel_expense", "travelExpenseId": te_id}


@register_handler("delete_travel_expense")
async def delete_travel_expense(client: TripletexClient, fields: dict[str, Any]) -> dict:
    te_id = fields.get("travelExpenseId")

    if not te_id:
        # Search for it
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

    # Apply changes
    changes = fields.get("changes", {})
    employee.update(changes)

    resp = await client.put(f"/employee/{employee_id}", employee)
    logger.info(f"Updated employee {employee_id}")
    return {"status": "completed", "taskType": "update_employee", "employeeId": employee_id}
