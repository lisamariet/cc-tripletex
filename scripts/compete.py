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

from typing import Any

import httpx
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

API_BASE = "https://api.ainm.no"
ENDPOINT_URL = "https://tripletex-agent-753459644453.europe-west1.run.app"
TASK_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"  # Tripletex challenge task ID
OUR_TEAM_ID = "ecfa24d3-9b1b-4ef2-a164-8568cf17839e"
SOLVE_PATH = "/solve"

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
    """Check if text is likely not Norwegian or English.

    Uses distinct words unlikely to appear in other languages (especially
    German, which shares many short words with Norwegian like 'den', 'for',
    'med', 'kunden').  Requires at least 2 matches to avoid false negatives.
    """
    # Words that are distinctly Norwegian (not shared with German/other langs)
    norwegian_distinct = {
        "opprett", "og", "fra", "skal", "det", "har", "som", "ikke",
        "denne", "kunde", "ansatt", "faktura", "bestilling", "produkt",
        "leverandør", "betaling", "registrer", "konverter", "ordre",
    }
    # Words that are distinctly English
    english_distinct = {
        "create", "the", "with", "and", "from", "customer", "employee",
        "invoice", "order", "product", "convert", "payment", "register",
    }
    words = set(text.lower().split()[:30])
    no_hits = len(words & norwegian_distinct)
    en_hits = len(words & english_distinct)
    if no_hits >= 2:
        return False
    if en_hits >= 2:
        return False
    return True


