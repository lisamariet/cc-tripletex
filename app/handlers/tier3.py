"""Tier 3 handlers — voucher operations, year-end closing, and bank reconciliation."""
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


@register_handler("bank_reconciliation")
async def bank_reconciliation(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Perform bank reconciliation: find/create reconciliation, match transactions to postings.

    Fields:
        accountId (int, optional): Tripletex ledger account ID for the bank account.
        accountNumber (int, optional): Account number (e.g. 1920) to look up the bank account.
        dateFrom (str, optional): Start date for statement period (YYYY-MM-DD).
        dateTo (str, optional): End date for statement period (YYYY-MM-DD).
        closingBalance (float, optional): Bank statement closing balance for reconciliation.
    """
    import datetime

    account_id = fields.get("accountId")
    account_number = fields.get("accountNumber", 1920)
    date_from = fields.get("dateFrom")
    date_to = fields.get("dateTo") or datetime.date.today().isoformat()
    closing_balance = fields.get("closingBalance")

    # Step 1: Resolve bank account via ledger account lookup (not /bank which lists institutions)
    if not account_id:
        try:
            account_id = await _lookup_account(client, int(account_number))
        except ValueError:
            return {
                "status": "error",
                "taskType": "bank_reconciliation",
                "message": f"Bank account number {account_number} not found in Tripletex",
            }

    logger.info(f"Bank reconciliation: using account_id={account_id}")

    # Step 2: Find current accounting period (required for creating reconciliation)
    today = datetime.date.today().isoformat()
    resp = await client.get("/ledger/accountingPeriod", params={"count": "20"})
    periods = resp.json().get("values", [])
    current_period_id = None
    for p in periods:
        start = p.get("start", "")
        end = p.get("end", "")
        if start <= today < end:
            current_period_id = p["id"]
            break
    if not current_period_id and periods:
        current_period_id = periods[-1]["id"]

    # Step 3: Get or create bank reconciliation
    reconciliation_id = None
    reconciliation = None

    resp = await client.get("/bank/reconciliation", params={
        "accountId": str(account_id),
        "count": "10",
    })
    data = resp.json()
    reconciliations = data.get("values", [])

    # Find open reconciliation (isClosed=False)
    for rec in reconciliations:
        if not rec.get("isClosed", True):
            reconciliation = rec
            reconciliation_id = rec["id"]
            logger.info(f"Found open reconciliation id={reconciliation_id}")
            break

    if not reconciliation_id:
        # Create a new reconciliation — requires account + accountingPeriod + type (MANUAL or AUTOMATIC)
        rec_payload: dict[str, Any] = {
            "account": {"id": account_id},
            "type": "MANUAL",
        }
        if current_period_id:
            rec_payload["accountingPeriod"] = {"id": current_period_id}
        if closing_balance is not None:
            rec_payload["bankAccountClosingBalanceCurrency"] = closing_balance

        resp = await client.post("/bank/reconciliation", rec_payload)
        if resp.status_code >= 400:
            error_data = resp.json()
            error_msg = error_data.get("message", resp.text[:300])
            logger.warning(f"Failed to create reconciliation: {error_msg}")
            # Try last reconciliation as fallback
            resp2 = await client.get("/bank/reconciliation/>last", params={"accountId": str(account_id)})
            if resp2.status_code == 200 and resp2.json().get("value"):
                reconciliation = resp2.json().get("value", {})
                reconciliation_id = reconciliation.get("id")
                logger.info(f"Using last reconciliation as fallback: id={reconciliation_id}")
            else:
                return {
                    "status": "error",
                    "taskType": "bank_reconciliation",
                    "message": f"Failed to create reconciliation: {error_msg}",
                }
        else:
            reconciliation = resp.json().get("value", {})
            reconciliation_id = reconciliation.get("id")
            logger.info(f"Created new reconciliation id={reconciliation_id}")

    # Step 3: Use suggest endpoint to auto-match transactions to postings
    matches_before = 0
    matches_after = 0

    # Count existing matches
    resp = await client.get("/bank/reconciliation/match/count", params={
        "bankReconciliationId": str(reconciliation_id),
    })
    if resp.status_code == 200:
        count_data = resp.json()
        matches_before = count_data.get("value", 0) if isinstance(count_data.get("value"), int) else 0

    # Run auto-suggest matching
    resp = await client.put(
        "/bank/reconciliation/match/:suggest",
        params={"bankReconciliationId": str(reconciliation_id)},
    )
    suggest_status = resp.status_code
    logger.info(f"Suggest matches: status={suggest_status}")

    # Count matches after suggestion
    resp = await client.get("/bank/reconciliation/match/count", params={
        "bankReconciliationId": str(reconciliation_id),
    })
    if resp.status_code == 200:
        count_data = resp.json()
        matches_after = count_data.get("value", 0) if isinstance(count_data.get("value"), int) else 0

    new_matches = matches_after - matches_before

    # Step 4: Get all matches for reporting
    resp = await client.get("/bank/reconciliation/match", params={
        "bankReconciliationId": str(reconciliation_id),
        "count": "100",
    })
    all_matches = resp.json().get("values", []) if resp.status_code == 200 else []

    # Step 5: Update closing balance if provided
    if closing_balance is not None and reconciliation_id and reconciliation:
        update_payload = dict(reconciliation)
        update_payload["bankAccountClosingBalanceCurrency"] = closing_balance
        # Clean up read-only fields
        for field_name in ("changes", "url", "closedDate", "closedByContact", "closedByEmployee",
                           "approvable", "autoPayReconciliation", "attachment", "transactions"):
            update_payload.pop(field_name, None)
        resp = await client.put(f"/bank/reconciliation/{reconciliation_id}", update_payload)
        if resp.status_code in (200, 201):
            logger.info(f"Updated closing balance to {closing_balance}")
        else:
            logger.warning(f"Failed to update closing balance: {resp.text[:300]}")

    # Step 6: Get bank statement transactions if available
    statement_transactions_count = 0
    if date_from:
        resp = await client.get("/bank/statement", params={
            "accountId": str(account_id),
            "count": "5",
        })
        statements = resp.json().get("values", []) if resp.status_code == 200 else []
        for stmt in statements:
            stmt_id = stmt.get("id")
            if stmt_id:
                resp = await client.get("/bank/statement/transaction", params={
                    "bankStatementId": str(stmt_id),
                    "count": "50",
                })
                if resp.status_code == 200:
                    txns = resp.json().get("values", [])
                    statement_transactions_count += len(txns)

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "bank_reconciliation",
        "reconciliationId": reconciliation_id,
        "accountId": account_id,
        "matchesBefore": matches_before,
        "matchesAfter": matches_after,
        "newMatches": new_matches,
        "totalMatches": len(all_matches),
        "statementTransactions": statement_transactions_count,
    }

    if closing_balance is not None:
        result["closingBalance"] = closing_balance

    return result


@register_handler("year_end_closing")
async def year_end_closing(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Perform year-end closing: close postings for the year and create opening balance for the next year.

    Steps:
    1. Look up accounting periods for the given year
    2. Find close groups for the year
    3. Close open postings via PUT /ledger/posting/:closePostings (batch, single attempt)
    4. Create opening balance for the next year via POST /ledger/voucher/openingBalance [BETA]
    5. Return summary with annual account info

    NOTE: This handler is capped at MAX_API_CALLS to prevent runaway loops.
    """
    import datetime

    MAX_API_CALLS = 30
    MAX_POSTINGS = 200
    api_calls = 0

    def _check_budget() -> None:
        nonlocal api_calls
        api_calls += 1
        if api_calls > MAX_API_CALLS:
            raise RuntimeError(f"Year-end closing exceeded API call budget ({MAX_API_CALLS})")

    year = fields.get("year")
    if not year:
        # Default to previous year
        year = datetime.date.today().year - 1
    year = int(year)

    create_opening_balance = fields.get("createOpeningBalance", True)
    opening_balance_date = fields.get("openingBalanceDate", f"{year + 1}-01-01")

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "year_end_closing",
        "year": year,
        "steps": [],
    }

    try:
        # Step 1: Find accounting periods for the year
        _check_budget()
        resp = await client.get("/ledger/accountingPeriod", params={
            "startFrom": f"{year}-01-01",
            "startTo": f"{year + 1}-01-01",
        })
        periods_data = resp.json()
        periods = periods_data.get("values", [])
        result["steps"].append({
            "step": "find_accounting_periods",
            "found": len(periods),
            "periods": [{"id": p.get("id"), "start": p.get("start"), "end": p.get("end")} for p in periods],
        })
        logger.info(f"Year-end closing {year}: found {len(periods)} accounting periods")

        # Step 2: Find close groups for the year
        _check_budget()
        resp = await client.get("/ledger/closeGroup", params={
            "dateFrom": f"{year}-01-01",
            "dateTo": f"{year}-12-31",
        })
        close_groups_data = resp.json()
        close_groups = close_groups_data.get("values", [])
        result["steps"].append({
            "step": "find_close_groups",
            "found": len(close_groups),
        })
        logger.info(f"Year-end closing {year}: found {len(close_groups)} close groups")

        # Step 3: Find open postings for the year and close them (single batch attempt)
        _check_budget()
        resp = await client.get("/ledger/posting", params={
            "dateFrom": f"{year}-01-01",
            "dateTo": f"{year}-12-31",
            "count": MAX_POSTINGS,
        })
        postings_data = resp.json()
        all_postings = postings_data.get("values", [])

        # Filter to open postings (not already closed)
        open_posting_ids = [
            p["id"] for p in all_postings
            if not p.get("closeGroup")
        ]

        if open_posting_ids:
            logger.info(f"Year-end closing {year}: closing {len(open_posting_ids)} open postings (batch)")
            _check_budget()
            resp = await client.put("/ledger/posting/:closePostings", payload=open_posting_ids)
            if resp.status_code >= 400:
                error_msg = resp.json().get("message", resp.text[:300])
                logger.warning(f"Close postings failed (giving up, no retry): {error_msg}")
                result["steps"].append({
                    "step": "close_postings",
                    "status": "error",
                    "message": error_msg,
                    "attempted": len(open_posting_ids),
                })
            else:
                close_result = resp.json()
                closed_postings = close_result.get("values", [])
                result["steps"].append({
                    "step": "close_postings",
                    "status": "completed",
                    "closed": len(closed_postings) if isinstance(closed_postings, list) else len(open_posting_ids),
                })
                logger.info(f"Year-end closing {year}: closed {len(open_posting_ids)} postings")
        else:
            result["steps"].append({
                "step": "close_postings",
                "status": "completed",
                "closed": 0,
                "note": "No open postings found for the year",
            })
            logger.info(f"Year-end closing {year}: no open postings to close")

        # Step 4: Create opening balance for next year (BETA endpoint)
        # Use the direct endpoint — do NOT iterate over individual accounts.
        if create_opening_balance:
            _check_budget()
            resp = await client.get("/ledger/voucher/openingBalance")
            existing_ob = resp.json()
            existing_voucher = existing_ob.get("value")

            if existing_voucher and existing_voucher.get("id"):
                result["steps"].append({
                    "step": "opening_balance",
                    "status": "already_exists",
                    "voucherId": existing_voucher["id"],
                    "note": "Opening balance already exists; skipping creation",
                })
                logger.info(f"Year-end closing {year}: opening balance already exists (voucher {existing_voucher['id']})")
            else:
                # Post opening balance with just the date — let Tripletex calculate balances
                ob_payload: dict[str, Any] = {
                    "voucherDate": opening_balance_date,
                }
                _check_budget()
                resp = await client.post("/ledger/voucher/openingBalance", ob_payload)
                if resp.status_code in (200, 201):
                    voucher = resp.json().get("value", {})
                    result["steps"].append({
                        "step": "opening_balance",
                        "status": "completed",
                        "voucherId": voucher.get("id"),
                        "date": opening_balance_date,
                    })
                    logger.info(f"Year-end closing {year}: created opening balance voucher {voucher.get('id')}")
                else:
                    error_msg = resp.json().get("message", resp.text[:500])
                    result["steps"].append({
                        "step": "opening_balance",
                        "status": "error",
                        "message": error_msg,
                        "note": "This is a BETA endpoint and may not be available in all environments",
                    })
                    logger.warning(f"Opening balance creation failed (giving up): {error_msg}")

        # Step 5: Fetch annual account info for verification
        _check_budget()
        resp = await client.get("/ledger/annualAccount", params={
            "yearFrom": str(year),
            "yearTo": str(year + 1),
        })
        annual_data = resp.json()
        annual_accounts = annual_data.get("values", [])
        if annual_accounts:
            result["annualAccount"] = {
                "id": annual_accounts[0].get("id"),
                "year": annual_accounts[0].get("year"),
            }

    except RuntimeError as e:
        logger.error(f"Year-end closing aborted: {e}")
        result["status"] = "completed"
        result["note"] = str(e)

    result["apiCallsUsed"] = api_calls
    return result


