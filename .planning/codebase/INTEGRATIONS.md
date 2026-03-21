# External Integrations

**Analysis Date:** 2026-03-21

## APIs & External Services

**Tripletex REST API:**
- Primary accounting system integration
  - SDK/Client: Custom `TripletexClient` in `app/tripletex.py` (async httpx wrapper)
  - Auth: Basic auth with username="0" and password=session_token (provided per-request)
  - Base URL: Dynamic from request body (`tripletex_credentials.base_url`)
  - Session token: Provided per task in request body (`tripletex_credentials.session_token`)

**Vertex AI (Google Cloud):**
- Gemini 2.5-flash for task parsing (multimodal - text + PDF/images)
  - SDK/Client: REST API via httpx (no official Python SDK used)
  - Auth: Google Application Default Credentials (ADC) with gcloud CLI fallback
  - Endpoint: `https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent`
  - Model: `gemini-2.5-flash` (configurable via `GEMINI_MODEL`)
  - Region: `europe-west1` (default, configurable via `GCP_LOCATION`)
  - Project: `ai-nm26osl-1771` (default, configurable via `GCP_PROJECT`)
  - Timeout: 30 seconds per request
  - Output tokens: 8192 for structured JSON parsing

**Vertex AI Text Embeddings:**
- text-embedding-005 for prompt classification (RAG first-pass filter)
  - Used in `app/embeddings.py` for similarity matching against pre-built index
  - Returns 768-dimensional embeddings
  - Cosine similarity matching (~10ms) before expensive LLM parsing

**Anthropic Claude API:**
- Fallback LLM for task parsing when Gemini unavailable
  - SDK/Client: `anthropic` Python SDK
  - Auth: `ANTHROPIC_API_KEY` environment variable
  - Primary model: `claude-haiku-4-5-20251001` (default via `LLM_MODEL`)
  - Fallback model: `claude-sonnet-4-20250514` (hardcoded in `app/config.py`)

## Data Storage

**Databases:**
- None - Tripletex is the system of record

**File Storage:**
- Google Cloud Storage (GCS)
  - Bucket: `tripletex-agent-requests` (configurable via `GCS_BUCKET`)
  - Client: `google.cloud.storage` (native Python library)
  - Usage: Persistent logging of all requests and results
    - Path: `requests/{timestamp}.json` - Full task request with files and credentials
    - Path: `results/{timestamp}.json` - Task result, API call tracking, execution metrics
  - Format: JSON with base64-encoded file contents
  - Retention: Indefinite (for audit trail and error pattern analysis)

**Caching:**
- In-memory only
  - `TripletexClient._cache` - Reference data lookups (vatType, paymentType, department)
  - `_cached_token` - Vertex AI access token (refreshed on expiry)
  - `_index`, `_index_matrix` - Embedding index for prompt classification
  - `_rag_index`, `_rag_matrix` - API documentation RAG index

## Authentication & Identity

**Auth Provider:**
- Multiple fallback chain per service:

**Tripletex:**
- Basic Auth: username="0" + session_token (no persistent auth)
- Token provided per-request from competition orchestrator
- No token refresh mechanism (stateless)

**Vertex AI:**
- Google Application Default Credentials (ADC)
  - Primary: `google.auth.default()` (works in Cloud Run with service account)
  - Fallback: `gcloud auth print-access-token` (local development)
  - Token caching with refresh on expiry
  - Implementation in `app/parser_gemini.py:_get_access_token()` and `app/embeddings.py:_get_access_token()`

**Anthropic:**
- API key auth (`ANTHROPIC_API_KEY` env var)
- No token refresh needed (bearer token in Authorization header)

## Monitoring & Observability

**Error Tracking:**
- No external service (Sentry, Rollbar, etc.)
- Python standard library logging to stdout

**Logs:**
- Python `logging` module (root logger with INFO level)
- Output to stdout (Cloud Run captures automatically)
- Contextual logging:
  - Request start/end with execution time
  - API call details (method, path, status, duration)
  - Error messages with full exception stack traces
  - Prefix tags: `[SmartRetry]`, `[Error Patterns]`, `[RAG]`, `[PreFlight]` for categorization

**Call Tracking:**
- In-memory `CallTracker` (dataclass) per request
  - Records every HTTP call to Tripletex API
  - Captures: method, path, status, duration_ms, error messages
  - Debug mode: Full request/response bodies (when `TRIPLETEX_DEBUG=1`)
  - Serialized to JSON in GCS result file

