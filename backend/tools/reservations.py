"""
Reservation tools: check_availability, hold_slot, confirm_reservation,
cancel_reservation, lookup_reservation.

Rule the DATABASE enforces: no two held/confirmed reservations overlap on the same table
(the no_double_booking EXCLUDE constraint - database/migrations/versions/0001_initial.py).

Rules these TOOLS must enforce (the database cannot):
  - expire old holds before checking availability or confirming (a constraint can't use now())
  - only within opening hours and the booking window
  - pick the smallest table that fits the party
  - confirm_reservation checks the hold hasn't expired, and is idempotent
  - retry on a genuine Postgres deadlock (see hold_slot) - under real concurrent inserts,
    a GiST exclusion constraint (no_double_booking) can deadlock two transactions that are
    checking different, unrelated table_ids against each other purely due to internal index
    lock ordering. This is documented Postgres behaviour, not a bug in this code - Postgres
    itself picks one transaction as the deadlock victim and aborts it, and the caller is
    expected to retry. Found by tests/test_reservations.py's 20-parallel-holds test, which
    fires real concurrent requests instead of a sequential loop.
"""

import asyncio
from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.constant import (
    CLOSE_TIME,
    HOLD_EXPIRY_MINUTES,
    LAST_RESERVATION_START,
    MAX_DAYS_AHEAD,
    MAX_PARTY_SIZE,
    OPEN_TIME,
    RESERVATION_DURATION_MINUTES,
    TIMEZONE,
)
from database.connection import async_session
from database.models import (
    RES_CANCELLED,
    RES_CONFIRMED,
    RES_EXPIRED,
    RES_HELD,
    CafeTable,
    Reservation,
)
from logger import logging

TZ = ZoneInfo(TIMEZONE)
UTC = ZoneInfo("UTC")
BRANCH_ID = 1
MAX_DEADLOCK_RETRIES = 5


def _parse_local(date_str: str, time_str: str) -> datetime:
    """'2026-10-01', '19:30' (local, Asia/Kolkata) -> aware UTC datetime."""
    d = date_type.fromisoformat(date_str)
    t = time_type.fromisoformat(time_str)
    local_dt = datetime.combine(d, t, tzinfo=TZ)
    return local_dt.astimezone(UTC)


def _validate_booking_window(start_utc: datetime) -> None:
    local_start = start_utc.astimezone(TZ)
    now_local = datetime.now(TZ)

    if local_start < now_local:
        raise ValueError("That time is in the past.")
    if local_start > now_local + timedelta(days=MAX_DAYS_AHEAD):
        raise ValueError(f"Bookings are only accepted up to {MAX_DAYS_AHEAD} days ahead.")

    open_t = time_type.fromisoformat(OPEN_TIME)
    last_res_t = time_type.fromisoformat(LAST_RESERVATION_START)
    start_t = local_start.time()
    if not (open_t <= start_t <= last_res_t):
        raise ValueError(f"We take reservations between {OPEN_TIME} and {LAST_RESERVATION_START}.")


async def _expire_old_holds(session) -> None:
    """A hold that has expired still has status='held' until something flips it, because
    the EXCLUDE constraint can't reference now(). Call this before every read or write
    that cares about which tables are actually free."""
    await session.execute(
        update(Reservation)
        .where(Reservation.status == RES_HELD, Reservation.hold_expires_at < datetime.now(UTC))
        .values(status=RES_EXPIRED)
    )


async def check_availability(date: str, time: str, party_size: int) -> dict:
    """Returns {"available": bool, "tables": [{"id","name","seats"}, ...]}, smallest
    fitting free tables first."""
    if party_size < 1 or party_size > MAX_PARTY_SIZE:
        raise ValueError(f"Party size must be between 1 and {MAX_PARTY_SIZE}.")

    start_utc = _parse_local(date, time)
    _validate_booking_window(start_utc)
    end_utc = start_utc + timedelta(minutes=RESERVATION_DURATION_MINUTES)

    async with async_session() as session:
        await _expire_old_holds(session)
        await session.commit()

        tables = (
            (
                await session.execute(
                    select(CafeTable)
                    .where(
                        CafeTable.branch_id == BRANCH_ID,
                        CafeTable.is_active.is_(True),
                        CafeTable.seats >= party_size,
                    )
                    .order_by(CafeTable.seats)
                )
            )
            .scalars()
            .all()
        )

        busy_table_ids = set(
            (
                await session.execute(
                    select(Reservation.table_id).where(
                        Reservation.status.in_([RES_HELD, RES_CONFIRMED]),
                        Reservation.starts_at < end_utc,
                        Reservation.ends_at > start_utc,
                    )
                )
            )
            .scalars()
            .all()
        )

        free = [t for t in tables if t.id not in busy_table_ids]
        return {
            "available": bool(free),
            "tables": [{"id": t.id, "name": t.name, "seats": t.seats} for t in free],
        }