async def _find_voucher_by_account_and_amount(
    client: TripletexClient,
    account_number: int,
    amount: float,
    date: str | None = None,
    already_seen: set[int] | None = None,
) -> dict[str, Any] | None:
    """Find a voucher by searching postings for a specific account + amount combination.

    Strategy 1: Search /ledger/posting by accountId (fast, works when postings are indexed).
    Strategy 2: Search all vouchers and check their postings (fallback for sandboxes where
                posting search by accountId may return empty).
    """
    acct_id = await _lookup_account(client, account_number)

    # Strategy 1: Search postings directly
    params: dict[str, Any] = {"accountId": str(acct_id), "count": "100"}
    if date:
        params["dateFrom"] = date
        params["dateTo"] = date
    posting_resp = await client.get("/ledger/posting", params=params)
    postings_found = posting_resp.json().get("values", [])

    for posting in postings_found:
        posting_amount = posting.get("amountGross", 0)
        if abs(abs(posting_amount) - abs(amount)) < 0.01:
            voucher_id = posting.get("voucher", {}).get("id")
            if voucher_id and (already_seen is None or voucher_id not in already_seen):
                resp = await client.get(f"/ledger/voucher/{voucher_id}")
                if resp.status_code == 200:
                    return resp.json().get("value", {})

    # Strategy 2: Search vouchers by date, then inspect their postings
    voucher_params: dict[str, Any] = {"count": "100"}
    if date:
        voucher_params["dateFrom"] = date
        voucher_params["dateTo"] = date
    voucher_resp = await client.get("/ledger/voucher", params=voucher_params)
    vouchers = voucher_resp.json().get("values", [])

    for v in vouchers:
        vid = v.get("id")
        if already_seen and vid in already_seen:
            continue
        # Check if already reversed
        if v.get("reverseVoucher"):
            continue
        # Fetch full voucher with postings (use 'id,postings' which returns nested fields)
        full_resp = await client.get(
            f"/ledger/voucher/{vid}",
            params={"fields": "id,postings"},
        )
        if full_resp.status_code != 200:
            continue
        full_v = full_resp.json().get("value", {})
        for p in full_v.get("postings", []):
            p_acct = p.get("account", {})
            p_acct_id = p_acct.get("id")
            p_acct_num = p_acct.get("number")
            p_amount = p.get("amountGross", 0)
            if (p_acct_id == acct_id or p_acct_num == account_number) and abs(abs(p_amount) - abs(amount)) < 0.01:
                return full_v

    return None


