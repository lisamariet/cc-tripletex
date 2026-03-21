<!-- GSD:project-start source:PROJECT.md -->
## Project

**Tripletex AI Accounting Agent — NM i AI 2026**

En AI-agent som løser regnskapsoppgaver i Tripletex for NM i AI 2026-konkurransen. Agenten mottar et prompt (på 7 språk), bruker Tripletex API via proxy for å utføre oppgaven, og scores på korrekthet og effektivitet. Deployert på Cloud Run, med embedding-basert parser, 33 handlers, og E2E-testsuite.

**Core Value:** Maks poengscore på alle 30 oppgavetyper — perfekt korrekthet + minimal API-kall + null 4xx-feil = opptil 6.0 per Tier 3-task.

### Constraints

- **Tidsfrist**: 24 timer igjen — alt arbeid må ha direkte poengeffekt
- **Rate limits**: 5 forsøk per task per dag — kan ikke brute-force
- **Timeout**: 5 min per submission — agent må være effektiv
- **Fersk sandbox**: Hver submission starter med tom konto — forutsetninger må opprettes
- **7 språk**: Prompts på nb, en, es, pt, nn, de, fr — parser må håndtere alle
- **Deploy**: Cloud Run europe-west1 — alltid test mot sandbox med E2E før deploy
- **Ingen submit uten tillatelse**: Brukeren må godkjenne før vi submitter
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.12 - FastAPI backend for task parsing and Tripletex API orchestration
## Runtime
- Python 3.12-slim (Docker)
- pip
- Lockfile: `requirements.txt` (pinned versions for production)
## Frameworks
- FastAPI 0.115.6 - REST API framework for `/solve` endpoint
- Uvicorn 0.34.0 - ASGI application server (port 8080)
- httpx 0.27.0 - Async HTTP client for Tripletex REST API and Vertex AI calls
- Pydantic 2.0+ - Data validation and model definitions
- NumPy 1.24.0+ - Vector operations for embedding similarity (cosine matching)
- Anthropic SDK 0.40.0+ - Claude API for task parsing fallback
- google-cloud-aiplatform 1.38.0+ - Vertex AI integration (Gemini models, embeddings)
- google-cloud-storage 2.19.0 - Google Cloud Storage for request/result logging
- python-dotenv 1.0.1 - Load environment variables from `.env`
## Key Dependencies
- `fastapi` - Core REST API handler for `/solve` endpoint receiving tasks from orchestrator
- `httpx` - Async HTTP for both Tripletex API calls and Vertex AI API communication
- `anthropic` - Claude API fallback when Gemini unavailable or embedding lookup fails
- `google-cloud-aiplatform` - Vertex AI for Gemini parsing and text embeddings
- `google-cloud-storage` - Persistent storage of all request/response logs to GCS bucket
- `pydantic` - Type-safe data models (ParsedTask, APICallRecord, CallTracker)
- `numpy` - Vector operations for embedding-based classifier (10ms first-pass filter)
## Configuration
- `ANTHROPIC_API_KEY` - Anthropic API key for Claude fallback
- `GCS_BUCKET` - Google Cloud Storage bucket for logging (default: `tripletex-agent-requests`)
- `LLM_MODEL` - Primary LLM model (default: `claude-haiku-4-5-20251001`)
- `LLM_FALLBACK_MODEL` - Fallback LLM (hardcoded: `claude-sonnet-4-20250514`)
- `API_KEY` - Bearer token for `/solve` endpoint protection (optional)
- `PARSER_BACKEND` - Task parser backend selection: `gemini` (default), `haiku`, `embedding`, or `auto`
- `GCP_PROJECT` - Google Cloud project ID (default: `ai-nm26osl-1771`)
- `GCP_LOCATION` - Vertex AI region (default: `europe-west1`)
- `GEMINI_MODEL` - Gemini model name (default: `gemini-2.5-flash`)
- `TRIPLETEX_DEBUG` - Enable detailed API request/response logging
- `Dockerfile` - Containerized deployment (Python 3.12-slim, uvicorn)
- Docker image runs FastAPI app listening on 0.0.0.0:8080
## Platform Requirements
- Python 3.12+
- pip package manager
- Google Cloud SDK (`gcloud CLI`) for local authentication fallback
- Anthropic API key (for Claude fallback parsing)
- Google Cloud credentials (ADC or `gcloud auth application-default login`)
- Cloud Run (Google Cloud) - deployed with service account having:
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Language & Stack
- `from __future__ import annotations` at top of every module
- Type hints on all function parameters and return values
- Use union syntax: `str | None` instead of `Optional[str]`
- Use generic types: `dict[str, Any]`, `list[dict]`, `tuple[str, int]`
## Naming Patterns
- Lowercase with underscores: `parser.py`, `tripletex.py`, `api_validator.py`
- Handler modules in tier groups: `tier1.py`, `tier2_invoice.py`, `tier3.py`
- Test/script files: `test_e2e.py`, `test_handlers.py`, `test_parser.py`
- Lowercase with underscores: `parse_task()`, `create_supplier()`, `_resolve_vat_type_id()`
- Private helpers prefixed with underscore: `_pick()`, `_build_address()`, `_warn_unused()`
- Async functions: same naming, called with `await`: `async def create_supplier(...)`
- Handler functions: action_entity pattern: `create_supplier`, `register_payment`, `year_end_closing`
- Lowercase with underscores: `session_token`, `api_calls`, `parsed_task`
- Constants: UPPERCASE with underscores: `VALID_TASK_TYPES`, `_VAT_CODE_TO_ID`, `HANDLER_REGISTRY`
- Single-letter loop variables acceptable for iteration: `for c in self.api_calls`
- PascalCase: `TripletexClient`, `ParsedTask`, `CallTracker`, `APICallRecord`
- Dataclasses with `@dataclass` decorator
- No trailing underscore convention used
- Type aliases for callbacks: `HandlerFunc = Callable[[TripletexClient, dict[str, Any]], Awaitable[dict[str, Any]]]`
- Use `Any` from `typing` for truly dynamic data
- Use `dict | None` not `Optional[dict]`
## Import Organization
- No path aliases used; all imports use full module paths from project root
- Example: `from app.parser import parse_task` (not `from .parser import ...`)
## Code Style
- No linter config file detected; follows PEP 8 implicitly
- Max line length: ~100-120 characters (observed)
- Indentation: 4 spaces
- No trailing commas in single-line lists
- All API calls wrapped in `async def` and awaited properly
- Client methods use `async` for I/O-bound operations
- Event loop management: `asyncio.run()` in scripts, FastAPI handles in main.py
- Module-level: Triple-quoted strings describing purpose
- Function-level: Brief description of purpose and parameters (not comprehensive)
- Examples shown in docstrings with usage patterns
- Triple-quotes on separate lines for multi-line docstrings:
- Inline comments for non-obvious logic: `# Fallback: API lookup for unknown codes`
- Section comments with `# -------` lines separating logical blocks
- Norwegian comments acceptable in error patterns and payroll logic
## Error Handling
## Logging
- **Info level:** Progress tracking, API calls, important milestones
- **Warning level:** Unexpected but recoverable situations
- **Error level:** Errors with traceback
- **Debug level:** Detailed tracing in verbose mode (rarely used)
- Secrets: session tokens, API keys
- Full request bodies (unless DEBUG_MODE set in TripletexClient)
- Passwords or credentials
## Function Design
- First param always `client: TripletexClient` for handlers
- Second param always `fields: dict[str, Any]` for task-specific data
- Optional `prompt: str = ""` for fallback handlers that need user intent
- Handlers always return `dict` with at least `"status": "completed"`
- Success includes `"created": {id, ...}` with created entity details
- Errors include `"error": str(exception)` and/or `"note": "explanation"`
- API calls tracked in `client.tracker`
## Handler Pattern
## Module Design
- `parser.py`: `parse_task(prompt, files) -> ParsedTask`
- `tripletex.py`: `TripletexClient` class with methods
- `handlers/__init__.py`: `HANDLER_REGISTRY`, `execute_task()`, handler imports
- `models.py`: `ParsedTask`, `APICallRecord`, `CallTracker` dataclasses
- `handlers/__init__.py` imports all tier modules to auto-register handlers
- Late imports with `# noqa: E402,F401` to allow import-side effects
## Dataclass Conventions
- Immutability not enforced (frozen=True not used)
- Default factories for mutable defaults
- Properties for derived data
## JSON Serialization
- No Pydantic models used for serialization
- Manual `to_dict()` methods
- Conditional fields added only if non-None
- Numeric fields rounded/formatted for readability
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- LLM-based task parsing → deterministic handler execution
- Decorator-based handler registry with automatic self-registration
- Smart retry logic with rule-based error correction on 422 validation failures
- Graceful degradation for optional enhancements (RAG, error patterns, API validation)
- Async throughout using FastAPI + httpx
## Layers
- Purpose: FastAPI application receiving incoming requests, validating auth, orchestrating flow
- Location: `app/main.py`
- Contains: POST /solve endpoint, health check, request/response handling
- Depends on: Config, parser, handlers, storage
- Used by: External competition API
- Purpose: Convert natural language + files into structured task definitions
- Location: `app/parser.py`, `app/parser_gemini.py`, `app/file_processor.py`
- Contains: LLM-based task inference, file preprocessing (images, PDFs, CSVs), confidence scoring
- Depends on: Anthropic SDK, Vertex AI REST API, file utilities
- Used by: Main orchestration flow
- Backends: Selectable via `PARSER_BACKEND` env (gemini, haiku, embedding, auto)
- Purpose: Thin async wrapper around Tripletex REST API with automatic call tracking and smart error recovery
- Location: `app/tripletex.py`, `app/models.py`
- Contains: HTTP methods (GET, POST, PUT, DELETE), retry logic, preflight correction, validation, call tracking
- Depends on: httpx, error patterns module, API validator, RAG
- Used by: All handlers
- Purpose: Task-specific business logic, mapped to task types via decorator registry
- Location: `app/handlers/__init__.py`, `app/handlers/tier1.py`, `app/handlers/tier2_*.py`, `app/handlers/tier3.py`, `app/handlers/fallback.py`
- Contains: ~30 registered handler functions organized by complexity/tier
- Depends on: Tripletex client, field extraction, entity lookups
- Used by: Orchestration layer
- Purpose: Optional features that degrade gracefully if unavailable
- Location: `app/error_patterns.py`, `app/api_rag.py`, `app/api_validator.py`, `app/embeddings.py`
- Contains: Pattern learning from past errors, RAG-based documentation lookup, OpenAPI validation, embeddings
- Depends on: JSON files, vector operations, API specs
- Resilience: Try-except blocks throughout; failures are logged but non-blocking
- Purpose: Persist request/response data to Google Cloud Storage for audit, analysis, debugging
- Location: `app/storage.py`
- Contains: GCS blob upload with JSON serialization
- Depends on: google-cloud-storage
## Data Flow
- **Request-scoped**: ParsedTask instance created per request (immutable)
- **Client-scoped**: TripletexClient instance exists for one request lifetime
- **Call tracking**: CallTracker accumulates all API calls (GET, POST, PUT, DELETE) with timing + errors
- **Persistent**: Error patterns in `app/error_patterns.json` updated at shutdown
- **Caching**: Response caching within TripletexClient lifetime (reference data only)
## Key Abstractions
- Purpose: Encapsulation of one task type's logic (create_supplier, bank_reconciliation, etc.)
- Examples: `app/handlers/tier1.py:create_supplier`, `app/handlers/tier3.py:year_end_closing`
- Pattern: Async function decorated with `@register_handler("task_type")`, receives `(client, fields)`, returns `dict`
- All handlers are self-registering via decorator at module import time
- Purpose: Immutable representation of parsed task with confidence
- Location: `app/models.py:ParsedTask` dataclass
- Fields: `task_type`, `fields`, `confidence`, `reasoning`
- Used for: Serialization to GCS, handler lookup
- Purpose: Record every Tripletex API call for auditing and debugging
- Location: `app/models.py:CallTracker` dataclass
- Records: method, path, status, duration_ms, error body (4xx), debug details (in debug mode)
- Serialization: `to_dict()` returns list of APICallRecord dicts
- Purpose: Smart async wrapper around Tripletex REST API
- Key methods:
- Resilience: Gracefully continues even if error patterns/RAG/validation fail
## Entry Points
- Location: `app/main.py:app` (FastAPI instance)
- Route: `POST /solve`
- Triggers: External API call with authentication
- Responsibilities: Parse request, orchestrate, respond
- Location: `app/main.py:health`
- Route: `GET /health`
- Response: `{"status": "healthy"}`
- Location: `app/handlers/__init__.py` (bottom of file)
- Triggers: Module import time
- Imports: tier1, tier2_invoice, tier2_travel, tier2_project, tier2_extra, tier3, fallback modules
- Each module self-registers its handlers via @register_handler decorator
## Error Handling
- **422 Validation Errors (API):** TripletexClient.post_with_retry applies rule-based fixes:
- **4xx Errors (Other):** Recorded to CallTracker, error body saved, handler continues or returns graceful error
- **Exception During Handler:** Caught at main level, returns `{"status": "completed", "error": "..."}`, tracker saved
- **Missing Credentials:** Detected early, returns note without making API calls
- **Unknown Task Type:** Routed to fallback handler (makes best-effort structured API call via LLM)
## Cross-Cutting Concerns
- Framework: Python logging (configured in main.py with INFO level)
- Log destinations: stderr (captured by container logs)
- Key loggers: app.main, app.tripletex, app.parser, app.handlers (per-module)
- Pattern: Log at parse time (prompt snippet), per API call (path, status, duration), and final summary
- Field validation: `app/api_validator.py` checks payload fields against OpenAPI spec (warnings only)
- Payload correction: `app/error_patterns.py` removes known invalid fields before sending
- RAG suggestions: `app/api_rag.py` provides fix hints on 422 (logged for observability)
- Tripletex: Basic auth with session token (username=0, password=token)
- API endpoint: Optional Bearer token verification (API_KEY env var)
- If API_KEY set: Require "Authorization: Bearer {token}" header, else no auth required
- Every API call (GET, POST, PUT, DELETE) recorded with: method, path, status, duration_ms, error (if 4xx)
- Debug mode: Also records full URL, query params, request body, response body (truncated to 2000 chars)
- Persisted to GCS results JSON alongside handler output
- Keyword patterns in parser support: Norwegian, English, Spanish, French, German, Portuguese
- Field parsing: Language-agnostic (JSON structure names are English)
- Error messages: May be in Norwegian (from Tripletex) — logged as-is
- All I/O operations async (httpx, GCS storage, auth lookups)
- Handler execution: Sequential per request (no concurrent handlers within one task)
- Multiple concurrent requests: Handled by FastAPI/uvicorn worker pool
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
