"""OpenAPI-based payload validator for the Tripletex API.

Loads the OpenAPI spec at module import and provides field-name validation
for POST/PUT request bodies.  Uses fuzzy matching (difflib) to suggest
correct field names when a typo or wrong name is detected.

Usage:
    from app.api_validator import validate_payload

    errors = validate_payload("POST", "/supplier", {"naame": "Acme"})
    # -> ["Field 'naame' is not valid on Supplier. Did you mean 'name'?"]
"""
from __future__ import annotations

import json
import logging
import os
from difflib import get_close_matches
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load OpenAPI spec once at module import
# ---------------------------------------------------------------------------

_SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "tripletex-openapi.json"

_spec: dict[str, Any] = {}
_schema_lookup: dict[str, dict[str, set[str]]] = {}  # (method, path) -> {schema_name, fields}


def _load_spec() -> dict[str, Any]:
    """Load and return the OpenAPI spec from disk."""
    if not _SPEC_PATH.exists():
        logger.warning(f"OpenAPI spec not found at {_SPEC_PATH}")
        return {}
    with open(_SPEC_PATH) as f:
        return json.load(f)


def _resolve_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a $ref like '#/components/schemas/Supplier' to the actual schema dict."""
    parts = ref.lstrip("#/").split("/")
    obj = spec
    for part in parts:
        obj = obj.get(part, {})
    return obj


def _extract_schema_fields(schema: dict[str, Any], spec: dict[str, Any], depth: int = 0) -> set[str]:
    """Extract all top-level property names from a schema, resolving $ref."""
    if depth > 3:
        return set()

    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], spec)

    # Handle allOf / oneOf / anyOf by merging properties
    for combiner in ("allOf", "oneOf", "anyOf"):
        if combiner in schema:
            fields: set[str] = set()
            for sub in schema[combiner]:
                fields |= _extract_schema_fields(sub, spec, depth + 1)
            # Also include direct properties if present
            fields |= set(schema.get("properties", {}).keys())
            return fields

    return set(schema.get("properties", {}).keys())


def _schema_name_from_ref(ref: str) -> str:
    """Extract the schema name from a $ref string.  e.g. '#/components/schemas/Supplier' -> 'Supplier'."""
    return ref.rsplit("/", 1)[-1] if "/" in ref else ref


def _build_lookup(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Build a lookup of (METHOD, path_pattern) -> {schema_name, fields, nested_schemas}.

    For each POST/PUT endpoint with a requestBody, extract the schema reference,
    resolve it, and store the set of valid top-level field names.
    Also stores nested object schemas so we can validate nested payloads.
    """
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    paths = spec.get("paths", {})
    components = spec.get("components", {}).get("schemas", {})

    for path, methods in paths.items():
        for method_lower in ("post", "put"):
            method_spec = methods.get(method_lower)
            if not method_spec or "requestBody" not in method_spec:
                continue

            content = method_spec["requestBody"].get("content", {})
            # Try both content types Tripletex uses
            schema_obj = None
            for ct in ("application/json; charset=utf-8", "application/json"):
                if ct in content:
                    schema_obj = content[ct].get("schema", {})
                    break
            if schema_obj is None:
                continue

            # Handle array wrapping (e.g. POST /activity/list)
            if schema_obj.get("type") == "array" and "items" in schema_obj:
                schema_obj = schema_obj["items"]

            ref = schema_obj.get("$ref", "")
            if not ref:
                continue

            schema_name = _schema_name_from_ref(ref)
            fields = _extract_schema_fields(schema_obj, spec)

            # Build nested schema map: field_name -> set of valid sub-fields
            nested: dict[str, tuple[str, set[str]]] = {}
            resolved = _resolve_ref(ref, spec)
            for prop_name, prop_def in resolved.get("properties", {}).items():
                nested_ref = prop_def.get("$ref")
                if not nested_ref and prop_def.get("type") == "array":
                    items = prop_def.get("items", {})
                    nested_ref = items.get("$ref")
                if nested_ref:
                    nested_name = _schema_name_from_ref(nested_ref)
                    nested_fields = _extract_schema_fields({"$ref": nested_ref}, spec)
                    if nested_fields:
                        nested[prop_name] = (nested_name, nested_fields)

            method_upper = method_lower.upper()
            lookup[(method_upper, path)] = {
                "schema_name": schema_name,
                "fields": fields,
                "nested": nested,
            }

    return lookup


# Eagerly load at import time
try:
    _spec = _load_spec()
    _schema_lookup = _build_lookup(_spec)
    logger.info(f"OpenAPI validator loaded: {len(_schema_lookup)} endpoint schemas indexed")
except Exception as exc:
    logger.warning(f"Failed to load OpenAPI spec for validation: {exc}")
    _spec = {}
    _schema_lookup = {}