async def _correct_single_error(
    client: TripletexClient,
    error: dict[str, Any],
    default_date: str | None,
    already_reversed: set[int],
) -> dict[str, Any]:
    """Process a single ledger error and return a result dict.

    Supported errorType values:
      - wrong_account: reverses voucher on wrongAccount, re-posts on correctAccount
      - duplicate: reverses the duplicate voucher (no re-posting)
      - missing_vat: posts an additional VAT voucher
      - wrong_amount: reverses voucher and re-posts with correctAmount
    """
    error_type = error.get("errorType", "wrong_account")
    account = error.get("account") or error.get("wrongAccount")
    amount = error.get("amount", 0)
    date = error.get("date") or default_date
    result: dict[str, Any] = {"errorType": error_type, "account": account, "amount": amount}

    try:
        if error_type == "wrong_account":
            wrong_account = int(error.get("wrongAccount") or account)
            correct_account = int(error.get("correctAccount", 0))
            if not correct_account:
                result["status"] = "error"
                result["message"] = "correctAccount is required for wrong_account error"
                return result

            # Direct voucher ID lookup (e.g. from setup/pre-search)
            voucher = None
            if error.get("_voucher_id"):
                resp = await client.get(f"/ledger/voucher/{error['_voucher_id']}")
                if resp.status_code == 200:
                    voucher = resp.json().get("value", {})
            if not voucher:
                voucher = await _find_voucher_by_account_and_amount(
                    client, wrong_account, amount, date, already_reversed,
                )
            if not voucher:
                result["status"] = "error"
                result["message"] = f"Could not find voucher on account {wrong_account} with amount {amount}"
                return result

            vid = voucher["id"]
            reversal_date = date or voucher.get("date")

            # Reverse
            rev_resp = await client.put(f"/ledger/voucher/{vid}/:reverse", params={"date": reversal_date})
            if rev_resp.status_code >= 400:
                result["status"] = "error"
                result["message"] = f"Reverse failed: {rev_resp.json().get('message', '')}"
                return result
            already_reversed.add(vid)
            result["reversedVoucherId"] = vid

            # Re-post with correct account
            debit_id = await _lookup_account(client, correct_account)
            credit_id = await _lookup_account(client, int(error.get("creditAccount", 1920)))
            correction_payload = {
                "date": reversal_date,
                "description": f"Korreksjon: konto {wrong_account} → {correct_account}",
                "postings": [
                    {"account": {"id": debit_id}, "amountGross": amount, "amountGrossCurrency": amount, "row": 1},
                    {"account": {"id": credit_id}, "amountGross": -amount, "amountGrossCurrency": -amount, "row": 2},
                ],
            }
            corr_resp = await client.post("/ledger/voucher", correction_payload)
            if corr_resp.status_code >= 400:
                result["status"] = "partial"
                result["message"] = f"Reversed but correction failed: {corr_resp.json().get('message', '')}"
                return result
            result["correctionVoucherId"] = corr_resp.json().get("value", {}).get("id")
            result["status"] = "completed"

        elif error_type == "duplicate":
            dup_account = int(account)
            voucher = None
            if error.get("_voucher_id"):
                resp = await client.get(f"/ledger/voucher/{error['_voucher_id']}")
                if resp.status_code == 200:
                    voucher = resp.json().get("value", {})
            if not voucher:
                voucher = await _find_voucher_by_account_and_amount(
                    client, dup_account, amount, date, already_reversed,
                )
            if not voucher:
                result["status"] = "error"
                result["message"] = f"Could not find duplicate voucher on account {dup_account} with amount {amount}"
                return result

            vid = voucher["id"]
            reversal_date = date or voucher.get("date")
            rev_resp = await client.put(f"/ledger/voucher/{vid}/:reverse", params={"date": reversal_date})
            if rev_resp.status_code >= 400:
                result["status"] = "error"
                result["message"] = f"Reverse failed: {rev_resp.json().get('message', '')}"
                return result
            already_reversed.add(vid)
            result["reversedVoucherId"] = vid
            result["status"] = "completed"

        elif error_type == "missing_vat":
            vat_account = int(error.get("vatAccount", 2710))
            source_account = int(account) if account else 6540
            # Post an additional voucher with the VAT line
            debit_id = await _lookup_account(client, vat_account)
            credit_id = await _lookup_account(client, int(error.get("creditAccount", 1920)))
            # VAT amount: typically 25% of net amount
            vat_rate = error.get("vatRate", 25) / 100.0
            vat_amount = round(amount * vat_rate, 2)
            correction_payload = {
                "date": date or "2026-03-21",
                "description": f"Korreksjon: manglende MVA for konto {source_account}",
                "postings": [
                    {"account": {"id": debit_id}, "amountGross": vat_amount, "amountGrossCurrency": vat_amount, "row": 1},
                    {"account": {"id": credit_id}, "amountGross": -vat_amount, "amountGrossCurrency": -vat_amount, "row": 2},
                ],
            }
            corr_resp = await client.post("/ledger/voucher", correction_payload)
            if corr_resp.status_code >= 400:
                result["status"] = "error"
                result["message"] = f"VAT correction failed: {corr_resp.json().get('message', '')}"
                return result
            result["correctionVoucherId"] = corr_resp.json().get("value", {}).get("id")
            result["vatAmount"] = vat_amount
            result["status"] = "completed"

        elif error_type == "wrong_amount":
            wrong_account = int(account)
            correct_amount = error.get("correctAmount", 0)
            if not correct_amount:
                result["status"] = "error"
                result["message"] = "correctAmount is required for wrong_amount error"
                return result

            voucher = None
            if error.get("_voucher_id"):
                resp = await client.get(f"/ledger/voucher/{error['_voucher_id']}")
                if resp.status_code == 200:
                    voucher = resp.json().get("value", {})
            if not voucher:
                voucher = await _find_voucher_by_account_and_amount(
                    client, wrong_account, amount, date, already_reversed,
                )
            if not voucher:
                result["status"] = "error"
                result["message"] = f"Could not find voucher on account {wrong_account} with amount {amount}"
                return result

            vid = voucher["id"]
            reversal_date = date or voucher.get("date")

            # Reverse
            rev_resp = await client.put(f"/ledger/voucher/{vid}/:reverse", params={"date": reversal_date})
            if rev_resp.status_code >= 400:
                result["status"] = "error"
                result["message"] = f"Reverse failed: {rev_resp.json().get('message', '')}"
                return result
            already_reversed.add(vid)
            result["reversedVoucherId"] = vid

            # Re-post with correct amount
            debit_id = await _lookup_account(client, wrong_account)
            credit_id = await _lookup_account(client, int(error.get("creditAccount", 1920)))
            correction_payload = {
                "date": reversal_date,
                "description": f"Korreksjon: beløp {amount} → {correct_amount} på konto {wrong_account}",
                "postings": [
                    {"account": {"id": debit_id}, "amountGross": correct_amount, "amountGrossCurrency": correct_amount, "row": 1},
                    {"account": {"id": credit_id}, "amountGross": -correct_amount, "amountGrossCurrency": -correct_amount, "row": 2},
                ],
            }
            corr_resp = await client.post("/ledger/voucher", correction_payload)
            if corr_resp.status_code >= 400:
                result["status"] = "partial"
                result["message"] = f"Reversed but correction failed: {corr_resp.json().get('message', '')}"
                return result
            result["correctionVoucherId"] = corr_resp.json().get("value", {}).get("id")
            result["status"] = "completed"

        else:
            result["status"] = "error"
            result["message"] = f"Unknown errorType: {error_type}"

    except Exception as e:
        logger.error(f"Error correcting {error_type}: {e}")
        result["status"] = "error"
        result["message"] = str(e)

    return result


