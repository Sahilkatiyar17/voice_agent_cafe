"""
get_today: the cafe's current date, in the cafe's own timezone (TIMEZONE in constant.py).

Called by OUR code - SessionRef loads it when a session starts - and deliberately NOT
registered as an LLM tool in agent/tools_binding.py, so the model can't call it and can't
invent a date of its own.

It uses the cafe's timezone rather than the server's clock. A server running in UTC is a
whole day behind India from 18:30 to midnight UTC, and "tomorrow" would come out wrong for
that stretch every day.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.constant import TIMEZONE

CAFE_TZ = ZoneInfo(TIMEZONE)
UTC = ZoneInfo("UTC")


def get_today(now: datetime | None = None) -> date:
    """`now` exists only so tests can pass a fixed moment; it must be timezone-aware.
    Normal callers leave it out."""
    now = now or datetime.now(UTC)
    return now.astimezone(CAFE_TZ).date()
