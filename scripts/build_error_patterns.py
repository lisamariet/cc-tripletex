#!/usr/bin/env python3
"""
Bygger error_patterns.json fra historiske resultatfiler.

Leser alle data/results/*.json, ekstraher 4xx-feil med validationMessages,
grupperer etter endpoint+method, og lagrer som app/error_patterns.json.
"""

import json
import glob
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "data" / "results"
OUTPUT_FILE = ROOT / "app" / "error_patterns.json"


def normalize_path(path: str) -> str:
    """Normaliser en API-path ved å fjerne IDer og variable."""
    # Erstatt numeriske IDer med {id}
    path = re.sub(r'/\d{5,}', '/{id}', path)
    # Erstatt $PREV_N.value.id-referanser med {id}
    path = re.sub(r'/\$PREV_\d+\.value\.id', '/{id}', path)
    # Fjern None
    path = re.sub(r'/None', '/{id}', path)
    return path


def extract_errors(results_dir: Path) -> list[dict]:
    """Ekstraher alle 4xx-feil fra resultatfiler."""
    errors = []
    files = sorted(glob.glob(str(results_dir / "*.json")))

    for f_path in files:
        with open(f_path) as f:
            data = json.load(f)

        for call in data.get("api_calls", []):
            status = call.get("status", 0)
            if 400 <= status < 500:
                error_body = call.get("error")
                parsed_error = {}
                validation_messages = []
                message = ""

                if error_body:
                    try:
                        parsed_error = json.loads(error_body)
                        message = parsed_error.get("message", "")
                        validation_messages = parsed_error.get("validationMessages") or []
                    except (json.JSONDecodeError, TypeError):
                        message = str(error_body)

                errors.append({
                    "method": call["method"],
                    "path": call["path"],
                    "normalized_path": normalize_path(call["path"]),
                    "status": status,
                    "message": message,
                    "developerMessage": parsed_error.get("developerMessage", ""),
                    "validationMessages": validation_messages,
                })

    return errors


def classify_error(error: dict) -> list[dict]:
    """Klassifiser en feil til ett eller flere mønster."""
    patterns = []
    method = error["method"]
    path = error["normalized_path"]
    status = error["status"]
    message = error["message"]

    if error["validationMessages"]:
        for vm in error["validationMessages"]:
            field = vm.get("field", "")
            msg = vm.get("message", "")
            pattern = {
                "field": field,
                "error_type": _categorize_validation(msg),
                "error_message": msg,
                "fix": _suggest_fix(field, msg, method, path),
                "status": status,
            }
            patterns.append(pattern)
    elif message:
        # Feil uten validationMessages — parse meldingen
        pattern = {
            "field": _extract_field_from_message(message),
            "error_type": _categorize_message(message),
            "error_message": message,
            "fix": _suggest_fix_from_message(message, method, path),
            "status": status,
        }
        patterns.append(pattern)
    else:
        # Feil uten noen info
        patterns.append({
            "field": "",
            "error_type": "unknown",
            "error_message": f"HTTP {status} uten feilmelding",
            "fix": f"Sjekk at endpointet {method} {path} brukes korrekt",
            "status": status,
        })

    return patterns


def _categorize_validation(msg: str) -> str:
    """Kategoriser en validationMessage."""
    if "eksisterer ikke" in msg:
        return "invalid_field"
    if "korrekt type" in msg:
        return "wrong_type"
    if "må fylles ut" in msg:
        return "required_field"
    if "mangler" in msg.lower():
        return "missing_value"
    if "kan ikke" in msg:
        return "business_rule"
    return "validation_error"


def _categorize_message(msg: str) -> str:
    """Kategoriser en feilmelding."""
    if "Illegal field" in msg:
        return "invalid_field_filter"
    if "Wrong data format" in msg:
        return "wrong_data_format"
    if "Object not found" in msg:
        return "not_found"
    if "mapping failed" in msg:
        return "mapping_error"
    return "api_error"


