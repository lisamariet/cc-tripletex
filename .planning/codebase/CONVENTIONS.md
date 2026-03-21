# Coding Conventions

**Analysis Date:** 2026-03-21

## Language & Stack

**Primary:** Python 3 (asyncio-based FastAPI application)

**Type Hints:** Mandatory. Use PEP 484 style:
- `from __future__ import annotations` at top of every module
- Type hints on all function parameters and return values
- Use union syntax: `str | None` instead of `Optional[str]`
- Use generic types: `dict[str, Any]`, `list[dict]`, `tuple[str, int]`

## Naming Patterns

**Files:**
- Lowercase with underscores: `parser.py`, `tripletex.py`, `api_validator.py`
- Handler modules in tier groups: `tier1.py`, `tier2_invoice.py`, `tier3.py`
- Test/script files: `test_e2e.py`, `test_handlers.py`, `test_parser.py`

**Functions:**
- Lowercase with underscores: `parse_task()`, `create_supplier()`, `_resolve_vat_type_id()`
- Private helpers prefixed with underscore: `_pick()`, `_build_address()`, `_warn_unused()`
- Async functions: same naming, called with `await`: `async def create_supplier(...)`
- Handler functions: action_entity pattern: `create_supplier`, `register_payment`, `year_end_closing`

**Variables:**
- Lowercase with underscores: `session_token`, `api_calls`, `parsed_task`
- Constants: UPPERCASE with underscores: `VALID_TASK_TYPES`, `_VAT_CODE_TO_ID`, `HANDLER_REGISTRY`
- Single-letter loop variables acceptable for iteration: `for c in self.api_calls`

**Classes:**
- PascalCase: `TripletexClient`, `ParsedTask`, `CallTracker`, `APICallRecord`
- Dataclasses with `@dataclass` decorator
- No trailing underscore convention used

**Types:**
- Type aliases for callbacks: `HandlerFunc = Callable[[TripletexClient, dict[str, Any]], Awaitable[dict[str, Any]]]`
- Use `Any` from `typing` for truly dynamic data
- Use `dict | None` not `Optional[dict]`

## Import Organization

**Order (strict):**
1. `from __future__ import annotations` (always first)
2. Standard library: `import json`, `import logging`, `import os`, `import re`, `import asyncio`, etc.
3. Third-party: `import httpx`, `import anthropic`, `from fastapi import`, `from pydantic import`
4. Local imports: `from app.config import`, `from app.tripletex import`, `from app.handlers import`
5. Late imports (for circular dependencies or lazy loading): `from app.handlers import HANDLER_REGISTRY` with `# noqa: E402,F401` comment

**Path Aliases:**
- No path aliases used; all imports use full module paths from project root
- Example: `from app.parser import parse_task` (not `from .parser import ...`)

**Module-level constants after imports:**
```python
logger = logging.getLogger(__name__)
HANDLER_REGISTRY: dict[str, HandlerFunc] = {}
```

## Code Style

**Formatting:**
- No linter config file detected; follows PEP 8 implicitly
- Max line length: ~100-120 characters (observed)
- Indentation: 4 spaces
- No trailing commas in single-line lists

**Async/Await:**
- All API calls wrapped in `async def` and awaited properly
- Client methods use `async` for I/O-bound operations
- Event loop management: `asyncio.run()` in scripts, FastAPI handles in main.py

**Docstrings:**
- Module-level: Triple-quoted strings describing purpose
- Function-level: Brief description of purpose and parameters (not comprehensive)
- Examples shown in docstrings with usage patterns
- Triple-quotes on separate lines for multi-line docstrings:
  ```python
  """Brief description.

  Longer explanation if needed.
  Usage examples.
  """
  ```

**Comments:**
- Inline comments for non-obvious logic: `# Fallback: API lookup for unknown codes`
- Section comments with `# -------` lines separating logical blocks
- Norwegian comments acceptable in error patterns and payroll logic

## Error Handling

**Strategy:** Layered with graceful degradation

**Patterns Observed:**

1. **Try-except with logging:**
   ```python
   try:
       result = await handler(client, fields)
   except Exception as e:
       logger.error(f"Error: {e}", exc_info=True)
       result = {"status": "completed", "error": str(e)}
   ```

2. **Graceful optional features:**
   ```python
   try:
       from app.error_patterns import check_payload as _ep_check_payload
       _HAS_ERROR_PATTERNS = True
   except Exception:
       _HAS_ERROR_PATTERNS = False
   ```
   - Core always works, optional features degrade gracefully

3. **HTTP error handling:**
   - Check `resp.status_code` explicitly
   - 4xx = API validation error, log and apply fix patterns
   - 5xx = server error, log and return early
   - Always return successful HTTP 200 status from `/solve` endpoint even on errors

4. **Field validation:**
   - Use `fields.get("key")` with defaults
   - Log warnings for unused parsed fields: `_warn_unused()`
   - Validate payloads before POST/PUT with `api_validator.validate_payload()`