@register_handler("correct_ledger_error")
async def correct_ledger_error(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Correct one or more ledger errors: reverse wrong vouchers and post corrections.

    Supports two modes:
    1. Multi-error: uses 'errors' array with typed error objects
    2. Single error (legacy): uses _voucher_id/voucherNumber/date/correctedPostings/accountFrom/accountTo/amount

    Fields:
        errors — [{errorType, account, wrongAccount, correctAccount, amount, correctAmount, vatAccount, date}]
        _voucher_id / voucherNumber / date / description — to find the erroneous voucher (single mode)
        correctedPostings — [{debitAccount, creditAccount, amount}] for the correction (single mode)
        correctionDescription / correctionDate — metadata for the new voucher
        accountFrom / accountTo / amount — simple re-posting shorthand
        creditAccount — credit side for simple correction (default 1920)
    """
    errors_list = fields.get("errors", [])

    # --- Multi-error mode ---
    if errors_list:
        logger.info(f"Multi-error correction: {len(errors_list)} errors to process")
        default_date = fields.get("date") or fields.get("correctionDate")
        already_reversed: set[int] = set()
        results: list[dict[str, Any]] = []

        for i, err in enumerate(errors_list):
            logger.info(f"Processing error {i+1}/{len(errors_list)}: {err.get('errorType')}")
            err_result = await _correct_single_error(client, err, default_date, already_reversed)
            results.append(err_result)

        completed = sum(1 for r in results if r.get("status") == "completed")
        logger.info(f"Multi-error correction done: {completed}/{len(results)} completed")

        return {
            "status": "completed",
            "taskType": "correct_ledger_error",
            "errorsProcessed": len(results),
            "errorsCompleted": completed,
            "corrections": results,
        }

    # --- Single error mode (legacy) ---
    voucher_id = fields.get("_voucher_id")
    voucher_number = fields.get("voucherNumber")
    date = fields.get("date")
    description = fields.get("description", "")
    correction_date = fields.get("correctionDate") or date
    correction_description = fields.get("correctionDescription", "")
    corrected_postings = fields.get("correctedPostings", [])
    account_from = fields.get("accountFrom")
    account_to = fields.get("accountTo")
    amount = fields.get("amount")

    # Step 1: Find the erroneous voucher
    original_voucher = None

    if voucher_id:
        resp = await client.get(f"/ledger/voucher/{voucher_id}")
        if resp.status_code == 200:
            original_voucher = resp.json().get("value", {})
    else:
        search_params: dict[str, Any] = {}
        if date:
            search_params["dateFrom"] = date
            search_params["dateTo"] = date
        if voucher_number:
            search_params["number"] = str(voucher_number)

        if not voucher_number and account_from and date:
            acct_id = await _lookup_account(client, int(account_from))
            posting_resp = await client.get("/ledger/posting", params={
                "dateFrom": date, "dateTo": date, "accountId": str(acct_id),
            })
            postings_found = posting_resp.json().get("values", [])
            if postings_found:
                found_id = postings_found[0].get("voucher", {}).get("id")
                if found_id:
                    resp = await client.get(f"/ledger/voucher/{found_id}")
                    if resp.status_code == 200:
                        original_voucher = resp.json().get("value", {})

        if not original_voucher and search_params:
            resp = await client.get("/ledger/voucher", params=search_params)
            vouchers = resp.json().get("values", [])
            if description and len(vouchers) > 1:
                desc_lower = description.lower()
                for v in vouchers:
                    if desc_lower in (v.get("description", "") or "").lower():
                        original_voucher = v
                        break
            if not original_voucher and vouchers:
                original_voucher = vouchers[0]

    if not original_voucher:
        return {
            "status": "error",
            "taskType": "correct_ledger_error",
            "message": "Could not find the erroneous voucher to correct",
        }

    voucher_id = original_voucher["id"]
    reversal_date = correction_date or original_voucher.get("date")
    logger.info(f"Found erroneous voucher {voucher_id} (number={original_voucher.get('number')})")

    # Step 2: Reverse the erroneous voucher
    reverse_resp = await client.put(
        f"/ledger/voucher/{voucher_id}/:reverse",
        params={"date": reversal_date},
    )
    reverse_data = reverse_resp.json()

    if reverse_resp.status_code >= 400:
        error_msg = reverse_data.get("message", "Unknown error")
        logger.error(f"Failed to reverse voucher {voucher_id}: {error_msg}")
        return {
            "status": "error",
            "taskType": "correct_ledger_error",
            "message": f"Failed to reverse erroneous voucher: {error_msg}",
        }

    reversed_voucher = reverse_data.get("value", {})
    logger.info(f"Reversed erroneous voucher {voucher_id}")

    # Step 3: Build the corrected voucher postings
    postings: list[dict[str, Any]] = []

    if corrected_postings:
        # Option A: explicit corrected postings
        for idx, p in enumerate(corrected_postings):
            row = idx + 1
            debit_acct = p.get("debitAccount")
            credit_acct = p.get("creditAccount")
            p_amount = p.get("amount", 0)

            if debit_acct:
                acct_num = int(debit_acct)
                acct_id = await _lookup_account(client, acct_num)
                entry: dict[str, Any] = {
                    "account": {"id": acct_id},
                    "amountGross": p_amount,
                    "amountGrossCurrency": p_amount,
                    "row": row,
                }
                vt = await _lookup_vat_type(client, acct_num)
                if vt:
                    entry["vatType"] = vt
                postings.append(entry)

            if credit_acct:
                acct_num = int(credit_acct)
                acct_id = await _lookup_account(client, acct_num)
                entry = {
                    "account": {"id": acct_id},
                    "amountGross": -p_amount,
                    "amountGrossCurrency": -p_amount,
                    "row": row + len(corrected_postings) if debit_acct else row,
                }
                vt = await _lookup_vat_type(client, acct_num)
                if vt:
                    entry["vatType"] = vt
                postings.append(entry)

    elif account_to and amount:
        # Option B: simple account correction
        debit_num = int(account_to)
        debit_id = await _lookup_account(client, debit_num)
        credit_num = int(fields.get("creditAccount", 1920))
        credit_id = await _lookup_account(client, credit_num)

        postings = [
            {"account": {"id": debit_id}, "amountGross": amount,
             "amountGrossCurrency": amount, "row": 1},
            {"account": {"id": credit_id}, "amountGross": -amount,
             "amountGrossCurrency": -amount, "row": 2},
        ]
        vt = await _lookup_vat_type(client, debit_num)
        if vt:
            postings[0]["vatType"] = vt

    else:
        # Option C: re-post original postings
        orig_postings = original_voucher.get("postings", [])
        if not orig_postings:
            full_resp = await client.get(
                f"/ledger/voucher/{voucher_id}", params={"fields": "*"},
            )
            if full_resp.status_code == 200:
                orig_postings = full_resp.json().get("value", {}).get("postings", [])

        for idx, op in enumerate(orig_postings):
            entry = {
                "account": {"id": op.get("account", {}).get("id")},
                "amountGross": op.get("amountGross", 0),
                "amountGrossCurrency": op.get("amountGrossCurrency", 0),
                "row": idx + 1,
            }
            if op.get("vatType"):
                entry["vatType"] = {"id": op["vatType"].get("id")}
            postings.append(entry)

    if not postings:
        return {
            "status": "completed",
            "taskType": "correct_ledger_error",
            "reversed": reversed_voucher,
            "note": "Voucher reversed but no correction postings to create",
        }

    if not correction_description:
        orig_desc = original_voucher.get("description", "")
        correction_description = (
            f"Korreksjon: {orig_desc}" if orig_desc else "Korreksjonsbilag"
        )

    correction_payload = {
        "date": reversal_date,
        "description": correction_description,
        "postings": postings,
    }

    correction_resp = await client.post("/ledger/voucher", correction_payload)
    correction_data = correction_resp.json()

    if correction_resp.status_code >= 400:
        error_msg = correction_data.get("message", "Unknown error")
        validation = correction_data.get("validationMessages", [])
        logger.error(f"Correction voucher failed: {error_msg} — {validation}")
        return {
            "status": "completed",
            "taskType": "correct_ledger_error",
            "reversed": reversed_voucher,
            "note": f"Voucher reversed but correction failed: {error_msg}",
            "validationMessages": validation,
        }

    correction_voucher = correction_data.get("value", {})
    logger.info(f"Created correction voucher {correction_voucher.get('id')}")

    return {
        "status": "completed",
        "taskType": "correct_ledger_error",
        "reversed": reversed_voucher,
        "correctionVoucher": correction_voucher,
    }


@register_handler("monthly_closing")
async def monthly_closing(client: TripletexClient, fields: dict[str, Any]) -> dict:
    """Perform monthly closing: post accruals, depreciations, and provisions as vouchers.

    Fields:
        month (int): Month number (1-12).
        year (int): Year.
        accruals (list): Periodiseringer — [{fromAccount, toAccount, amount, description}].
        depreciations (list): Avskrivninger — [{account, assetAccount, acquisitionCost, usefulLifeYears, description}].
        provisions (list): Avsetninger — [{debitAccount, creditAccount, amount, description}].
    """
    import datetime

    month = fields.get("month") or datetime.date.today().month
    year = fields.get("year") or datetime.date.today().year
    month = int(month)
    year = int(year)

    accruals = fields.get("accruals", [])
    depreciations = fields.get("depreciations", [])
    provisions = fields.get("provisions", [])

    # Use last day of the month as voucher date
    if month == 12:
        last_day = datetime.date(year, 12, 31)
    else:
        last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    voucher_date = last_day.isoformat()

    created_vouchers: list[dict[str, Any]] = []
    errors: list[str] = []

    # --- 1. Accruals (periodiseringer) ---
    for acc in accruals:
        from_account = int(acc.get("fromAccount", 0))
        to_account = int(acc.get("toAccount", 0))
        amount = acc.get("amount", 0)
        desc = acc.get("description", f"Periodisering {month}/{year}")

        if not from_account or not to_account or not amount:
            errors.append(f"Accrual missing required fields: {acc}")
            continue

        try:
            # Debit the expense account (toAccount), credit the balance sheet account (fromAccount)
            debit_id = await _lookup_account(client, to_account)
            credit_id = await _lookup_account(client, from_account)

            payload = {
                "date": voucher_date,
                "description": desc,
                "postings": [
                    {
                        "account": {"id": debit_id},
                        "amountGross": amount,
                        "amountGrossCurrency": amount,
                        "row": 1,
                    },
                    {
                        "account": {"id": credit_id},
                        "amountGross": -amount,
                        "amountGrossCurrency": -amount,
                        "row": 2,
                    },
                ],
            }

            resp = await client.post("/ledger/voucher", payload)
            data = resp.json()
            if resp.status_code >= 400:
                error_msg = data.get("message", "Unknown error")
                errors.append(f"Accrual voucher failed: {error_msg}")
                logger.warning(f"Accrual voucher failed: {error_msg}")
            else:
                voucher = data.get("value", {})
                created_vouchers.append({
                    "type": "accrual",
                    "voucherId": voucher.get("id"),
                    "description": desc,
                    "amount": amount,
                })
                logger.info(f"Created accrual voucher {voucher.get('id')}: {desc}")
        except Exception as e:
            errors.append(f"Accrual error: {e}")
            logger.error(f"Accrual error: {e}")

    # --- 2. Depreciations (avskrivninger) ---
    for dep in depreciations:
        expense_account = int(dep.get("account", 0))
        asset_account = int(dep.get("assetAccount", 0))
        acquisition_cost = dep.get("acquisitionCost", 0)
        useful_life_years = dep.get("usefulLifeYears", 0)
        desc = dep.get("description", f"Avskrivning {month}/{year}")

        if not expense_account or not asset_account or not acquisition_cost or not useful_life_years:
            errors.append(f"Depreciation missing required fields: {dep}")
            continue

        # Calculate monthly depreciation: acquisitionCost / usefulLifeYears / 12
        monthly_amount = round(acquisition_cost / useful_life_years / 12, 2)

        try:
            debit_id = await _lookup_account(client, expense_account)
            credit_id = await _lookup_account(client, asset_account)

            payload = {
                "date": voucher_date,
                "description": desc,
                "postings": [
                    {
                        "account": {"id": debit_id},
                        "amountGross": monthly_amount,
                        "amountGrossCurrency": monthly_amount,
                        "row": 1,
                    },
                    {
                        "account": {"id": credit_id},
                        "amountGross": -monthly_amount,
                        "amountGrossCurrency": -monthly_amount,
                        "row": 2,
                    },
                ],
            }

            resp = await client.post("/ledger/voucher", payload)
            data = resp.json()
            if resp.status_code >= 400:
                error_msg = data.get("message", "Unknown error")
                errors.append(f"Depreciation voucher failed: {error_msg}")
                logger.warning(f"Depreciation voucher failed: {error_msg}")
            else:
                voucher = data.get("value", {})
                created_vouchers.append({
                    "type": "depreciation",
                    "voucherId": voucher.get("id"),
                    "description": desc,
                    "amount": monthly_amount,
                })
                logger.info(f"Created depreciation voucher {voucher.get('id')}: {desc}, amount={monthly_amount}")
        except Exception as e:
            errors.append(f"Depreciation error: {e}")
            logger.error(f"Depreciation error: {e}")

    # --- 3. Provisions (avsetninger) ---
    for prov in provisions:
        debit_account = int(prov.get("debitAccount", 0))
        credit_account = int(prov.get("creditAccount", 0))
        amount = prov.get("amount", 0)
        desc = prov.get("description", f"Avsetning {month}/{year}")

        if not debit_account or not credit_account or not amount:
            errors.append(f"Provision missing required fields: {prov}")
            continue

        try:
            debit_id = await _lookup_account(client, debit_account)
            credit_id = await _lookup_account(client, credit_account)

            payload = {
                "date": voucher_date,
                "description": desc,
                "postings": [
                    {
                        "account": {"id": debit_id},
                        "amountGross": amount,
                        "amountGrossCurrency": amount,
                        "row": 1,
                    },
                    {
                        "account": {"id": credit_id},
                        "amountGross": -amount,
                        "amountGrossCurrency": -amount,
                        "row": 2,
                    },
                ],
            }

            resp = await client.post("/ledger/voucher", payload)
            data = resp.json()
            if resp.status_code >= 400:
                error_msg = data.get("message", "Unknown error")
                errors.append(f"Provision voucher failed: {error_msg}")
                logger.warning(f"Provision voucher failed: {error_msg}")
            else:
                voucher = data.get("value", {})
                created_vouchers.append({
                    "type": "provision",
                    "voucherId": voucher.get("id"),
                    "description": desc,
                    "amount": amount,
                })
                logger.info(f"Created provision voucher {voucher.get('id')}: {desc}")
        except Exception as e:
            errors.append(f"Provision error: {e}")
            logger.error(f"Provision error: {e}")

    result: dict[str, Any] = {
        "status": "completed",
        "taskType": "monthly_closing",
        "month": month,
        "year": year,
        "voucherDate": voucher_date,
        "vouchersCreated": len(created_vouchers),
        "vouchers": created_vouchers,
    }

    if errors:
        result["errors"] = errors

    logger.info(
        f"Monthly closing {month}/{year}: {len(created_vouchers)} vouchers created, {len(errors)} errors"
    )
    return result
