"""Tier 3 handlers — voucher operations (create, reverse, delete)."""
from __future__ import annotations

import logging
from typing import Any

from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)


async def _lookup_account(client: TripletexClient, account_number: int) -> int:
    """Look up a Tripletex account ID by account number."""
    resp = await client.get("/ledger/account", params={"number": str(account_number)})
    data = resp.json()
    values = data.get("values", [])
    if not values:
        raise ValueError(f"Account number {account_number} not found in Tripletex")
    return values[0]["id"]


async def _lookup_vat_type(client: TripletexClient, account_number: int) -> dict[str, Any] | None:
    """For revenue/sales accounts (3000-series), look up the default VAT type."""
    if 3000 <= account_number < 4000:
        resp = await client.get("/ledger/vatType", params={"number": "3"})  # Standard MVA 25%
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
    logger.info(f"Created voucher: {data.get('value', {}).get('id')}")
    return {"status": "completed", "taskType": "create_voucher", "created": data.get("value", {})}


@register_handler("reverse_voucher")
async def reverse_voucher(client: TripletexClient, fields: dict[str, Any]) -> dict:
    voucher_number = fields.get("voucherNumber")
    date = fields.get("date")

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

    resp = await client.put(
        f"/ledger/voucher/{voucher_id}/:reverse",
        params={"date": reversal_date},
    )
    data = resp.json()
    logger.info(f"Reversed voucher {voucher_id}")
    return {"status": "completed", "taskType": "reverse_voucher", "reversed": data.get("value", {})}


@register_handler("delete_voucher")
async def delete_voucher(client: TripletexClient, fields: dict[str, Any]) -> dict:
    voucher_number = fields.get("voucherNumber")
    date = fields.get("date")

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
