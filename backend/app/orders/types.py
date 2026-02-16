"""Order domain types shared across the order management system.

Frozen dataclasses for value objects. All monetary values use Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.broker.types import OrderType, Side


class OrderState(str, Enum):
    """Local order lifecycle states."""

    PENDING_SUBMIT = "pending_submit"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    SUBMIT_FAILED = "submit_failed"


TERMINAL_STATES = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.EXPIRED,
        OrderState.REJECTED,
        OrderState.SUBMIT_FAILED,
    }
)


class OrderRole(str, Enum):
    """Purpose of an order within a trade lifecycle."""

    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    EXIT_MARKET = "exit_market"


@dataclass(frozen=True)
class Signal:
    """Strategy output -- request to open a position."""

    symbol: str
    side: Side
    entry_price: Decimal
    stop_loss_price: Decimal
    order_type: OrderType
    strategy_name: str
    timestamp: datetime


@dataclass(frozen=True)
class RiskApproval:
    """Risk Manager decision on a signal."""

    approved: bool
    qty: Decimal
    reason: str


@dataclass(frozen=True)
class SubmitResult:
    """Result of submitting an entry order."""

    local_id: str
    correlation_id: str
    state: OrderState
    error: str
