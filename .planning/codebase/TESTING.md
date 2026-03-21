# Testing Patterns

**Analysis Date:** 2026-03-21

## Test Framework

**Runner:** Python standard `asyncio` + custom test harness (no pytest/unittest framework)

**Test Files:**
- `scripts/test_e2e.py` - End-to-end integration tests (prompt → parse → execute → verify)
- `scripts/test_handlers.py` - Handler unit tests against sandbox
- `scripts/test_parser.py` - Parser accuracy tests across languages
- `scripts/pre_deploy_test.py` - Pre-deployment validation

**Assertion Pattern:** Manual checks with colored terminal output
```python
def green(t: str) -> str: return _c(t, "32")
def red(t: str) -> str: return _c(t, "31")
if ok:
    print(f"  {green('PASS')}  {name}: {detail}")
else:
    print(f"  {red('FAIL')}  {name}: {detail}")
```

**Run Commands:**
```bash
# End-to-end tests (sandbox integration)
python3 scripts/test_e2e.py             # Dry-run: shows test plan only
python3 scripts/test_e2e.py --live      # Execute against sandbox
python3 scripts/test_e2e.py --live -v   # Verbose output
python3 scripts/test_e2e.py --live --only create_customer,create_supplier  # Specific tests
python3 scripts/test_e2e.py --live --tier2   # Only Tier 2 tests

# Handler field validation
python3 scripts/test_handlers.py --base-url URL --token TOKEN
python3 scripts/test_handlers.py --from-gcs  # Use latest sandbox creds

# Parser accuracy
python3 scripts/test_parser.py              # Dry-run
python3 scripts/test_parser.py --live       # Call API
python3 scripts/test_parser.py --real-only  # Skip generated prompts
python3 scripts/test_parser.py --live --real-only

# Pre-deploy validation
python3 scripts/pre_deploy_test.py [--live]
```

## Test File Organization

**Location:** Tests are in `scripts/` directory (separate from source `app/`)

**Structure:**
```
scripts/
├── test_e2e.py           # Integration tests (71KB)
├── test_handlers.py      # Handler field validation
├── test_parser.py        # Parser output verification
├── pre_deploy_test.py    # Deployment readiness check
├── validate_handlers.py  # Handler registry validation
└── compete.py            # Competition submission harness
```

**No pytest/unittest:** Test files are standalone executables:
- Shebang: `#!/usr/bin/env python3`
- Can run directly: `python3 scripts/test_e2e.py`
- Command-line argument parsing: `argparse` module
- Async test execution: `asyncio.run()`

## Test Structure

### E2E Test Suite (`test_e2e.py`)

**Test case definition:**
```python
@dataclass
class E2ETestCase:
    name: str
    expected_task_type: str
    expected_fields: dict[str, Any]  # subset of fields that MUST parse out
    verify: VerifySpec | None = None
    request_file: str = ""          # filename under data/requests/
    prompt: str = ""                # inline prompt
    direct_fields: dict[str, Any] | None = None  # bypass LLM
    setup: str = ""                 # setup function name
    tier: int = 1                   # 1 or 2 for filtering
```

**Verification spec:**
```python
@dataclass
class VerifySpec:
    endpoint: str                   # e.g. "/customer"
    search_params: dict[str, Any] = field(default_factory=dict)
    checks: list[FieldCheck] = field(default_factory=list)
    search_by_id: bool = False      # use entity id from handler result

@dataclass
class FieldCheck:
    field: str
    expected: Any
    mode: str = "eq"  # eq | contains | gt | gte | exists | not_exists
```

**Example test case:**
```python
E2ETestCase(
    name="create_customer_with_address",
    request_file="20260319_235722_219962.json",
    expected_task_type="create_customer",
    expected_fields={
        "name": "Bølgekraft AS",
        "organizationNumber": "988957747",
    },
    verify=VerifySpec(
        endpoint="/customer",
        search_params={"organizationNumber": "988957747"},
        checks=[
            FieldCheck("name", "Bølgekraft AS"),
            FieldCheck("organizationNumber", "988957747"),
            FieldCheck("email", "post@blgekraft.no"),
        ],
    ),
    tier=1,
),
```

### Handler Test Suite (`test_handlers.py`)

