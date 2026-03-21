# Codebase Structure

**Analysis Date:** 2026-03-21

## Directory Layout

```
cc-accounting-ai-tripletex/
├── app/                           # Main application code (Python)
│   ├── __init__.py               # Empty module marker
│   ├── main.py                   # FastAPI app + /solve endpoint
│   ├── config.py                 # Environment configuration
│   ├── models.py                 # Data models (ParsedTask, CallTracker, etc.)
│   ├── tripletex.py              # Tripletex API client wrapper
│   ├── parser.py                 # Task parsing orchestration + keyword inference
│   ├── parser_gemini.py          # Gemini/Vertex AI parser backend
│   ├── file_processor.py         # Convert files (PDF, images, CSV) to LLM content blocks
│   ├── storage.py                # Google Cloud Storage persistence
│   ├── api_validator.py          # OpenAPI spec-based payload validation
│   ├── api_rag.py                # RAG-based API documentation lookup
│   ├── error_patterns.py         # Learn from 4xx errors, prevent repeats
│   ├── embeddings.py             # Vertex AI embeddings for RAG
│   ├── call_planner.py           # Hardcoded optimal API call sequences (documentation)
│   └── handlers/                 # Task type handlers (auto-registering)
│       ├── __init__.py           # Handler registry + execute_task dispatcher
│       ├── tier1.py              # Tier 1: 1-call operations (create_supplier, etc.)
│       ├── tier2_invoice.py      # Tier 2: Invoice operations
│       ├── tier2_travel.py       # Tier 2: Travel expenses
│       ├── tier2_project.py      # Tier 2: Project operations
│       ├── tier2_extra.py        # Tier 2: Orders, supplier invoices, timesheet, payroll
│       ├── tier3.py              # Tier 3: Vouchers, closing, reconciliation
│       └── fallback.py           # Fallback: unknown task → LLM + generic API call
├── data/                         # Request/response data (local during dev)
│   ├── requests/                 # Request JSONs saved locally (mirror of GCS)
│   └── results/                  # Result JSONs saved locally (mirror of GCS)
├── docs/                         # Documentation
├── scripts/                      # Helper scripts (if any)
├── .planning/
│   └── codebase/                 # This directory (generated docs)
├── Dockerfile                    # Container definition (Python 3.12-slim)
├── requirements.txt              # Python dependencies
├── .env                          # Environment variables (not committed)
├── .gitignore                    # Git ignore rules
└── README.md, SYSTEMDOKUMENTASJON.md, etc. # Documentation files
```

## Directory Purposes

**app/:**
- Purpose: All application code
- Contains: FastAPI app, client wrapper, handlers, parsers, utilities
- Key imports: All relative imports within app/ use `from app.X import Y`

**app/handlers/:**
- Purpose: Task-specific logic organized by tier/complexity
- Contains: 30+ handler functions, each decorated with `@register_handler("task_type")`
- Import pattern: Modules self-register on import (triggered by `app/handlers/__init__.py` at bottom)

