"""Tests for UTC helpers and market calendar wrapper.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.utils.time import (
    format_timestamp,
    is_half_day,
    is_market_open,
    is_trading_day,
    market_close,
    market_open,
    next_market_open,
    parse_timestamp,
    utc_now,
)


class TestUtcHelpers:
    """Test UTC time helpers."""

    def test_utc_now_is_utc(self) -> None:
        dt = utc_now()
        assert dt.tzinfo is not None
        assert dt.tzinfo == UTC

    def test_format_timestamp_z_suffix(self) -> None:
        dt = datetime(2026, 2, 14, 12, 30, 45, 123456, tzinfo=UTC)
        result = format_timestamp(dt)
        assert result.endswith("Z")
        assert result == "2026-02-14T12:30:45.123456Z"

    def test_parse_timestamp_roundtrip(self) -> None:
        dt = datetime(2026, 2, 14, 12, 30, 45, 123456, tzinfo=UTC)
        formatted = format_timestamp(dt)
        parsed = parse_timestamp(formatted)
        assert parsed == dt
        assert parsed.tzinfo == UTC


class TestTradingDay:
    """Test trading day detection."""

    def test_regular_friday_is_trading_day(self) -> None:
        """2026-02-13 is a Friday - regular trading day."""
        assert is_trading_day(date(2026, 2, 13)) is True

    def test_saturday_is_not_trading_day(self) -> None:
        assert is_trading_day(date(2026, 2, 14)) is False

    def test_sunday_is_not_trading_day(self) -> None:
        assert is_trading_day(date(2026, 2, 15)) is False

    def test_new_years_not_trading_day(self) -> None:
        """Jan 1, 2026 is New Year's Day."""
        assert is_trading_day(date(2026, 1, 1)) is False

    def test_presidents_day_not_trading_day(self) -> None:
        """2026-02-16 is Presidents' Day (3rd Monday in Feb)."""
        assert is_trading_day(date(2026, 2, 16)) is False

    def test_regular_tuesday_is_trading_day(self) -> None:
        assert is_trading_day(date(2026, 2, 17)) is True


class TestMarketHours:
    """Test market open/close times."""

    def test_market_open_regular_day(self) -> None:
        """Regular day opens at 14:30 UTC (9:30 AM ET in winter)."""
        dt = market_open(date(2026, 2, 13))
        assert dt.hour == 14
        assert dt.minute == 30
        assert dt.tzinfo == UTC

    def test_market_close_regular_day(self) -> None:
        """Regular day closes at 21:00 UTC (4:00 PM ET in winter)."""
        dt = market_close(date(2026, 2, 13))
        assert dt.hour == 21
        assert dt.minute == 0
        assert dt.tzinfo == UTC

    def test_market_open_not_on_weekend(self) -> None:
        """market_open raises for non-trading days."""
        with pytest.raises(ValueError):
            market_open(date(2026, 2, 14))

    def test_market_close_not_on_weekend(self) -> None:
        with pytest.raises(ValueError):
            market_close(date(2026, 2, 14))


class TestHalfDay:
    """Test half-day detection."""

    def test_day_after_thanksgiving_is_half_day(self) -> None:
        """Black Friday 2026 = Nov 27."""
        assert is_half_day(date(2026, 11, 27)) is True

    def test_regular_day_is_not_half_day(self) -> None:
        assert is_half_day(date(2026, 2, 13)) is False

    def test_half_day_early_close(self) -> None:
        """Half-day closes at 18:00 UTC (1:00 PM ET in winter)."""
        dt = market_close(date(2026, 11, 27))
        assert dt.hour == 18
        assert dt.minute == 0


class TestIsMarketOpen:
    """Test real-time market open check."""

    def test_during_market_hours(self) -> None:
        """15:00 UTC on a Friday in Feb = 10:00 AM ET = market open."""
        dt = datetime(2026, 2, 13, 15, 0, 0, tzinfo=UTC)
        assert is_market_open(dt) is True

    def test_after_market_close(self) -> None:
        """22:00 UTC = 5:00 PM ET = market closed."""
        dt = datetime(2026, 2, 13, 22, 0, 0, tzinfo=UTC)
        assert is_market_open(dt) is False

    def test_before_market_open(self) -> None:
        """13:00 UTC = 8:00 AM ET = market not yet open."""
        dt = datetime(2026, 2, 13, 13, 0, 0, tzinfo=UTC)
        assert is_market_open(dt) is False

    def test_weekend(self) -> None:
        dt = datetime(2026, 2, 14, 15, 0, 0, tzinfo=UTC)
        assert is_market_open(dt) is False


class TestNextMarketOpen:
    """Test next market open calculation."""

    def test_from_weekend(self) -> None:
        """From Saturday Feb 14, next open is Tuesday Feb 17 (Presidents' Day Mon)."""
        dt = datetime(2026, 2, 14, 12, 0, 0, tzinfo=UTC)
        result = next_market_open(dt)
        assert result.date() == date(2026, 2, 17)  # Tuesday (Mon is holiday)
        assert result.hour == 14
        assert result.minute == 30

    def test_from_after_close(self) -> None:
        """From Friday after close, next open is Tuesday (Presidents' Day Mon)."""
        dt = datetime(2026, 2, 13, 22, 0, 0, tzinfo=UTC)
        result = next_market_open(dt)
        assert result.date() == date(2026, 2, 17)  # Tuesday

    def test_from_before_open_same_day(self) -> None:
        """From Friday before open, next open is same day."""
        dt = datetime(2026, 2, 13, 10, 0, 0, tzinfo=UTC)
        result = next_market_open(dt)
        assert result.date() == date(2026, 2, 13)


class TestDstTransition:
    """Test DST transition handling (March 2026)."""

    def test_market_open_after_spring_forward(self) -> None:
        """After DST (March 9, 2026), market opens at 13:30 UTC (9:30 AM EDT)."""
        # March 9, 2026 is a Monday - clocks spring forward
        # But DST starts Sunday March 8, so Monday March 9 is first EDT trading day
        dt = market_open(date(2026, 3, 9))
        assert dt.hour == 13
        assert dt.minute == 30

    def test_market_close_after_spring_forward(self) -> None:
        """After DST, market closes at 20:00 UTC (4:00 PM EDT)."""
        dt = market_close(date(2026, 3, 9))
        assert dt.hour == 20
        assert dt.minute == 0