# ---------------------------------------------------------------------------
# Path matching helpers
# ---------------------------------------------------------------------------

def _normalize_path(path: str) -> str:
    """Normalize an actual request path to match spec patterns.

    Converts concrete paths like '/supplier/123' to '/supplier/{id}'.
    Strips the /v2 prefix if present.
    """
    if path.startswith("/v2"):
        path = path[3:]

    parts = path.strip("/").split("/")
    normalized: list[str] = []
    for part in parts:
        if part.isdigit():
            normalized.append("{id}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


def _find_matching_schema(method: str, path: str) -> dict[str, Any] | None:
    """Find the schema entry for a given method+path, handling path params."""
    method = method.upper()
    path = _normalize_path(path)

    # Direct match
    entry = _schema_lookup.get((method, path))
    if entry:
        return entry

    # Try matching with path parameter patterns from the spec
    for (m, spec_path), entry in _schema_lookup.items():
        if m != method:
            continue
        # Convert spec pattern like /supplier/{id} to regex-matchable form
        pattern_parts = spec_path.strip("/").split("/")
        path_parts = path.strip("/").split("/")
        if len(pattern_parts) != len(path_parts):
            continue
        match = True
        for pp, rp in zip(pattern_parts, path_parts):
            if pp.startswith("{") and pp.endswith("}"):
                continue  # wildcard
            if pp != rp:
                match = False
                break
        if match:
            return entry

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_payload(method: str, path: str, payload: dict[str, Any] | None) -> list[str]:
    """Validate a request payload against the OpenAPI spec.

    Returns an empty list if valid, or a list of human-readable error strings
    for each invalid field name.  Uses fuzzy matching to suggest corrections.
    """
    if not payload or not _schema_lookup:
        return []

    entry = _find_matching_schema(method, path)
    if not entry:
        return []  # Unknown endpoint — skip validation

    return _validate_fields(payload, entry["schema_name"], entry["fields"], entry.get("nested", {}))


def _validate_fields(
    payload: dict[str, Any],
    schema_name: str,
    valid_fields: set[str],
    nested: dict[str, tuple[str, set[str]]],
) -> list[str]:
    """Validate field names in payload against valid_fields. Recurse into nested objects."""
    errors: list[str] = []

    for key, value in payload.items():
        if key not in valid_fields:
            # Fuzzy match
            suggestions = get_close_matches(key, list(valid_fields), n=3, cutoff=0.5)
            if suggestions:
                hint = f"Did you mean '{suggestions[0]}'?"
                if len(suggestions) > 1:
                    hint = f"Did you mean one of: {', '.join(repr(s) for s in suggestions)}?"
                errors.append(f"Field '{key}' is not valid on {schema_name}. {hint}")
            else:
                errors.append(f"Field '{key}' is not valid on {schema_name}.")
            continue

        # Recurse into nested objects
        if key in nested and isinstance(value, dict):
            nested_name, nested_fields = nested[key]
            for sub_key in value:
                if sub_key not in nested_fields:
                    suggestions = get_close_matches(sub_key, list(nested_fields), n=3, cutoff=0.5)
                    if suggestions:
                        hint = f"Did you mean '{suggestions[0]}'?"
                        errors.append(f"Field '{key}.{sub_key}' is not valid on {nested_name}. {hint}")
                    else:
                        errors.append(f"Field '{key}.{sub_key}' is not valid on {nested_name}.")

        # Recurse into arrays of objects
        if key in nested and isinstance(value, list):
            nested_name, nested_fields = nested[key]
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for sub_key in item:
                        if sub_key not in nested_fields:
                            suggestions = get_close_matches(sub_key, list(nested_fields), n=3, cutoff=0.5)
                            if suggestions:
                                hint = f"Did you mean '{suggestions[0]}'?"
                                errors.append(
                                    f"Field '{key}[{i}].{sub_key}' is not valid on {nested_name}. {hint}"
                                )
                            else:
                                errors.append(f"Field '{key}[{i}].{sub_key}' is not valid on {nested_name}.")

    return errors


def get_valid_fields(method: str, path: str) -> set[str]:
    """Return the set of valid top-level field names for a given endpoint, or empty set."""
    entry = _find_matching_schema(method, path)
    return entry["fields"] if entry else set()


def get_schema_name(method: str, path: str) -> str | None:
    """Return the schema name for a given endpoint, or None."""
    entry = _find_matching_schema(method, path)
    return entry["schema_name"] if entry else None


def get_all_endpoints() -> list[tuple[str, str, str]]:
    """Return a list of (method, path, schema_name) for all indexed endpoints."""
    return [(m, p, e["schema_name"]) for (m, p), e in sorted(_schema_lookup.items())]
