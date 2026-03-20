#!/usr/bin/env python3
"""
Local parser test suite for the LLM parser.

Tests parse_task() against:
  1. All logged prompts from data/requests/
  2. Generated prompts for untested task types across 7 languages

Usage:
  python scripts/test_parser.py              # dry-run (default), shows prompts without calling API
  python scripts/test_parser.py --live       # actually calls the Anthropic API
  python scripts/test_parser.py --real-only  # skip generated prompts
  python scripts/test_parser.py --live --real-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import glob
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path so we can import app modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env manually before importing app modules
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.parser import parse_task
from app.models import ParsedTask

# ---------------------------------------------------------------------------
# All supported task types from the parser's SYSTEM_PROMPT
# ---------------------------------------------------------------------------
ALL_TASK_TYPES = [
    "create_supplier",
    "create_customer",
    "create_employee",
    "create_product",
    "create_department",
    "create_invoice",
    "register_payment",
    "reverse_payment",
    "create_credit_note",
    "create_travel_expense",
    "delete_travel_expense",
    "create_project",
    "update_employee",
    "update_customer",
    "create_voucher",
    "reverse_voucher",
    "delete_voucher",
    "update_supplier",
    "update_product",
    "delete_employee",
    "delete_customer",
    "delete_supplier",
    "create_order",
    "register_supplier_invoice",
]

# ---------------------------------------------------------------------------
# Heuristic: guess expected task type from the prompt text
# ---------------------------------------------------------------------------
TASK_HINTS: list[tuple[str, list[str]]] = [
    # Order matters: more specific patterns first, generic ones last.
    # Multi-word patterns checked before single-word ones.
    ("register_supplier_invoice", ["leverandørfaktura", "innkjøpsfaktura", "supplier invoice", "fatura do fornecedor", "lieferantenrechnung", "facture fournisseur"]),
    ("reverse_payment",          ["returnert av banken", "reverse payment", "reverser betaling", "returned by bank", "estorno de pagamento", "stornierung"]),
    ("register_payment",         ["enregistrez le paiement", "registe o pagamento", "register payment", "registrer betaling", "paiement intégral", "pagamento integral", "fatura pendente", "facture impayée", "zahlung registrieren"]),
    ("create_credit_note",       ["kreditnota", "credit note", "nota de crédito", "gutschrift", "reklamert"]),
    ("reverse_voucher",          ["reverser bilag", "reverse voucher", "contrepass"]),
    ("delete_voucher",           ["slett bilag", "delete voucher"]),
    ("create_voucher",           ["bilag", "voucher", "journal entry", "lançamento contabil", "buchungsbeleg", "écriture comptable", "asiento contable", "dimensão contabilística", "dimension comptable"]),
    ("delete_travel_expense",    ["slett reiseregning", "delete travel expense"]),
    ("create_travel_expense",    ["reiseregning", "travel expense", "despesa de viagem", "reisekosten"]),
    ("update_employee",          ["oppdater ansatt", "update employee", "atualizar empregado"]),
    ("update_customer",          ["oppdater kunde", "update customer"]),
    ("update_supplier",          ["oppdater leverandør", "update supplier", "aktualisieren sie den lieferanten", "mettez à jour le fournisseur", "actualice el proveedor", "atualize o fornecedor"]),
    ("update_product",           ["oppdater produkt", "update product", "aktualisieren sie das produkt", "mettez à jour le produit", "actualice el producto", "atualize o produto"]),
    ("delete_employee",          ["slett ansatt", "slett den tilsette", "delete employee", "elimine al empleado", "supprimez l'employé", "löschen sie den mitarbeiter", "exclua o empregado"]),
    ("delete_customer",          ["slett kunde", "delete customer", "elimine al cliente", "supprimez le client", "löschen sie den kunden", "exclua o cliente"]),
    ("delete_supplier",          ["slett leverandør", "delete supplier", "elimine al proveedor", "supprimez le fournisseur", "löschen sie den lieferanten", "exclua o fornecedor"]),
    ("create_order",             ["auftrag", "bestilling", "pedido", "commande", "create an order", "opprett en ordre", "opprett ein ordre"]),
    ("create_project",           ["prosjekt", "project", "proyecto", "projet", "projeto", "projekt"]),
    ("create_invoice",           ["opprett ein faktura", "opprett en faktura", "créez et envoyez une facture", "create invoice", "erstellen sie eine rechnung", "crie uma fatura"]),
    ("create_department",        ["department", "avdeling"]),
    ("create_employee",          ["employé", "tilsett", "ansatt", "employee", "empregado", "mitarbeiter", "angestellte", "gehaltsabrechnung"]),
    ("create_product",           ["produkt", "product", "producto", "produit"]),
    ("create_supplier",          ["proveedor", "supplier", "leverandør", "fornecedor", "lieferant", "fournisseur"]),
    ("create_customer",          ["opprett kunden", "opprett kunde", "create customer", "registrer kunden"]),
]


def guess_expected_type(prompt: str) -> str | None:
    """Best-effort guess of the expected task type from prompt keywords."""
    lower = prompt.lower()

    # Special cases: "test" prompts -> unknown is acceptable
    stripped = lower.strip()
    if stripped in ("test", "test oppgave"):
        return "unknown"

    # Reverse payment must be checked before register_payment
    for task_type, keywords in TASK_HINTS:
        for kw in keywords:
            if kw in lower:
                return task_type
    return None


# ---------------------------------------------------------------------------
# Key-field expectations per task type
# ---------------------------------------------------------------------------
EXPECTED_FIELDS: dict[str, list[str]] = {
    "create_supplier":          ["name"],
    "create_customer":          ["name"],
    "create_employee":          ["firstName", "lastName"],
    "create_product":           ["name"],
    "create_department":        ["name"],
    "create_invoice":           ["customerName"],
    "register_payment":         ["customerName"],
    "reverse_payment":          ["customerName"],
    "create_credit_note":       ["customerName"],
    "create_travel_expense":    ["employeeName"],
    "delete_travel_expense":    ["employeeName"],
    "create_project":           ["name"],
    "update_employee":          ["employeeName"],
    "update_customer":          ["customerName"],
    "create_voucher":           ["description"],
    "reverse_voucher":          ["voucherNumber"],
    "delete_voucher":           ["voucherNumber"],
    "update_supplier":          ["supplierName"],
    "update_product":           ["productName"],
    "delete_employee":          ["employeeName"],
    "delete_customer":          ["customerName"],
    "delete_supplier":          ["supplierName"],
    "create_order":             ["customerName"],
    "register_supplier_invoice": ["supplierName"],
}


# ---------------------------------------------------------------------------
# Generated prompts for missing task types (7 languages each)
# ---------------------------------------------------------------------------
GENERATED_PROMPTS: dict[str, list[tuple[str, str]]] = {
    "update_supplier": [
        ("nb", 'Oppdater leverandøren Fjordteknikk AS (org.nr 912345678) med ny e-post: faktura@fjordteknikk.no og nytt telefonnummer 99887766.'),
        ("en", 'Update the supplier Northwave Ltd (org no. 949044378) with the new email billing@northwave.co.uk and phone +44 20 7946 0958.'),
        ("es", 'Actualice el proveedor Dorada SL (nº org. 853166553) con el nuevo correo electrónico facturacion@doradasl.es y dirección Calle Mayor 10, Madrid.'),
        ("fr", 'Mettez à jour le fournisseur Lumière SA (nº org. 901234567) avec le nouvel e-mail commandes@lumiere.fr.'),
        ("de", 'Aktualisieren Sie den Lieferanten Waldstein GmbH (Org.-Nr. 975687821) mit der neuen E-Mail einkauf@waldstein.de.'),
        ("pt", 'Atualize o fornecedor Luz do Sol Lda (org. nº 939210970) com o novo e-mail compras@luzdosol.pt.'),
        ("nn", 'Oppdater leverandøren Fjordteknikk AS (org.nr 912345678) med ny e-post: faktura@fjordteknikk.no.'),
    ],
    "update_product": [
        ("nb", 'Oppdater produktet "Konsulenttimer" (produktnummer 9497) med ny pris 18500 kr eksklusiv MVA.'),
        ("en", 'Update the product "Cloud Storage" (product number 2001) with a new price of 12000 NOK excluding VAT.'),
        ("es", 'Actualice el producto "Servicio de red" (número de producto 4366) con un nuevo precio de 15000 NOK sin IVA.'),
        ("fr", 'Mettez à jour le produit "Hébergement web" (numéro de produit 3050) avec un nouveau prix de 9500 NOK HT.'),
        ("de", 'Aktualisieren Sie das Produkt "Orangensaft" (Produktnummer 1256) mit einem neuen Preis von 18000 NOK ohne MwSt.'),
        ("pt", 'Atualize o produto "Manutenção" (número do produto 5010) com um novo preço de 22000 NOK sem IVA.'),
        ("nn", 'Oppdater produktet "Konsulenttimar" (produktnummer 9497) med ny pris 19000 kr eksklusiv MVA.'),
    ],
    "delete_employee": [
        ("nb", 'Slett ansatt Bjørn Neset fra systemet.'),
        ("en", 'Delete employee John Smith from the system.'),
        ("es", 'Elimine al empleado Carlos Martínez del sistema.'),
        ("fr", "Supprimez l'employé Pierre Dupont du système."),
        ("de", 'Löschen Sie den Mitarbeiter Hans Müller aus dem System.'),
        ("pt", 'Exclua o empregado João Silva do sistema.'),
        ("nn", 'Slett den tilsette Bjørn Neset frå systemet.'),
    ],
    "delete_customer": [
        ("nb", 'Slett kunden Bølgekraft AS (org.nr 988957747) fra Tripletex.'),
        ("en", 'Delete the customer Northwave Ltd (org no. 950072652) from the system.'),
        ("es", 'Elimine al cliente Montaña SL (nº org. 876543210) del sistema.'),
        ("fr", 'Supprimez le client Colline SARL (nº org. 944164340) du système.'),
        ("de", 'Löschen Sie den Kunden Waldstein GmbH (Org.-Nr. 975687821) aus dem System.'),
        ("pt", 'Exclua o cliente Floresta Lda (org. nº 916058896) do sistema.'),
        ("nn", 'Slett kunden Bølgekraft AS (org.nr 988957747) frå systemet.'),
    ],
    "delete_supplier": [
        ("nb", 'Slett leverandøren Fjordteknikk AS (org.nr 912345678) fra systemet.'),
        ("en", 'Delete the supplier Northwave Ltd (org no. 949044378) from the system.'),
        ("es", 'Elimine al proveedor Dorada SL (nº org. 853166553) del sistema.'),
        ("fr", 'Supprimez le fournisseur Lumière SA (nº org. 901234567) du système.'),
        ("de", 'Löschen Sie den Lieferanten Waldstein GmbH (Org.-Nr. 975687821) aus dem System.'),
        ("pt", 'Exclua o fornecedor Luz do Sol Lda (org. nº 939210970) do sistema.'),
        ("nn", 'Slett leverandøren Fjordteknikk AS (org.nr 912345678) frå systemet.'),
    ],
    "create_order": [
        ("nb", 'Opprett en ordre for kunden Bølgekraft AS (org.nr 988957747) med produktet Webdesign til 27000 kr ekskl. MVA, leveringsdato 2026-04-15.'),
        ("en", 'Create an order for the customer Northwave Ltd (org no. 950072652) with product Network Service at 15000 NOK excl. VAT, delivery date 2026-04-20.'),
        ("es", 'Cree un pedido para el cliente Montaña SL (nº org. 876543210) con el producto Servicio de consultoría a 20000 NOK sin IVA.'),
        ("fr", 'Créez une commande pour le client Colline SARL (nº org. 944164340) avec le produit Hébergement web à 9500 NOK HT.'),
        ("de", 'Erstellen Sie einen Auftrag für den Kunden Waldstein GmbH (Org.-Nr. 975687821) mit dem Produkt Netzwerkdienst zu 15000 NOK ohne MwSt.'),
        ("pt", 'Crie um pedido para o cliente Floresta Lda (org. nº 916058896) com o produto Manutenção a 22000 NOK sem IVA.'),
        ("nn", 'Opprett ein ordre for kunden Bølgekraft AS (org.nr 988957747) med produktet Webdesign til 27000 kr ekskl. MVA.'),
    ],
    "register_supplier_invoice": [
        ("nb", 'Registrer en leverandørfaktura fra Fjordteknikk AS (org.nr 912345678) på 45000 kr for "Kontorrekvisita", fakturadato 2026-03-15.'),
        ("en", 'Register a supplier invoice from Northwave Ltd (org no. 949044378) for 30000 NOK for "Office supplies", invoice date 2026-03-10.'),
        ("es", 'Registre una factura de proveedor de Dorada SL (nº org. 853166553) por 25000 NOK por "Material de oficina", fecha de factura 2026-03-12.'),
        ("fr", 'Enregistrez une facture fournisseur de Lumière SA (nº org. 901234567) de 35000 NOK pour "Fournitures de bureau", date de facture 2026-03-14.'),
        ("de", 'Registrieren Sie eine Lieferantenrechnung von Waldstein GmbH (Org.-Nr. 975687821) über 28000 NOK für "Bürobedarf", Rechnungsdatum 2026-03-11.'),
        ("pt", 'Registe uma fatura do fornecedor Luz do Sol Lda (org. nº 939210970) de 20000 NOK por "Material de escritório", data da fatura 2026-03-13.'),
        ("nn", 'Registrer ein leverandørfaktura frå Fjordteknikk AS (org.nr 912345678) på 40000 kr for "Kontorrekvisita", fakturadato 2026-03-15.'),
    ],
    "create_voucher": [
        ("nb", 'Opprett et bilag med beskrivelse "Husleie mars 2026", dato 2026-03-01. Debet konto 6300 og kredit konto 1920, beløp 15000 kr.'),
        ("en", 'Create a voucher with description "March rent 2026", date 2026-03-01. Debit account 6300, credit account 1920, amount 15000 NOK.'),
        ("es", 'Cree un asiento contable con la descripción "Alquiler marzo 2026", fecha 2026-03-01. Débito cuenta 6300, crédito cuenta 1920, importe 15000 NOK.'),
        ("fr", 'Créez une écriture comptable avec la description "Loyer mars 2026", date 2026-03-01. Débit compte 6300, crédit compte 1920, montant 15000 NOK.'),
        ("de", 'Erstellen Sie einen Buchungsbeleg mit der Beschreibung "Miete März 2026", Datum 2026-03-01. Soll Konto 6300, Haben Konto 1920, Betrag 15000 NOK.'),
        ("pt", 'Crie um lançamento contabilístico com a descrição "Renda março 2026", data 2026-03-01. Débito conta 6300, crédito conta 1920, valor 15000 NOK.'),
        ("nn", 'Opprett eit bilag med skildring "Husleige mars 2026", dato 2026-03-01. Debet konto 6300 og kredit konto 1920, beløp 15000 kr.'),
    ],
    "reverse_voucher": [
        ("nb", 'Reverser bilag nummer 1042, dato 2026-03-05.'),
        ("en", 'Reverse voucher number 1042, dated 2026-03-05.'),
        ("es", 'Revierta el asiento contable número 1042, fecha 2026-03-05.'),
        ("fr", 'Contrepassez le voucher numéro 1042, daté du 2026-03-05.'),
        ("de", 'Stornieren Sie den Buchungsbeleg Nummer 1042, Datum 2026-03-05.'),
        ("pt", 'Reverta o lançamento contabilístico número 1042, data 2026-03-05.'),
        ("nn", 'Reverser bilag nummer 1042, dato 2026-03-05.'),
    ],
    "delete_voucher": [
        ("nb", 'Slett bilag nummer 1055, dato 2026-03-10.'),
        ("en", 'Delete voucher number 1055, dated 2026-03-10.'),
        ("es", 'Elimine el asiento contable número 1055, fecha 2026-03-10.'),
        ("fr", 'Supprimez le voucher numéro 1055, daté du 2026-03-10.'),
        ("de", 'Löschen Sie den Buchungsbeleg Nummer 1055, Datum 2026-03-10.'),
        ("pt", 'Exclua o lançamento contabilístico número 1055, data 2026-03-10.'),
        ("nn", 'Slett bilag nummer 1055, dato 2026-03-10.'),
    ],
}


# ---------------------------------------------------------------------------
# Result row
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    source: str           # REAL or GENERATED
    prompt_snippet: str   # first 60 chars
    expected_type: str
    parsed_type: str
    match: str            # MATCH / MISMATCH / SKIP (dry-run)
    confidence: float
    key_fields: str       # comma-separated found fields
    lang: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_real_prompts() -> list[dict[str, Any]]:
    """Load all request JSON files, returning list of {file, prompt, expected_type}."""
    results = []
    req_dir = PROJECT_ROOT / "data" / "requests"
    for fpath in sorted(req_dir.glob("*.json")):
        with open(fpath) as f:
            data = json.load(f)
        prompt = data.get("prompt", "")
        expected = guess_expected_type(prompt)
        results.append({
            "file": fpath.name,
            "prompt": prompt,
            "expected_type": expected,
        })
    return results


def get_seen_task_types() -> set[str]:
    """Determine which task types already appear in data/results/."""
    seen: set[str] = set()
    results_dir = PROJECT_ROOT / "data" / "results"
    for fpath in results_dir.glob("*.json"):
        with open(fpath) as f:
            data = json.load(f)
        pt = data.get("parsed_task")
        if pt:
            tt = pt.get("task_type", "")
            if tt and tt != "unknown":
                seen.add(tt)
    return seen


def check_key_fields(task_type: str, fields: dict) -> list[str]:
    """Return list of expected key fields that are present in parsed fields."""
    expected = EXPECTED_FIELDS.get(task_type, [])
    found = []
    for k in expected:
        if k in fields and fields[k]:
            found.append(k)
    # Also report any other non-empty fields
    for k, v in fields.items():
        if v and k not in found:
            found.append(k)
    return found


def run_parse(prompt: str, live: bool) -> ParsedTask | None:
    """Run parse_task if live, otherwise return None."""
    if not live:
        return None
    return parse_task(prompt)


def format_table(results: list[TestResult]) -> str:
    """Format results as an aligned table."""
    headers = ["Source", "Lang", "Prompt (first 60 chars)", "Expected", "Parsed", "Match", "Conf", "Key Fields Found"]
    rows = []
    for r in results:
        rows.append([
            r.source,
            r.lang,
            r.prompt_snippet[:60],
            r.expected_type,
            r.parsed_type,
            r.match,
            f"{r.confidence:.2f}" if r.confidence >= 0 else "-",
            r.key_fields or "-",
        ])

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt_row(headers), "-+-".join("-" * w for w in widths)]
    for row in rows:
        lines.append(fmt_row(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test the LLM parser against logged and generated prompts.")
    parser.add_argument("--live", action="store_true", help="Actually call the Anthropic API (costs money). Default is dry-run.")
    parser.add_argument("--real-only", action="store_true", help="Only test real prompts from data/requests/, skip generated.")
    parser.add_argument("--dry-run", action="store_true", help="Show prompts without calling API (this is the default).")
    args = parser.parse_args()

    live = args.live and not args.dry_run

    if live:
        print("=== LIVE MODE: will call the Anthropic API ===\n")
    else:
        print("=== DRY-RUN MODE: showing prompts without calling API ===")
        print("    Use --live to actually call the API.\n")

    real_prompts = load_real_prompts()
    seen_types = get_seen_task_types()
    test_results: list[TestResult] = []
    real_failures = 0

    # --- Part 1: Real prompts ---
    print(f"--- Testing {len(real_prompts)} REAL prompts from data/requests/ ---\n")
    for rp in real_prompts:
        prompt = rp["prompt"]
        expected = rp["expected_type"] or "?"
        snippet = prompt[:60].replace("\n", " ")

        if live:
            try:
                result = parse_task(prompt)
                parsed_type = result.task_type
                confidence = result.confidence
                fields_found = check_key_fields(parsed_type, result.fields)
                fields_str = ", ".join(fields_found) if fields_found else "-"

                # Determine match
                if expected == "?":
                    match_str = "OK (no expectation)"
                elif expected == "unknown" and parsed_type == "unknown":
                    match_str = "MATCH"
                elif expected == "unknown" and parsed_type != "unknown":
                    match_str = "OK (parsed better than expected)"
                elif parsed_type == expected:
                    match_str = "MATCH"
                elif parsed_type.replace("batch_", "") == expected:
                    match_str = "MATCH (batch)"
                else:
                    match_str = "MISMATCH"
                    real_failures += 1
            except Exception as e:
                parsed_type = f"ERROR: {e}"
                confidence = -1
                fields_str = "-"
                match_str = "ERROR"
                real_failures += 1
        else:
            parsed_type = "(dry-run)"
            confidence = -1
            fields_str = "(dry-run)"
            match_str = "SKIP"

        test_results.append(TestResult(
            source="REAL",
            prompt_snippet=snippet,
            expected_type=expected,
            parsed_type=parsed_type,
            match=match_str,
            confidence=confidence,
            key_fields=fields_str,
            lang="",
        ))

    # --- Part 2: Generated prompts ---
    if not args.real_only:
        # Determine which task types need generated prompts
        missing_types = set(GENERATED_PROMPTS.keys()) - seen_types
        # Always include all generated types for completeness
        gen_types = sorted(GENERATED_PROMPTS.keys())

        total_gen = sum(len(v) for v in GENERATED_PROMPTS.values())
        print(f"\n--- Testing {total_gen} GENERATED prompts for {len(gen_types)} task types ---")
        print(f"    Task types already seen in results: {sorted(seen_types)}")
        print(f"    Generated types (always tested): {gen_types}\n")

        for task_type in gen_types:
            prompts = GENERATED_PROMPTS[task_type]
            for lang, prompt in prompts:
                snippet = prompt[:60].replace("\n", " ")

                if live:
                    try:
                        result = parse_task(prompt)
                        parsed_type = result.task_type
                        confidence = result.confidence
                        fields_found = check_key_fields(parsed_type, result.fields)
                        fields_str = ", ".join(fields_found) if fields_found else "-"
                        match_str = "MATCH" if parsed_type == task_type else "MISMATCH"
                    except Exception as e:
                        parsed_type = f"ERROR: {e}"
                        confidence = -1
                        fields_str = "-"
                        match_str = "ERROR"
                else:
                    parsed_type = "(dry-run)"
                    confidence = -1
                    fields_str = "(dry-run)"
                    match_str = "SKIP"

                test_results.append(TestResult(
                    source="GENERATED",
                    prompt_snippet=snippet,
                    expected_type=task_type,
                    parsed_type=parsed_type,
                    match=match_str,
                    confidence=confidence,
                    key_fields=fields_str,
                    lang=lang,
                ))

    # --- Output ---
    print("\n" + "=" * 120)
    print("RESULTS")
    print("=" * 120 + "\n")
    print(format_table(test_results))

    # Summary
    total = len(test_results)
    real_count = sum(1 for r in test_results if r.source == "REAL")
    gen_count = sum(1 for r in test_results if r.source == "GENERATED")
    matches = sum(1 for r in test_results if "MATCH" in r.match)
    mismatches = sum(1 for r in test_results if r.match == "MISMATCH")
    errors = sum(1 for r in test_results if r.match == "ERROR")
    skips = sum(1 for r in test_results if r.match == "SKIP")

    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Total tests:    {total} ({real_count} real, {gen_count} generated)")
    print(f"  Matches:        {matches}")
    print(f"  Mismatches:     {mismatches}")
    print(f"  Errors:         {errors}")
    print(f"  Skipped (dry):  {skips}")
    print(f"  Real failures:  {real_failures}")

    if live:
        if real_failures > 0:
            print(f"\nFAILED: {real_failures} real prompt(s) did not parse correctly.")
            sys.exit(1)
        else:
            print(f"\nPASSED: All real prompts parsed correctly.")
            sys.exit(0)
    else:
        print(f"\nDRY-RUN complete. Use --live to actually call the API.")
        sys.exit(0)


if __name__ == "__main__":
    main()
