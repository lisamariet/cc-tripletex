#!/usr/bin/env python3
"""CLI for NM i AI competition: submit and check results."""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

API_BASE = "https://api.ainm.no"
ENDPOINT_URL = "https://tripletex-agent-753459644453.europe-west1.run.app"

COMMON_HEADERS = {
    "accept": "*/*",
    "origin": "https://app.ainm.no",
    "referer": "https://app.ainm.no/",
}


def get_token() -> str:
    token = os.environ.get("NMIAI_TRIPLETEX_ACCESS_TOKEN")
    if not token:
        print("Error: NMIAI_TRIPLETEX_ACCESS_TOKEN not found in .env")
        sys.exit(1)
    return token


def make_client() -> httpx.Client:
    token = get_token()
    return httpx.Client(
        headers=COMMON_HEADERS,
        cookies={"access_token": token},
        timeout=30.0,
    )


def fetch_submissions(client: httpx.Client) -> list[dict]:
    resp = client.get(f"{API_BASE}/tripletex/my/submissions")
    resp.raise_for_status()
    return resp.json()


def format_timestamp(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts[:19] if ts else "-"


def print_submissions_table(submissions: list[dict]) -> None:
    if not submissions:
        print("No submissions found.")
        return

    # Sort by queued_at descending (most recent first)
    submissions = sorted(
        submissions,
        key=lambda s: s.get("queued_at") or "",
        reverse=True,
    )

    headers = ["#", "Timestamp", "Score", "Checks", "Duration", "Feedback"]
    rows = []
    for i, sub in enumerate(submissions[:20], 1):
        ts = sub.get("queued_at")
        raw = sub.get("score_raw", 0)
        mx = sub.get("score_max", 0)
        norm = sub.get("normalized_score", 0)
        score_str = f"{raw}/{mx} ({norm:.0%})"
        duration = sub.get("duration_ms", 0)
        dur_str = f"{duration / 1000:.1f}s"
        feedback = sub.get("feedback", {})
        comment = feedback.get("comment", "-")
        rows.append([str(i), format_timestamp(ts), score_str, comment, dur_str, sub.get("status", "-")])

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for j, cell in enumerate(row):
            col_widths[j] = max(col_widths[j], len(cell))

    def format_row(cells: list[str]) -> str:
        return " | ".join(cell.ljust(col_widths[j]) for j, cell in enumerate(cells))

    separator = "-+-".join("-" * w for w in col_widths)

    print(format_row(headers))
    print(separator)
    for row in rows:
        print(format_row(row))


def cmd_status(args: argparse.Namespace) -> None:
    """Fetch and display recent submissions."""
    with make_client() as client:
        print("Fetching submissions...")
        submissions = fetch_submissions(client)
        print()

        if isinstance(submissions, dict):
            # API might wrap in an object
            submissions = submissions.get("submissions") or submissions.get("data") or [submissions]

        print_submissions_table(submissions)


def cmd_submit(args: argparse.Namespace) -> None:
    """Trigger a new submission and poll for result."""
    endpoint = args.endpoint or ENDPOINT_URL

    with make_client() as client:
        print(f"Submitting endpoint: {endpoint}")

        # Try POST to /tripletex/submit with endpoint URL
        payload = {"endpoint_url": endpoint}
        resp = client.post(f"{API_BASE}/tripletex/submit", json=payload)

        if resp.status_code == 404:
            # Fallback: try with just url field
            payload = {"url": endpoint}
            resp = client.post(f"{API_BASE}/tripletex/submit", json=payload)

        if resp.status_code == 404:
            # Another fallback: POST to submissions endpoint
            resp = client.post(f"{API_BASE}/tripletex/my/submissions", json={"endpoint_url": endpoint})

        if resp.status_code == 405:
            # Method not allowed - try other approaches
            print(f"Warning: POST returned 405. Response: {resp.text}")
            print("You may need to submit via the web UI at https://app.ainm.no/submit/tripletex")
            return

        if not resp.is_success:
            print(f"Submit failed ({resp.status_code}): {resp.text}")
            return

        result = resp.json()
        print(f"Submission triggered: {result}")

        # Poll for result
        submission_id = result.get("id") or result.get("submission_id")
        if submission_id and not args.no_poll:
            print("\nPolling for result...")
            poll_for_result(client, submission_id)
        elif not args.no_poll:
            # No ID returned, just fetch latest after a delay
            print("\nWaiting for results...")
            time.sleep(5)
            submissions = fetch_submissions(client)
            if isinstance(submissions, dict):
                submissions = submissions.get("submissions") or submissions.get("data") or [submissions]
            print()
            print_submissions_table(submissions[:5])


def poll_for_result(client: httpx.Client, submission_id: str, max_wait: int = 300) -> None:
    """Poll until submission is complete or timeout."""
    start = time.time()
    interval = 5

    while time.time() - start < max_wait:
        time.sleep(interval)
        elapsed = int(time.time() - start)
        print(f"  ... {elapsed}s elapsed", end="\r")

        submissions = fetch_submissions(client)
        if isinstance(submissions, dict):
            submissions = submissions.get("submissions") or submissions.get("data") or [submissions]

        # Find our submission
        for sub in submissions:
            sid = sub.get("id") or sub.get("submission_id")
            if str(sid) == str(submission_id):
                status = sub.get("status", "")
                if status.lower() in ("completed", "done", "scored", "failed", "error"):
                    print(f"\n\nSubmission {submission_id} finished!")
                    print()
                    print_submissions_table([sub])
                    return

        # Increase interval gradually
        interval = min(interval + 2, 15)

    print(f"\n\nTimeout after {max_wait}s. Check status with: python scripts/compete.py status")


def cmd_insights(args: argparse.Namespace) -> None:
    """Analyze GCS result logs for efficiency insights."""
    import json
    import subprocess

    print("Henter resultat-logger fra GCS...\n")
    result = subprocess.run(
        ["gsutil", "ls", "gs://tripletex-agent-requests/results/"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Ingen resultat-logger funnet.")
        return

    files = sorted(result.stdout.strip().split("\n"))
    if not files or files == [""]:
        print("Ingen resultat-logger funnet.")
        return

    total_submissions = 0
    total_api_calls = 0
    total_4xx = 0
    handler_stats: dict[str, dict] = {}

    for f in files:
        r = subprocess.run(["gsutil", "cat", f], capture_output=True, text=True)
        if r.returncode != 0:
            continue
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            continue

        total_submissions += 1
        task = data.get("parsed_task", {})
        task_type = task.get("task_type", "unknown")
        api_calls = data.get("api_calls", [])
        n_calls = len(api_calls)
        n_4xx = sum(1 for c in api_calls if 400 <= c.get("status", 0) < 500)
        total_api_calls += n_calls
        total_4xx += n_4xx

        if task_type not in handler_stats:
            handler_stats[task_type] = {"runs": 0, "calls": 0, "errors_4xx": 0, "calls_detail": []}
        handler_stats[task_type]["runs"] += 1
        handler_stats[task_type]["calls"] += n_calls
        handler_stats[task_type]["errors_4xx"] += n_4xx

        for c in api_calls:
            status = c.get("status", 0)
            detail = f"{c['method']:6} {c['path']:40} {status} ({c.get('duration_ms', 0):.0f}ms)"
            if 400 <= status < 500:
                detail += "  ⚠️  4xx ERROR"
            handler_stats[task_type]["calls_detail"].append(detail)

    # Summary
    print(f"{'='*60}")
    print(f"  INSIGHTS — {total_submissions} submissions analysert")
    print(f"{'='*60}")
    print(f"  Totalt API-kall:  {total_api_calls}")
    print(f"  Totalt 4xx-feil:  {total_4xx}")
    if total_api_calls > 0:
        print(f"  Feilrate:         {total_4xx/total_api_calls:.0%}")
    print()

    # Per handler
    print(f"{'Handler':<25} {'Kjøringer':>9} {'API-kall':>9} {'4xx':>5} {'Snitt kall':>11}")
    print("-" * 65)
    for task_type in sorted(handler_stats.keys()):
        s = handler_stats[task_type]
        avg = s["calls"] / s["runs"] if s["runs"] > 0 else 0
        err_marker = "  ⚠️" if s["errors_4xx"] > 0 else ""
        print(f"{task_type:<25} {s['runs']:>9} {s['calls']:>9} {s['errors_4xx']:>5} {avg:>10.1f}{err_marker}")

    # Detailed call log per handler
    if args.detail:
        print(f"\n{'='*60}")
        print("  DETALJERT API-KALL-LOGG")
        print(f"{'='*60}")
        for task_type in sorted(handler_stats.keys()):
            s = handler_stats[task_type]
            print(f"\n  [{task_type}]")
            for detail in s["calls_detail"]:
                print(f"    {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="NM i AI competition CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status command
    subparsers.add_parser("status", help="Show recent submissions and scores")

    # submit command
    submit_parser = subparsers.add_parser("submit", help="Trigger a new submission")
    submit_parser.add_argument(
        "--endpoint",
        default=None,
        help=f"Endpoint URL (default: {ENDPOINT_URL})",
    )
    submit_parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Don't poll for result after submitting",
    )

    # insights command
    insights_parser = subparsers.add_parser("insights", help="Analyze API call efficiency from GCS logs")
    insights_parser.add_argument(
        "--detail",
        action="store_true",
        help="Show detailed API call log per handler",
    )

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "submit":
        cmd_submit(args)
    elif args.command == "insights":
        cmd_insights(args)


if __name__ == "__main__":
    main()
