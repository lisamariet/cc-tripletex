"""Tier 2 handlers — project operations (×2 points)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient
from app.handlers.tier2_invoice import _find_or_create_customer

logger = logging.getLogger(__name__)


@register_handler("create_project")
async def create_project(client: TripletexClient, fields: dict[str, Any]) -> dict:
    # Projects need a project manager — find the first employee if not specified
    pm_id = None
    if fields.get("projectManagerName"):
        parts = fields["projectManagerName"].strip().split()
        params: dict[str, Any] = {}
        if len(parts) >= 2:
            params["firstName"] = parts[0]
            params["lastName"] = " ".join(parts[1:])
        else:
            params["firstName"] = parts[0]
        resp = await client.get("/employee", params=params)
        employees = resp.json().get("values", [])
        if employees:
            pm_id = employees[0]["id"]

    if pm_id is None:
        # Use first available employee
        resp = await client.get("/employee", params={"count": 1})
        employees = resp.json().get("values", [])
        if employees:
            pm_id = employees[0]["id"]

    project_payload: dict[str, Any] = {
        "name": fields["name"],
        "isInternal": False,
    }

    if pm_id:
        project_payload["projectManager"] = {"id": pm_id}

    if fields.get("customerName") or fields.get("customerOrgNumber"):
        customer_id = await _find_or_create_customer(client, fields)
        project_payload["customer"] = {"id": customer_id}

    # startDate is required by Tripletex — default to today
    from datetime import date
    project_payload["startDate"] = fields.get("startDate") or date.today().isoformat()
    if fields.get("endDate"):
        project_payload["endDate"] = fields["endDate"]
    if fields.get("isClosed") is not None:
        project_payload["isClosed"] = fields["isClosed"]

    resp = await client.post("/project", project_payload)
    data = resp.json()
    logger.info(f"Created project: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_project", "created": data.get("value", {})}
