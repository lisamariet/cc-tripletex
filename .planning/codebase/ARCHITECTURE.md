# Architecture

**Analysis Date:** 2026-03-21

## Pattern Overview

**Overall:** Multi-tier handler pattern with intelligent orchestration

**Key Characteristics:**
- LLM-based task parsing → deterministic handler execution
- Decorator-based handler registry with automatic self-registration
- Smart retry logic with rule-based error correction on 422 validation failures
- Graceful degradation for optional enhancements (RAG, error patterns, API validation)
- Async throughout using FastAPI + httpx

## Layers

**API/HTTP Layer:**
- Purpose: FastAPI application receiving incoming requests, validating auth, orchestrating flow
- Location: `app/main.py`
- Contains: POST /solve endpoint, health check, request/response handling
- Depends on: Config, parser, handlers, storage
- Used by: External competition API

**Parsing/Task Analysis Layer:**
- Purpose: Convert natural language + files into structured task definitions
- Location: `app/parser.py`, `app/parser_gemini.py`, `app/file_processor.py`
- Contains: LLM-based task inference, file preprocessing (images, PDFs, CSVs), confidence scoring
- Depends on: Anthropic SDK, Vertex AI REST API, file utilities
- Used by: Main orchestration flow
- Backends: Selectable via `PARSER_BACKEND` env (gemini, haiku, embedding, auto)

**Tripletex API Client Layer:**
- Purpose: Thin async wrapper around Tripletex REST API with automatic call tracking and smart error recovery
- Location: `app/tripletex.py`, `app/models.py`
- Contains: HTTP methods (GET, POST, PUT, DELETE), retry logic, preflight correction, validation, call tracking
- Depends on: httpx, error patterns module, API validator, RAG
- Used by: All handlers

**Handler Execution Layer:**
- Purpose: Task-specific business logic, mapped to task types via decorator registry
- Location: `app/handlers/__init__.py`, `app/handlers/tier1.py`, `app/handlers/tier2_*.py`, `app/handlers/tier3.py`, `app/handlers/fallback.py`
- Contains: ~30 registered handler functions organized by complexity/tier
- Depends on: Tripletex client, field extraction, entity lookups
- Used by: Orchestration layer

**Enhancement/Cross-Cutting Modules:**
- Purpose: Optional features that degrade gracefully if unavailable
- Location: `app/error_patterns.py`, `app/api_rag.py`, `app/api_validator.py`, `app/embeddings.py`
- Contains: Pattern learning from past errors, RAG-based documentation lookup, OpenAPI validation, embeddings
- Depends on: JSON files, vector operations, API specs
- Resilience: Try-except blocks throughout; failures are logged but non-blocking

**Storage Layer:**
- Purpose: Persist request/response data to Google Cloud Storage for audit, analysis, debugging
- Location: `app/storage.py`
- Contains: GCS blob upload with JSON serialization
- Depends on: google-cloud-storage

## Data Flow

**Request → Response Flow:**

1. **Receive** (main.py)
   - POST /solve with `prompt`, `files`, `tripletex_credentials`
   - Save raw request to GCS: `requests/{timestamp}.json`

2. **Parse** (parser.py → parser_gemini.py)
   - Extract task type and fields from prompt + files
   - LLM returns JSON with `{"task_type": "...", "fields": {...}}`
   - Fallback: keyword-based inference if LLM returns "unknown"
   - Infer multiple candidate types if confidence < 1.0

3. **Initialize Client** (main.py → tripletex.py)
   - Create TripletexClient with base_url + session_token
   - Instantiate CallTracker for recording API calls

4. **Execute Handler** (handlers/__init__.py → tier-specific)
   - Look up handler by task_type in HANDLER_REGISTRY
   - Handler processes fields and makes API calls via client
   - For batch_* tasks: iterate items and run appropriate handlers
   - Fallback handler "unknown" used if no handler registered

5. **Respond + Log** (main.py)
   - Return 200 with `{"status": "completed", ...}`
   - Save result + tracker to GCS: `results/{timestamp}.json`
   - Log summary to stderr

**State Management:**

- **Request-scoped**: ParsedTask instance created per request (immutable)
- **Client-scoped**: TripletexClient instance exists for one request lifetime
- **Call tracking**: CallTracker accumulates all API calls (GET, POST, PUT, DELETE) with timing + errors
- **Persistent**: Error patterns in `app/error_patterns.json` updated at shutdown
- **Caching**: Response caching within TripletexClient lifetime (reference data only)

## Key Abstractions