**Test case structure:**
```python
TEST_CASES: list[dict] = [
    {
        "name": "create_supplier",
        "handler": "create_supplier",
        "fields": {
            "name": "Test Leverandør AS",
            "organizationNumber": "999888777",
            "email": "test@leverandor.no",
        },
        "verify_path": "/supplier",
        "verify_field": "name",
    },
    # More test cases...
]
```

**Test execution:**
```python
async def run_test(client: TripletexClient, test: dict) -> tuple[str, bool, str]:
    """Run a single handler test. Returns (name, passed, detail)."""
    handler = HANDLER_REGISTRY.get(test["handler"])
    if not handler:
        return test["name"], False, "Handler not registered"

    try:
        result = await handler(client, test["fields"])
        status = result.get("status", "")
        created = result.get("created", {})

        if created and created.get("id"):
            return test["name"], True, f"ID={created['id']}"
        # ... more validation
    except Exception as e:
        return test["name"], False, str(e)[:200]
```

### Parser Test Suite (`test_parser.py`)

**Test corpus:**
1. Real prompts from `data/requests/*.json`
2. Generated prompts (7 languages × task types)

**Checking logic:**
```python
expected_type = t.get("expected_task_type")
actual_type = result.task_type

if actual_type == expected_type:
    passed += 1
else:
    failed += 1
    print(f"MISMATCH: expected {expected_type}, got {actual_type}")
```

## Mocking

**No mocking framework:** Tests use real Tripletex sandbox credentials

**When to mock:**
- Not applicable; all tests run against actual Tripletex sandbox API
- Credentials fetched from NM i AI API: `get_sandbox_creds()` in test_e2e.py

**Credential management:**
```python
def get_sandbox_creds() -> tuple[str, str]:
    """Fetch sandbox credentials from NM i AI API."""
    token = os.environ.get("NMIAI_ACCESS_TOKEN")
    r = httpx.get(
        "https://api.ainm.no/tripletex/sandbox",
        cookies={"access_token": token},
        headers={"origin": "https://app.ainm.no"},
    )
    data = r.json()
    return data["api_url"], data["session_token"]
```

**Test isolation:**
- Each E2E test creates fresh entities in sandbox
- Unique names/numbers to avoid collisions
- Tests are idempotent where possible
- No persistent test database

## Fixtures and Test Data

**Location:** `data/requests/` directory

**Request format:** JSON files with structure:
```json
{
  "timestamp": "20260319_235722_219962",
  "prompt": "Opprett kunde Bølgekraft AS...",
  "tripletex_credentials": {
    "base_url": "https://...",
    "session_token": "..."
  }
}
```

**Fixture generation:**
- Real request logs saved by `main.py` to GCS during development
- Downloaded and stored in `data/requests/` for reproducible testing
- Test references by filename: `request_file="20260319_235722_219962.json"`

**Test data factories (inline):**
```python
{
    "name": "create_product",
    "handler": "create_product",
    "fields": {
        "name": "Testprodukt",
        "number": str(int(__import__('time').time()) % 100000),  # Unique
        "priceExcludingVat": 1000,
        "vatCode": "3",
    },
}
```

## Coverage

**Requirements:** Not enforced (no coverage config found)

**What IS tested:**
- **E2E paths:** All 30+ handlers tested with real sandbox
- **Parser accuracy:** All task types tested across 7 languages
- **Field validation:** OpenAPI spec coverage via `api_validator.py`

**What is NOT tested in scripts:**
- Unit tests for individual functions (no pytest)
- Mocking (all tests use real sandbox)
- Edge cases beyond what request logs capture

## Test Types

### End-to-End Tests (`test_e2e.py`)

**Scope:** Full pipeline from prompt to API verification

**Coverage:**
- Tier 1 handlers: ~13 tests (create_supplier, create_customer, etc.)
- Tier 2 handlers: ~20 tests (create_invoice, register_payment, create_project, etc.)
- Tier 3 handlers: ~5 tests (create_voucher, year_end_closing, etc.)

**Approach:**
1. Load prompt from request file or pass directly
2. Call `parse_task(prompt, files)` → returns `ParsedTask`
3. Verify parsed task type and fields match expected
4. Execute handler via `execute_task(task_type, client, fields)`
5. Verify result includes created entity or expected note
6. (Optional) GET the created entity and verify specific fields