def _translate_prompt(prompt: str) -> str | None:
    """Translate a prompt to Norwegian using Google Translate (free, no key needed),
    with Anthropic Claude as fallback."""
    # Strategy 1: Google Translate via deep-translator (free, fast)
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="auto", target="no").translate(prompt)
        if result and result.strip():
            return result.strip()
    except Exception:
        pass

    # Strategy 2: Anthropic Claude API
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
    """Load logs from local data/ directory (fast) with optional GCS sync.
    log_type: 'results' or 'requests'
    """
    local_dir = PROJECT_ROOT / "data" / log_type
    if not local_dir.exists():
        return []

    logs = []
    for f in sorted(local_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            data["_local_path"] = str(f)
            logs.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return logs


def sync_gcs_data() -> None:
    """Sync GCS data to local data/ directory."""
    subprocess.run(
        ["gsutil", "-m", "rsync", "gs://tripletex-agent-requests/results/", str(PROJECT_ROOT / "data" / "results/")],
        capture_output=True, text=True,
    )
    subprocess.run(
        ["gsutil", "-m", "rsync", "gs://tripletex-agent-requests/requests/", str(PROJECT_ROOT / "data" / "requests/")],
        capture_output=True, text=True,
    )


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


def _infer_task_type_from_prompt(prompt: str) -> str | None:
    """Infer task type from prompt keywords when parser returned unknown."""
    import re
    pl = prompt.lower()
    # Order matters: more specific patterns first
    patterns = [
        ("fastpris|fixed price|prix fix|precio fijo|festpreis|preço fix|prix forfait", "set_project_fixed_price"),
        ("dimensjon|dimension|dimensão|dimensión", "create_custom_dimension"),
        ("lønn|payroll|salário|gehalt|salaire|nómina|gehaltsabrechnung", "run_payroll"),
        ("timesheet|timer for|horas para|stunden für|heures pour|registrer.*timer|erfassen.*stunden", "register_timesheet"),
        ("tre.*avdeling|three.*department|tres departamento|drei abteilung|trois département|três departamento", "batch_create_department"),
        ("ordre|order|pedido|auftrag|commande|encomenda", "create_order"),
        ("reiseregning|travel.?expense|gastos de viaje|nota de gastos|frais de voyage|reisekosten|despesas de viagem|Reisekostenabrechnung", "create_travel_expense"),
        ("kreditnota|credit note|nota de crédito|avoir|gutschrift", "create_credit_note"),
        ("reverser.*betal|reverse.*payment|revertir.*pago|annuler.*paiement|stornieren.*zahlung", "reverse_payment"),
        ("registrer.*betal|register.*payment|registrar.*pago|enregistrer.*paiement|zahlung.*registr", "register_payment"),
        ("leverandørfaktura|supplier invoice|factura.*proveedor|facture.*fournisseur|lieferantenrechnung|fatura.*fornecedor", "register_supplier_invoice"),
        ("faktura|invoice|factura|facture|rechnung|fatura", "create_invoice"),
        ("prosjekt|project|proyecto|projet|projekt|projeto", "create_project"),
        ("ansatt|employee|empleado|employé|mitarbeiter|empregado", "create_employee"),
        ("kunde|customer|cliente|client|kund", "create_customer"),
        ("leverandør|supplier|proveedor|fournisseur|lieferant|fornecedor", "create_supplier"),
        ("produkt|product|producto|produit|produkt|produto", "create_product"),
        ("avdeling|department|departamento|département|abteilung", "create_department"),
    ]
    for pattern, task_type in patterns:
        if re.search(pattern, pl):
            return task_type
    return None


def get_task_type_for_sub(sub: dict, gcs_logs: list[dict], request_logs: list[dict] | None = None) -> str:
    """Find task type from GCS logs for a submission.

    Returns the task_type if known. If unknown, infers from prompt keywords.
    """
    sub_ts = sub.get("queued_at") or sub.get("created_at") or ""
    if not sub_ts:
        return "?"
    try:
        dt_sub = datetime.fromisoformat(sub_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return "?"

    best_type = "?"
    best_delta = timedelta(minutes=10)
    best_log = None

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
                best_log = log
        except Exception:
            continue

    # If task_type is still unknown, infer from prompt keywords
    if best_type in ("?", "", "unknown"):
        prompt = None
        if best_log:
            prompt = best_log.get("prompt", "")
        if not prompt:
            prompt = _get_prompt_for_sub(sub, gcs_logs, request_logs)
        if prompt:
            inferred = _infer_task_type_from_prompt(prompt)
            if inferred:
                return inferred
            # Last resort: show snippet
            snippet = prompt.replace("\n", " ").strip()[:30]
            return f"[{snippet}...]"

    return best_type


def _get_prompt_for_sub(sub: dict, gcs_logs: list[dict], request_logs: list[dict] | None = None) -> str | None:
    """Find prompt text for a submission from GCS logs (result or request)."""
    sub_ts = sub.get("queued_at") or sub.get("created_at") or ""
    if not sub_ts:
        return None
    try:
        dt_sub = datetime.fromisoformat(sub_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

    best_prompt = None
    best_delta = timedelta(minutes=10)

    # Check all log sources for a prompt
    all_logs = list(gcs_logs)
    if request_logs:
        all_logs.extend(request_logs)

    for log in all_logs:
        log_ts = log.get("timestamp", "")
        if not log_ts:
            continue
        try:
            dt_log = datetime.strptime(log_ts[:15], "%Y%m%d_%H%M%S")
            delta = abs(dt_log - dt_sub)
            if delta < best_delta:
                prompt = log.get("prompt", "")
                if prompt:
                    best_delta = delta
                    best_prompt = prompt
        except Exception:
            continue

    return best_prompt


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
    # Always sync GCS data so task types are available
    sync_gcs_data()
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
    gcs_requests = []
    try:
        gcs_logs = fetch_gcs_logs("results")
    except Exception:
        pass
    try:
        gcs_requests = fetch_gcs_logs("requests")
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
        task_type = get_task_type_for_sub(sub, gcs_logs, gcs_requests) if (gcs_logs or gcs_requests) else "?"

        # Track best per task type (for real task types, including keyword-inferred)
        if task_type != "?" and not task_type.startswith("["):
            current_best = best_scores.get(task_type, 0.0)
            score_val = safe_float(sub.get("normalized_score")) or 0.0
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

    # ANSI italic
    ITALIC = "\033[3m"

    for i, sub in enumerate(submissions[:25], 1):
        ts = format_ts_short(sub.get("queued_at"))
        raw = sub.get("score_raw")
        mx = sub.get("score_max")
        norm = sub.get("normalized_score")
        duration = safe_int(sub.get("duration_ms"))
        status = sub.get("status", "-")
        task_type = get_task_type_for_sub(sub, gcs_logs, gcs_requests) if (gcs_logs or gcs_requests) else "?"

        # Format task type: dim+italic for prompt snippets
        if task_type.startswith("["):
            task_display = f"{DIM}{ITALIC}{task_type[:25]}{RESET}"
            task_visible = task_type[:25]
        else:
            task_display = task_type[:25]
            task_visible = task_type[:25]

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

        # Pad task_display to 25 visible chars (compensate for ANSI if present)
        task_pad = 25 - len(task_visible)
        task_col = task_display + " " * max(0, task_pad)

        print(f"  {i:>3}  {ts:<10} {task_col} {score_display} {dur_str:>8}  {status}")


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

    # Sync and fetch GCS logs
    print("Synkroniserer data...")
    sync_gcs_data()
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

    # Task type from GCS log
    task_type = get_task_type_for_sub(sub, gcs_logs, gcs_requests)

    print(f"  Tidspunkt:  {ts}")
    print(f"  Oppgave:    {CYAN}{task_type}{RESET}")
    print(f"  Status:     {status}")
    if raw is not None:
        norm_f = safe_float(norm)
        color = score_color(norm_f)
        print(f"  Score:      {color}{safe_int(raw)}/{safe_int(mx)} ({norm_f:.0%}){RESET}")
    else:
        print(f"  Score:      {DIM}(ikke ferdig){RESET}")
    print(f"  Varighet:   {duration / 1000:.1f}s" if duration else "  Varighet:   -")

    # ── Prompt (show early for context) ──
    prompt = None
    if req_log:
        prompt = req_log.get("prompt", "")
    if not prompt and log:
        prompt = log.get("prompt", "")

    if prompt:
        print(f"\n  {BOLD}Prompt:{RESET}")
        for line in prompt.split("\n"):
            print(f"    {line}")

        if _needs_translation(prompt):
            translated = _translate_prompt(prompt)
            if translated:
                print(f"\n  {BOLD}Oversettelse:{RESET}")
                for line in translated.split("\n"):
                    print(f"    {DIM}{line}{RESET}")

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

                detail = getattr(args, "detail", False)

                # Show query params if present
                qp = call.get("query_params")
                qp_str = f"  ?{qp}" if qp and detail else ""
                print(f"    {j:>3}  {method:<7} {path:<42} {color}{status_code:>6}{RESET} {dur:>6.0f}ms{DIM}{qp_str}{RESET}")

                if detail:
                    # Show request body
                    req_body = call.get("request_body")
                    if req_body:
                        import json as _json
                        body_str = _json.dumps(req_body, ensure_ascii=False)[:500]
                        print(f"         {DIM}→ {body_str}{RESET}")

                    # Show response body (all calls in detail mode)
                    if 400 <= status_code < 500:
                        error_body = call.get("response_body") or call.get("error") or ""
                        if error_body:
                            print(f"         {RED}← {str(error_body)[:500]}{RESET}")
                    elif call.get("response_body"):
                        print(f"         {DIM}← {str(call['response_body'])[:300]}{RESET}")
                else:
                    # Without --detail: only show 4xx errors
                    if 400 <= status_code < 500:
                        error_body = call.get("response_body") or call.get("error") or ""
                        if error_body:
                            print(f"         {RED}{str(error_body)[:120]}{RESET}")

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

    # ── Build handler stats map from GCS logs (needed for tables) ──
    handler_stats_map: dict[str, dict] = {}
    if gcs_logs:
        for data in gcs_logs:
            task = data.get("parsed_task", {}) or {}
            task_type = task.get("task_type", "unknown")
            # Resolve unknowns from prompt
            if task_type in ("unknown", "?", ""):
                prompt = data.get("prompt", "")
                if prompt:
                    inferred = _infer_task_type_from_prompt(prompt)
                    if inferred:
                        task_type = inferred
            api_calls = data.get("api_calls") or []
            n_calls = len(api_calls)
            n_4xx = sum(1 for c in api_calls if 400 <= safe_int(c.get("status")) < 500)
            if task_type not in handler_stats_map:
                handler_stats_map[task_type] = {"runs": 0, "calls": 0, "errors_4xx": 0, "calls_list": []}
            hs = handler_stats_map[task_type]
            hs["runs"] += 1
            hs["calls"] += n_calls
            hs["errors_4xx"] += n_4xx
            hs["calls_list"].append(n_calls)

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

    # ── Collect ALL known task types (from KNOWN_TASK_TYPES, registered handlers, GCS logs, and submissions) ──
    all_task_types: set[str] = set(KNOWN_TASK_TYPES)
    try:
        from app.handlers import HANDLER_REGISTRY
        all_task_types.update(k for k in HANDLER_REGISTRY.keys() if k != "unknown")
    except ImportError:
        pass
    all_task_types.update(task_best.keys())
    all_task_types.update(handler_stats_map.keys())
    # Remove noise entries
    all_task_types.discard("?")
    all_task_types.discard("")
    all_task_types.discard("unknown")

    # Ensure all task types have entries in task_best (fill with zeros for unseen)
    for tt in all_task_types:
        if tt not in task_best:
            task_best[tt] = {
                "best_raw": 0, "best_max": 0, "best_norm": 0, "count": 0,
                "scores": [],
            }

    # ── Per-task-type table (sorted by best score descending, then alpha) ──
    print(f"\n  {BOLD}Beste score per oppgavetype (sortert etter score):{RESET}")
    print(f"    {'Oppgavetype':<28} {'Beste':>8} {'Norm':>6} {'Forsøk':>7} {'Snitt 4xx':>10} {'Status'}")
    print(f"    {'─'*80}")

    # Sort by best_norm descending, then alphabetically
    sorted_tasks = sorted(task_best.keys(), key=lambda t: (-task_best[t]["best_norm"], t))

    for task_type in sorted_tasks:
        tb = task_best[task_type]
        norm = tb["best_norm"]
        color = score_color(norm)

        if tb["count"] == 0:
            raw_str = "-"
            norm_str = "-"
        else:
            raw_str = f"{tb['best_raw']:.1f}/{tb['best_max']:.0f}"
            norm_str = f"{norm:.0%}"

        # Get 4xx stats from GCS logs for this task type
        avg_4xx_str = "-"
        hs = handler_stats_map.get(task_type)
        if hs and hs["runs"] > 0:
            avg_4xx = hs["errors_4xx"] / hs["runs"]
            avg_4xx_str = f"{avg_4xx:.1f}"

        if tb["count"] == 0:
            status = f"{DIM}ikke testet{RESET}"
        elif norm >= 1.0:
            status = f"{GREEN}perfekt{RESET}"
        elif norm > 0:
            status = f"{YELLOW}kan forbedres{RESET}"
        else:
            status = f"{RED}feilet{RESET}"

        print(f"    {task_type:<28} {color}{raw_str:>8}{RESET} {color}{norm_str:>6}{RESET} {tb['count']:>7} {avg_4xx_str:>10} {status}")

    print(f"    {'─'*80}")
    print(f"    {BOLD}Totalt: {len(sorted_tasks)} oppgavetyper{RESET}")

    # ── Improvement opportunities ──
    improvable = {k: v for k, v in task_best.items() if 0 < v["best_norm"] < 1.0}
    if improvable:
        print(f"\n  {BOLD}Forbedringsmuligheter (delvis score):{RESET}")
        for task_type in sorted(improvable.keys(), key=lambda t: improvable[t]["best_norm"]):
            tb = improvable[task_type]
            print(f"    {YELLOW}• {task_type}: {tb['best_norm']:.0%} ({tb['best_raw']:.1f}/{tb['best_max']:.0f}){RESET}")

    failed_types = {k: v for k, v in task_best.items() if v["best_norm"] == 0 and v["count"] > 0}
    if failed_types:
        print(f"\n  {BOLD}Feilet oppgaver (0 poeng, med forsøk):{RESET}")
        for task_type in sorted(failed_types.keys()):
            tb = failed_types[task_type]
            print(f"    {RED}• {task_type}: {tb['count']} forsøk{RESET}")

    # ── GCS API efficiency analysis ──
    if gcs_logs and handler_stats_map:
        print(f"\n{BOLD}{'═'*70}{RESET}")
        print(f"{BOLD}  API-EFFEKTIVITET (fra GCS-logger){RESET}")
        print(f"{BOLD}{'═'*70}{RESET}")

        total_api_calls = sum(hs["calls"] for hs in handler_stats_map.values())
        total_4xx = sum(hs["errors_4xx"] for hs in handler_stats_map.values())
        total_runs = sum(hs["runs"] for hs in handler_stats_map.values())

        print(f"\n  Logger analysert:  {total_runs}")
        print(f"  Totalt API-kall:   {total_api_calls}")
        print(f"  Totalt 4xx-feil:   {total_4xx}")
        if total_api_calls > 0:
            print(f"  Global feilrate:   {total_4xx/total_api_calls:.0%}")
        if total_runs > 0:
            print(f"  Snitt kall/oppgave: {total_api_calls / total_runs:.1f}")
            print(f"  Snitt 4xx/oppgave:  {total_4xx / total_runs:.1f}")

        print(f"\n    {'Handler':<28} {'Kjør':>5} {'Kall':>5} {'4xx':>4} {'Snitt':>6} {'Feilr':>6}")
        print(f"    {'─'*60}")
        # Sort by error rate descending (highest first)
        sorted_handlers = sorted(
            handler_stats_map.keys(),
            key=lambda t: (handler_stats_map[t]["errors_4xx"] / handler_stats_map[t]["calls"] if handler_stats_map[t]["calls"] > 0 else 0),
            reverse=True,
        )
        for task_type in sorted_handlers:
            hs = handler_stats_map[task_type]
            avg = hs["calls"] / hs["runs"] if hs["runs"] > 0 else 0
            err_rate = hs["errors_4xx"] / hs["calls"] if hs["calls"] > 0 else 0
            err_color = RED if err_rate > 0.2 else (YELLOW if err_rate > 0 else GREEN)
            print(f"    {task_type:<28} {hs['runs']:>5} {hs['calls']:>5} {err_color}{hs['errors_4xx']:>4}{RESET} {avg:>5.1f} {err_color}{err_rate:>5.0%}{RESET}")

        # 4xx details
        if total_4xx > 0 and args.detail:
            print(f"\n  {BOLD}4xx FEIL-DETALJER:{RESET}")
            for data in gcs_logs:
                task = data.get("parsed_task", {}) or {}
                task_type = task.get("task_type", "unknown")
                if task_type in ("unknown", "?", ""):
                    prompt = data.get("prompt", "")
                    if prompt:
                        inferred = _infer_task_type_from_prompt(prompt)
                        if inferred:
                            task_type = inferred
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
    api_key = os.environ.get("API_KEY", "")

    with make_client() as client:
        print(f"Submitting: {endpoint}")

        payload: dict[str, Any] = {
            "endpoint_url": f"{endpoint}{SOLVE_PATH}",
        }
        if api_key:
            payload["endpoint_api_key"] = api_key

        resp = client.post(f"{API_BASE}/tasks/{TASK_ID}/submissions", json=payload)

        if not resp.is_success:
            print(f"Submit feilet ({resp.status_code}): {resp.text}")
            return

        result = resp.json()
        sub_id = result.get("id", "?")
        used = result.get("daily_submissions_used", "?")
        max_sub = result.get("daily_submissions_max", "?")
        print(f"  Submission: {sub_id}")
        print(f"  Status: {result.get('status', '?')}")
        print(f"  Daglig forbruk: {used}/{max_sub}")

        submission_id = result.get("id")
        if submission_id and not args.no_poll:
            print("\nPoller for resultat...")
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
#  compare command
# ──────────────────────────────────────────────

def cmd_compare(args: argparse.Namespace) -> None:
    """Compare our task scores with the #1 team on the leaderboard."""
    with make_client() as client:
        # 1. Fetch leaderboard to find #1 team
        print("Henter leaderboard...")
        resp_lb = client.get(f"{API_BASE}/tripletex/leaderboard")
        resp_lb.raise_for_status()
        leaderboard = resp_lb.json()

        # Sort by total score descending to find #1
        if isinstance(leaderboard, list):
            lb_sorted = sorted(leaderboard, key=lambda t: safe_float(t.get("total_score", 0)), reverse=True)
        else:
            print(f"{RED}Uventet leaderboard-format{RESET}")
            return

        if not lb_sorted:
            print("Tomt leaderboard.")
            return

        top_team = lb_sorted[0]
        top_team_id = top_team.get("team_id") or top_team.get("id", "")
        top_team_name = top_team.get("team_name") or top_team.get("name", "ukjent")
        top_team_score = safe_float(top_team.get("total_score", 0))

        # Find our placement
        our_placement = "?"
        our_total_from_lb = 0.0
        our_team_name = "oss"
        for i, team in enumerate(lb_sorted, 1):
            tid = team.get("team_id") or team.get("id", "")
            if tid == OUR_TEAM_ID:
                our_placement = str(i)
                our_total_from_lb = safe_float(team.get("total_score", 0))
                our_team_name = team.get("team_name") or team.get("name", "oss")
                break

        # 2. Fetch task details for both teams
        print(f"Henter task-detaljer for oss ({our_team_name})...")
        resp_us = client.get(f"{API_BASE}/tripletex/leaderboard/{OUR_TEAM_ID}")
        resp_us.raise_for_status()
        our_tasks = resp_us.json()

        print(f"Henter task-detaljer for #1 ({top_team_name})...")
        resp_top = client.get(f"{API_BASE}/tripletex/leaderboard/{top_team_id}")
        resp_top.raise_for_status()
        top_tasks = resp_top.json()

    # Build lookup dicts: tx_task_id -> {best_score, total_attempts}
    our_map: dict[str, dict] = {}
    if isinstance(our_tasks, list):
        for t in our_tasks:
            tid = t.get("tx_task_id", "")
            if tid:
                our_map[tid] = t
    elif isinstance(our_tasks, dict):
        for t in our_tasks.get("tasks", our_tasks.get("data", [])):
            tid = t.get("tx_task_id", "")
            if tid:
                our_map[tid] = t

    top_map: dict[str, dict] = {}
    if isinstance(top_tasks, list):
        for t in top_tasks:
            tid = t.get("tx_task_id", "")
            if tid:
                top_map[tid] = t
    elif isinstance(top_tasks, dict):
        for t in top_tasks.get("tasks", top_tasks.get("data", [])):
            tid = t.get("tx_task_id", "")
            if tid:
                top_map[tid] = t

    # Merge all task IDs
    all_task_ids = sorted(set(list(our_map.keys()) + list(top_map.keys())))

    # Build comparison rows
    rows = []
    sum_ours = 0.0
    sum_top = 0.0
    for tid in all_task_ids:
        our_score = safe_float((our_map.get(tid) or {}).get("best_score", 0))
        top_score = safe_float((top_map.get(tid) or {}).get("best_score", 0))
        our_attempts = safe_int((our_map.get(tid) or {}).get("total_attempts", 0))
        top_attempts = safe_int((top_map.get(tid) or {}).get("total_attempts", 0))
        gap = our_score - top_score
        sum_ours += our_score
        sum_top += top_score

        # Use short task ID (last 2 digits or first meaningful part)
        short_id = tid[-2:] if len(tid) >= 2 else tid

        rows.append({
            "task_id": short_id,
            "full_id": tid,
            "our_score": our_score,
            "top_score": top_score,
            "gap": gap,
            "our_attempts": our_attempts,
            "top_attempts": top_attempts,
        })

    # Sort by gap ascending (biggest negative gap first = most to gain)
    rows.sort(key=lambda r: r["gap"])

    # Print output
    total_gap = sum_ours - sum_top

    print()
    print(f"{BOLD}  SAMMENLIGNING MED #1 ({top_team_name} — {top_team_score:.2f} poeng){RESET}")
    print(f"  {DIM}Vi er #{our_placement} ({our_team_name} — {sum_ours:.2f} poeng){RESET}")
    print()
    print(f"  {'Task':<6} {'Vår score':>10} {'#1 score':>10} {'Gap':>8} {'Forsøk':>10}")
    print(f"  {'─' * 50}")

    for row in rows:
        gap = row["gap"]
        if gap > 0.001:
            color = GREEN
        elif gap < -0.001:
            color = RED
        else:
            color = GREEN

        gap_str = f"{gap:+.2f}"
        attempts_str = f"{row['our_attempts']}/{row['top_attempts']}"

        print(f"  {color}{row['task_id']:<6} {row['our_score']:>10.4f} {row['top_score']:>10.4f} {gap_str:>8} {attempts_str:>10}{RESET}")

    print(f"  {'─' * 50}")

    # Sum line
    sum_gap = sum_ours - sum_top
    if sum_gap > 0.001:
        color = GREEN
    elif sum_gap < -0.001:
        color = RED
    else:
        color = GREEN
    print(f"  {color}{BOLD}{'Sum':<6} {sum_ours:>10.2f} {sum_top:>10.2f} {sum_gap:>+8.2f}{RESET}")
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
  compare     Sammenlign task-score med #1 på leaderboard
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
        "--detail",
        action="store_true",
        help="Vis full request/response body for alle API-kall (debug trace)",
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

    # compare command
    subparsers.add_parser("compare", help="Sammenlign task-score med #1 på leaderboard")

    # errors command
    subparsers.add_parser("errors", help="Detaljert 4xx-feilanalyse fra logger")

    # batch command
    batch_parser = subparsers.add_parser("batch", help="Submit N ganger med pause mellom")
    batch_parser.add_argument("count", type=int, help="Antall submissions")
    batch_parser.add_argument("--interval", type=int, default=60,
                              help="Sekunder mellom submissions (default: 60)")
    batch_parser.add_argument("--max-concurrent", type=int, default=3,
                              help="Maks samtidige submissions (default: 3)")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "submit":
        cmd_submit(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "insights":
        cmd_insights(args)
    elif args.command == "errors":
        cmd_errors(args)
    elif args.command == "poll":
        cmd_poll(args)
    elif args.command == "compare":
        cmd_compare(args)


# ──────────────────────────────────────────────
#  errors command (4xx analysis)
# ──────────────────────────────────────────────

def cmd_errors(args: argparse.Namespace) -> None:
    """Detailed 4xx error analysis from GCS logs."""
    sync_gcs_data()
    gcs_logs = fetch_gcs_logs("results")

    if not gcs_logs:
        print("Ingen logger funnet.")
        return

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    # Collect all 4xx errors
    all_errors: list[dict] = []
    for data in gcs_logs:
        task = data.get("parsed_task", {}) or {}
        task_type = task.get("task_type", "unknown")
        if task_type in ("unknown", "?", ""):
            prompt = data.get("prompt", "")
            if prompt:
                inferred = _infer_task_type_from_prompt(prompt)
                if inferred:
                    task_type = inferred

        log_ts = data.get("timestamp", "")
        try:
            dt_log = datetime.strptime(log_ts[:15], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            dt_log = None

        for call in data.get("api_calls", []):
            status = safe_int(call.get("status"))
            if 400 <= status < 500:
                error_body = call.get("error") or call.get("response_body") or ""
                error_str = str(error_body)[:500]
                # Extract validationMessages from 422 responses
                validation_msgs: list[str] = []
                if status == 422:
                    raw = call.get("error") or call.get("response_body")
                    if isinstance(raw, dict):
                        for vm in (raw.get("validationMessages") or []):
                            msg_text = vm.get("message", "") if isinstance(vm, dict) else str(vm)
                            field = vm.get("field", "") if isinstance(vm, dict) else ""
                            if field:
                                validation_msgs.append(f"{field}: {msg_text}")
                            elif msg_text:
                                validation_msgs.append(msg_text)
                    elif isinstance(raw, str):
                        try:
                            import json as _json
                            parsed = _json.loads(raw)
                            for vm in (parsed.get("validationMessages") or []):
                                msg_text = vm.get("message", "") if isinstance(vm, dict) else str(vm)
                                field = vm.get("field", "") if isinstance(vm, dict) else ""
                                if field:
                                    validation_msgs.append(f"{field}: {msg_text}")
                                elif msg_text:
                                    validation_msgs.append(msg_text)
                        except (ValueError, AttributeError):
                            pass
                all_errors.append({
                    "task_type": task_type,
                    "method": call.get("method", "?"),
                    "path": call.get("path", "?"),
                    "status": status,
                    "error": error_str,
                    "validation_msgs": validation_msgs,
                    "timestamp": dt_log,
                    "recent": dt_log and dt_log > one_hour_ago if dt_log else False,
                })

    if not all_errors:
        print(f"\n  {GREEN}Ingen 4xx-feil funnet! 🎉{RESET}")
        return

    recent_errors = [e for e in all_errors if e["recent"]]

    print()
    print(f"{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  4xx FEILANALYSE{RESET}")
    print(f"{BOLD}{'═'*70}{RESET}")
    print(f"\n  Totalt 4xx-feil:     {len(all_errors)}")
    print(f"  Siste timen:         {len(recent_errors)}")
    print(f"  Logger analysert:    {len(gcs_logs)}")

    # Group by endpoint
    by_endpoint: dict[str, list] = {}
    for e in all_errors:
        key = f"{e['method']} {e['path']}"
        by_endpoint.setdefault(key, []).append(e)

    print(f"\n  {BOLD}Per endpoint (sortert etter antall):{RESET}")
    print(f"    {'Endpoint':<45} {'Totalt':>6} {'Siste t':>8} {'Status'}")
    print(f"    {'─'*70}")
    for endpoint in sorted(by_endpoint.keys(), key=lambda k: -len(by_endpoint[k])):
        errors = by_endpoint[endpoint]
        recent = sum(1 for e in errors if e["recent"])
        statuses = sorted(set(e["status"] for e in errors))
        recent_color = RED if recent > 0 else DIM
        print(f"    {endpoint:<45} {len(errors):>6} {recent_color}{recent:>8}{RESET} {statuses}")

    # Group by task type
    by_task: dict[str, list] = {}
    for e in all_errors:
        by_task.setdefault(e["task_type"], []).append(e)

    print(f"\n  {BOLD}Per oppgavetype:{RESET}")
    print(f"    {'Oppgavetype':<28} {'Totalt':>6} {'Siste t':>8}")
    print(f"    {'─'*50}")
    for task_type in sorted(by_task.keys(), key=lambda k: -len(by_task[k])):
        errors = by_task[task_type]
        recent = sum(1 for e in errors if e["recent"])
        recent_color = RED if recent > 0 else DIM
        print(f"    {task_type:<28} {len(errors):>6} {recent_color}{recent:>8}{RESET}")

    # Group by error message
    by_msg: dict[str, int] = {}
    for e in all_errors:
        msg = e["error"][:500] if e["error"] else "(ingen feilmelding)"
        by_msg[msg] = by_msg.get(msg, 0) + 1

    print(f"\n  {BOLD}Vanligste feilmeldinger:{RESET}")
    for msg, count in sorted(by_msg.items(), key=lambda x: -x[1])[:15]:
        print(f"    {RED}{count:>3}x{RESET} {msg}")

    # Show recent errors in detail
    if recent_errors:
        print(f"\n  {BOLD}Siste timens feil (detaljer):{RESET}")
        for e in sorted(recent_errors, key=lambda x: x["timestamp"] or datetime.min, reverse=True)[:20]:
            ts = e["timestamp"].strftime("%H:%M:%S") if e["timestamp"] else "?"
            print(f"    {RED}[{ts}]{RESET} {e['method']} {e['path']} → {e['status']}  [{e['task_type']}]")
            if e["error"]:
                print(f"           {DIM}{e['error'][:500]}{RESET}")
            if e.get("validation_msgs"):
                for vm in e["validation_msgs"]:
                    print(f"           {RED}↳ {vm}{RESET}")

    print()


def _count_active_submissions(client: httpx.Client) -> int:
    """Count submissions currently queued or running (not completed or failed)."""
    try:
        resp = client.get(f"{API_BASE}/tasks/{TASK_ID}/submissions")
        if not resp.is_success:
            return 0
        subs = resp.json()
        if isinstance(subs, dict):
            subs = subs.get("data", subs.get("submissions", []))
        active = [s for s in subs if s.get("status") not in ("completed", "failed", "error")]
        return len(active)
    except Exception:
        return 0


def _wait_for_capacity(client: httpx.Client, max_concurrent: int, wait_s: int = 30, max_retries: int = 10) -> bool:
    """Wait until active submission count is below max_concurrent. Returns True if capacity available."""
    for attempt in range(max_retries):
        active = _count_active_submissions(client)
        if active < max_concurrent:
            return True
        print(f"  {YELLOW}Aktive submissions: {active}/{max_concurrent} — venter {wait_s}s (forsøk {attempt+1}/{max_retries})...{RESET}")
        time.sleep(wait_s)
    return False


def cmd_batch(args: argparse.Namespace) -> None:
    """Submit multiple times with interval between each."""
    count = args.count
    interval = args.interval
    max_concurrent = getattr(args, "max_concurrent", 3)
    endpoint = ENDPOINT_URL
    api_key = os.environ.get("API_KEY", "")

    print(f"{BOLD}Batch submit: {count} submissions, {interval}s mellom hver, maks {max_concurrent} samtidige{RESET}\n")

    with make_client() as client:
        for i in range(count):
            # Throttle: wait if too many active submissions
            if not _wait_for_capacity(client, max_concurrent):
                print(f"  {RED}[{i+1}/{count}] Tidsavbrudd — for mange aktive submissions. Avbryter.{RESET}")
                break

            payload: dict[str, Any] = {"endpoint_url": f"{endpoint}{SOLVE_PATH}"}
            if api_key:
                payload["endpoint_api_key"] = api_key

            resp = client.post(f"{API_BASE}/tasks/{TASK_ID}/submissions", json=payload)

            if not resp.is_success:
                print(f"  {RED}[{i+1}/{count}] Feilet ({resp.status_code}): {resp.text[:100]}{RESET}")
                if resp.status_code == 429:
                    print(f"  Rate limit — venter 60s...")
                    time.sleep(60)
                continue

            result = resp.json()
            used = result.get("daily_submissions_used", "?")
            max_sub = result.get("daily_submissions_max", "?")
            print(f"  {GREEN}[{i+1}/{count}]{RESET} {result.get('id','?')[:8]}... "
                  f"status={result.get('status','?')} ({used}/{max_sub} brukt)")

            if i < count - 1:
                print(f"  Venter {interval}s...", end="\r", flush=True)
                time.sleep(interval)

    print(f"\n{BOLD}Ferdig. Sjekk resultater: python3 scripts/compete.py status{RESET}")


if __name__ == "__main__":
    main()
