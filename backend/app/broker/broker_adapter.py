"""BrokerAdapter protocol — abstract interface for order execution.

All broker implementations (Alpaca, IBKR, fake) must satisfy this protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.broker.types import (
    AccountInfo,
    BracketOrderRequest,
    OrderRequest,
    OrderStatus,
    Position,
    TradeUpdate,
)


@runtime_checkable
class BrokerAdapter(Protocol):
    """Async interface for order execution and account management.

    Implementations must support ``async with`` for lifecycle management.
    ``subscribe_trade_updates`` can only be called once per connection.
    """

    async def connect(self) -> None:
        """Establish connection to the broker."""
        ...

    async def disconnect(self) -> None:
        """Tear down connection and release resources."""
        ...

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        """Submit a single order (market, limit, stop, trailing stop)."""
        ...

    async def submit_bracket_order(
        self,
        bracket: BracketOrderRequest,
    ) -> OrderStatus:
        """Submit a bracket order (entry + stop-loss + optional take-profit)."""
        ...

    async def cancel_order(self, broker_order_id: str) -> None:
        """Cancel an open order by broker order ID."""
        ...

    async def replace_order(
        self,
        broker_order_id: str,
        qty: Decimal | None = None,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderStatus:
        """Modify an existing order (atomic replace, not cancel-resubmit).

        Only non-None fields are updated. Maps to Alpaca PATCH /orders/{id}.
        """
        ...

    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """Get the current status of a specific order."""
        ...

    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        ...

    async def get_account(self) -> AccountInfo:
        """Get account summary (equity, cash, buying power, etc.)."""
        ...

    async def get_open_orders(self) -> list[OrderStatus]:
        """Get all currently open orders."""
        ...

    async def get_recent_orders(
        self,
        since_hours: int = 24,
    ) -> list[OrderStatus]:
        """Get orders from the last N hours."""
        ...

    async def subscribe_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        """Start streaming trade update events.

        Can only be called once per connection. Returns an AsyncIterator
        that yields TradeUpdate objects as they arrive from the broker.
        """
        ...

    async def __aenter__(self) -> BrokerAdapter:
        """Connect on context manager entry."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Disconnect on context manager exit."""
        ...