5. **Null handling:**
   - Return `None` for not found cases: `dict | None`
   - Check with `if not entity:` or `if entity is None:`

## Logging

**Framework:** Python `logging` module

**Setup:**
```python
logger = logging.getLogger(__name__)
# In main.py:
logging.basicConfig(level=logging.INFO)
```

**Patterns:**

- **Info level:** Progress tracking, API calls, important milestones
  ```python
  logger.info(f"Received task: {prompt[:100]}...")
  logger.info(f"Registered handler: {task_type}")
  ```

- **Warning level:** Unexpected but recoverable situations
  ```python
  logger.warning(f"[{handler_name}] Unused parsed fields: {unused}")
  logger.warning(f"No handler for task type: {task_type}")
  ```

- **Error level:** Errors with traceback
  ```python
  logger.error(f"Error: {e}", exc_info=True)
  logger.error("Missing Tripletex credentials")
  ```

- **Debug level:** Detailed tracing in verbose mode (rarely used)

**What NOT to log:**
- Secrets: session tokens, API keys
- Full request bodies (unless DEBUG_MODE set in TripletexClient)
- Passwords or credentials

## Function Design

**Size:** Handler functions typically 30-100 lines; helper functions 10-40 lines

**Parameters:**
```python
async def create_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict
```
- First param always `client: TripletexClient` for handlers
- Second param always `fields: dict[str, Any]` for task-specific data
- Optional `prompt: str = ""` for fallback handlers that need user intent

**Return Values:**
- Handlers always return `dict` with at least `"status": "completed"`
- Success includes `"created": {id, ...}` with created entity details
- Errors include `"error": str(exception)` and/or `"note": "explanation"`
- API calls tracked in `client.tracker`

## Handler Pattern

All handlers follow this structure:

1. **Registration decorator:**
   ```python
   @register_handler("task_type")
   async def handler_name(client: TripletexClient, fields: dict[str, Any]) -> dict:
   ```

2. **Field extraction and defaults:**
   ```python
   name = fields.get("name")
   email = fields.get("email") or fields.get("invoiceEmail")
   ```

3. **Validation before API calls:**
   ```python
   if not name:
       return {"status": "completed", "note": "Missing required field: name"}
   ```

4. **API calls with tracking:**
   ```python
   resp = await client.post("/customer", payload)
   if resp.status_code >= 400:
       return {"status": "completed", "error": resp.text[:500]}
   ```

5. **Return success dict:**
   ```python
   result = resp.json().get("value", {})
   return {"status": "completed", "created": result}
   ```

## Module Design

**Exports:** Each module explicitly defines what it exports

- `parser.py`: `parse_task(prompt, files) -> ParsedTask`
- `tripletex.py`: `TripletexClient` class with methods
- `handlers/__init__.py`: `HANDLER_REGISTRY`, `execute_task()`, handler imports
- `models.py`: `ParsedTask`, `APICallRecord`, `CallTracker` dataclasses

**Barrel files:**
- `handlers/__init__.py` imports all tier modules to auto-register handlers
- Late imports with `# noqa: E402,F401` to allow import-side effects

**Module dependencies (clean):**
```
main.py (FastAPI)
  ├─ parser.py (parse_task)
  ├─ tripletex.py (TripletexClient)
  ├─ handlers/__init__.py (execute_task)
  │  ├─ tier1.py, tier2_*.py, tier3.py (handlers)
  │  └─ fallback.py (unknown handler)
  └─ storage.py (save_to_gcs)

tripletex.py
  ├─ api_validator.py (field validation)
  ├─ error_patterns.py (fix suggestions)
  └─ api_rag.py (RAG lookup)
```

## Dataclass Conventions

All domain models use `@dataclass`:

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ParsedTask:
    task_type: str
    fields: dict[str, Any]
    confidence: float = 1.0
    reasoning: str = ""

@dataclass
class CallTracker:
    api_calls: list[APICallRecord] = field(default_factory=list)
    debug: bool = field(default=False)

    @property
    def total_calls(self) -> int:
        return len(self.api_calls)
```

- Immutability not enforced (frozen=True not used)
- Default factories for mutable defaults
- Properties for derived data

## JSON Serialization

**Pattern:** Explicit serialization methods on dataclasses

```python
def to_dict(self) -> list[dict]:
    result = []
    for c in self.api_calls:
        d: dict[str, Any] = {
            "method": c.method, "path": c.path, "status": c.status,
            "duration_ms": round(c.duration_ms, 1), "error": c.error,
        }
        if c.url:
            d["url"] = c.url
        result.append(d)
    return result
```

- No Pydantic models used for serialization
- Manual `to_dict()` methods
- Conditional fields added only if non-None
- Numeric fields rounded/formatted for readability

---

*Convention analysis: 2026-03-21*
