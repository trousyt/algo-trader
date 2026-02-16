"""Shared test factories for creating domain objects.

Provides make_bar(), make_green_bar(), make_red_bar() with sensible
defaults so tests can focus on the values they care about.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.broker.types import AccountInfo, Bar, OrderType, Side
from app.orders.types import Signal

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


def make_signal(
    *,
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    entry_price: Decimal = Decimal("155.20"),
    stop_loss_price: Decimal = Decimal("154.70"),
    order_type: OrderType = OrderType.STOP,
    strategy_name: str = "velez",
    timestamp: datetime = _DEFAULT_TIMESTAMP,
) -> Signal:
    """Create a Signal with sensible defaults."""
    return Signal(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        order_type=order_type,
        strategy_name=strategy_name,
        timestamp=timestamp,
    )


def make_account_info(
    *,
    equity: Decimal = Decimal("25000"),
    cash: Decimal = Decimal("25000"),
    buying_power: Decimal = Decimal("50000"),
    portfolio_value: Decimal = Decimal("25000"),
    day_trade_count: int = 0,
    pattern_day_trader: bool = False,
) -> AccountInfo:
    """Create an AccountInfo with sensible defaults."""
    return AccountInfo(
        equity=equity,
        cash=cash,
        buying_power=buying_power,
        portfolio_value=portfolio_value,
        day_trade_count=day_trade_count,
        pattern_day_trader=pattern_day_trader,
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