### Handler Tests (`test_handlers.py`)

**Scope:** Handler field name validation against OpenAPI spec

**Coverage:**
- One test per Tier 1 handler
- Validates that field names produce valid API payloads
- Checks that created entities have IDs

**Approach:**
1. Create minimal field dict for each handler
2. Call handler directly: `await handler(client, fields)`
3. Check result: `created` dict with non-null `id`
4. Log API call tracker for debugging

### Parser Tests (`test_parser.py`)

**Scope:** Parser task-type classification accuracy

**Coverage:**
- Real prompts from `data/requests/` (25+ prompts)
- Generated prompts for 34 task types × 7 languages (238 synthetic)
- Total: ~260 test cases

**Approach:**
1. For each prompt:
   - Call `parse_task(prompt, files=[])` if files present else `parse_task(prompt)`
   - Check `result.task_type == expected_task_type`
   - Check critical fields are parsed (subset check)
2. Report pass/fail rate and confidence score distribution

## Common Patterns

### Async Test Pattern

All handler tests are async:
```python
async def main_async(base_url: str, token: str) -> int:
    client = TripletexClient(base_url, token)

    for test in TEST_CASES:
        name, ok, detail = await run_test(client, test)
        if ok:
            print(f"  {green('PASS')}  {name}: {detail}")
        else:
            print(f"  {red('FAIL')}  {name}: {detail}")

    await client.close()
    return failed


def main():
    # ... parse args ...
    failed = asyncio.run(main_async(base_url, token))
    sys.exit(1 if failed else 0)
```

### Error Testing

**Pattern: Check for 4xx status and track calls**
```python
last_call = client.tracker.api_calls[-1] if client.tracker.api_calls else None
if last_call and 400 <= last_call.status < 500:
    return test["name"], False, f"API error {last_call.status}: check field names"
```

**Pattern: Verify error handling in handler result**
```python
if "note" in result:
    return test["name"], False, f"Note: {result['note']}"
elif "error" in result:
    return test["name"], False, f"Error: {result['error']}"
```

### Verification Pattern

**GET and field check:**
```python
verify = test_case.verify
if verify:
    resp = await client.get(verify.endpoint, params=verify.search_params)
    entities = resp.json().get("values", [])
    if entities:
        entity = entities[0]
        for check in verify.checks:
            if check.mode == "eq":
                actual = entity.get(check.field)
                if actual != check.expected:
                    return False, f"{check.field}: expected {check.expected}, got {actual}"
```

## Pre-deployment Testing

**Script:** `scripts/pre_deploy_test.py`

**Checks:**
1. All handlers registered in `HANDLER_REGISTRY`
2. All handlers callable with correct signature
3. Parser can import and function
4. API validator spec loads
5. Error patterns file exists and is valid JSON
6. No obvious syntax errors in modules

**Run before deploy:**
```bash
python3 scripts/pre_deploy_test.py [--live]
```

## Test Execution Order

When running `--live` tests, order matters:

1. **Setup:** Fetch sandbox credentials from NM i AI API
2. **Create entities first:** supplier, customer, employee, product, department
3. **Reference entities:** invoice needs customer, payment needs invoice
4. **Complex operations:** travel expense, project, timesheet
5. **Tier 3:** Vouchers, closing operations (after entities created)

Tier 1 tests are independent and can run in any order.

## Debugging Tests

**Verbose output:**
```bash
python3 scripts/test_e2e.py --live -v
```

**From GCS logs:**
```bash
python3 scripts/test_handlers.py --from-gcs  # Uses latest request log
```

**Environment setup for tests:**
```bash
export NMIAI_ACCESS_TOKEN="your_token_here"
# .env file loads ANTHROPIC_API_KEY, TRIPLETEX_* defaults
python3 scripts/test_e2e.py --live
```

## Known Test Gaps

**Not tested:**
- Concurrency/parallel handler execution
- Memory/performance under load
- Rate limiting behavior
- All edge cases in error recovery
- Integration with Gemini fallback parser (when API parser times out)

**Mitigation:**
- E2E tests run sequentially to avoid conflicts
- Performance tracked via `client.tracker` timing
- Error patterns learn from production failures (`error_patterns.py` updates at runtime)

---

*Testing analysis: 2026-03-21*
