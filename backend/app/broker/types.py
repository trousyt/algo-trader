"""Broker domain types shared across the trading system.

Frozen dataclasses for value objects, mutable dataclasses for state objects.
All monetary values use Decimal (never float).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    """Order side — matches Alpaca SDK OrderSide values."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class TimeInForce(str, Enum):
    """Time-in-force for orders."""

    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"


class BrokerOrderStatus(str, Enum):
    """Order status as reported by the broker."""

    NEW = "new"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    PENDING_CANCEL = "pending_cancel"
    REPLACED = "replaced"


class TradeEventType(str, Enum):
    """Trade update event types from the broker stream.

    Only actionable events are included. Informational events
    (PENDING_NEW, PENDING_REPLACE, RESTATED) are filtered at the mapper layer.
    """

    NEW = "new"
    ACCEPTED = "accepted"
    FILL = "fill"
    PARTIAL_FILL = "partial_fill"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"


# --- Value Objects (frozen) ---


@dataclass(frozen=True)
class Bar:
    """OHLCV bar (candlestick) data."""

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Quote:
    """Current quote with bid/ask/last prices."""

    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal
    bid_size: int
    ask_size: int
    volume: int


@dataclass(frozen=True)
class OrderRequest:
    """Immutable order request — describes what to submit to the broker."""

    symbol: str
    side: Side
    qty: Decimal
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    trail_price: Decimal | None = None
    trail_percent: Decimal | None = None


@dataclass(frozen=True)
class BracketOrderRequest:
    """Immutable bracket order — entry with stop-loss and optional take-profit."""

    symbol: str
    side: Side
    qty: Decimal
    order_type: OrderType
    stop_loss_price: Decimal
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Decimal | None = None
    take_profit_price: Decimal | None = None


# --- State Objects (mutable) ---


@dataclass
class Position:
    """Current position in a symbol."""

    symbol: str
    qty: Decimal
    side: Side
    avg_entry_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    unrealized_pl_pct: Decimal


@dataclass
class AccountInfo:
    """Brokerage account summary."""

    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    portfolio_value: Decimal
    day_trade_count: int
    pattern_day_trader: bool


@dataclass
class OrderStatus:
    """Current status of an order as reported by the broker."""

    broker_order_id: str
    symbol: str
    side: Side
    qty: Decimal
    order_type: OrderType
    status: BrokerOrderStatus
    filled_qty: Decimal
    filled_avg_price: Decimal | None
    submitted_at: datetime


@dataclass
class TradeUpdate:
    """Trade update event from the broker stream."""

    event: TradeEventType
    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    filled_qty: Decimal
    filled_avg_price: Decimal | None
    timestamp: datetime
