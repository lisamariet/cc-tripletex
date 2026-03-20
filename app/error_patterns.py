"""
Error Pattern Learning — lærer av tidligere 4xx-feil og forhindrer gjentakelse.

Eksporterte funksjoner:
  - get_known_errors(endpoint, method) -> list[dict]
  - check_payload(endpoint, method, payload) -> list[str]
  - record_error(endpoint, method, status_code, error_body, payload)
  - get_fix_suggestions(endpoint, method, error_message) -> list[str]
"""

import json
import re
import atexit
from pathlib import Path
from collections import defaultdict
from typing import Any

_PATTERNS_FILE = Path(__file__).resolve().parent / "error_patterns.json"

# In-memory database — lastes fra fil + utvides ved runtime
_patterns: dict[str, list[dict]] = {}
_runtime_errors: list[dict] = []
_loaded = False


def _normalize_path(path: str) -> str:
    """Normaliser en API-path ved å fjerne IDer og variable."""
    path = re.sub(r'/\d{5,}', '/{id}', path)
    path = re.sub(r'/\$PREV_\d+\.value\.\w+', '/{id}', path)
    path = re.sub(r'/None', '/{id}', path)
    return path


def _make_key(endpoint: str, method: str) -> str:
    """Lag en nøkkel for oppslag."""
    norm = _normalize_path(endpoint)
    return f"{method.upper()} {norm}"


def _ensure_loaded():
    """Last patterns fra fil hvis ikke allerede gjort."""
    global _patterns, _loaded
    if _loaded:
        return
    _loaded = True
    if _PATTERNS_FILE.exists():
        try:
            with open(_PATTERNS_FILE, "r", encoding="utf-8") as f:
                _patterns = json.load(f)
        except (json.JSONDecodeError, OSError):
            _patterns = {}
    else:
        _patterns = {}


def _save_patterns():
    """Lagre oppdaterte patterns til fil (kalles ved shutdown)."""
    if not _runtime_errors:
        return
    _ensure_loaded()
    # Merge runtime-feil inn i patterns
    for err in _runtime_errors:
        key = err["key"]
        pattern = err["pattern"]
        if key not in _patterns:
            _patterns[key] = []
        # Sjekk om mønsteret allerede finnes
        sig = (pattern.get("field", ""), pattern.get("error_type", ""),
               pattern.get("error_message", ""))
        existing_sigs = {
            (p.get("field", ""), p.get("error_type", ""), p.get("error_message", ""))
            for p in _patterns[key]
        }
        if sig not in existing_sigs:
            _patterns[key].append(pattern)
    try:
        with open(_PATTERNS_FILE, "w", encoding="utf-8") as f:
            json.dump(_patterns, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# Registrer save ved shutdown
atexit.register(_save_patterns)


def get_known_errors(endpoint: str, method: str) -> list[dict]:
    """
    Hent kjente feilmønstre for et gitt endpoint og method.

    Returns:
        Liste av dicts med keys: field, error_type, error_message, fix, status
    """
    _ensure_loaded()
    key = _make_key(endpoint, method)
    # Prøv eksakt match først
    if key in _patterns:
        return _patterns[key]
    # Prøv å matche med normalisert path
    for k, v in _patterns.items():
        if k == key:
            return v
    return []


def check_payload(endpoint: str, method: str, payload: dict) -> list[str]:
    """
    Sjekk en payload mot kjente feilmønstre og returner advarsler.

    Returns:
        Liste av advarsel-strenger, f.eks.:
        "ADVARSEL: POST /order krever customer.id som int — funnet None"
    """
    _ensure_loaded()
    warnings = []
    known = get_known_errors(endpoint, method)
    key = _make_key(endpoint, method)

    for pattern in known:
        field = pattern.get("field", "")
        error_type = pattern.get("error_type", "")

        if not field:
            # Generisk feil uten spesifikt felt
            continue

        if error_type == "invalid_field":
            # Sjekk om payload inneholder et felt som ikke skal være der
            if _field_exists_in_payload(field, payload):
                warnings.append(
                    f"ADVARSEL: {key} — feltet '{field}' bør fjernes fra payload "
                    f"({pattern['error_message']})"
                )

        elif error_type == "wrong_type":
            # Sjekk om feltet har feil type
            value = _get_field_value(field, payload)
            if value is not None and not isinstance(value, int):
                if "id" in field.lower():
                    warnings.append(
                        f"ADVARSEL: {key} — '{field}' må være int, "
                        f"funnet {type(value).__name__}: {value}"
                    )
            elif value is None and _field_exists_in_payload(field, payload):
                warnings.append(
                    f"ADVARSEL: {key} — '{field}' er None, "
                    f"men må ha en gyldig verdi ({pattern['fix']})"
                )

        elif error_type == "required_field":
            # Sjekk om et påkrevd felt mangler
            if not _field_exists_in_payload(field, payload):
                warnings.append(
                    f"ADVARSEL: {key} — påkrevd felt '{field}' mangler i payload"
                )

        elif error_type == "missing_value":
            # Sjekk om feltet mangler verdi
            value = _get_field_value(field, payload)
            if value is None:
                warnings.append(
                    f"ADVARSEL: {key} — '{field}' mangler verdi ({pattern['fix']})"
                )

    return warnings


def record_error(
    endpoint: str,
    method: str,
    status_code: int,
    error_body: str | dict | None,
    payload: dict | None = None,
):
    """
    Registrer en ny feil for runtime-læring.

    Lagrer feilen i minnet og oppdaterer JSON-filen ved shutdown.
    """
    _ensure_loaded()
    key = _make_key(endpoint, method)

    # Parse error body
    parsed = {}
    if isinstance(error_body, str):
        try:
            parsed = json.loads(error_body)
        except (json.JSONDecodeError, TypeError):
            parsed = {"message": error_body}
    elif isinstance(error_body, dict):
        parsed = error_body

    message = parsed.get("message", "")
    validation_msgs = parsed.get("validationMessages") or []

    if validation_msgs:
        for vm in validation_msgs:
            field = vm.get("field", "")
            msg = vm.get("message", "")
            pattern = {
                "field": field,
                "error_type": _categorize_validation(msg),
                "error_message": msg,
                "fix": _suggest_fix(field, msg),
                "status": status_code,
            }
            _runtime_errors.append({"key": key, "pattern": pattern})
            # Legg til i in-memory patterns umiddelbart
            if key not in _patterns:
                _patterns[key] = []
            _patterns[key].append(pattern)
    elif message:
        pattern = {
            "field": _extract_field_from_message(message),
            "error_type": _categorize_message(message),
            "error_message": message,
            "fix": _suggest_fix_from_message(message),
            "status": status_code,
        }
        _runtime_errors.append({"key": key, "pattern": pattern})
        if key not in _patterns:
            _patterns[key] = []
        _patterns[key].append(pattern)
    else:
        pattern = {
            "field": "",
            "error_type": "unknown",
            "error_message": f"HTTP {status_code} uten feilmelding",
            "fix": f"Sjekk at {method} {endpoint} brukes korrekt",
            "status": status_code,
        }
        _runtime_errors.append({"key": key, "pattern": pattern})
        if key not in _patterns:
            _patterns[key] = []
        _patterns[key].append(pattern)


def get_fix_suggestions(
    endpoint: str, method: str, error_message: str
) -> list[str]:
    """
    Hent fix-forslag basert på endpoint, method og feilmelding.

    Matcher mot kjente feilmønstre og returnerer relevante fix-strenger.
    """
    _ensure_loaded()
    suggestions = []
    known = get_known_errors(endpoint, method)

    for pattern in known:
        pm = pattern.get("error_message", "")
        # Eksakt match eller delvis match
        if pm and (pm in error_message or error_message in pm
                   or _similar_messages(pm, error_message)):
            suggestions.append(pattern["fix"])

    # Fjern duplikater, behold rekkefølge
    seen = set()
    unique = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return unique


# --- Hjelpefunksjoner ---

def _field_exists_in_payload(field_path: str, payload: dict) -> bool:
    """Sjekk om et felt (med punktnotasjon) finnes i payload."""
    if not payload or not field_path:
        return False
    parts = field_path.split(".")
    current: Any = payload
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            # Sjekk i alle elementer
            found = False
            for item in current:
                if isinstance(item, dict) and part in item:
                    current = item[part]
                    found = True
                    break
            if not found:
                return False
        else:
            return False
    return True


def _get_field_value(field_path: str, payload: dict) -> Any:
    """Hent verdien av et felt (med punktnotasjon) fra payload."""
    if not payload or not field_path:
        return None
    parts = field_path.split(".")
    current: Any = payload
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, dict) and part in item:
                    current = item[part]
                    break
            else:
                return None
        else:
            return None
    return current