**data/**
- Purpose: Local mirror of GCS data during development/testing
- Contains: JSON files with request/response bodies
- Structure: `requests/{timestamp}.json`, `results/{timestamp}.json`
- Auto-created: By `app/storage.py` on each request (if GCS upload fails gracefully)

**docs/**
- Purpose: User/system documentation
- Contains: SYSTEMDOKUMENTASJON.md (detailed system docs), BRUKERVEILEDNING.md, ANALYSE_RAPPORT.md

## Key File Locations

**Entry Points:**
- `app/main.py:app` — FastAPI application instance
- `app/main.py:@app.post("/solve")` — Main request handler

**Configuration:**
- `app/config.py` — Environment variable loading (API_KEY, GCS_BUCKET, LLM_MODEL, etc.)
- `.env` — Environment variables (not committed, contains secrets)

**Core API Integration:**
- `app/tripletex.py` — TripletexClient class (request/response handling, retry logic)
- `app/models.py` — ParsedTask, CallTracker, APICallRecord dataclasses

**Task Parsing:**
- `app/parser.py` — Parse orchestration, keyword-based fallback
- `app/parser_gemini.py` — Vertex AI Gemini implementation
- `app/file_processor.py` — Multi-format file handling

**Handlers (Business Logic):**
- `app/handlers/__init__.py` — HANDLER_REGISTRY dict, execute_task dispatcher
- `app/handlers/tier1.py` — Simple single-call operations (create_supplier, create_customer, etc.)
- `app/handlers/tier2_invoice.py` — Invoice creation, payment registration, credit notes
- `app/handlers/tier2_travel.py` — Travel expense registration, per diem, updates
- `app/handlers/tier2_project.py` — Project creation, fixed price setup
- `app/handlers/tier2_extra.py` — Orders, supplier invoice registration, timesheet, payroll
- `app/handlers/tier3.py` — Vouchers, deletion, year-end closing, bank reconciliation, monthly closing, ledger error correction
- `app/handlers/fallback.py` — Unknown task type handler

**Persistence & Observability:**
- `app/storage.py` — GCS upload (requests and results)
- `app/models.py:CallTracker` — Call tracking and serialization
- `app/error_patterns.py` — Persistent error pattern learning (JSON-based)

**Optional Enhancements:**
- `app/api_validator.py` — OpenAPI spec validation (non-blocking)
- `app/api_rag.py` — Documentation lookup via embeddings (non-blocking)
- `app/embeddings.py` — Vertex AI embeddings generation
- `app/call_planner.py` — Documentation of optimal call sequences (informational)

## Naming Conventions

**Files:**
- Modules: `snake_case.py` (e.g., `parser.py`, `tripletex.py`, `error_patterns.py`)
- Handlers: `tier{N}*.py` (e.g., `tier1.py`, `tier2_invoice.py`, `tier3.py`)

**Functions:**
- Public handlers: `handle_task_type` decorated with `@register_handler("task_type")`
- Private helpers: `_prefix_name` (e.g., `_resolve_vat_type_id`, `_apply_known_fixes`, `_find_supplier`)
- Async: `async def` prefix indicates async function

**Variables:**
- Constants: `UPPER_SNAKE_CASE` (e.g., `HANDLER_REGISTRY`, `VALID_TASK_TYPES`, `PARSER_BACKEND`)
- Env vars: `UPPER_SNAKE_CASE` with prefix (e.g., `GCS_BUCKET`, `ANTHROPIC_API_KEY`, `PARSER_BACKEND`)
- Dicts/configs: `snake_case` (e.g., `_VAT_CODE_TO_ID`, `_REQUIRED_FIELD_DEFAULTS`)

**Types:**
- Dataclasses: `PascalCase` (e.g., `ParsedTask`, `CallTracker`, `APICallRecord`)
- Type aliases: `snake_case` (e.g., `HandlerFunc = Callable[[...], ...]`)

## Where to Add New Code

**New Task Handler (e.g., "pay_vendor"):**
1. Create handler in appropriate tier module:
   - Simple (1 API call): `app/handlers/tier1.py`
   - Medium (2-5 calls): `app/handlers/tier2_extra.py`
   - Complex (6+ calls, multi-step logic): `app/handlers/tier3.py`
2. Implement async function: `async def pay_vendor(client: TripletexClient, fields: dict) -> dict:`
3. Decorate: `@register_handler("pay_vendor")`
4. Add task type to `VALID_TASK_TYPES` set in `app/parser.py`
5. Add keyword patterns to `_KEYWORD_RULES` in `app/parser.py` (for fallback inference)
6. Return dict with `"status": "completed"` and optional result fields

**New Parser Backend (e.g., OpenAI):**
1. Create `app/parser_openai.py`
2. Implement `async def parse_task_openai(prompt: str, files: list) -> ParsedTask:`
3. Update `app/parser.py` to call it based on `PARSER_BACKEND` selection
4. Add to parser dispatch in `PARSER_BACKEND` handling

**New Validation/Enhancement Module:**
1. Create `app/enhancement_name.py`
2. Implement gracefully with try-except at import (see `api_rag.py` pattern)
3. Import optionally in consuming modules (see `tripletex.py` pattern)
4. Ensure module is non-blocking (failures logged, continue execution)

**New Data Model:**
1. Add dataclass to `app/models.py`
2. Use `@dataclass` decorator
3. Include type hints and optional defaults
4. Add `to_dict()` method if serialization needed

## Special Directories

**app/handlers/:**
- Purpose: All task-specific handlers live here
- Auto-registration: Modules imported in `__init__.py` at bottom, each handler self-registers via decorator
- Organization: Split by tier (tier1, tier2_*, tier3) for code clarity
- Generated: No, all hand-written
- Committed: Yes

**data/requests/ and data/results/:**
- Purpose: Local cache of GCS data (for development/debugging)
- Generated: Yes (auto-created by `storage.py` on each request)
- Committed: No (in .gitignore)
- Usage: Mirror of what's in Google Cloud Storage

**.planning/codebase/:**
- Purpose: Generated architecture/structure documentation (this file, ARCHITECTURE.md, etc.)
- Generated: Yes (by `/gsd:map-codebase` command)
- Committed: Yes
- Usage: Reference for future development phases

**.env:**
- Purpose: Local environment configuration (secrets, API keys)
- Generated: No (created manually)
- Committed: No (in .gitignore)
- Contains: ANTHROPIC_API_KEY, API_KEY, GCS_BUCKET, GCP_PROJECT, PARSER_BACKEND, etc.

## Import Organization

**Pattern used throughout codebase:**
1. `from __future__ import annotations` (enables forward references, type hints as strings)
2. Standard library imports (`import json`, `import logging`, `from typing import`)
3. Third-party imports (`import httpx`, `import anthropic`, `from google.cloud import storage`)
4. Local imports (`from app.models import ParsedTask`, `from app.handlers import register_handler`)

**Example from tripletex.py:**
```python
from __future__ import annotations

import copy
import json as _json
import logging
import os
import re
import time
from typing import Any

import httpx

from app.api_validator import validate_payload
from app.models import CallTracker
```

**Path Aliases:**
- All imports use absolute paths within `app/` (no relative imports like `from . import X`)
- Format: `from app.module import name`
- This makes imports consistent and IDE-friendly

**Circular Import Prevention:**
- Handler registry: Modules import from `__init__.py` to register, `__init__.py` imports modules at bottom
- Optional features: Try-except blocks at module level prevent import failures
- Models: Centralized in `app/models.py` to avoid circular dependencies

## Code Organization Principles

**Handlers are Stateless:**
- All state passed via function arguments (client, fields)
- No shared mutable module-level state
- Each handler is a pure async function

**Client is Stateful (Request-scoped):**
- CallTracker accumulates calls within client lifetime
- Cache persists within client lifetime (cleared when client closed)
- Auth (BasicAuth) set once at init

**Error Patterns are Persistent:**
- Stored in `app/error_patterns.json`
- Loaded on first access
- Updated at program shutdown (via atexit handler)
- Non-blocking if file I/O fails

**Modules are Auto-Registering:**
- Handler modules register themselves via decorator at import time
- No central registration code needed
- Clean separation of concerns (handler file = self-contained feature)
