#!/usr/bin/env python3
"""Test all run_payroll prompts against sandbox, one by one."""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_payroll")

from app.parser import parse_task
from app.tripletex import TripletexClient
from app.handlers import execute_task


def get_sandbox_creds() -> tuple[str, str]:
    """Fetch sandbox credentials from NM i AI API."""
    token = os.environ.get("NMIAI_ACCESS_TOKEN")
    if not token:
        print("ERROR: NMIAI_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    r = httpx.get(
        "https://api.ainm.no/tripletex/sandbox",
        cookies={"access_token": token},
        headers={"origin": "https://app.ainm.no", "referer": "https://app.ainm.no/"},
    )
    if r.status_code != 200:
        print(f"ERROR: Failed to get sandbox creds: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    data = r.json()
    return data["api_url"], data["session_token"]


async def test_one_prompt(prompt_file: str, api_url: str, session_token: str) -> dict:
    """Test a single prompt. Returns result dict."""
    raw = open(prompt_file).read()
    # Strip the "Confidence: X.XX\n\n" prefix
    lines = raw.strip().split("\n")
    prompt = "\n".join(lines[2:]) if lines[0].startswith("Confidence:") else raw.strip()

    print(f"\n{'='*70}")
    print(f"FILE: {os.path.basename(prompt_file)}")
    print(f"PROMPT: {prompt[:100]}...")

    # Parse
    parsed = parse_task(prompt, [])
    print(f"  PARSER: task_type={parsed.task_type}, confidence={parsed.confidence:.0%}")
    print(f"  FIELDS: {json.dumps(parsed.fields, ensure_ascii=False)}")

    if parsed.task_type != "run_payroll":
        print(f"  *** WRONG TASK TYPE: expected run_payroll, got {parsed.task_type} ***")
        return {"file": os.path.basename(prompt_file), "status": "PARSER_ERROR",
                "task_type": parsed.task_type, "error": f"Wrong task type: {parsed.task_type}"}

    # Create client
    client = TripletexClient(base_url=api_url, session_token=session_token)

    try:
        result = await execute_task(parsed.task_type, client, parsed.fields, prompt=prompt)
    except Exception as e:
        print(f"  *** HANDLER EXCEPTION: {e} ***")
        await client.close()
        return {"file": os.path.basename(prompt_file), "status": "EXCEPTION", "error": str(e)}

    # Analyze
    api_calls = client.tracker.api_calls if hasattr(client.tracker, 'api_calls') else []
    errors_4xx = [c for c in api_calls if 400 <= (c.status or 0) < 500]
    errors_5xx = [c for c in api_calls if 500 <= (c.status or 0) < 600]

    status = result.get("status", "unknown")
    tx_id = result.get("transactionId")
    payslip_id = result.get("payslipId")
    note = result.get("note", "")

    print(f"  STATUS: {status}")
    print(f"  transactionId: {tx_id}")
    print(f"  payslipId: {payslip_id}")
    print(f"  API calls: {len(api_calls)}")
    if note:
        print(f"  NOTE: {note}")
    if errors_4xx:
        print(f"  4xx ERRORS ({len(errors_4xx)}):")
        for e in errors_4xx:
            print(f"    {e.method} {e.path} -> {e.status}")
    if errors_5xx:
        print(f"  5xx ERRORS ({len(errors_5xx)}):")
        for e in errors_5xx:
            print(f"    {e.method} {e.path} -> {e.status}")

    success = tx_id is not None and status == "completed"
    print(f"  RESULT: {'OK' if success else 'FAIL'}")

    await client.close()

    return {
        "file": os.path.basename(prompt_file),
        "status": "OK" if success else "FAIL",
        "task_type": parsed.task_type,
        "transactionId": tx_id,
        "payslipId": payslip_id,
        "api_calls": len(api_calls),
        "errors_4xx": len(errors_4xx),
        "errors_5xx": len(errors_5xx),
        "note": note,
        "error": "" if success else (note or "no transactionId"),
    }


async def main():
    files = sorted(glob.glob(str(PROJECT_ROOT / "data/classified_prompts/run_payroll/*.txt")))
    print(f"Found {len(files)} run_payroll prompts")

    api_url, session_token = get_sandbox_creds()
    print(f"Sandbox URL: {api_url}")

    results = []
    for f in files:
        r = await test_one_prompt(f, api_url, session_token)
        results.append(r)
        # Small delay between prompts
        await asyncio.sleep(1)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    ok = sum(1 for r in results if r["status"] == "OK")
    fail = sum(1 for r in results if r["status"] != "OK")
    print(f"OK: {ok}/{len(results)}, FAIL: {fail}")
    for r in results:
        marker = "OK" if r["status"] == "OK" else "FAIL"
        print(f"  [{marker}] {r['file']}: api_calls={r.get('api_calls','?')}, "
              f"4xx={r.get('errors_4xx','?')}, tx={r.get('transactionId','?')}, "
              f"err={r.get('error','')}")


if __name__ == "__main__":
    asyncio.run(main())
