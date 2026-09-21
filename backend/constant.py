"""Fixed (non-secret) values for the backend. Secrets and per-machine values live in .env."""

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

# Latency target (milliseconds, end of speech to first audio)
LATENCY_TARGET_P50_MS = 1000
LATENCY_TARGET_P95_MS = 1500