def _similar_messages(a: str, b: str) -> bool:
    """Enkel likhetskontroll mellom feilmeldinger."""
    # Fjern variable deler (IDer, tall) og sammenlign
    def normalize(s):
        s = re.sub(r'\d+', 'N', s)
        s = re.sub(r'["\']', '', s)
        return s.lower().strip()
    return normalize(a) == normalize(b)


def _categorize_validation(msg: str) -> str:
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
    if "Illegal field" in msg:
        return "invalid_field_filter"
    if "Wrong data format" in msg:
        return "wrong_data_format"
    if "Object not found" in msg:
        return "not_found"
    return "api_error"


def _extract_field_from_message(msg: str) -> str:
    m = re.search(r'Illegal field in fields filter: (\w+)', msg)
    if m:
        return m.group(1)
    m = re.search(r'For input string: "([^"]+)"', msg)
    if m:
        return m.group(1)
    return ""


def _suggest_fix(field: str, msg: str) -> str:
    if "eksisterer ikke" in msg:
        return f"Fjern feltet '{field}' fra payload — finnes ikke i API-modellen"
    if "korrekt type" in msg:
        if "id" in field.lower():
            return f"'{field}' må være int, ikke None eller string"
        return f"Sjekk datatypen for '{field}'"
    if "må fylles ut" in msg:
        return f"'{field}' er påkrevd — legg til en gyldig verdi"
    if "mangler" in msg.lower():
        return f"'{field}' mangler — sett en gyldig verdi"
    if "kan ikke" in msg:
        return f"Forretningsregel: {msg}"
    return f"Valideringsfeil: {msg}"


def _suggest_fix_from_message(msg: str) -> str:
    if "Illegal field" in msg:
        m = re.search(r'Illegal field in fields filter: (\w+).*model: (\w+)', msg)
        if m:
            return f"Fjern '{m.group(1)}' fra fields — finnes ikke i {m.group(2)}"
    if "Wrong data format" in msg:
        return "Bruk riktig ID (int) i URL-path, ikke en string-referanse"
    if "Object not found" in msg:
        return "Objektet finnes ikke — sjekk at IDen er gyldig"
    return f"API-feil: {msg}"
