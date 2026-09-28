"""Fixed (non-secret) values for the backend. Secrets and per-machine values live in .env."""

# Cafe identity (used in get_business_info, and later the agent's opening line)
CAFE_NAME = "Saffron & Seoul"
CAFE_ADDRESS = "12th Main Road, Indiranagar, Bengaluru 560038"

# Time
TIMEZONE = "Asia/Kolkata"  # store UTC, show this zone

# Opening hours (24h, local time)
OPEN_TIME = "11:00"
CLOSE_TIME = "23:00"
LAST_ORDER_TIME = "22:30"
LAST_RESERVATION_START = "21:30"

# Reservations
RESERVATION_DURATION_MINUTES = 90
SLOT_STEP_MINUTES = 30
HOLD_EXPIRY_MINUTES = 5
MAX_PARTY_SIZE = 6
MAX_DAYS_AHEAD = 14

# Delivery
DELIVERY_RADIUS_KM = 5
MIN_ORDER_VALUE = 250
DELIVERY_FEE = 40
FREE_DELIVERY_ABOVE = 700
DELIVERY_ETA_MINUTES = 40
PAYMENT_MODE = "cash_on_delivery"

# API
API_TITLE = "Cafe Voice Agent API"
API_HOST = "0.0.0.0"
API_PORT = 8000
# React dev server (Vite default port) is allowed to call the API
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Phase 3: text agent. Provider is switchable so a quota-exhausted one doesn't block
# testing - see backend/agent/llm.py. "groq", "nvidia", or "openrouter".
AGENT_LLM_PROVIDER = "groq"
AGENT_LLM_TEMPERATURE = 0.3

# Groq (see restaurant_voice_agent_plan.md - chosen for its free tier)
# llama-3.3-70b-versatile returned 404 "does not exist or you do not have access to it" as
# of 2026-09-26 (deprecated or access-gated after this codebase's knowledge cutoff) -
# switched to openai/gpt-oss-120b, confirmed live via Groq's own console listing, and it
# supports tool calling. If Groq changes this again, check console.groq.com/docs/models
# for the current list rather than guessing a name.
GROQ_AGENT_MODEL = "openai/gpt-oss-120b"

# NVIDIA (build.nvidia.com, OpenAI-compatible endpoint, free tier)
# PLACEHOLDER - verify the exact model id on build.nvidia.com yourself: open a chat model
# whose card says it supports function calling / tool use, and copy the exact `model=`
# string from its API/code tab. Don't trust a guessed name here - the same way
# llama-3.3-70b-versatile above turned out to be wrong once Groq moved on.
NVIDIA_AGENT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# OpenRouter (openrouter.ai, OpenAI-compatible endpoint, unified access to many providers'
# models including some free-tier ones) - the actual route requested for Nemotron 3 Ultra.
# PLACEHOLDER - same caveat as NVIDIA_AGENT_MODEL above: get the exact model id from the
# model's page on openrouter.ai (its API tab shows the precise string, which may include a
# ":free" suffix), don't trust a guessed name.
OPENROUTER_AGENT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Latency target (milliseconds, end of speech to first audio)
LATENCY_TARGET_P50_MS = 1000
LATENCY_TARGET_P95_MS = 1500
