#!/usr/bin/env python3
"""CLI for NM i AI competition: submit and check results."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
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

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# All 30 known task types (from docs)
KNOWN_TASK_TYPES = [
    "create_employee", "create_customer", "create_product", "create_invoice",
    "create_order", "create_project", "create_department", "create_contact",
    "create_supplier", "create_travel_expense",
    "update_employee", "update_customer", "update_contact",
    "delete_travel_expense", "delete_invoice",
    "invoice_with_payment", "credit_note", "project_billing",
    "register_payment", "multi_step_invoice",
    "bank_reconciliation", "error_correction", "year_end_closing",
    "create_invoice_from_pdf", "expense_report",
    "enable_department_accounting", "assign_role",
    "create_product_with_vat", "batch_create_employees",
    "reverse_payment",
]


def get_token() -> str:
    token = os.environ.get("NMIAI_ACCESS_TOKEN")
    if not token:
        print("Error: NMIAI_ACCESS_TOKEN not found in .env")
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


def normalize_submissions(subs) -> list[dict]:
    """Normalize API response to a list of submission dicts."""
    if isinstance(subs, dict):
        subs = subs.get("submissions") or subs.get("data") or [subs]
    return subs


def format_timestamp(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts[:19] if ts else "-"


def format_ts_short(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return ts[11:19] if ts and len(ts) > 19 else (ts or "-")


def score_color(norm: float | None) -> str:
    """Return ANSI color based on normalized score."""
    if norm is None:
        return DIM
    if norm >= 1.0:
        return GREEN
    if norm > 0:
        return YELLOW
    return RED


def safe_float(val, default=0.0) -> float:
    """Safely convert to float, handling None."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(val, default=0) -> int:
    """Safely convert to int, handling None."""
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────
#  Translation helpers
# ──────────────────────────────────────────────

def _needs_translation(text: str) -> bool:
    """Check if text is likely not Norwegian or English."""
    norwegian_words = {"opprett", "kunden", "med", "og", "fra", "til", "for", "er", "skal", "den", "det", "har"}
    english_words = {"create", "the", "with", "and", "from", "for", "is", "customer", "employee"}
    words = set(text.lower().split()[:20])
    if words & norwegian_words:
        return False
    if words & english_words:
        return False
    return True


def _translate_prompt(prompt: str) -> str | None:
    """Translate a prompt to Norwegian using Claude."""
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        client = anthropic.Anthropic(api_key=api_key, timeout=10.0)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": f"Oversett til norsk. Kun oversettelsen, ingen forklaring:\n\n{prompt}"}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


# ──────────────────────────────────────────────
#  GCS log helpers
# ──────────────────────────────────────────────

