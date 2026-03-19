import os

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "tripletex-agent-requests")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_FALLBACK_MODEL = "claude-sonnet-4-20250514"
