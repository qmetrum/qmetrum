"""UTC time handling for everything that is persisted or served.

The rule this module enforces: **every instant in this service is timezone-aware
UTC in Python, and naive UTC on disk.**

Why it matters. The service used to call ``datetime.utcnow()``, which returns a
*naive* datetime — the value is UTC, but it carries no tzinfo. Pydantic then
serialised it as ``"2026-07-29T14:54:14.123456"``, with no timezone designator.
Per the ECMAScript spec a date-time string without an offset is parsed as LOCAL
time, so every browser silently shifted our timestamps by the viewer's UTC
offset: a freshly triggered alert read "2h ago" the moment it arrived.

``utcnow()`` returns an aware value, so ``.isoformat()`` and Pydantic both emit
an explicit offset and no client has to guess.

The catch, and why ``UtcDateTime`` exists. SQLite and a plain ``DateTime``
column silently discard tzinfo on write and hand back naive values on read.
Mixing those with aware values raises ``TypeError: can't compare offset-naive
and offset-aware datetimes`` at runtime. ``UtcDateTime`` closes that gap from
both sides: it strips tzinfo on the way in (so the on-disk format is byte-for-byte
what it always was — no migration, and rows written before this change still
read back correctly) and re-attaches UTC on the way out. Everything the ORM
returns is therefore aware, including rows written years ago.

Note what is deliberately NOT converted: columns holding a *calendar date*
(a trading session, a training-window boundary) rather than an instant. Those
are midnight-anchored dates whose timezone is meaningless, and they flow into
pandas, where mixing tz-aware and tz-naive values is its own class of bug.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """The current instant, as timezone-aware UTC.

    Drop-in replacement for ``datetime.utcnow()``, which returned a naive value
    and is deprecated from Python 3.12 for exactly this reason.
    """
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce a datetime to aware UTC, assuming naive input is already UTC.

    Use at boundaries where a datetime arrives from outside this service —
    parsed from a request body, a cached JSON blob, or a vendor payload — before
    comparing it against anything from the database or from :func:`utcnow`.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: Optional[datetime]) -> Optional[str]:
    """Serialise a datetime as an unambiguous UTC ISO-8601 string, or None.

    Naive input is treated as UTC, matching how this service has always stored
    timestamps, so the output always carries an offset a client can trust.
    """
    coerced = as_utc(value)
    return None if coerced is None else coerced.isoformat()


class UtcDateTime(TypeDecorator):
    """A ``DateTime`` column that always yields timezone-aware UTC.

    Storage is unchanged — naive UTC, exactly as before — so this needs no
    migration and no backfill; it only changes what Python sees.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        # Already naive: it was UTC by this service's convention.
        return value

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