async def hold_slot(
    date: str,
    time: str,
    party_size: int,
    customer_name: str,
    phone: str,
    call_id: str | None = None,
) -> dict:
    """Picks the smallest free table and holds it for HOLD_EXPIRY_MINUTES.
    Returns {"available": True, "reservation_id", "table_name", "hold_expires_at"}
    or {"available": False, "reservation_id": None} if nothing fits."""
    start_utc = _parse_local(date, time)
    _validate_booking_window(start_utc)
    end_utc = start_utc + timedelta(minutes=RESERVATION_DURATION_MINUTES)

    async with async_session() as session:
        await _expire_old_holds(session)

        candidate_rows = (
            (
                await session.execute(
                    select(CafeTable)
                    .where(
                        CafeTable.branch_id == BRANCH_ID,
                        CafeTable.is_active.is_(True),
                        CafeTable.seats >= party_size,
                    )
                    .order_by(CafeTable.seats)
                )
            )
            .scalars()
            .all()
        )
        # Capture plain values now - a rollback() below expires every ORM object tied to
        # this session, and touching an expired object's attributes afterwards (table.id
        # on a table we haven't gotten to yet) tries to lazy-refresh it, which raises
        # MissingGreenlet under AsyncSession. Plain tuples don't have that problem.
        candidates = [(t.id, t.name) for t in candidate_rows]

        for table_id, table_name in candidates:
            for retry in range(MAX_DEADLOCK_RETRIES):
                hold_expires_at = datetime.now(UTC) + timedelta(minutes=HOLD_EXPIRY_MINUTES)
                reservation = Reservation(
                    branch_id=BRANCH_ID,
                    call_id=call_id,
                    table_id=table_id,
                    customer_name=customer_name,
                    phone=phone,
                    party_size=party_size,
                    starts_at=start_utc,
                    ends_at=end_utc,
                    status=RES_HELD,
                    hold_expires_at=hold_expires_at,
                )
                session.add(reservation)
                try:
                    # flush (not commit) so the EXCLUDE constraint fires now, letting us
                    # try the next candidate table instead of failing the whole call
                    await session.flush()
                except IntegrityError as e:
                    await session.rollback()
                    if "no_double_booking" in str(getattr(e, "orig", e)):
                        break  # a genuine conflict on this table - move on to the next one
                    raise
                except DBAPIError as e:
                    # a transient deadlock between two unrelated concurrent inserts (see the
                    # module docstring) - not a real conflict, so retry the SAME table
                    await session.rollback()
                    if "deadlock detected" in str(getattr(e, "orig", e)).lower():
                        await asyncio.sleep(0.01 * (retry + 1))
                        continue
                    raise
                else:
                    await session.commit()
                    logging.info("Held reservation %s on table %s", reservation.id, table_name)
                    return {
                        "available": True,
                        "reservation_id": reservation.id,
                        "table_name": table_name,
                        "hold_expires_at": hold_expires_at.isoformat(),
                    }
            # exhausted retries on this table (repeated deadlocks) - fall through to the
            # next candidate table rather than looping forever

        return {"available": False, "reservation_id": None}


async def confirm_reservation(reservation_id: int) -> dict:
    """Idempotent: confirming an already-confirmed reservation just returns success again."""
    async with async_session() as session:
        reservation = await session.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError("No such reservation.")

        if reservation.status == RES_CONFIRMED:
            return {"confirmed": True, "reservation_id": reservation.id}

        if reservation.status != RES_HELD:
            raise ValueError(f"Reservation is '{reservation.status}', not held - can't confirm.")

        if reservation.hold_expires_at and reservation.hold_expires_at < datetime.now(UTC):
            reservation.status = RES_EXPIRED
            await session.commit()
            raise ValueError("That hold has expired. Please check availability again.")

        reservation.status = RES_CONFIRMED
        reservation.hold_expires_at = None
        await session.commit()
        logging.info("Confirmed reservation %s", reservation.id)
        return {"confirmed": True, "reservation_id": reservation.id}


async def cancel_reservation(reservation_id: int) -> dict:
    """Idempotent: cancelling an already-cancelled/expired reservation is a no-op success."""
    async with async_session() as session:
        reservation = await session.get(Reservation, reservation_id)
        if reservation is None:
            raise ValueError("No such reservation.")
        if reservation.status in (RES_CANCELLED, RES_EXPIRED):
            return {"cancelled": True, "reservation_id": reservation.id}
        reservation.status = RES_CANCELLED
        await session.commit()
        logging.info("Cancelled reservation %s", reservation.id)
        return {"cancelled": True, "reservation_id": reservation.id}


async def lookup_reservation(
    phone: str | None = None, reservation_id: int | None = None, limit: int = 10
) -> dict:
    """Looks up reservations by phone and/or id, in ANY status - including cancelled and
    expired - so "what happened to my booking?" after a cancellation still gets an answer
    instead of an empty list. Most recently created first, capped at `limit`."""
    if not phone and not reservation_id:
        raise ValueError("Provide a phone number or a reservation id.")

    async with async_session() as session:
        await _expire_old_holds(session)  # so a stale 'held' row reports as 'expired', not 'held'
        await session.commit()

        query = select(Reservation)
        if reservation_id:
            query = query.where(Reservation.id == reservation_id)
        if phone:
            query = query.where(Reservation.phone == phone)
        query = query.order_by(Reservation.created_at.desc()).limit(limit)

        reservations = (await session.execute(query)).scalars().all()
        return {
            "reservations": [
                {
                    "id": r.id,
                    "table_id": r.table_id,
                    "customer_name": r.customer_name,
                    "party_size": r.party_size,
                    "starts_at": r.starts_at.isoformat(),
                    "status": r.status,
                }
                for r in reservations
            ]
        }
