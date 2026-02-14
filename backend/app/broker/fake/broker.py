"""FakeBrokerAdapter — in-memory order execution for testing.

Lightweight implementation of BrokerAdapter for unit testing
downstream components (order manager, risk manager, etc.).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Self

from app.broker.types import (
    AccountInfo,
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TradeUpdate,
)


class FakeBrokerAdapter:
    """In-memory BrokerAdapter for testing.

    Supply canned positions/account at construction, or inspect
    submitted_orders after test execution.
    """

    def __init__(
        self,
        positions: list[Position] | None = None,
        account: AccountInfo | None = None,
    ) -> None:
        self._positions: list[Position] = positions if positions is not None else []
        self._account: AccountInfo = account or AccountInfo(
            equity=Decimal("100000"),
            cash=Decimal("100000"),
            buying_power=Decimal("200000"),
            portfolio_value=Decimal("100000"),
            day_trade_count=0,
            pattern_day_trader=False,
        )
        self._trade_queue: asyncio.Queue[TradeUpdate] = asyncio.Queue()
        self._connected = False
        self.submitted_orders: list[OrderRequest | BracketOrderRequest] = []

    def push_trade_update(self, update: TradeUpdate) -> None:
        """Push a trade update into the streaming queue."""
        self._trade_queue.put_nowait(update)

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        self.submitted_orders.append(order)
        return OrderStatus(
            broker_order_id=str(uuid.uuid4()),
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            status=BrokerOrderStatus.ACCEPTED,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            submitted_at=datetime.now(tz=UTC),
        )

    async def submit_bracket_order(
        self,
        bracket: BracketOrderRequest,
    ) -> OrderStatus:
        self.submitted_orders.append(bracket)
        return OrderStatus(
            broker_order_id=str(uuid.uuid4()),
            symbol=bracket.symbol,
            side=bracket.side,
            qty=bracket.qty,
            order_type=bracket.order_type,
            status=BrokerOrderStatus.ACCEPTED,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            submitted_at=datetime.now(tz=UTC),
        )

    async def cancel_order(self, broker_order_id: str) -> None:
        pass

    async def replace_order(
        self,
        broker_order_id: str,
        qty: Decimal | None = None,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderStatus:
        return OrderStatus(
            broker_order_id=broker_order_id,
            symbol="UNKNOWN",
            side=Side.BUY,
            qty=qty or Decimal("0"),
            order_type=OrderType.LIMIT,
            status=BrokerOrderStatus.REPLACED,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            submitted_at=datetime.now(tz=UTC),
        )

    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        return OrderStatus(
            broker_order_id=broker_order_id,
            symbol="UNKNOWN",
            side=Side.BUY,
            qty=Decimal("0"),
            order_type=OrderType.MARKET,
            status=BrokerOrderStatus.NEW,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            submitted_at=datetime.now(tz=UTC),
        )

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def get_account(self) -> AccountInfo:
        return self._account

    async def get_open_orders(self) -> list[OrderStatus]:
        return []

    async def get_recent_orders(
        self,
        since_hours: int = 24,
    ) -> list[OrderStatus]:
        return []

    async def subscribe_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        return self._trade_iterator()

    async def _trade_iterator(self) -> AsyncIterator[TradeUpdate]:
        while self._connected:
            try:
                update = await asyncio.wait_for(
                    self._trade_queue.get(),
                    timeout=0.1,
                )
                yield update
            except TimeoutError:
                continue

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        await self.disconnect()