def _extract_field_from_message(msg: str) -> str:
    """Ekstraher feltnavn fra en feilmelding."""
    # "Illegal field in fields filter: amountOutstandingCurrency..."
    m = re.search(r'Illegal field in fields filter: (\w+)', msg)
    if m:
        return m.group(1)
    # "Expected number. For input string: ..."
    m = re.search(r'For input string: "([^"]+)"', msg)
    if m:
        return m.group(1)
    return ""


def _suggest_fix(field: str, msg: str, method: str, path: str) -> str:
    """Generer et fix-forslag basert på feil."""
    if "eksisterer ikke" in msg:
        return f"Fjern feltet '{field}' fra payload — det finnes ikke i API-modellen"
    if "korrekt type" in msg:
        if "id" in field.lower():
            return f"Feltet '{field}' må være et heltall (int), ikke None eller string"
        return f"Sjekk datatypen for '{field}' — forventet type stemmer ikke"
    if "må fylles ut" in msg:
        return f"Feltet '{field}' er påkrevd og må ha en verdi"
    if "mangler" in msg.lower():
        return f"Feltet '{field}' mangler — legg til en gyldig verdi"
    if "kan ikke" in msg:
        return f"Forretningsregel: {msg}"
    return f"Valideringsfeil på '{field}': {msg}"


def _suggest_fix_from_message(msg: str, method: str, path: str) -> str:
    """Generer fix-forslag fra en feilmelding uten validationMessages."""
    if "Illegal field" in msg:
        m = re.search(r'Illegal field in fields filter: (\w+).*model: (\w+)', msg)
        if m:
            return f"Fjern '{m.group(1)}' fra fields-parameteren — finnes ikke i {m.group(2)}"
    if "Wrong data format" in msg:
        return "Bruk riktig ID (int) i URL-path, ikke en string-referanse"
    if "Object not found" in msg:
        return "Objektet finnes ikke — sjekk at IDen er gyldig og at ressursen er opprettet"
    return f"API-feil: {msg}"


def build_patterns(errors: list[dict]) -> dict:
    """Bygg en gruppering av feilmønstre per endpoint."""
    grouped = defaultdict(list)

    for error in errors:
        key = f"{error['method']} {error['normalized_path']}"
        patterns = classify_error(error)
        for p in patterns:
            grouped[key].append(p)

    # Dedupliser: fjern like mønstre innenfor samme endpoint
    result = {}
    for key, patterns in sorted(grouped.items()):
        seen = set()
        unique = []
        for p in patterns:
            sig = (p["field"], p["error_type"], p["error_message"])
            if sig not in seen:
                seen.add(sig)
                unique.append(p)
        result[key] = unique

    return result


def print_stats(patterns: dict):
    """Skriv ut statistikk."""
    total = sum(len(v) for v in patterns.values())
    print(f"\n{'='*60}")
    print(f"Error Pattern Statistikk")
    print(f"{'='*60}")
    print(f"Antall unike endpoints med feil: {len(patterns)}")
    print(f"Totalt antall unike feilmønstre:  {total}")
    print(f"{'='*60}")
    print(f"{'Endpoint':<50} {'Mønstre':>8}")
    print(f"{'-'*50} {'-'*8}")
    for key in sorted(patterns.keys(), key=lambda k: -len(patterns[k])):
        print(f"{key:<50} {len(patterns[key]):>8}")
    print(f"{'='*60}")

    # Vis noen eksempler
    print(f"\nEksempler på feilmønstre:")
    print(f"{'-'*60}")
    for key, pats in sorted(patterns.items()):
        for p in pats[:2]:
            print(f"  {key}")
            print(f"    Type:  {p['error_type']}")
            print(f"    Felt:  {p['field'] or '(ingen)'}")
            print(f"    Feil:  {p['error_message']}")
            print(f"    Fix:   {p['fix']}")
            print()


def main():
    print(f"Leser resultatfiler fra {RESULTS_DIR}...")
    errors = extract_errors(RESULTS_DIR)
    print(f"Fant {len(errors)} 4xx-feil totalt.")

    patterns = build_patterns(errors)
    print_stats(patterns)

    # Lagre
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(patterns, f, indent=2, ensure_ascii=False)
    print(f"\nLagret {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
