"""Order manager -- async lifecycle orchestrator.

Owns the full order lifecycle: submit, track fills, manage stop-losses,
handle exits, create trade records. All lifecycle events logged via structlog.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.broker_adapter import BrokerAdapter
from app.broker.types import (
    OrderRequest,
    OrderType,
    Side,
    TimeInForce,
    TradeEventType,
    TradeUpdate,
)
from app.models.order import OrderEventModel, OrderStateModel, TradeModel
from app.orders.state_machine import InvalidTransitionError, OrderStateMachine
from app.orders.types import (
    TERMINAL_STATES,
    OrderRole,
    OrderState,
    RiskApproval,
    Signal,
    SubmitResult,
)
from app.utils.time import format_timestamp, parse_timestamp, utc_now

log = structlog.get_logger()

# Maximum retry attempts for stop-loss submission after entry fill
_STOP_RETRY_MAX = 3
_STOP_RETRY_DELAY = 1.0


def _trade_side_from_entry(entry_side: Side) -> str:
    """Map entry order side to trade position side."""
    return {Side.BUY: "long", Side.SELL: "short"}[entry_side]


class OrderManager:
    """Async lifecycle manager for orders.

    Consumes Signals + RiskApprovals, submits to broker, processes
    TradeUpdate events, manages stop-losses, and creates Trade records.
    """

    def __init__(
        self,
        broker: BrokerAdapter,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._broker = broker
        self._session_factory = session_factory
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._candle_counts: dict[str, int] = {}  # local_id -> candles elapsed

    async def submit_entry(
        self,
        signal: Signal,
        approval: RiskApproval,
    ) -> SubmitResult:
        """Submit an entry order.

        Generates correlation_id internally. Creates OrderStateModel
        (PENDING_SUBMIT, role=ENTRY), submits via broker, transitions
        to SUBMITTED. On broker error -> SUBMIT_FAILED.
        """
        local_id = str(uuid4())
        correlation_id = str(uuid4())
        now = format_timestamp(utc_now())

        # Create order record in PENDING_SUBMIT
        async with self._session_factory() as session, session.begin():
            order = OrderStateModel(
                local_id=local_id,
                correlation_id=correlation_id,
                symbol=signal.symbol,
                side=signal.side.value,
                order_type=signal.order_type.value,
                order_role=OrderRole.ENTRY.value,
                strategy=signal.strategy_name,
                qty_requested=approval.qty,
                state=OrderState.PENDING_SUBMIT.value,
                created_at=now,
                updated_at=now,
            )
            session.add(order)

        log.info(
            "order_submitted",
            symbol=signal.symbol,
            local_id=local_id,
            role="entry",
            qty=str(approval.qty),
            price=str(signal.entry_price),
        )

        # Submit to broker
        try:
            status = await self._broker.submit_order(
                OrderRequest(
                    symbol=signal.symbol,
                    side=signal.side,
                    qty=approval.qty,
                    order_type=signal.order_type,
                    stop_price=signal.entry_price,
                    time_in_force=TimeInForce.DAY,
                )
            )
        except Exception as exc:
            await self._transition_order(
                local_id,
                OrderState.SUBMIT_FAILED,
                event_type="submit_failed",
                detail=str(exc),
            )
            return SubmitResult(
                local_id=local_id,
                correlation_id=correlation_id,
                state=OrderState.SUBMIT_FAILED,
                error=str(exc),
            )

        # Update with broker_id and transition to SUBMITTED
        await self._transition_order(
            local_id,
            OrderState.SUBMITTED,
            event_type="submitted",
            broker_id=status.broker_order_id,
        )

        # Track candle count for this pending entry
        self._candle_counts[local_id] = 0

        return SubmitResult(
            local_id=local_id,
            correlation_id=correlation_id,
            state=OrderState.SUBMITTED,
            error="",
        )

    async def handle_trade_update(self, update: TradeUpdate) -> None:
        """Process a fill/cancel/reject event from broker.

        Matches update.order_id to local OrderStateModel.broker_id.
        If no match: log warning and return.
        """
        order = await self._find_by_broker_id(update.order_id)
        if order is None:
            log.warning(
                "unknown_order_update",
                broker_order_id=update.order_id,
                event_type=update.event.value,
            )
            return

        if update.event == TradeEventType.FILL:
            await self._handle_fill(order, update)
        elif update.event == TradeEventType.PARTIAL_FILL:
            await self._handle_partial_fill(order, update)
        elif update.event == TradeEventType.CANCELED:
            await self._handle_canceled(order, update)
        elif update.event == TradeEventType.REJECTED:
            await self._handle_rejected(order, update)
        elif update.event == TradeEventType.EXPIRED:
            await self._handle_expired(order, update)
        elif update.event in (
            TradeEventType.NEW,
            TradeEventType.ACCEPTED,
        ):
            new_state = {
                TradeEventType.NEW: OrderState.SUBMITTED,
                TradeEventType.ACCEPTED: OrderState.ACCEPTED,
            }[update.event]
            await self._transition_order(
                order.local_id,
                new_state,
                event_type=update.event.value,
            )
        elif update.event == TradeEventType.REPLACED:
            # Handle replaced: update broker_id in-place
            await self._handle_replaced(order, update)

        # Signal any waiting cancel events
        event = self._cancel_events.get(update.order_id)
        if event is not None and update.event in (
            TradeEventType.CANCELED,
            TradeEventType.FILL,
        ):
            event.set()

    async def cancel_pending_entry(self, local_id: str) -> None:
        """Cancel an unfilled entry order (buy-stop expiry)."""
        order = await self._find_by_local_id(local_id)
        if order is None or order.broker_id is None:
            return
        if OrderState(order.state) in TERMINAL_STATES:
            return

        await self._broker.cancel_order(order.broker_id)
        self._candle_counts.pop(local_id, None)
        log.info(
            "order_canceled",
            symbol=order.symbol,
            local_id=local_id,
            reason="entry_expiry",
        )

    async def request_exit(
        self,
        symbol: str,
        correlation_id: str,
    ) -> None:
        """Strategy exit signal.

        Cancel stop -> asyncio.Event confirmation -> sell if holding.
        """
        stop_order = await self._find_active_stop(correlation_id)
        if stop_order is None:
            return

        if stop_order.broker_id is None:
            return

        # Register event for this broker order
        cancel_event = asyncio.Event()
        self._cancel_events[stop_order.broker_id] = cancel_event

        # Request cancellation
        await self._broker.cancel_order(stop_order.broker_id)
        log.info("stop_cancel_requested", broker_id=stop_order.broker_id)

        # Wait for broker confirmation
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=5.0)
        except TimeoutError:
            log.warning("stop_cancel_timeout", broker_id=stop_order.broker_id)
        finally:
            self._cancel_events.pop(stop_order.broker_id, None)

        # Check if we still hold the position
        positions = await self._broker.get_positions()
        position = next((p for p in positions if p.symbol == symbol), None)
        if position is not None and position.qty > Decimal("0"):
            await self._submit_market_exit(symbol, correlation_id, position.qty)

    async def update_stop_loss(
        self,
        correlation_id: str,
        new_stop_price: Decimal,
    ) -> None:
        """Update active stop-loss price via replace_order."""
        stop_order = await self._find_active_stop(correlation_id)
        if stop_order is None or stop_order.broker_id is None:
            return

        old_price = stop_order.avg_fill_price  # stored stop price
        try:
            status = await self._broker.replace_order(
                stop_order.broker_id,
                stop_price=new_stop_price,
            )
        except Exception:
            log.exception(
                "stop_replace_failed",
                broker_id=stop_order.broker_id,
            )
            return

        # In-place update: update broker_id if changed
        new_broker_id = status.broker_order_id
        if new_broker_id != stop_order.broker_id:
            async with self._session_factory() as session, session.begin():
                result = await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == stop_order.local_id,
                    )
                )
                db_order = result.scalar_one()
                old_broker_id = db_order.broker_id
                db_order.broker_id = new_broker_id
                db_order.updated_at = format_timestamp(utc_now())
                session.add(
                    OrderEventModel(
                        order_local_id=stop_order.local_id,
                        event_type="replaced",
                        old_state=db_order.state,
                        new_state=db_order.state,
                        broker_id=new_broker_id,
                        detail=f"old_broker_id={old_broker_id}",
                        recorded_at=format_timestamp(utc_now()),
                    )
                )

        log.info(
            "stop_moved",
            symbol=stop_order.symbol,
            old_price=str(old_price) if old_price else "unknown",
            new_price=str(new_stop_price),
        )

    async def on_candle(self, symbol: str) -> None:
        """Called each candle. Increments candle counter for pending entries."""
        for local_id in list(self._candle_counts.keys()):
            order = await self._find_by_local_id(local_id)
            if order is None:
                self._candle_counts.pop(local_id, None)
                continue
            if order.symbol != symbol:
                continue
            state = OrderState(order.state)
            if state in TERMINAL_STATES:
                self._candle_counts.pop(local_id, None)
                continue
            self._candle_counts[local_id] = self._candle_counts.get(local_id, 0) + 1

    def get_candles_since_order(self, local_id: str) -> int:
        """Get candle count for a pending entry."""
        return self._candle_counts.get(local_id, 0)

    async def cancel_all_pending(self) -> None:
        """Cancel all non-terminal entry orders. Called on startup."""
        async with self._session_factory() as session:
            terminal_values = [s.value for s in TERMINAL_STATES]
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.order_role == OrderRole.ENTRY.value,
                    OrderStateModel.state.notin_(terminal_values),
                )
            )
            orders = result.scalars().all()

        for order in orders:
            if order.broker_id is not None:
                try:
                    await self._broker.cancel_order(order.broker_id)
                except Exception:
                    log.exception(
                        "cancel_pending_failed",
                        local_id=order.local_id,
                    )

        self._candle_counts.clear()

    # --- Internal helpers ---

    async def _handle_fill(
        self,
        order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """Handle FILL event."""
        await self._transition_order(
            order.local_id,
            OrderState.FILLED,
            event_type="fill",
            qty_filled=update.filled_qty,
            fill_price=update.filled_avg_price,
        )

        log.info(
            "order_filled",
            symbol=order.symbol,
            local_id=order.local_id,
            qty=str(update.filled_qty),
            fill_price=str(update.filled_avg_price),
        )

        role = OrderRole(order.order_role)
        if role == OrderRole.ENTRY:
            self._candle_counts.pop(order.local_id, None)
            await self._submit_stop_loss_with_retry(order, update)
        elif role in (OrderRole.STOP_LOSS, OrderRole.EXIT_MARKET):
            await self._create_trade_record(order.correlation_id)

    async def _handle_partial_fill(
        self,
        order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """Handle PARTIAL_FILL event."""
        await self._transition_order(
            order.local_id,
            OrderState.PARTIALLY_FILLED,
            event_type="partial_fill",
            qty_filled=update.filled_qty,
            fill_price=update.filled_avg_price,
        )

        role = OrderRole(order.order_role)
        if role == OrderRole.ENTRY:
            # Submit or update stop-loss for filled qty
            await self._update_stop_for_partial(order, update)

    async def _handle_canceled(
        self,
        order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """Handle CANCELED event."""
        await self._transition_order(
            order.local_id,
            OrderState.CANCELED,
            event_type="canceled",
        )

        log.info(
            "order_canceled",
            symbol=order.symbol,
            local_id=order.local_id,
            reason="broker_canceled",
        )

        role = OrderRole(order.order_role)
        if role == OrderRole.ENTRY:
            self._candle_counts.pop(order.local_id, None)
            # If partial fill + cancel: close remaining at market
            refreshed = await self._find_by_local_id(order.local_id)
            filled = Decimal(str(refreshed.qty_filled)) if refreshed else Decimal("0")
            if refreshed is not None and filled > Decimal("0"):
                await self._handle_partial_cancel(refreshed)

    async def _handle_rejected(
        self,
        order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """Handle REJECTED event."""
        await self._transition_order(
            order.local_id,
            OrderState.REJECTED,
            event_type="rejected",
        )
        log.info(
            "order_rejected",
            symbol=order.symbol,
            local_id=order.local_id,
        )

    async def _handle_expired(
        self,
        order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """Handle EXPIRED event."""
        await self._transition_order(
            order.local_id,
            OrderState.EXPIRED,
            event_type="expired",
        )

    async def _handle_replaced(
        self,
        order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """Handle REPLACED event -- in-place broker_id update."""
        new_broker_id = update.order_id
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.local_id == order.local_id,
                )
            )
            db_order = result.scalar_one()
            old_broker_id = db_order.broker_id
            db_order.broker_id = new_broker_id
            db_order.updated_at = format_timestamp(utc_now())
            session.add(
                OrderEventModel(
                    order_local_id=order.local_id,
                    event_type="replaced",
                    old_state=db_order.state,
                    new_state=db_order.state,
                    broker_id=new_broker_id,
                    detail=f"old_broker_id={old_broker_id}",
                    recorded_at=format_timestamp(utc_now()),
                )
            )

    async def _submit_stop_loss_with_retry(
        self,
        entry_order: OrderStateModel,
        fill_update: TradeUpdate,
    ) -> None:
        """No-op. Stop-loss submission is TradingEngine's responsibility.

        TradingEngine._handle_entry_fill() calls submit_stop_loss() after
        entry fills. OrderManager does NOT submit stop-losses autonomously
        to avoid duplicate orders. See submit_stop_loss() for the real impl.
        """
        pass

    async def submit_stop_loss(
        self,
        correlation_id: str,
        symbol: str,
        qty: Decimal,
        stop_price: Decimal,
        parent_local_id: str,
        strategy_name: str,
    ) -> SubmitResult:
        """Submit a stop-loss order linked to an entry.

        Called by TradingEngine after entry fill. Retry 3x with
        backoff, market sell fallback on failure.
        """
        local_id = str(uuid4())
        now = format_timestamp(utc_now())

        # Create stop-loss record
        async with self._session_factory() as session, session.begin():
            order = OrderStateModel(
                local_id=local_id,
                correlation_id=correlation_id,
                symbol=symbol,
                side=Side.SELL.value,
                order_type=OrderType.STOP.value,
                order_role=OrderRole.STOP_LOSS.value,
                strategy=strategy_name,
                qty_requested=qty,
                parent_id=parent_local_id,
                state=OrderState.PENDING_SUBMIT.value,
                created_at=now,
                updated_at=now,
            )
            session.add(order)

        # Retry loop
        last_error = ""
        for attempt in range(_STOP_RETRY_MAX):
            try:
                status = await self._broker.submit_order(
                    OrderRequest(
                        symbol=symbol,
                        side=Side.SELL,
                        qty=qty,
                        order_type=OrderType.STOP,
                        stop_price=stop_price,
                        time_in_force=TimeInForce.GTC,
                    )
                )
                await self._transition_order(
                    local_id,
                    OrderState.SUBMITTED,
                    event_type="submitted",
                    broker_id=status.broker_order_id,
                )
                log.info(
                    "order_submitted",
                    symbol=symbol,
                    local_id=local_id,
                    role="stop_loss",
                    qty=str(qty),
                    price=str(stop_price),
                )
                return SubmitResult(
                    local_id=local_id,
                    correlation_id=correlation_id,
                    state=OrderState.SUBMITTED,
                    error="",
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < _STOP_RETRY_MAX - 1:
                    await asyncio.sleep(_STOP_RETRY_DELAY)

        # All retries failed: market sell fallback
        log.critical(
            "stop_fallback_market_sell",
            symbol=symbol,
            qty=str(qty),
            error=last_error,
        )
        await self._transition_order(
            local_id,
            OrderState.SUBMIT_FAILED,
            event_type="submit_failed",
            detail=last_error,
        )
        await self._submit_market_exit(symbol, correlation_id, qty)

        return SubmitResult(
            local_id=local_id,
            correlation_id=correlation_id,
            state=OrderState.SUBMIT_FAILED,
            error=last_error,
        )

    async def _update_stop_for_partial(
        self,
        entry_order: OrderStateModel,
        update: TradeUpdate,
    ) -> None:
        """On partial fill: submit or update stop-loss for filled qty."""
        existing_stop = await self._find_active_stop(entry_order.correlation_id)
        if existing_stop is None:
            # No stop yet -- will be submitted by TradingEngine after
            # it receives the partial fill notification
            return

        # Update existing stop qty via replace_order
        if existing_stop.broker_id is not None:
            try:
                status = await self._broker.replace_order(
                    existing_stop.broker_id,
                    qty=update.filled_qty,
                )
                # Update broker_id if changed
                if status.broker_order_id != existing_stop.broker_id:
                    async with (
                        self._session_factory() as session,
                        session.begin(),
                    ):
                        result = await session.execute(
                            select(OrderStateModel).where(
                                OrderStateModel.local_id == existing_stop.local_id,
                            )
                        )
                        db_order = result.scalar_one()
                        old_id = db_order.broker_id
                        db_order.broker_id = status.broker_order_id
                        db_order.qty_requested = update.filled_qty  # type: ignore[assignment]
                        db_order.updated_at = format_timestamp(utc_now())
                        detail = f"old_broker_id={old_id}, qty={update.filled_qty}"
                        session.add(
                            OrderEventModel(
                                order_local_id=existing_stop.local_id,
                                event_type="replaced",
                                old_state=db_order.state,
                                new_state=db_order.state,
                                broker_id=status.broker_order_id,
                                detail=detail,
                                recorded_at=format_timestamp(utc_now()),
                            )
                        )
            except Exception:
                log.exception(
                    "stop_qty_update_failed",
                    broker_id=existing_stop.broker_id,
                )

    async def _handle_partial_cancel(
        self,
        entry_order: OrderStateModel,
    ) -> None:
        """Partial fill + cancel: close remaining at market."""
        filled_qty = Decimal(str(entry_order.qty_filled))
        correlation_id = entry_order.correlation_id

        # Cancel stop-loss if any
        stop = await self._find_active_stop(correlation_id)
        if stop is not None and stop.broker_id is not None:
            try:
                await self._broker.cancel_order(stop.broker_id)
            except Exception:
                log.exception("stop_cancel_failed", local_id=stop.local_id)

        # Submit market sell for the partial
        await self._submit_market_exit(
            entry_order.symbol,
            correlation_id,
            filled_qty,
        )

    async def _submit_market_exit(
        self,
        symbol: str,
        correlation_id: str,
        qty: Decimal,
    ) -> None:
        """Submit a market sell order for exit."""
        local_id = str(uuid4())
        now = format_timestamp(utc_now())

        async with self._session_factory() as session, session.begin():
            order = OrderStateModel(
                local_id=local_id,
                correlation_id=correlation_id,
                symbol=symbol,
                side=Side.SELL.value,
                order_type=OrderType.MARKET.value,
                order_role=OrderRole.EXIT_MARKET.value,
                qty_requested=qty,
                state=OrderState.PENDING_SUBMIT.value,
                created_at=now,
                updated_at=now,
            )
            session.add(order)

        try:
            status = await self._broker.submit_order(
                OrderRequest(
                    symbol=symbol,
                    side=Side.SELL,
                    qty=qty,
                    order_type=OrderType.MARKET,
                )
            )
            await self._transition_order(
                local_id,
                OrderState.SUBMITTED,
                event_type="submitted",
                broker_id=status.broker_order_id,
            )
        except Exception as exc:
            await self._transition_order(
                local_id,
                OrderState.SUBMIT_FAILED,
                event_type="submit_failed",
                detail=str(exc),
            )

    async def _create_trade_record(self, correlation_id: str) -> None:
        """Create a Trade record from filled entry + exit orders."""
        async with self._session_factory() as session:
            # Find entry and exit orders
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.correlation_id == correlation_id,
                    OrderStateModel.state == OrderState.FILLED.value,
                )
            )
            filled_orders = result.scalars().all()

            entry = next(
                (o for o in filled_orders if o.order_role == OrderRole.ENTRY.value),
                None,
            )
            exit_order = next(
                (
                    o
                    for o in filled_orders
                    if o.order_role
                    in (OrderRole.STOP_LOSS.value, OrderRole.EXIT_MARKET.value)
                ),
                None,
            )

            if entry is None or exit_order is None:
                return

            entry_price = Decimal(str(entry.avg_fill_price or "0"))
            exit_price = Decimal(str(exit_order.avg_fill_price or "0"))
            qty = Decimal(str(entry.qty_filled))
            entry_side = Side(entry.side)

            if entry_side == Side.BUY:
                pnl = (exit_price - entry_price) * qty
            else:
                pnl = (entry_price - exit_price) * qty

            position_cost = entry_price * qty
            if position_cost > Decimal("0"):
                pnl_pct = pnl / position_cost
            else:
                pnl_pct = Decimal("0")

            entry_at = entry.updated_at
            exit_at = exit_order.updated_at

            # Calculate duration
            entry_dt = parse_timestamp(entry_at)
            exit_dt = parse_timestamp(exit_at)
            duration = int((exit_dt - entry_dt).total_seconds())

            trade = TradeModel(
                trade_id=str(uuid4()),
                correlation_id=correlation_id,
                symbol=entry.symbol,
                side=_trade_side_from_entry(entry_side),
                qty=str(qty),
                entry_price=str(entry_price),
                exit_price=str(exit_price),
                entry_at=entry_at,
                exit_at=exit_at,
                pnl=str(pnl),
                pnl_pct=str(pnl_pct),
                strategy=entry.strategy or "unknown",
                duration_seconds=duration,
                commission=str(Decimal("0")),
            )

            # Need a new session to bypass immutability trigger for insert
            # (The trigger only blocks UPDATE and DELETE, INSERT is fine)
            async with (
                self._session_factory() as write_session,
                write_session.begin(),
            ):
                write_session.add(trade)

        log.info(
            "trade_closed",
            symbol=entry.symbol,
            pnl=str(pnl),
            pnl_pct=str(pnl_pct),
            duration=duration,
        )

    async def _transition_order(
        self,
        local_id: str,
        new_state: OrderState,
        event_type: str,
        broker_id: str | None = None,
        detail: str | None = None,
        qty_filled: Decimal | None = None,
        fill_price: Decimal | None = None,
    ) -> None:
        """Transition order state atomically with audit event."""
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.local_id == local_id,
                )
            )
            order = result.scalar_one()

            # Validate transition
            old_state = OrderState(order.state)
            machine = OrderStateMachine(old_state)
            try:
                machine.transition(new_state)
            except InvalidTransitionError:
                log.warning(
                    "invalid_transition",
                    local_id=local_id,
                    from_state=old_state.value,
                    to_state=new_state.value,
                )
                return

            # Update order
            order.state = new_state.value
            order.updated_at = format_timestamp(utc_now())
            if broker_id is not None:
                order.broker_id = broker_id
            if qty_filled is not None:
                order.qty_filled = qty_filled  # type: ignore[assignment]
            if fill_price is not None:
                order.avg_fill_price = fill_price  # type: ignore[assignment]

            # Append audit event
            session.add(
                OrderEventModel(
                    order_local_id=local_id,
                    event_type=event_type,
                    old_state=old_state.value,
                    new_state=new_state.value,
                    qty_filled=qty_filled,
                    fill_price=fill_price,
                    broker_id=broker_id,
                    detail=detail,
                    recorded_at=format_timestamp(utc_now()),
                )
            )

    async def _find_by_broker_id(
        self,
        broker_id: str,
    ) -> OrderStateModel | None:
        """Find an order by broker_id."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.broker_id == broker_id,
                )
            )
            return result.scalar_one_or_none()

    async def _find_by_local_id(
        self,
        local_id: str,
    ) -> OrderStateModel | None:
        """Find an order by local_id."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.local_id == local_id,
                )
            )
            return result.scalar_one_or_none()

    async def _find_active_stop(
        self,
        correlation_id: str,
    ) -> OrderStateModel | None:
        """Find active (non-terminal) stop-loss for a correlation_id."""
        terminal_values = [s.value for s in TERMINAL_STATES]
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.correlation_id == correlation_id,
                    OrderStateModel.order_role == OrderRole.STOP_LOSS.value,
                    OrderStateModel.state.notin_(terminal_values),
                )
            )
            return result.scalar_one_or_none()
