#!/usr/bin/env python3
"""Build RAG index from Tripletex OpenAPI spec and endpoint documentation.

Parses the OpenAPI spec to extract per-endpoint chunks with:
- Path, method, summary
- Required and optional fields with types
- Request body schema (resolved $ref)
- Query parameters

Embeds all chunks using Vertex AI text-embedding-005 and saves
the index to app/api_rag_index.json.

Usage:
    python3 scripts/build_api_rag.py
    python3 scripts/build_api_rag.py --test   # Run verification tests after building
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OPENAPI_PATH = PROJECT_ROOT / "docs" / "tripletex-openapi.json"
ENDPOINT_DOCS_PATH = PROJECT_ROOT / "docs" / "06-tripletex-api-endpoints.md"
RAG_INDEX_PATH = PROJECT_ROOT / "app" / "api_rag_index.json"

# Endpoints most relevant to the competition tasks
PRIORITY_PATHS = {
    "/customer", "/supplier", "/employee", "/project", "/invoice",
    "/order", "/order/orderline", "/product", "/department",
    "/ledger/voucher", "/ledger/account", "/ledger/vatType",
    "/salary/type",  # read-only; POST /salary/transaction and /salary/payslip are BETA (403)
    "/contact", "/currency", "/supplierInvoice",
    "/travelExpense", "/travelExpense/cost",
    "/travelExpense/mileageAllowance",
    "/travelExpense/accommodationAllowance",
    "/travelExpense/perDiemCompensation",
    "/employee/employment", "/employee/employment/details",
    "/employee/hourlyCostAndRate", "/employee/standardTime",
    "/project/category", "/project/participant",
    "/project/hourlyRates", "/project/orderline",
    "/project/projectActivity",
    "/ledger/voucher/historical/historical",
    "/ledger/paymentTypeOut",
    "/ledger/accountingDimensionName",
    "/ledger/accountingDimensionValue",
    # "/salary/settings" — BETA, returns 403
    "/employee/employment/leaveOfAbsence",
    "/incomingInvoice",
    "/customer/category",
}


def load_openapi_spec() -> dict:
    """Load and return the OpenAPI spec."""
    with open(OPENAPI_PATH) as f:
        return json.load(f)


def resolve_ref(spec: dict, ref: str, depth: int = 0) -> dict:
    """Resolve a $ref reference in the OpenAPI spec.

    Limits depth to avoid infinite recursion.
    """
    if depth > 3:
        return {}

    parts = ref.replace("#/", "").split("/")
    obj = spec
    for part in parts:
        obj = obj.get(part, {})
        if not obj:
            return {}
    return obj


def format_schema_fields(
    spec: dict, schema: dict, depth: int = 0, max_fields: int = 40
) -> list[str]:
    """Extract field descriptions from a schema.

    Returns lines like:
        - name (string, required): Customer name
        - email (string, optional): Email address
    """
    if depth > 2:
        return []

    # Resolve $ref if present
    if "$ref" in schema:
        schema = resolve_ref(spec, schema["$ref"], depth)
        if not schema:
            return ["  (unresolved reference)"]

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    lines = []
    count = 0

    for field_name, field_info in properties.items():
        if count >= max_fields:
            lines.append(f"  ... and {len(properties) - count} more fields")
            break

        # Skip read-only fields for POST/PUT chunks
        is_readonly = field_info.get("readOnly", False)

        # Resolve nested $ref for type info
        resolved = field_info
        if "$ref" in field_info:
            resolved = resolve_ref(spec, field_info["$ref"], depth + 1)
            type_str = f"object ({field_info['$ref'].split('/')[-1]})"
        elif field_info.get("type") == "array":
            items = field_info.get("items", {})
            if "$ref" in items:
                item_name = items["$ref"].split("/")[-1]
                type_str = f"array of {item_name}"
            else:
                type_str = f"array of {items.get('type', 'any')}"
        else:
            type_str = field_info.get("type", "any")
            fmt = field_info.get("format")
            if fmt:
                type_str = f"{type_str} ({fmt})"

        # Enum values
        enum = field_info.get("enum") or resolved.get("enum")
        if enum:
            type_str += f", values: {enum}"

        req_str = "required" if field_name in required_fields else "optional"
        if is_readonly:
            req_str = "read-only"

        desc = field_info.get("description", resolved.get("description", ""))
        desc_str = f": {desc}" if desc else ""

        # Min/max
        constraints = []
        if "minimum" in field_info:
            constraints.append(f"min={field_info['minimum']}")
        if "maximum" in field_info:
            constraints.append(f"max={field_info['maximum']}")
        if "maxLength" in field_info:
            constraints.append(f"maxLength={field_info['maxLength']}")
        constraint_str = f" [{', '.join(constraints)}]" if constraints else ""

        lines.append(
            f"  - {field_name} ({type_str}, {req_str}){constraint_str}{desc_str}"
        )
        count += 1

    return lines


def build_chunks_from_openapi(spec: dict) -> list[dict]:
    """Build text chunks from the OpenAPI spec.

    Each chunk represents one endpoint+method combination with its
    schema information.
    """
    chunks = []
    paths = spec.get("paths", {})

    for path, path_info in paths.items():
        # Check if this is a priority path or starts with one
        is_priority = any(
            path == p or path.startswith(p + "/") or path.startswith(p + "/{")
            for p in PRIORITY_PATHS
        )

        for method in ("get", "post", "put", "delete"):
            if method not in path_info:
                continue

            op = path_info[method]
            summary = op.get("summary", "")
            description = op.get("description", "")

            # Build chunk text
            lines = [
                f"{method.upper()} {path}",
                f"Summary: {summary}",
            ]

            if description and description != summary:
                # Truncate long descriptions
                lines.append(f"Description: {description[:300]}")

            # Query parameters
            params = op.get("parameters", [])
            query_params = [p for p in params if p.get("in") == "query"]
            required_params = [p for p in query_params if p.get("required")]
            if required_params:
                lines.append("Required query parameters:")
                for p in required_params:
                    p_type = p.get("schema", {}).get("type", "string")
                    lines.append(f"  - {p['name']} ({p_type}): {p.get('description', '')}")

            if query_params and not required_params:
                optional_names = [p["name"] for p in query_params[:10]]
                lines.append(f"Optional query parameters: {', '.join(optional_names)}")

            # Request body
            request_body = op.get("requestBody", {})
            if request_body:
                content = request_body.get("content", {})
                for content_type, content_info in content.items():
                    schema = content_info.get("schema", {})
                    if schema:
                        schema_name = ""
                        if "$ref" in schema:
                            schema_name = schema["$ref"].split("/")[-1]
                            lines.append(f"Request body schema: {schema_name}")
                        elif schema.get("type") == "array" and "$ref" in schema.get("items", {}):
                            schema_name = schema["items"]["$ref"].split("/")[-1]
                            lines.append(f"Request body: array of {schema_name}")

                        fields = format_schema_fields(spec, schema)
                        if fields:
                            lines.append("Fields:")
                            lines.extend(fields)

            # Response schema (for GET mainly)
            responses = op.get("responses", {})
            success_resp = responses.get("200", responses.get("201", {}))
            if success_resp and method == "get":
                resp_content = success_resp.get("content", {})
                for ct, ci in resp_content.items():
                    resp_schema = ci.get("schema", {})
                    if "$ref" in resp_schema:
                        resp_name = resp_schema["$ref"].split("/")[-1]
                        lines.append(f"Response schema: {resp_name}")

            text = "\n".join(lines)

            # Skip very small chunks
            if len(text) < 50:
                continue

            chunks.append({
                "text": text,
                "path": path,
                "method": method.upper(),
                "is_priority": is_priority,
            })

    return chunks


def build_chunks_from_endpoint_docs() -> list[dict]:
    """Build supplementary chunks from the markdown endpoint docs."""
    if not ENDPOINT_DOCS_PATH.exists():
        return []

    with open(ENDPOINT_DOCS_PATH) as f:
        content = f.read()

    chunks = []
    current_section = ""
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## ") and not line.startswith("## All API tags"):
            # Save previous section
            if current_section and current_lines:
                text = f"Endpoint group: {current_section}\n" + "\n".join(current_lines)
                if len(text) > 50:
                    chunks.append({
                        "text": text,
                        "path": current_section,
                        "method": "OVERVIEW",
                        "is_priority": False,
                    })
            current_section = line[3:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    # Save last section
    if current_section and current_lines:
        text = f"Endpoint group: {current_section}\n" + "\n".join(current_lines)
        if len(text) > 50:
            chunks.append({
                "text": text,
                "path": current_section,
                "method": "OVERVIEW",
                "is_priority": False,
            })

    return chunks


def build_all_chunks() -> list[dict]:
    """Build all chunks from both sources."""
    spec = load_openapi_spec()

    logger.info("Building chunks from OpenAPI spec...")
    openapi_chunks = build_chunks_from_openapi(spec)
    logger.info(f"  {len(openapi_chunks)} chunks from OpenAPI")

    logger.info("Building chunks from endpoint docs...")
    doc_chunks = build_chunks_from_endpoint_docs()
    logger.info(f"  {len(doc_chunks)} chunks from endpoint docs")

    # Prioritize: include all priority chunks, and a subset of non-priority
    priority = [c for c in openapi_chunks if c["is_priority"]]
    non_priority = [c for c in openapi_chunks if not c["is_priority"]]

    # Only include POST/PUT/DELETE for non-priority (skip GET-only endpoints)
    non_priority_write = [
        c for c in non_priority if c["method"] in ("POST", "PUT", "DELETE")
    ]

    all_chunks = priority + non_priority_write + doc_chunks
    logger.info(
        f"Total chunks to embed: {len(all_chunks)} "
        f"({len(priority)} priority, {len(non_priority_write)} non-priority writes, "
        f"{len(doc_chunks)} doc chunks)"
    )

    return all_chunks


def embed_and_save(chunks: list[dict]) -> None:
    """Embed all chunks and save the index."""
    from app.embeddings import embed_texts_batch

    texts = [c["text"] for c in chunks]
    logger.info(f"Embedding {len(texts)} chunks...")
    embeddings = embed_texts_batch(texts, batch_size=30)

    index = []
    for chunk, embedding in zip(chunks, embeddings):
        index.append({
            "text": chunk["text"],
            "path": chunk["path"],
            "method": chunk["method"],
            "embedding": embedding,
        })

    with open(RAG_INDEX_PATH, "w") as f:
        json.dump(index, f, ensure_ascii=False)

    logger.info(f"Saved RAG index ({len(index)} entries) to {RAG_INDEX_PATH}")
    file_size_mb = RAG_INDEX_PATH.stat().st_size / (1024 * 1024)
    logger.info(f"Index file size: {file_size_mb:.1f} MB")


def run_tests() -> bool:
    """Run verification tests on the built index."""
    from app.api_rag import lookup_api_docs

    # Force reload
    import app.api_rag as rag_module
    rag_module._rag_index = None

    tests_passed = 0
    tests_total = 0

    def check(description: str, endpoint: str, method: str, expected_keywords: list[str]):
        nonlocal tests_passed, tests_total
        tests_total += 1
        result = lookup_api_docs(endpoint, method)
        if not result:
            logger.error(f"FAIL: {description} — got empty result")
            return

        result_lower = result.lower()
        missing = [kw for kw in expected_keywords if kw.lower() not in result_lower]
        if missing:
            logger.error(f"FAIL: {description} — missing keywords: {missing}")
            logger.error(f"  Result preview: {result[:200]}")
        else:
            logger.info(f"PASS: {description}")
            tests_passed += 1

    check(
        "POST /project should mention fixedPrice/isFixedPrice/startDate",
        "/project", "POST",
        ["project", "name"]
    )
    check(
        "POST /customer should mention name/isCustomer",
        "/customer", "POST",
        ["name", "customer"]
    )
    # Skipped: POST /salary/transaction is BETA (403) — using voucher instead
    check(
        "POST /ledger/voucher should mention postings",
        "/ledger/voucher", "POST",
        ["voucher", "post"]
    )
    check(
        "POST /invoice should mention order/customer",
        "/invoice", "POST",
        ["invoice"]
    )

    logger.info(f"\nTests: {tests_passed}/{tests_total} passed")
    return tests_passed == tests_total


def main():
    run_test = "--test" in sys.argv

    logger.info("Building RAG index from API documentation...")
    chunks = build_all_chunks()
    embed_and_save(chunks)

    if run_test:
        logger.info("\nRunning verification tests...")
        success = run_tests()
        if not success:
            logger.error("Some tests failed!")
            sys.exit(1)
        logger.info("All tests passed!")


if __name__ == "__main__":
    main()
