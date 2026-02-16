"""Simulated broker for backtesting — implements BrokerAdapter protocol.

Maintains in-memory order book, position tracking, and account state.
Fill simulation uses configurable slippage with bar-boundary clamping.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Self

import structlog

from app.broker.types import (
    AccountInfo,
    Bar,
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TradeUpdate,
)
from app.orders.types import OrderRole

log = structlog.get_logger()

_ZERO = Decimal("0")
_MIN_FILL_PRICE = Decimal("0.01")
_VOLUME_WARN_FRACTION = Decimal("0.10")


@dataclass
class _PendingOrder:
    """Internal pending order tracking."""

    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    order_type: OrderType
    stop_price: Decimal | None
    limit_price: Decimal | None
    role: OrderRole
    candles_since: int = 0


@dataclass
class _SimPosition:
    """Internal simulated position tracking."""

    symbol: str
    qty: Decimal
    avg_entry_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    opened_at: datetime = field(default_factory=lambda: datetime.min)


@dataclass(frozen=True)
class Fill:
    """Result of a simulated fill."""

    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    fill_price: Decimal
    timestamp: datetime
    order_role: OrderRole


class BacktestExecution:
    """Simulated broker for backtesting. Implements BrokerAdapter protocol.

    Backtest-specific methods (process_bar, update_market_prices, etc.) are
    called by BacktestRunner. BrokerAdapter protocol methods provide protocol
    compliance.
    """

    def __init__(
        self,
        initial_capital: Decimal,
        slippage_per_share: Decimal = Decimal("0.01"),
    ) -> None:
        self._cash = initial_capital
        self._slippage = slippage_per_share

        # Order book
        self._pending_orders: dict[str, _PendingOrder] = {}
        self._next_order_id: int = 0

        # Position tracking
        self._positions: dict[str, _SimPosition] = {}
        self._closed_positions: dict[str, _SimPosition] = {}

        # Runner coordination
        self._planned_stops: dict[str, Decimal] = {}
        self._entry_filled_this_bar: set[str] = set()

        # Filled orders for protocol compliance
        self._filled_orders: list[OrderStatus] = []

    # ------------------------------------------------------------------
    # Sync properties for hot loop (avoid async overhead)
    # ------------------------------------------------------------------

    @property
    def equity(self) -> Decimal:
        """Cash + sum of position market values."""
        return self._cash + sum(p.market_value for p in self._positions.values())

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    # ------------------------------------------------------------------
    # Backtest-specific methods (called by BacktestRunner)
    # ------------------------------------------------------------------

    def process_bar(self, bar: Bar) -> list[Fill]:
        """Check pending orders against this bar. Returns fills.

        Priority: stop-losses first, then entries, then market orders.
        """
        self._entry_filled_this_bar.clear()
        fills: list[Fill] = []

        # Collect pending orders for this symbol
        symbol_orders = [
            o for o in self._pending_orders.values() if o.symbol == bar.symbol
        ]
        if not symbol_orders:
            return fills

        # Sort: stop-losses first, entries second, market third
        stop_losses = [
            o
            for o in symbol_orders
            if o.side == Side.SELL and o.order_type == OrderType.STOP
        ]
        entries = [
            o
            for o in symbol_orders
            if o.side == Side.BUY and o.order_type == OrderType.STOP
        ]
        markets = [o for o in symbol_orders if o.order_type == OrderType.MARKET]

        for order in stop_losses:
            fill = self._try_fill_stop_sell(order, bar)
            if fill is not None:
                fills.append(fill)

        for order in entries:
            fill = self._try_fill_stop_buy(order, bar)
            if fill is not None:
                fills.append(fill)

        for order in markets:
            fill = self._try_fill_market(order, bar)
            if fill is not None:
                fills.append(fill)

        return fills

    def update_market_prices(self, bar: Bar) -> None:
        """Update position unrealized P&L from latest bar close."""
        pos = self._positions.get(bar.symbol)
        if pos is None:
            return
        pos.market_value = pos.qty * bar.close
        pos.unrealized_pl = (bar.close - pos.avg_entry_price) * pos.qty

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions

    def get_position(self, symbol: str) -> Position:
        """Get position as broker.types.Position for strategy evaluation."""
        pos = self._positions[symbol]
        pct = (
            (pos.unrealized_pl / (pos.avg_entry_price * pos.qty)) * Decimal("100")
            if pos.avg_entry_price > _ZERO and pos.qty > _ZERO
            else _ZERO
        )
        return Position(
            symbol=pos.symbol,
            qty=pos.qty,
            side=Side.BUY,
            avg_entry_price=pos.avg_entry_price,
            market_value=pos.market_value,
            unrealized_pl=pos.unrealized_pl,
            unrealized_pl_pct=pct,
        )

    def get_closed_position(self, symbol: str) -> _SimPosition:
        """Get the most recently closed position (for trade recording)."""
        return self._closed_positions[symbol]

    def has_pending_entry(self, symbol: str) -> bool:
        return any(
            o.symbol == symbol and o.side == Side.BUY and o.role == OrderRole.ENTRY
            for o in self._pending_orders.values()
        )

    def cancel_pending_entry(self, symbol: str) -> None:
        """Cancel the pending buy-stop entry for a symbol."""
        to_remove = [
            oid
            for oid, o in self._pending_orders.items()
            if o.symbol == symbol and o.side == Side.BUY and o.role == OrderRole.ENTRY
        ]
        for oid in to_remove:
            del self._pending_orders[oid]

    def increment_candle_count(self, symbol: str) -> None:
        for o in self._pending_orders.values():
            if o.symbol == symbol and o.side == Side.BUY and o.role == OrderRole.ENTRY:
                o.candles_since += 1

    def candles_since_order(self, symbol: str) -> int:
        for o in self._pending_orders.values():
            if o.symbol == symbol and o.side == Side.BUY and o.role == OrderRole.ENTRY:
                return o.candles_since
        return 0

    def set_planned_stop(self, symbol: str, price: Decimal) -> None:
        self._planned_stops[symbol] = price

    def get_planned_stop(self, symbol: str) -> Decimal:
        return self._planned_stops[symbol]

    def update_stop(self, symbol: str, new_stop: Decimal) -> None:
        """Update the pending stop-loss order price for a symbol."""
        for o in self._pending_orders.values():
            if (
                o.symbol == symbol
                and o.side == Side.SELL
                and o.order_type == OrderType.STOP
            ):
                o.stop_price = new_stop
                return

    def cancel_all_pending(self) -> None:
        """Cancel all pending orders (EOD cleanup)."""
        self._pending_orders.clear()

    # ------------------------------------------------------------------
    # Fill simulation internals
    # ------------------------------------------------------------------

    def _try_fill_stop_buy(self, order: _PendingOrder, bar: Bar) -> Fill | None:
        """Buy-stop: triggers when bar.high >= stop_price."""
        assert order.stop_price is not None
        if bar.high < order.stop_price:
            return None

        base_price = max(bar.open, order.stop_price)
        fill_price = self._apply_slippage_buy(base_price, bar)

        self._entry_filled_this_bar.add(order.symbol)
        return self._execute_fill(order, fill_price, bar.timestamp)

    def _try_fill_stop_sell(self, order: _PendingOrder, bar: Bar) -> Fill | None:
        """Stop-loss: triggers when bar.low <= stop_price.

        Skip if this symbol had an entry fill this bar (same-bar prevention).
        """
        assert order.stop_price is not None

        # Same-bar prevention: don't trigger stop on the bar entry filled
        if order.symbol in self._entry_filled_this_bar:
            return None

        if bar.low > order.stop_price:
            return None

        base_price = min(bar.open, order.stop_price)
        fill_price = self._apply_slippage_sell(base_price, bar)

        return self._execute_fill(order, fill_price, bar.timestamp)

    def _try_fill_market(self, order: _PendingOrder, bar: Bar) -> Fill | None:
        """Market order: fills at open ± slippage."""
        if order.side == Side.BUY:
            fill_price = self._apply_slippage_buy(bar.open, bar)
        else:
            fill_price = self._apply_slippage_sell(bar.open, bar)

        return self._execute_fill(order, fill_price, bar.timestamp)

    def _apply_slippage_buy(self, base_price: Decimal, bar: Bar) -> Decimal:
        """Apply slippage for buys: price + slippage, clamped to bar.high."""
        price = base_price + self._slippage
        price = min(price, bar.high)
        return max(price, _MIN_FILL_PRICE)

    def _apply_slippage_sell(self, base_price: Decimal, bar: Bar) -> Decimal:
        """Apply slippage for sells: price - slippage, clamped to bar.low."""
        price = base_price - self._slippage
        price = max(price, bar.low)
        return max(price, _MIN_FILL_PRICE)

    def _execute_fill(
        self,
        order: _PendingOrder,
        fill_price: Decimal,
        timestamp: datetime,
    ) -> Fill:
        """Execute a fill: update positions, cash, remove order."""
        # Volume warning
        # (checked in process_bar context — bar not available here, skip for now)

        if order.side == Side.BUY:
            cost = order.qty * fill_price
            self._cash -= cost
            self._positions[order.symbol] = _SimPosition(
                symbol=order.symbol,
                qty=order.qty,
                avg_entry_price=fill_price,
                market_value=cost,
                unrealized_pl=_ZERO,
                opened_at=timestamp,
            )
        else:
            # Close position
            pos = self._positions.get(order.symbol)
            if pos is not None:
                proceeds = order.qty * fill_price
                self._cash += proceeds
                self._closed_positions[order.symbol] = pos
                del self._positions[order.symbol]

        # Remove from pending orders
        del self._pending_orders[order.order_id]

        # Record filled order status
        self._filled_orders.append(
            OrderStatus(
                broker_order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                order_type=order.order_type,
                status=BrokerOrderStatus.FILLED,
                filled_qty=order.qty,
                filled_avg_price=fill_price,
                submitted_at=timestamp,
            )
        )

        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            fill_price=fill_price,
            timestamp=timestamp,
            order_role=order.role,
        )

    def _next_id(self) -> str:
        self._next_order_id += 1
        return f"bt-{self._next_order_id}"

    def _infer_role(self, order: OrderRequest) -> OrderRole:
        """Infer the order role from side and type."""
        if order.side == Side.BUY:
            return OrderRole.ENTRY
        if order.order_type == OrderType.STOP:
            return OrderRole.STOP_LOSS
        return OrderRole.EXIT_MARKET

    # ------------------------------------------------------------------
    # BrokerAdapter protocol methods (all 13)
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        """Add order to pending book. Returns ACCEPTED status."""
        oid = self._next_id()
        role = self._infer_role(order)

        self._pending_orders[oid] = _PendingOrder(
            order_id=oid,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            stop_price=order.stop_price,
            limit_price=order.limit_price,
            role=role,
        )

        return OrderStatus(
            broker_order_id=oid,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            status=BrokerOrderStatus.ACCEPTED,
            filled_qty=_ZERO,
            filled_avg_price=None,
            submitted_at=datetime.min,
        )

    async def submit_bracket_order(
        self,
        bracket: BracketOrderRequest,
    ) -> OrderStatus:
        """Not used in backtesting — submit entry and stop separately."""
        raise NotImplementedError("Bracket orders not supported in backtest")

    async def cancel_order(self, broker_order_id: str) -> None:
        self._pending_orders.pop(broker_order_id, None)

    async def replace_order(
        self,
        broker_order_id: str,
        qty: Decimal | None = None,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderStatus:
        """Modify pending order in-place."""
        order = self._pending_orders[broker_order_id]
        if qty is not None:
            order.qty = qty
        if limit_price is not None:
            order.limit_price = limit_price
        if stop_price is not None:
            order.stop_price = stop_price

        return OrderStatus(
            broker_order_id=broker_order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            status=BrokerOrderStatus.ACCEPTED,
            filled_qty=_ZERO,
            filled_avg_price=None,
            submitted_at=datetime.min,
        )

    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """Check pending or filled orders."""
        pending = self._pending_orders.get(broker_order_id)
        if pending is not None:
            return OrderStatus(
                broker_order_id=pending.order_id,
                symbol=pending.symbol,
                side=pending.side,
                qty=pending.qty,
                order_type=pending.order_type,
                status=BrokerOrderStatus.ACCEPTED,
                filled_qty=_ZERO,
                filled_avg_price=None,
                submitted_at=datetime.min,
            )
        for filled in self._filled_orders:
            if filled.broker_order_id == broker_order_id:
                return filled
        raise KeyError(f"Order not found: {broker_order_id}")

    async def get_positions(self) -> list[Position]:
        return [self.get_position(sym) for sym in self._positions]

    async def get_account(self) -> AccountInfo:
        return AccountInfo(
            equity=self.equity,
            cash=self._cash,
            buying_power=self._cash,
            portfolio_value=self.equity,
            day_trade_count=0,
            pattern_day_trader=False,
        )

    async def get_open_orders(self) -> list[OrderStatus]:
        return [
            OrderStatus(
                broker_order_id=o.order_id,
                symbol=o.symbol,
                side=o.side,
                qty=o.qty,
                order_type=o.order_type,
                status=BrokerOrderStatus.ACCEPTED,
                filled_qty=_ZERO,
                filled_avg_price=None,
                submitted_at=datetime.min,
            )
            for o in self._pending_orders.values()
        ]

    async def get_recent_orders(
        self,
        since_hours: int = 24,
    ) -> list[OrderStatus]:
        return list(self._filled_orders)

    async def subscribe_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        """No-op for backtesting — runner calls process_bar directly."""
        return _empty_iterator()

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


async def _empty_iterator() -> AsyncIterator[TradeUpdate]:
    """Empty async iterator for subscribe_trade_updates."""
    return
    yield  # Make it an async generator  # pragma: no cover