**Metrics:**
- No metrics collection service
- Computed per-request and saved to GCS:
  - Total execution time (ms)
  - Total Tripletex API calls
  - 4xx error count
  - Breakdown by handler type

## CI/CD & Deployment

**Hosting:**
- Google Cloud Run (serverless container)
- Region: `europe-west1`
- Service account: Has roles for:
  - Vertex AI API (genaiplatform.googleapis.com)
  - Google Cloud Storage (storage-api)
  - IAM permissions to read embeddings and RAG indices

**CI Pipeline:**
- None detected - Deploy via `gcloud run deploy` or Cloud Build triggers
- Git hooks: Not used
- Environment secrets: Injected as Cloud Run secrets or environment variables

## Environment Configuration

**Required env vars:**
- `GCP_PROJECT` - Google Cloud project (default: `ai-nm26osl-1771`)
- `GCP_LOCATION` - Vertex AI region (default: `europe-west1`)
- `ANTHROPIC_API_KEY` - For Claude fallback

**Optional env vars:**
- `LLM_MODEL` - Primary LLM (default: `claude-haiku-4-5-20251001`)
- `GCS_BUCKET` - Logging bucket (default: `tripletex-agent-requests`)
- `PARSER_BACKEND` - Task parser selection (default: `gemini`)
- `API_KEY` - Bearer token to protect /solve endpoint
- `TRIPLETEX_DEBUG` - Enable full request/response logging
- `GEMINI_MODEL` - Gemini variant (default: `gemini-2.5-flash`)

**Secrets location:**
- `.env` file (local development only) - Never committed
- Cloud Run secrets or environment variables (production)
- Handled by `python-dotenv` (load from .env, then os.getenv fallback)

## Webhooks & Callbacks

**Incoming:**
- `/solve` - Main webhook endpoint
  - POST only
  - Receives: `prompt`, `files[]`, `tripletex_credentials`
  - Always returns 200 with `{"status": "completed"}` (fire-and-forget)
  - Validates Bearer token if `API_KEY` set

**Outgoing:**
- None - Results saved to GCS, not posted back

**Request/Response Model:**
```json
POST /solve
{
  "prompt": "string - task description in natural language",
  "files": [
    {
      "filename": "string",
      "mime_type": "string (application/pdf, image/jpeg, etc.)",
      "content_base64": "string - base64 encoded file content"
    }
  ],
  "tripletex_credentials": {
    "base_url": "string - Tripletex API endpoint",
    "session_token": "string - Bearer token for Tripletex auth"
  }
}

Response (always):
{
  "status": "completed",
  "taskType": "string - inferred task type",
  "batch_results": [] | null,
  "error": "string - only if exception occurred",
  "note": "string - additional context"
}
```

## Data Flow

**Request → Parse → Execute → Response:**

1. **Receive** (`/solve` POST)
   - Validate API key (Bearer token if `API_KEY` set)
   - Save full request to GCS (`requests/{timestamp}.json`)

2. **Parse Task** (`parse_task()`)
   - Cascade LLM backend selection (configurable):
     - Gemini (default): Fast, supports files
     - Embedding: ~10ms similarity lookup against pre-built index
     - Claude (fallback): Reliable
     - Keyword rules (instant): Regex patterns for common tasks
   - Returns `ParsedTask` with task_type and extracted fields

3. **Execute Handler** (`execute_task()`)
   - Lookup handler by task_type in `HANDLER_REGISTRY`
   - Call handler with `TripletexClient` and parsed fields
   - Handler makes 1+ Tripletex API calls with smart retry:
     - 422 validation errors: Apply rule-based fixes and retry once
     - 403: Do not retry (permission/token error)
   - Track all calls in `CallTracker`

4. **Return** (always 200)
   - Save result to GCS (`results/{timestamp}.json`)
   - Include execution metrics and API call log
   - Return `{"status": "completed"}` to orchestrator

## API Documentation Sources

**Tripletex OpenAPI:**
- File: `docs/tripletex-openapi.json` (reference only)
- Used for API validation in `app/api_validator.py`

**RAG Index:**
- File: `app/api_rag_index.json` (pre-built embeddings of API documentation chunks)
- Used by `app/api_rag.py:suggest_fix()` to recommend payload corrections
- Requires pre-building: Run embedding generation against OpenAPI schema

**Error Patterns:**
- File: `app/error_patterns.json` (learned from runtime errors)
- Records known field validation errors per endpoint
- Prevents repetition of known mistakes on retry

---

*Integration audit: 2026-03-21*
