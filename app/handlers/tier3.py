"""Tier 3 handlers — voucher operations (create, reverse, delete)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


async def _lookup_account(client: TripletexClient, account_number: int) -> int:
    """Look up a Tripletex account ID by account number (cached)."""
    resp = await client.get_cached("/ledger/account", params={"number": str(account_number)})
    data = resp.json()
    values = data.get("values", [])
    if not values:
        raise ValueError(f"Account number {account_number} not found in Tripletex")
    return values[0]["id"]


async def _lookup_vat_type(client: TripletexClient, account_number: int) -> dict[str, Any] | None:
    """For revenue/sales accounts (3000-series), look up the default VAT type (cached)."""
    if 3000 <= account_number < 4000:
        resp = await client.get_cached("/ledger/vatType", params={"number": "3"})  # Standard MVA 25%
        data = resp.json()
        vat_types = data.get("values", [])
        if vat_types:
            return {"id": vat_types[0]["id"]}
    return None


@register_handler("create_voucher")
async def create_voucher(client: TripletexClient, fields: dict[str, Any]) -> dict:
    description = fields.get("description", "")
    date = fields["date"]
    postings_input = fields.get("postings", [])

    postings = []
    for idx, p in enumerate(postings_input):
        row = idx + 1  # row must be >= 1 (row 0 is system-reserved for VAT)

        # Determine account number and direction
        debit_account = p.get("debitAccount")
        credit_account = p.get("creditAccount")
        amount = p.get("amount", 0)

        if debit_account:
            account_number = int(debit_account)
            account_id = await _lookup_account(client, account_number)
            posting = {
                "account": {"id": account_id},
                "amountGross": amount,
                "amountGrossCurrency": amount,
                "row": row,
            }
            vat_type = await _lookup_vat_type(client, account_number)
            if vat_type:
                posting["vatType"] = vat_type
            postings.append(posting)

        if credit_account:
            account_number = int(credit_account)
            account_id = await _lookup_account(client, account_number)
            posting = {
                "account": {"id": account_id},
                "amountGross": -amount,
                "amountGrossCurrency": -amount,
                "row": row + len(postings_input) if debit_account else row,
            }
            vat_type = await _lookup_vat_type(client, account_number)
            if vat_type:
                posting["vatType"] = vat_type
            postings.append(posting)

    payload = {
        "date": date,
        "description": description,
        "postings": postings,
    }

    resp = await client.post("/ledger/voucher", payload)
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        validation = data.get("validationMessages", [])
        logger.error(f"Voucher creation failed: {error_msg} — {validation}")
        return {
            "status": "completed",
            "note": f"Voucher creation failed: {error_msg}",
            "validationMessages": validation,
        }

    logger.info(f"Created voucher: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_voucher", "created": data.get("value", {})}


@register_handler("reverse_voucher")
async def reverse_voucher(client: TripletexClient, fields: dict[str, Any]) -> dict:
    voucher_id = fields.get("_voucher_id")
    voucher_number = fields.get("voucherNumber")
    date = fields.get("date")

    if not voucher_id:
        # Find the voucher by searching
        search_params: dict[str, Any] = {}
        if date:
            search_params["dateFrom"] = date
            search_params["dateTo"] = date
        if voucher_number:
            search_params["number"] = str(voucher_number)

        resp = await client.get("/ledger/voucher", params=search_params)
        data = resp.json()
        vouchers = data.get("values", [])

        if not vouchers:
            return {"status": "error", "taskType": "reverse_voucher", "message": "Voucher not found"}

        voucher_id = vouchers[0]["id"]
        reversal_date = date or vouchers[0].get("date")
    else:
        # We have a direct voucher ID — fetch it to get the date
        resp = await client.get(f"/ledger/voucher/{voucher_id}")
        voucher_data = resp.json().get("value", {})
        reversal_date = date or voucher_data.get("date")

    resp = await client.put(
        f"/ledger/voucher/{voucher_id}/:reverse",
        params={"date": reversal_date},
    )
    data = resp.json()
    logger.info(f"Reversed voucher {voucher_id}")
    return {"status": "completed", "taskType": "reverse_voucher", "reversed": data.get("value", {})}


@register_handler("delete_voucher")
async def delete_voucher(client: TripletexClient, fields: dict[str, Any]) -> dict:
    voucher_id = fields.get("_voucher_id")
    voucher_number = fields.get("voucherNumber")
    date = fields.get("date")

    if not voucher_id:
        # Find the voucher by searching
        search_params: dict[str, Any] = {}
        if date:
            search_params["dateFrom"] = date
            search_params["dateTo"] = date
        if voucher_number:
            search_params["number"] = str(voucher_number)

        resp = await client.get("/ledger/voucher", params=search_params)
        data = resp.json()
        vouchers = data.get("values", [])

        if not vouchers:
            return {"status": "error", "taskType": "delete_voucher", "message": "Voucher not found"}

        # Only the LAST voucher in number series can be deleted
        voucher_id = vouchers[0]["id"]

    resp = await client.delete(f"/ledger/voucher/{voucher_id}")
    logger.info(f"Deleted voucher {voucher_id}")
    return {"status": "completed", "taskType": "delete_voucher", "deletedId": voucher_id}


@register_handler("create_custom_dimension")
async def create_custom_dimension(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Create a custom accounting dimension with values, then optionally post a voucher linked to a dimension value."""
    import datetime

    dimension_name = fields.get("dimensionName", "")
    values = fields.get("values", [])
    voucher_date = fields.get("voucherDate") or datetime.date.today().isoformat()
    voucher_description = fields.get("voucherDescription", "")
    account_number = fields.get("accountNumber")
    amount = fields.get("amount")
    dimension_value_name = fields.get("dimensionValue")
    credit_account = fields.get("creditAccount", 1920)

    if not dimension_name:
        return {"status": "error", "taskType": "create_custom_dimension", "message": "dimensionName is required"}
    if not values:
        return {"status": "error", "taskType": "create_custom_dimension", "message": "values array is required"}

    # Step 1: Check if dimension already exists by searching
    # Note: activeOnly param has inverted behaviour in some sandbox versions —
    # omit it to get all dimensions reliably.
    existing_dimension = None
    resp = await client.get("/ledger/accountingDimensionName")
    data = resp.json()
    for dim in data.get("values", []):
        if dim.get("dimensionName", "").lower() == dimension_name.lower():
            existing_dimension = dim
            break

    # Step 2: Create the dimension if it doesn't exist
    if existing_dimension:
        dimension_id = existing_dimension["id"]
        dimension_index = existing_dimension["dimensionIndex"]
        logger.info(f"Dimension '{dimension_name}' already exists with id={dimension_id}, index={dimension_index}")
    else:
        dim_payload = {"dimensionName": dimension_name, "active": True}
        resp = await client.post("/ledger/accountingDimensionName", dim_payload)
        dim_data = resp.json()
        if resp.status_code not in (200, 201):
            # If max 3 dimensions reached, reuse first existing one and rename it
            all_dims = data.get("values", [])
            if all_dims:
                reuse = all_dims[0]
                dimension_id = reuse["id"]
                dimension_index = reuse["dimensionIndex"]
                # Rename the dimension
                reuse["dimensionName"] = dimension_name
                await client.put(f"/ledger/accountingDimensionName/{dimension_id}", reuse)
                logger.info(f"Reused dimension index={dimension_index}, renamed to '{dimension_name}'")
            else:
                return {
                    "status": "error",
                    "taskType": "create_custom_dimension",
                    "message": f"Failed to create dimension: {resp.text[:500]}",
                }
        else:
            created_dim = dim_data.get("value", {})
            dimension_id = created_dim["id"]
            dimension_index = created_dim["dimensionIndex"]
            logger.info(f"Created dimension '{dimension_name}' with id={dimension_id}, index={dimension_index}")

    # Step 3: Create dimension values
    # First, check existing values for this dimension
    existing_values_resp = await client.get(
        "/ledger/accountingDimensionValue/search",
        params={"dimensionIndex": str(dimension_index)},
    )
    existing_values_data = existing_values_resp.json()
    existing_value_names = {
        v.get("displayName", "").lower(): v for v in existing_values_data.get("values", [])
    }

    created_values = []
    for val_name in values:
        if val_name.lower() in existing_value_names:
            created_values.append(existing_value_names[val_name.lower()])
            logger.info(f"Dimension value '{val_name}' already exists")
            continue

        val_payload = {
            "displayName": val_name,
            "dimensionIndex": dimension_index,
            "active": True,
            "showInVoucherRegistration": True,
        }
        resp = await client.post("/ledger/accountingDimensionValue", val_payload)
        val_data = resp.json()
        if resp.status_code not in (200, 201):
            logger.warning(f"Failed to create dimension value '{val_name}': {resp.text[:300]}")
            continue
        created_val = val_data.get("value", {})
        created_values.append(created_val)
        logger.info(f"Created dimension value '{val_name}' with id={created_val.get('id')}")

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "create_custom_dimension",
        "dimension": {"id": dimension_id, "name": dimension_name, "index": dimension_index},
        "values": [{"id": v.get("id"), "name": v.get("displayName")} for v in created_values],
    }

    # Step 4: If voucher details are provided, create a voucher linked to the dimension value
    if account_number and amount and dimension_value_name:
        # Find the dimension value ID for the specified value
        target_value_id = None
        for v in created_values:
            if v.get("displayName", "").lower() == dimension_value_name.lower():
                target_value_id = v.get("id")
                break

        if not target_value_id:
            result["voucher"] = {"status": "error", "message": f"Dimension value '{dimension_value_name}' not found"}
            return result

        # Look up account IDs
        debit_account_id = await _lookup_account(client, int(account_number))
        credit_account_id = await _lookup_account(client, int(credit_account))

        # Build the dimension reference based on dimension index
        dim_field = f"freeAccountingDimension{dimension_index}"
        dim_ref = {"id": target_value_id}

        # Build postings
        debit_posting: dict[str, Any] = {
            "account": {"id": debit_account_id},
            "amountGross": amount,
            "amountGrossCurrency": amount,
            "row": 1,
            dim_field: dim_ref,
        }

        credit_posting: dict[str, Any] = {
            "account": {"id": credit_account_id},
            "amountGross": -amount,
            "amountGrossCurrency": -amount,
            "row": 2,
        }

        voucher_payload = {
            "date": voucher_date,
            "description": voucher_description or f"Voucher linked to {dimension_value_name}",
            "postings": [debit_posting, credit_posting],
        }

        resp = await client.post("/ledger/voucher", voucher_payload)
        voucher_data = resp.json()
        if resp.status_code in (200, 201):
            voucher = voucher_data.get("value", {})
            logger.info(f"Created voucher {voucher.get('id')} linked to dimension value '{dimension_value_name}'")
            result["voucher"] = {"status": "completed", "created": voucher}
        else:
            logger.warning(f"Failed to create voucher: {resp.text[:500]}")
            result["voucher"] = {"status": "error", "message": resp.text[:500]}

    return result
