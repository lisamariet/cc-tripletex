# Technology Stack

**Analysis Date:** 2026-03-21

## Languages

**Primary:**
- Python 3.12 - FastAPI backend for task parsing and Tripletex API orchestration

## Runtime

**Environment:**
- Python 3.12-slim (Docker)

**Package Manager:**
- pip
- Lockfile: `requirements.txt` (pinned versions for production)

## Frameworks

**Core:**
- FastAPI 0.115.6 - REST API framework for `/solve` endpoint
- Uvicorn 0.34.0 - ASGI application server (port 8080)

**API Integration:**
- httpx 0.27.0 - Async HTTP client for Tripletex REST API and Vertex AI calls

**Data/Validation:**
- Pydantic 2.0+ - Data validation and model definitions
- NumPy 1.24.0+ - Vector operations for embedding similarity (cosine matching)

**ML/LLM Integration:**
- Anthropic SDK 0.40.0+ - Claude API for task parsing fallback
- google-cloud-aiplatform 1.38.0+ - Vertex AI integration (Gemini models, embeddings)

**Cloud:**
- google-cloud-storage 2.19.0 - Google Cloud Storage for request/result logging

**Environment:**
- python-dotenv 1.0.1 - Load environment variables from `.env`

## Key Dependencies

**Critical:**
- `fastapi` - Core REST API handler for `/solve` endpoint receiving tasks from orchestrator
- `httpx` - Async HTTP for both Tripletex API calls and Vertex AI API communication
- `anthropic` - Claude API fallback when Gemini unavailable or embedding lookup fails
- `google-cloud-aiplatform` - Vertex AI for Gemini parsing and text embeddings
- `google-cloud-storage` - Persistent storage of all request/response logs to GCS bucket

**Infrastructure:**
- `pydantic` - Type-safe data models (ParsedTask, APICallRecord, CallTracker)
- `numpy` - Vector operations for embedding-based classifier (10ms first-pass filter)

## Configuration

**Environment:**
Configuration via environment variables (see `app/config.py`):
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

**Build:**
- `Dockerfile` - Containerized deployment (Python 3.12-slim, uvicorn)
- Docker image runs FastAPI app listening on 0.0.0.0:8080

## Platform Requirements

**Development:**
- Python 3.12+
- pip package manager
- Google Cloud SDK (`gcloud CLI`) for local authentication fallback
- Anthropic API key (for Claude fallback parsing)
- Google Cloud credentials (ADC or `gcloud auth application-default login`)

**Production:**
- Cloud Run (Google Cloud) - deployed with service account having:
  - Vertex AI access (Gemini API, embeddings)
  - Google Cloud Storage access (logging bucket)
  - Anthropic API key injected as secret

---

*Stack analysis: 2026-03-21*
