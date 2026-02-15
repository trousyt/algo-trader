"""Shared test factories for creating domain objects.

Provides make_bar(), make_green_bar(), make_red_bar() with sensible
defaults so tests can focus on the values they care about.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.broker.types import Bar

# Default timestamp: a regular trading day at 10:00 AM ET (14:00 UTC)
_DEFAULT_TIMESTAMP = datetime(2026, 2, 10, 15, 0, tzinfo=UTC)


def make_bar(
    *,
    symbol: str = "AAPL",
    timestamp: datetime = _DEFAULT_TIMESTAMP,
    open: Decimal = Decimal("150.00"),
    high: Decimal = Decimal("151.00"),
    low: Decimal = Decimal("149.00"),
    close: Decimal = Decimal("150.50"),
    volume: int = 1000,
) -> Bar:
    """Create a Bar with sensible defaults."""
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_green_bar(
    *,
    symbol: str = "AAPL",
    timestamp: datetime = _DEFAULT_TIMESTAMP,
    open: Decimal = Decimal("150.00"),
    close: Decimal = Decimal("152.00"),
    low: Decimal | None = None,
    high: Decimal | None = None,
    volume: int = 1000,
) -> Bar:
    """Create a green bar (close > open) with sensible defaults."""
    if low is None:
        low = open - Decimal("0.50")
    if high is None:
        high = close + Decimal("0.50")
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_red_bar(
    *,
    symbol: str = "AAPL",
    timestamp: datetime = _DEFAULT_TIMESTAMP,
    open: Decimal = Decimal("152.00"),
    close: Decimal = Decimal("150.00"),
    low: Decimal | None = None,
    high: Decimal | None = None,
    volume: int = 1000,
) -> Bar:
    """Create a red bar (close < open) with sensible defaults."""
    if low is None:
        low = close - Decimal("0.50")
    if high is None:
        high = open + Decimal("0.50")
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
