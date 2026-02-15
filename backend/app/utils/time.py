"""UTC helpers and market calendar wrapper.

All times are UTC. The market calendar uses exchange-calendars
for NYSE (XNYS) with proper DST handling.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import exchange_calendars as xcals

NYSE_CALENDAR_NAME = "XNYS"

# Lazy-loaded singleton - exchange_calendars loads the full date range
# on init, so we only do it once.
_calendar: xcals.ExchangeCalendar | None = None


def _get_calendar() -> xcals.ExchangeCalendar:
    """Get or create the NYSE calendar singleton."""
    global _calendar
    if _calendar is None:
        _calendar = xcals.get_calendar(NYSE_CALENDAR_NAME)
    return _calendar


def utc_now() -> datetime:
    """Return the current UTC datetime, timezone-aware."""
    return datetime.now(UTC)


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with microsecond precision and Z suffix.

    Output format: YYYY-MM-DDTHH:MM:SS.ffffffZ
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_timestamp(s: str) -> datetime:
    """Parse an ISO 8601 timestamp with Z suffix back to UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def is_trading_day(d: date) -> bool:
    """Check if the given date is a NYSE trading day."""
    cal = _get_calendar()
    import pandas as pd

    ts = pd.Timestamp(d)
    return bool(cal.is_session(ts))


def is_half_day(d: date) -> bool:
    """Check if the given date is a NYSE half-day (early close)."""
    if not is_trading_day(d):
        return False
    cal = _get_calendar()
    import pandas as pd

    ts = pd.Timestamp(d)
    open_time = cal.session_open(ts)
    close_time = cal.session_close(ts)
    # Regular session is 6.5 hours; half-day is 3.5 hours
    duration = (close_time - open_time).total_seconds() / 3600
    return bool(duration < 5.0)


def market_open(d: date) -> datetime:
    """Get the UTC market open time for a given trading day.

    Raises:
        ValueError: If the date is not a trading day.
    """
    if not is_trading_day(d):
        raise ValueError(f"{d} is not a trading day")
    cal = _get_calendar()
    import pandas as pd

    ts = pd.Timestamp(d)
    open_ts = cal.session_open(ts)
    result: datetime = open_ts.to_pydatetime().replace(tzinfo=UTC)
    return result


def market_close(d: date) -> datetime:
    """Get the UTC market close time for a given trading day.

    Raises:
        ValueError: If the date is not a trading day.
    """
    if not is_trading_day(d):
        raise ValueError(f"{d} is not a trading day")
    cal = _get_calendar()
    import pandas as pd

    ts = pd.Timestamp(d)
    close_ts = cal.session_close(ts)
    result: datetime = close_ts.to_pydatetime().replace(tzinfo=UTC)
    return result


def is_market_open(dt: datetime) -> bool:
    """Check if the market is open at the given UTC datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    d = dt.date()
    if not is_trading_day(d):
        return False
    open_dt = market_open(d)
    close_dt = market_close(d)
    return open_dt <= dt < close_dt


def next_market_open(dt: datetime) -> datetime:
    """Get the next market open time from the given UTC datetime.

    If the market hasn't opened yet today, returns today's open.
    Otherwise returns the next trading day's open.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    d = dt.date()

    # Check if today is a trading day and market hasn't opened yet
    if is_trading_day(d):
        today_open = market_open(d)
        if dt < today_open:
            return today_open

    # Find next trading day
    cal = _get_calendar()
    import pandas as pd

    # Search forward up to 10 days (covers weekends + holidays)
    for i in range(1, 11):
        next_date = d + timedelta(days=i)
        ts = pd.Timestamp(next_date)
        if cal.is_session(ts):
            return market_open(next_date)

    raise ValueError(f"No trading day found within 10 days of {d}")