**Handler:**
- Purpose: Encapsulation of one task type's logic (create_supplier, bank_reconciliation, etc.)
- Examples: `app/handlers/tier1.py:create_supplier`, `app/handlers/tier3.py:year_end_closing`
- Pattern: Async function decorated with `@register_handler("task_type")`, receives `(client, fields)`, returns `dict`
- All handlers are self-registering via decorator at module import time

**ParsedTask:**
- Purpose: Immutable representation of parsed task with confidence
- Location: `app/models.py:ParsedTask` dataclass
- Fields: `task_type`, `fields`, `confidence`, `reasoning`
- Used for: Serialization to GCS, handler lookup

**CallTracker:**
- Purpose: Record every Tripletex API call for auditing and debugging
- Location: `app/models.py:CallTracker` dataclass
- Records: method, path, status, duration_ms, error body (4xx), debug details (in debug mode)
- Serialization: `to_dict()` returns list of APICallRecord dicts

**TripletexClient:**
- Purpose: Smart async wrapper around Tripletex REST API
- Key methods:
  - `post_with_retry(path, payload)` — POST with automatic 422 fix + 1 retry
  - `put_with_retry(path, payload)` — PUT with automatic 422 fix + 1 retry
  - `get_cached(path, params)` — GET with in-memory cache for reference data
  - `_apply_known_fixes()` — Rule-based 422 correction (remove invalid fields, add defaults, convert refs)
  - `_preflight_correct()` — Pre-flight validation against known error patterns
- Resilience: Gracefully continues even if error patterns/RAG/validation fail

## Entry Points

**HTTP:**
- Location: `app/main.py:app` (FastAPI instance)
- Route: `POST /solve`
- Triggers: External API call with authentication
- Responsibilities: Parse request, orchestrate, respond

**Health:**
- Location: `app/main.py:health`
- Route: `GET /health`
- Response: `{"status": "healthy"}`

**Handler Auto-Registration:**
- Location: `app/handlers/__init__.py` (bottom of file)
- Triggers: Module import time
- Imports: tier1, tier2_invoice, tier2_travel, tier2_project, tier2_extra, tier3, fallback modules
- Each module self-registers its handlers via @register_handler decorator

## Error Handling

**Strategy:** Always return 200 with `{"status": "completed"}` regardless of success/failure (competition requirement)

**Patterns:**

- **422 Validation Errors (API):** TripletexClient.post_with_retry applies rule-based fixes:
  - "allerede i bruk" (already in use) → attempt to find existing entity
  - "eksisterer ikke" (does not exist) → remove invalid field from payload
  - "kan ikke opprette subelement" → convert vatType references (number → id)
  - "må fylles ut" (required) → add default values for known fields
  - Retry once with corrected payload if any fix applied

- **4xx Errors (Other):** Recorded to CallTracker, error body saved, handler continues or returns graceful error

- **Exception During Handler:** Caught at main level, returns `{"status": "completed", "error": "..."}`, tracker saved

- **Missing Credentials:** Detected early, returns note without making API calls

- **Unknown Task Type:** Routed to fallback handler (makes best-effort structured API call via LLM)

## Cross-Cutting Concerns

**Logging:**
- Framework: Python logging (configured in main.py with INFO level)
- Log destinations: stderr (captured by container logs)
- Key loggers: app.main, app.tripletex, app.parser, app.handlers (per-module)
- Pattern: Log at parse time (prompt snippet), per API call (path, status, duration), and final summary

**Validation:**
- Field validation: `app/api_validator.py` checks payload fields against OpenAPI spec (warnings only)
- Payload correction: `app/error_patterns.py` removes known invalid fields before sending
- RAG suggestions: `app/api_rag.py` provides fix hints on 422 (logged for observability)

**Authentication:**
- Tripletex: Basic auth with session token (username=0, password=token)
- API endpoint: Optional Bearer token verification (API_KEY env var)
- If API_KEY set: Require "Authorization: Bearer {token}" header, else no auth required

**Call Tracking:**
- Every API call (GET, POST, PUT, DELETE) recorded with: method, path, status, duration_ms, error (if 4xx)
- Debug mode: Also records full URL, query params, request body, response body (truncated to 2000 chars)
- Persisted to GCS results JSON alongside handler output

**Multi-Language Support:**
- Keyword patterns in parser support: Norwegian, English, Spanish, French, German, Portuguese
- Field parsing: Language-agnostic (JSON structure names are English)
- Error messages: May be in Norwegian (from Tripletex) — logged as-is

**Async/Concurrency:**
- All I/O operations async (httpx, GCS storage, auth lookups)
- Handler execution: Sequential per request (no concurrent handlers within one task)
- Multiple concurrent requests: Handled by FastAPI/uvicorn worker pool