def fetch_gcs_logs(log_type: str = "results") -> list[dict]:
    """Fetch all GCS log files and return parsed JSON list.
    log_type: 'results' or 'requests'
    """
    result = subprocess.run(
        ["gsutil", "ls", f"gs://tripletex-agent-requests/{log_type}/"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    files = sorted(result.stdout.strip().split("\n"))
    if not files or files == [""]:
        return []

    logs = []
    for f in files:
        r = subprocess.run(["gsutil", "cat", f], capture_output=True, text=True)
        if r.returncode != 0:
            continue
        try:
            data = json.loads(r.stdout)
            data["_gcs_path"] = f
            logs.append(data)
        except json.JSONDecodeError:
            continue
    return logs


def match_log_to_submission(log: dict, submissions: list[dict]) -> dict | None:
    """Match a GCS log to a submission by timestamp proximity."""
    log_ts = log.get("timestamp", "")  # e.g. "20260319_224215_118186"
    if not log_ts:
        return None

    try:
        # Parse GCS timestamp format: YYYYMMDD_HHMMSS_microseconds
        dt_log = datetime.strptime(log_ts[:15], "%Y%m%d_%H%M%S")
    except (ValueError, IndexError):
        return None

    best_match = None
    best_delta = timedelta(minutes=10)  # max 10 min tolerance

    for sub in submissions:
        sub_ts = sub.get("queued_at") or sub.get("created_at") or ""
        if not sub_ts:
            continue
        try:
            dt_sub = datetime.fromisoformat(sub_ts.replace("Z", "+00:00")).replace(tzinfo=None)
            delta = abs(dt_log - dt_sub)
            if delta < best_delta:
                best_delta = delta
                best_match = sub
        except Exception:
            continue

    return best_match


def get_task_type_for_sub(sub: dict, gcs_logs: list[dict]) -> str:
    """Find task type from GCS logs for a submission."""
    sub_ts = sub.get("queued_at") or sub.get("created_at") or ""
    if not sub_ts:
        return "?"
    try:
        dt_sub = datetime.fromisoformat(sub_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return "?"

    best_type = "?"
    best_delta = timedelta(minutes=10)

    for log in gcs_logs:
        log_ts = log.get("timestamp", "")
        if not log_ts:
            continue
        try:
            dt_log = datetime.strptime(log_ts[:15], "%Y%m%d_%H%M%S")
            delta = abs(dt_log - dt_sub)
            if delta < best_delta:
                best_delta = delta
                task = log.get("parsed_task", {}) or {}
                best_type = task.get("task_type", "?")
        except Exception:
            continue

    return best_type


def get_log_for_sub(sub: dict, gcs_logs: list[dict]) -> dict | None:
    """Find the GCS log closest in time to a submission."""
    sub_ts = sub.get("queued_at") or sub.get("created_at") or ""
    if not sub_ts:
        return None
    try:
        dt_sub = datetime.fromisoformat(sub_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

    best_log = None
    best_delta = timedelta(minutes=10)

    for log in gcs_logs:
        log_ts = log.get("timestamp", "")
        if not log_ts:
            continue
        try:
            dt_log = datetime.strptime(log_ts[:15], "%Y%m%d_%H%M%S")
            delta = abs(dt_log - dt_sub)
            if delta < best_delta:
                best_delta = delta
                best_log = log
        except Exception:
            continue

    return best_log


# ──────────────────────────────────────────────
#  status command
# ──────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    """Fetch and display recent submissions with summary."""
    with make_client() as client:
        print("Henter submissions...")
        submissions = normalize_submissions(fetch_submissions(client))

    if not submissions:
        print("Ingen submissions funnet.")
        return

    # Sort by queued_at descending
    submissions = sorted(
        submissions,
        key=lambda s: s.get("queued_at") or "",
        reverse=True,
    )

    # Try to fetch GCS logs for task type info (silently skip on error)
    gcs_logs = []
    try:
        gcs_logs = fetch_gcs_logs("results")
    except Exception:
        pass

    # ── Summary line ──
    total_score = 0.0
    best_scores: dict[str, float] = {}
    today_count = 0
    today_str = datetime.now().strftime("%Y-%m-%d")

    for sub in submissions:
        norm = safe_float(sub.get("normalized_score"))
        raw = safe_float(sub.get("score_raw"))
        mx = safe_float(sub.get("score_max"))
        task_type = get_task_type_for_sub(sub, gcs_logs) if gcs_logs else "?"

        # Track best per task type
        if task_type != "?":
            current_best = best_scores.get(task_type, 0.0)
            # Use the actual score (raw, which includes tier multiplier + efficiency)
            score_val = raw if raw is not None else 0.0
            if score_val > current_best:
                best_scores[task_type] = score_val

        ts = sub.get("queued_at") or ""
        if today_str in ts:
            today_count += 1

    total_score = sum(best_scores.values())
    tasks_with_score = sum(1 for v in best_scores.values() if v > 0)

    print()
    print(f"{BOLD}  Totalpoeng: {total_score:.1f} | Oppgaver med poeng: {tasks_with_score}/30 | Submissions i dag: {today_count}/32{RESET}")
    print()

    # ── Table ──
    print(f"  {'#':>3}  {'Tid':<10} {'Oppgavetype':<25} {'Score':>12} {'Varighet':>8}  {'Status'}")
    print(f"  {'─'*80}")

    for i, sub in enumerate(submissions[:25], 1):
        ts = format_ts_short(sub.get("queued_at"))
        raw = sub.get("score_raw")
        mx = sub.get("score_max")
        norm = sub.get("normalized_score")
        duration = safe_int(sub.get("duration_ms"))
        status = sub.get("status", "-")
        task_type = get_task_type_for_sub(sub, gcs_logs) if gcs_logs else "?"

        if raw is not None and mx is not None:
            norm_f = safe_float(norm)
            color = score_color(norm_f)
            score_str = f"{color}{safe_int(raw)}/{safe_int(mx)} ({norm_f:.0%}){RESET}"
            # Pad for ANSI codes: actual visible length is ~12, ANSI adds ~10 chars
            score_pad = f"{safe_int(raw)}/{safe_int(mx)} ({norm_f:.0%})"
        else:
            score_str = f"{DIM}venter...{RESET}"
            score_pad = "venter..."

        dur_str = f"{duration / 1000:.1f}s" if duration else "-"

        # Right-align score (compensate for ANSI)
        visible_pad = 12 - len(score_pad)
        score_display = " " * max(0, visible_pad) + score_str

        print(f"  {i:>3}  {ts:<10} {task_type:<25} {score_display} {dur_str:>8}  {status}")


# ──────────────────────────────────────────────
#  show command (per-submission detail)
# ──────────────────────────────────────────────

def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed view of a specific submission."""
    n = args.number  # 1 = latest

    with make_client() as client:
        print("Henter submissions...")
        submissions = normalize_submissions(fetch_submissions(client))

    if not submissions:
        print("Ingen submissions funnet.")
        return

    submissions = sorted(
        submissions,
        key=lambda s: s.get("queued_at") or "",
        reverse=True,
    )

    if n < 1 or n > len(submissions):
        print(f"Ugyldig nummer. Velg mellom 1 og {len(submissions)}.")
        return

    sub = submissions[n - 1]

    # Fetch GCS logs
    print("Henter GCS-logger...")
    gcs_logs = fetch_gcs_logs("results")
    gcs_requests = fetch_gcs_logs("requests")

    log = get_log_for_sub(sub, gcs_logs)
    req_log = get_log_for_sub(sub, gcs_requests)

    print()
    print(f"{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  SUBMISSION #{n}{RESET}")
    print(f"{BOLD}{'═'*70}{RESET}")

    # ── Basic info ──
    ts = format_timestamp(sub.get("queued_at"))
    raw = sub.get("score_raw")
    mx = sub.get("score_max")
    norm = sub.get("normalized_score")
    duration = safe_int(sub.get("duration_ms"))
    status = sub.get("status", "-")

    print(f"  Tidspunkt:  {ts}")
    print(f"  Status:     {status}")
    if raw is not None:
        norm_f = safe_float(norm)
        color = score_color(norm_f)
        print(f"  Score:      {color}{safe_int(raw)}/{safe_int(mx)} ({norm_f:.0%}){RESET}")
    else:
        print(f"  Score:      {DIM}(ikke ferdig){RESET}")
    print(f"  Varighet:   {duration / 1000:.1f}s" if duration else "  Varighet:   -")

    # ── Feedback / Checks ──
    feedback = sub.get("feedback") or {}
    if feedback:
        print(f"\n  {BOLD}Tilbakemelding:{RESET}")
        comment = feedback.get("comment", "")
        if comment:
            print(f"  {comment}")

        checks = feedback.get("checks") or feedback.get("details") or []
        if checks:
            print(f"\n  {BOLD}Sjekker:{RESET}")
            for check in checks:
                if isinstance(check, dict):
                    name = check.get("name") or check.get("check") or check.get("field", "?")
                    passed = check.get("passed") or check.get("success", False)
                    points = check.get("points") or check.get("score", "?")
                    max_pts = check.get("max_points") or check.get("max", "?")
                    icon = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
                    print(f"    {icon} {name}: {points}/{max_pts}")
                else:
                    print(f"    {check}")

    # ── Prompt (from request log) ──
    prompt = None
    if req_log:
        prompt = req_log.get("prompt", "")
    if not prompt and log:
        prompt = log.get("prompt", "")

    if prompt:
        print(f"\n  {BOLD}Prompt:{RESET}")
        for line in prompt.split("\n"):
            print(f"    {line}")

        # Translate if not Norwegian/English
        if args.translate and _needs_translation(prompt):
            translated = _translate_prompt(prompt)
            if translated:
                print(f"\n  {BOLD}Oversettelse:{RESET}")
                for line in translated.split("\n"):
                    print(f"    {DIM}{line}{RESET}")

    # ── Parsed task ──
    if log:
        parsed = log.get("parsed_task") or {}
        if parsed:
            print(f"\n  {BOLD}Parsed oppgave:{RESET}")
            task_type = parsed.get("task_type", "?")
            print(f"    Type:   {CYAN}{task_type}{RESET}")
            fields = parsed.get("fields") or {}
            if fields:
                print(f"    Felt:")
                for k, v in fields.items():
                    print(f"      {k}: {v}")

    # ── API calls ──
    if log:
        api_calls = log.get("api_calls") or []
        if api_calls:
            n_calls = len(api_calls)
            n_4xx = sum(1 for c in api_calls if 400 <= safe_int(c.get("status")) < 500)
            n_5xx = sum(1 for c in api_calls if safe_int(c.get("status")) >= 500)
            total_api_ms = sum(safe_float(c.get("duration_ms")) for c in api_calls)

            print(f"\n  {BOLD}API-kall ({n_calls} totalt, {n_4xx} 4xx-feil, {n_5xx} 5xx-feil):{RESET}")
            print(f"  Total API-tid: {total_api_ms:.0f}ms")
            print()
            print(f"    {'#':>3}  {'Metode':<7} {'Sti':<42} {'Status':>6} {'Tid':>7}")
            print(f"    {'─'*70}")

            for j, call in enumerate(api_calls, 1):
                method = call.get("method", "?")
                path = call.get("path", "?")
                if len(path) > 40:
                    path = path[:37] + "..."
                status_code = safe_int(call.get("status"))
                dur = safe_float(call.get("duration_ms"))

                if 400 <= status_code < 500:
                    color = RED
                elif 200 <= status_code < 300:
                    color = GREEN
                else:
                    color = YELLOW

                print(f"    {j:>3}  {method:<7} {path:<42} {color}{status_code:>6}{RESET} {dur:>6.0f}ms")

                # Show 4xx error body if available
                if 400 <= status_code < 500:
                    error_body = call.get("response_body") or call.get("error") or call.get("body", "")
                    if error_body:
                        err_str = str(error_body)[:120]
                        print(f"         {RED}{err_str}{RESET}")

    # ── Efficiency metrics ──
    if log:
        api_calls = log.get("api_calls") or []
        if api_calls:
            n_calls = len(api_calls)
            n_4xx = sum(1 for c in api_calls if 400 <= safe_int(c.get("status")) < 500)
            err_rate = n_4xx / n_calls if n_calls > 0 else 0
            print(f"\n  {BOLD}Effektivitet:{RESET}")
            print(f"    Totalt kall:    {n_calls}")
            print(f"    4xx-feil:       {n_4xx}")
            print(f"    Feilrate:       {err_rate:.0%}")
            if raw is not None and safe_float(norm) >= 1.0:
                print(f"    {GREEN}Perfekt score → effektivitetsbonus aktiv{RESET}")
            elif raw is not None:
                print(f"    {YELLOW}Ikke perfekt → ingen effektivitetsbonus{RESET}")

    print()


# ──────────────────────────────────────────────
#  insights command (improved)
# ──────────────────────────────────────────────

def cmd_insights(args: argparse.Namespace) -> None:
    """Comprehensive analysis: competition scores + GCS API call logs."""

    # ── Fetch competition data ──
    print("Henter submissions...")
    with make_client() as client:
        subs = normalize_submissions(fetch_submissions(client))

    print("Henter GCS-logger...")
    gcs_logs = fetch_gcs_logs("results")

    print()
    print(f"{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  KONKURRANSE-ANALYSE{RESET}")
    print(f"{BOLD}{'═'*70}{RESET}")

    # ── Per-task-type best scores ──
    task_best: dict[str, dict] = {}  # task_type -> {best_raw, best_max, best_norm, count}

    for sub in subs:
        raw = safe_float(sub.get("score_raw"))
        mx = safe_float(sub.get("score_max"))
        norm = safe_float(sub.get("normalized_score"))
        task_type = get_task_type_for_sub(sub, gcs_logs) if gcs_logs else "?"

        if task_type == "?" or task_type == "":
            continue

        if task_type not in task_best:
            task_best[task_type] = {
                "best_raw": 0, "best_max": 0, "best_norm": 0, "count": 0,
                "scores": [],
            }
        tb = task_best[task_type]
        tb["count"] += 1
        tb["scores"].append(norm)
        if raw > tb["best_raw"]:
            tb["best_raw"] = raw
            tb["best_max"] = mx
            tb["best_norm"] = norm

    # Summary
    total = len(subs)
    perfect = sum(1 for s in subs if safe_float(s.get("normalized_score")) >= 1.0)
    failed = sum(1 for s in subs if safe_float(s.get("score_raw")) == 0 and s.get("score_raw") is not None)
    partial = total - perfect - failed
    pending = sum(1 for s in subs if s.get("score_raw") is None)
    total_best = sum(tb["best_raw"] for tb in task_best.values())

    print(f"\n  {BOLD}Oversikt:{RESET}")
    print(f"    Submissions totalt:   {total}")
    print(f"    {GREEN}Perfekt (100%+):{RESET}      {perfect}")
    print(f"    {YELLOW}Delvis:{RESET}               {partial}")
    print(f"    {RED}Feilet (0%):{RESET}          {failed}")
    if pending:
        print(f"    {DIM}Under behandling:{RESET}     {pending}")
    print(f"    {BOLD}Sum beste poeng:{RESET}      {total_best:.1f}")
    print(f"    {BOLD}Unike oppgavetyper:{RESET}   {len(task_best)}/30")

    # ── Per-task-type table ──
    if task_best:
        print(f"\n  {BOLD}Beste score per oppgavetype:{RESET}")
        print(f"    {'Oppgavetype':<28} {'Beste':>8} {'Norm':>6} {'Forsøk':>7} {'Status'}")
        print(f"    {'─'*65}")

        for task_type in sorted(task_best.keys()):
            tb = task_best[task_type]
            norm = tb["best_norm"]
            color = score_color(norm)
            raw_str = f"{tb['best_raw']:.1f}/{tb['best_max']:.0f}"
            norm_str = f"{norm:.0%}"

            if norm >= 1.0:
                status = f"{GREEN}perfekt{RESET}"
            elif norm > 0:
                status = f"{YELLOW}kan forbedres{RESET}"
            else:
                status = f"{RED}feilet{RESET}"

            print(f"    {task_type:<28} {color}{raw_str:>8}{RESET} {color}{norm_str:>6}{RESET} {tb['count']:>7} {status}")

    # ── Missing task types ──
    seen_types = set(task_best.keys())
    # We don't know the exact 30 types, but we can show what we know
    unseen_from_known = [t for t in KNOWN_TASK_TYPES if t not in seen_types]
    if unseen_from_known:
        print(f"\n  {BOLD}Oppgavetyper vi ikke har truffet ennå:{RESET}")
        for t in sorted(unseen_from_known):
            print(f"    {DIM}• {t}{RESET}")
        print(f"    {DIM}(NB: listen er basert på kjente typer, faktisk sett kan variere){RESET}")

    # ── Improvement opportunities ──
    improvable = {k: v for k, v in task_best.items() if 0 < v["best_norm"] < 1.0}
    if improvable:
        print(f"\n  {BOLD}Forbedringsmuligheter (delvis score):{RESET}")
        for task_type in sorted(improvable.keys(), key=lambda t: improvable[t]["best_norm"]):
            tb = improvable[task_type]
            print(f"    {YELLOW}• {task_type}: {tb['best_norm']:.0%} ({tb['best_raw']:.1f}/{tb['best_max']:.0f}){RESET}")

    failed_types = {k: v for k, v in task_best.items() if v["best_norm"] == 0}
    if failed_types:
        print(f"\n  {BOLD}Feilet oppgaver (0 poeng):{RESET}")
        for task_type in sorted(failed_types.keys()):
            tb = failed_types[task_type]
            print(f"    {RED}• {task_type}: {tb['count']} forsøk{RESET}")

    # ── GCS API efficiency analysis ──
    if gcs_logs:
        print(f"\n{BOLD}{'═'*70}{RESET}")
        print(f"{BOLD}  API-EFFEKTIVITET (fra GCS-logger){RESET}")
        print(f"{BOLD}{'═'*70}{RESET}")

        total_api_calls = 0
        total_4xx = 0
        handler_stats: dict[str, dict] = {}

        for data in gcs_logs:
            task = data.get("parsed_task", {}) or {}
            task_type = task.get("task_type", "unknown")
            api_calls = data.get("api_calls") or []
            n_calls = len(api_calls)
            n_4xx = sum(1 for c in api_calls if 400 <= safe_int(c.get("status")) < 500)
            total_api_calls += n_calls
            total_4xx += n_4xx

            if task_type not in handler_stats:
                handler_stats[task_type] = {
                    "runs": 0, "calls": 0, "errors_4xx": 0,
                    "calls_list": [],
                }
            hs = handler_stats[task_type]
            hs["runs"] += 1
            hs["calls"] += n_calls
            hs["errors_4xx"] += n_4xx
            hs["calls_list"].append(n_calls)

        print(f"\n  Logger analysert:  {len(gcs_logs)}")
        print(f"  Totalt API-kall:   {total_api_calls}")
        print(f"  Totalt 4xx-feil:   {total_4xx}")
        if total_api_calls > 0:
            print(f"  Global feilrate:   {total_4xx/total_api_calls:.0%}")
        if gcs_logs:
            avg_calls = total_api_calls / len(gcs_logs)
            avg_4xx = total_4xx / len(gcs_logs)
            print(f"  Snitt kall/oppgave: {avg_calls:.1f}")
            print(f"  Snitt 4xx/oppgave:  {avg_4xx:.1f}")

        print(f"\n    {'Handler':<25} {'Kjør':>5} {'Kall':>5} {'4xx':>4} {'Snitt':>6} {'Feilr':>6}")
        print(f"    {'─'*60}")
        for task_type in sorted(handler_stats.keys()):
            hs = handler_stats[task_type]
            avg = hs["calls"] / hs["runs"] if hs["runs"] > 0 else 0
            err_rate = hs["errors_4xx"] / hs["calls"] if hs["calls"] > 0 else 0
            err_color = RED if err_rate > 0.2 else (YELLOW if err_rate > 0 else GREEN)
            print(f"    {task_type:<25} {hs['runs']:>5} {hs['calls']:>5} {err_color}{hs['errors_4xx']:>4}{RESET} {avg:>5.1f} {err_color}{err_rate:>5.0%}{RESET}")

        # 4xx details
        if total_4xx > 0 and args.detail:
            print(f"\n  {BOLD}4xx FEIL-DETALJER:{RESET}")
            for data in gcs_logs:
                task = data.get("parsed_task", {}) or {}
                task_type = task.get("task_type", "unknown")
                api_calls = data.get("api_calls") or []
                errors = [c for c in api_calls if 400 <= safe_int(c.get("status")) < 500]
                if errors:
                    print(f"\n    [{task_type}]")
                    for c in errors:
                        path = c.get("path", "?")
                        if len(path) > 45:
                            path = path[:42] + "..."
                        print(f"      {c.get('method','?'):<6} {path:<45} {RED}{safe_int(c.get('status'))}{RESET}")
                        err_body = c.get("response_body") or c.get("error") or ""
                        if err_body:
                            print(f"        {DIM}{str(err_body)[:100]}{RESET}")

    print()


# ──────────────────────────────────────────────
#  submit command
# ──────────────────────────────────────────────

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
            print("\nWaiting for results...")
            time.sleep(5)
            submissions = normalize_submissions(fetch_submissions(client))
            print()
            cmd_status(argparse.Namespace())


def poll_for_result(client: httpx.Client, submission_id: str, max_wait: int = 300) -> None:
    """Poll until submission is complete or timeout."""
    start = time.time()
    interval = 5

    while time.time() - start < max_wait:
        time.sleep(interval)
        elapsed = int(time.time() - start)
        print(f"  ... {elapsed}s", end="\r", flush=True)

        submissions = normalize_submissions(fetch_submissions(client))

        for sub in submissions:
            sid = sub.get("id") or sub.get("submission_id")
            if str(sid) == str(submission_id):
                status = sub.get("status", "")
                if status.lower() in ("completed", "done", "scored", "failed", "error"):
                    print(f"\n\nSubmission {submission_id} ferdig!")
                    norm = safe_float(sub.get("normalized_score"))
                    raw = sub.get("score_raw")
                    mx = sub.get("score_max")
                    dur = safe_int(sub.get("duration_ms"))
                    color = score_color(norm)
                    if raw is not None:
                        print(f"  Score: {color}{safe_int(raw)}/{safe_int(mx)} ({norm:.0%}){RESET}")
                    print(f"  Varighet: {dur/1000:.1f}s")
                    fb = (sub.get("feedback") or {}).get("comment", "")
                    if fb:
                        print(f"  Sjekker: {fb}")
                    return

        interval = min(interval + 2, 15)

    print(f"\n\nTimeout etter {max_wait}s. Sjekk status: python scripts/compete.py status")


# ──────────────────────────────────────────────
#  poll command (watch for new submissions)
# ──────────────────────────────────────────────

def cmd_poll(args: argparse.Namespace) -> None:
    """Watch for new submissions and display results as they come in."""
    interval = args.interval
    max_wait = args.timeout

    print(f"{BOLD}Overvåker nye submissions... (Ctrl+C for å avslutte){RESET}")
    print(f"  Sjekker hvert {interval}. sekund, maks {max_wait//60} minutter.\n")

    seen_ids: set[str] = set()
    last_count = 0

    with make_client() as client:
        # Initial fetch to establish baseline
        submissions = normalize_submissions(fetch_submissions(client))
        for sub in submissions:
            sid = str(sub.get("id") or sub.get("submission_id") or sub.get("queued_at", ""))
            seen_ids.add(sid)
            # Also track pending ones to detect when they complete
        last_count = len(submissions)

        # Track pending submissions
        pending: dict[str, dict] = {}
        for sub in submissions:
            sid = str(sub.get("id") or sub.get("submission_id") or sub.get("queued_at", ""))
            status = (sub.get("status") or "").lower()
            if status in ("queued", "running", "pending", "processing"):
                pending[sid] = sub

        print(f"  Baseline: {len(submissions)} submissions ({len(pending)} under behandling)")
        print()

        start = time.time()
        try:
            while time.time() - start < max_wait:
                time.sleep(interval)
                now = datetime.now().strftime("%H:%M:%S")

                try:
                    submissions = normalize_submissions(fetch_submissions(client))
                except Exception as e:
                    print(f"  {DIM}[{now}] Feil ved henting: {e}{RESET}")
                    continue

                # Check for new submissions
                for sub in submissions:
                    sid = str(sub.get("id") or sub.get("submission_id") or sub.get("queued_at", ""))
                    status = (sub.get("status") or "").lower()

                    if sid not in seen_ids:
                        # New submission
                        seen_ids.add(sid)
                        if status in ("queued", "running", "pending", "processing"):
                            pending[sid] = sub
                            print(f"  {CYAN}[{now}] Ny submission oppdaget (under behandling){RESET}")
                        else:
                            # Already completed
                            _print_poll_result(sub, now)

                    elif sid in pending:
                        # Check if pending submission has completed
                        if status in ("completed", "done", "scored", "failed", "error"):
                            del pending[sid]
                            _print_poll_result(sub, now)

                # Heartbeat
                if len(submissions) == last_count:
                    print(f"  {DIM}[{now}] Ingen endringer ({len(pending)} venter){RESET}", end="\r", flush=True)

                last_count = len(submissions)

        except KeyboardInterrupt:
            print(f"\n\n{BOLD}Overvåking avsluttet.{RESET}")


def _print_poll_result(sub: dict, timestamp: str) -> None:
    """Print a submission result in the poll view."""
    raw = sub.get("score_raw")
    mx = sub.get("score_max")
    norm = safe_float(sub.get("normalized_score"))
    dur = safe_int(sub.get("duration_ms"))
    status = sub.get("status", "?")
    color = score_color(norm if raw is not None else None)
    fb = (sub.get("feedback") or {}).get("comment", "")

    if raw is not None:
        score_str = f"{safe_int(raw)}/{safe_int(mx)} ({norm:.0%})"
    else:
        score_str = status

    print(f"  {color}{BOLD}[{timestamp}] Resultat: {score_str}  ({dur/1000:.1f}s){RESET}")
    if fb:
        print(f"           {fb}")
    print()


# ──────────────────────────────────────────────
#  main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NM i AI competition CLI — Tripletex",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Kommandoer:
  status      Vis submissions og total score
  show N      Vis detaljer for submission #N (1=nyeste)
  insights    Dyp analyse av score og API-effektivitet
  poll        Overvåk nye submissions i sanntid
  submit      Trigger ny submission
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status command
    subparsers.add_parser("status", help="Vis submissions og total score")

    # show command
    show_parser = subparsers.add_parser("show", help="Vis detaljer for en submission")
    show_parser.add_argument(
        "number",
        type=int,
        help="Submission-nummer (1=nyeste)",
    )
    show_parser.add_argument(
        "--translate", "-t",
        action="store_true",
        help="Oversett prompt til norsk (bruker Claude)",
    )

    # submit command
    submit_parser = subparsers.add_parser("submit", help="Trigger ny submission")
    submit_parser.add_argument(
        "--endpoint",
        default=None,
        help=f"Endpoint URL (default: {ENDPOINT_URL})",
    )
    submit_parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Ikke poll for resultat etter submit",
    )

    # insights command
    insights_parser = subparsers.add_parser("insights", help="Analyser score og API-effektivitet")
    insights_parser.add_argument(
        "--detail",
        action="store_true",
        help="Vis detaljerte 4xx-feil",
    )

    # poll command
    poll_parser = subparsers.add_parser("poll", help="Overvåk nye submissions i sanntid")
    poll_parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Sekunder mellom sjekk (default: 10)",
    )
    poll_parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Maks ventetid i sekunder (default: 1800 = 30 min)",
    )

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "submit":
        cmd_submit(args)
    elif args.command == "insights":
        cmd_insights(args)
    elif args.command == "poll":
        cmd_poll(args)


if __name__ == "__main__":
    main()
