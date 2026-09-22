"""get_business_info: static facts about the cafe (hours, delivery area, payment mode)
the agent can quote directly - no DB call needed since these don't change per-call."""

from backend.constant import (
    CAFE_ADDRESS,
    CAFE_NAME,
    CLOSE_TIME,
    DELIVERY_ETA_MINUTES,
    DELIVERY_RADIUS_KM,
    FREE_DELIVERY_ABOVE,
    LAST_ORDER_TIME,
    LAST_RESERVATION_START,
    MAX_DAYS_AHEAD,
    MAX_PARTY_SIZE,
    MIN_ORDER_VALUE,
    OPEN_TIME,
    PAYMENT_MODE,
    RESERVATION_DURATION_MINUTES,
    TIMEZONE,
)


def get_business_info() -> dict:
    return {
        "name": CAFE_NAME,
        "address": CAFE_ADDRESS,
        "timezone": TIMEZONE,
        "open_time": OPEN_TIME,
        "close_time": CLOSE_TIME,
        "last_order_time": LAST_ORDER_TIME,
        "last_reservation_start": LAST_RESERVATION_START,
        "reservation_duration_minutes": RESERVATION_DURATION_MINUTES,
        "max_party_size": MAX_PARTY_SIZE,
        "max_days_ahead": MAX_DAYS_AHEAD,
        "delivery_radius_km": DELIVERY_RADIUS_KM,
        "min_order_value": MIN_ORDER_VALUE,
        "free_delivery_above": FREE_DELIVERY_ABOVE,
        "delivery_eta_minutes": DELIVERY_ETA_MINUTES,
        "payment_mode": PAYMENT_MODE,
    }
