"""Startup reconciler -- crash recovery and state correction.

Runs once before any live trading on every process start. Compares
local SQLite order state against broker truth, corrects discrepancies,
and protects any open position that lacks an active stop-loss.

Safety-critical: an unprotected position has unlimited downside risk.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.broker_adapter import BrokerAdapter
from app.broker.types import (
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TimeInForce,
)
from app.models.order import OrderEventModel, OrderStateModel
from app.orders.types import TERMINAL_STATES, OrderRole, OrderState

log = structlog.get_logger()

# Retry parameters matching OrderManager conventions
_STOP_RETRY_MAX = 3
_STOP_RETRY_DELAY = 1.0

# Broker REST call timeout (seconds)
_BROKER_CALL_TIMEOUT = 10.0

# Reasonable bounds for broker response validation (D11)
_MAX_POSITION_SHARES = 100_000
_MAX_EQUITY_PRICE = Decimal("1000000")


class ReconciliationFatalError(Exception):
    """Raised when reconciliation cannot proceed safely. Aborts startup."""


@dataclass(frozen=True)
class ReconciliationResult:
    """Structured result of reconciliation for logging and test assertions."""

    orders_reconciled: int
    orphans_detected: int
    orphan_orders_canceled: int
    emergency_stops_placed: int
    errors: list[str] = field(default_factory=list)


# Broker status -> local OrderState mapping (D4/Kieran)
STATUS_MAP: dict[BrokerOrderStatus, OrderState | None] = {
    BrokerOrderStatus.NEW: OrderState.SUBMITTED,
    BrokerOrderStatus.ACCEPTED: OrderState.ACCEPTED,
    BrokerOrderStatus.FILLED: OrderState.FILLED,
    BrokerOrderStatus.PARTIALLY_FILLED: OrderState.PARTIALLY_FILLED,
    BrokerOrderStatus.CANCELED: OrderState.CANCELED,
    BrokerOrderStatus.EXPIRED: OrderState.EXPIRED,
    BrokerOrderStatus.REJECTED: OrderState.REJECTED,
    BrokerOrderStatus.PENDING_CANCEL: None,  # transient, no change
    BrokerOrderStatus.REPLACED: None,  # handled via broker_id update
}


def map_broker_status(status: BrokerOrderStatus) -> OrderState | None:
    """Map broker status to local OrderState. Returns None for transient states."""
    if status not in STATUS_MAP:
        raise ReconciliationFatalError(f"Unknown broker status: {status}")
    return STATUS_MAP[status]


def _format_ts(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class StartupReconciler:
    """Reconcile local state against broker on startup.

    Runs before WebSocket subscriptions, indicator warm-up, or any
    strategy evaluation. The broker is the source of truth.
    """

    def __init__(
        self,
        broker: BrokerAdapter,
        session_factory: async_sessionmaker[AsyncSession],
        emergency_stop_pct: Decimal,
    ) -> None:
        self._broker = broker
        self._session_factory = session_factory
        self._emergency_stop_pct = emergency_stop_pct

    async def reconcile(self) -> ReconciliationResult:
        """Run full reconciliation.

        Raises:
            ReconciliationFatalError: If broker reads fail after retries.
        """
        # SETUP: fetch broker state in parallel
        (
            broker_positions,
            broker_open_orders,
            broker_recent_orders,
        ) = await self._fetch_broker_state()

        # Build lookup maps
        broker_order_map: dict[str, OrderStatus] = {
            o.broker_order_id: o for o in [*broker_open_orders, *broker_recent_orders]
        }

        # Load local non-terminal orders
        async with self._session_factory() as session:
            terminal_values = [s.value for s in TERMINAL_STATES]
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.state.notin_(terminal_values),
                )
            )
            local_nonterminal = list(result.scalars().all())

        errors: list[str] = []

        # Phase 1: Reconcile local orders against broker
        orders_reconciled = await self._reconcile_orders(
            local_nonterminal,
            broker_order_map,
            broker_open_orders,
            errors,
        )

        # Phase 2: Reconcile positions (orphan detection + stop protection)
        orphans_detected, emergency_stops_placed = await self._reconcile_positions(
            broker_positions,
            errors,
        )

        result_obj = ReconciliationResult(
            orders_reconciled=orders_reconciled,
            orphans_detected=orphans_detected,
            orphan_orders_canceled=len(
                [
                    o
                    for o in broker_open_orders
                    if o.broker_order_id
                    not in {
                        lo.broker_id
                        for lo in local_nonterminal
                        if lo.broker_id is not None
                    }
                ]
            ),
            emergency_stops_placed=emergency_stops_placed,
            errors=errors,
        )

        log.info(
            "reconciliation_complete",
            orders_reconciled=result_obj.orders_reconciled,
            orphans_detected=result_obj.orphans_detected,
            orphan_orders_canceled=result_obj.orphan_orders_canceled,
            emergency_stops_placed=result_obj.emergency_stops_placed,
            error_count=len(result_obj.errors),
        )

        return result_obj

    async def _fetch_broker_state(
        self,
    ) -> tuple[list[Position], list[OrderStatus], list[OrderStatus]]:
        """Parallel fetch of positions + open orders + recent orders.

        Retries 3x with exponential backoff. Raises ReconciliationFatalError
        on total failure.
        """
        last_error: str = ""
        for attempt in range(_STOP_RETRY_MAX):
            try:
                positions, open_orders, recent_orders = await asyncio.gather(
                    asyncio.wait_for(
                        self._broker.get_positions(),
                        timeout=_BROKER_CALL_TIMEOUT,
                    ),
                    asyncio.wait_for(
                        self._broker.get_open_orders(),
                        timeout=_BROKER_CALL_TIMEOUT,
                    ),
                    asyncio.wait_for(
                        self._broker.get_recent_orders(24),
                        timeout=_BROKER_CALL_TIMEOUT,
                    ),
                )
                return positions, open_orders, recent_orders
            except Exception as exc:
                last_error = str(exc)
                log.warning(
                    "broker_fetch_failed",
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < _STOP_RETRY_MAX - 1:
                    await asyncio.sleep(_STOP_RETRY_DELAY * (2**attempt))

        raise ReconciliationFatalError(
            f"Broker state fetch failed after {_STOP_RETRY_MAX} attempts: {last_error}"
        )

    async def _reconcile_orders(
        self,
        local_orders: list[OrderStateModel],
        broker_order_map: dict[str, OrderStatus],
        broker_open_orders: list[OrderStatus],
        errors: list[str],
    ) -> int:
        """Phase 1: Reconcile local orders against broker state."""
        orders_reconciled = 0

        # 1a. Orders with broker_id -> match against broker state
        for local_order in local_orders:
            if local_order.broker_id is not None:
                broker_order = broker_order_map.get(local_order.broker_id)

                # Individual fallback for orders not in 24h batch
                if broker_order is None:
                    try:
                        broker_order = await asyncio.wait_for(
                            self._broker.get_order_status(local_order.broker_id),
                            timeout=_BROKER_CALL_TIMEOUT,
                        )
                    except Exception as exc:
                        msg = (
                            f"Individual lookup failed for "
                            f"broker_id={local_order.broker_id}: {exc}"
                        )
                        log.warning("broker_order_not_found", detail=msg)
                        errors.append(msg)
                        continue

                mapped_state = map_broker_status(broker_order.status)
                if mapped_state is None:
                    # Transient state, skip
                    continue

                local_state = OrderState(local_order.state)
                if mapped_state != local_state:
                    await self._force_transition(
                        local_order,
                        mapped_state,
                        broker_order,
                        errors,
                    )
                    orders_reconciled += 1

            elif OrderState(local_order.state) == OrderState.PENDING_SUBMIT:
                # 1b. PENDING_SUBMIT with no broker_id -> stale
                await self._force_transition_stale(local_order)
                orders_reconciled += 1

        # 1c. Orphan broker orders -> cancel
        local_broker_ids = {
            o.broker_id for o in local_orders if o.broker_id is not None
        }
        for broker_order in broker_open_orders:
            if broker_order.broker_order_id not in local_broker_ids:
                try:
                    await self._broker.cancel_order(broker_order.broker_order_id)
                    log.warning(
                        "orphan_broker_order_canceled",
                        broker_order_id=broker_order.broker_order_id,
                        symbol=broker_order.symbol,
                    )
                except Exception as exc:
                    msg = (
                        f"Failed to cancel orphan broker order "
                        f"{broker_order.broker_order_id}: {exc}"
                    )
                    log.warning("orphan_cancel_failed", detail=msg)
                    errors.append(msg)

        return orders_reconciled

    async def _reconcile_positions(
        self,
        broker_positions: list[Position],
        errors: list[str],
    ) -> tuple[int, int]:
        """Phase 2: Orphan detection + emergency stop protection."""
        orphans_detected = 0
        emergency_stops_placed = 0

        for position in broker_positions:
            # Validate broker response (D11)
            if not self._validate_position(position, errors):
                continue

            # Check for local match (FILLED entry order for this symbol)
            has_local_match = await self._has_local_entry(position.symbol)

            if not has_local_match:
                # Orphan: create synthetic record with deterministic ID
                created = await self._create_orphan_record(position, errors)
                if created:
                    orphans_detected += 1

            # Check for active stop protection
            has_stop = await self._has_active_stop(position.symbol)
            if not has_stop:
                placed = await self._place_emergency_stop(position, errors)
                if placed:
                    emergency_stops_placed += 1

        return orphans_detected, emergency_stops_placed

    def _validate_position(
        self,
        position: Position,
        errors: list[str],
    ) -> bool:
        """Validate broker position data (D11)."""
        if position.qty <= Decimal("0") or position.qty > _MAX_POSITION_SHARES:
            msg = (
                f"Invalid position qty for {position.symbol}: "
                f"{position.qty} (bounds: 0 < qty <= {_MAX_POSITION_SHARES})"
            )
            log.critical("invalid_broker_position", detail=msg)
            errors.append(msg)
            return False

        if (
            position.avg_entry_price is None
            or position.avg_entry_price <= Decimal("0")
            or position.avg_entry_price > _MAX_EQUITY_PRICE
        ):
            msg = (
                f"Invalid avg_entry_price for {position.symbol}: "
                f"{position.avg_entry_price}"
            )
            log.critical("invalid_broker_position", detail=msg)
            errors.append(msg)
            return False

        return True

    async def _has_local_entry(self, symbol: str) -> bool:
        """Check if there's a local FILLED entry order for the given symbol."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.symbol == symbol,
                    OrderStateModel.order_role == OrderRole.ENTRY.value,
                    OrderStateModel.state == OrderState.FILLED.value,
                )
            )
            return result.scalar_one_or_none() is not None

    async def _has_active_stop(self, symbol: str) -> bool:
        """Check if there's an active (non-terminal) stop-loss for the symbol."""
        terminal_values = [s.value for s in TERMINAL_STATES]
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.symbol == symbol,
                    OrderStateModel.order_role == OrderRole.STOP_LOSS.value,
                    OrderStateModel.state.notin_(terminal_values),
                )
            )
            return result.scalar_one_or_none() is not None

    async def _create_orphan_record(
        self,
        position: Position,
        errors: list[str],
    ) -> bool:
        """Create synthetic OrderStateModel for an orphan broker position."""
        today = datetime.now(tz=UTC).strftime("%Y%m%d")
        correlation_id = f"orphan-{position.symbol}-{today}"

        # Dedup check: existing non-terminal orphan for this symbol
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.correlation_id == correlation_id,
                    OrderStateModel.state == OrderState.FILLED.value,
                )
            )
            if result.scalar_one_or_none() is not None:
                return False  # Already exists, idempotent

        # Create synthetic record
        now = _format_ts(datetime.now(tz=UTC))
        local_id = str(uuid4())
        async with self._session_factory() as session, session.begin():
            order = OrderStateModel(
                local_id=local_id,
                correlation_id=correlation_id,
                symbol=position.symbol,
                side=position.side.value,
                order_type=OrderType.MARKET.value,
                order_role=OrderRole.ENTRY.value,
                strategy="unknown",
                qty_requested=position.qty,
                qty_filled=position.qty,
                avg_fill_price=position.avg_entry_price,
                state=OrderState.FILLED.value,
                created_at=now,
                updated_at=now,
            )
            session.add(order)
            session.add(
                OrderEventModel(
                    order_local_id=local_id,
                    event_type="orphan_created",
                    old_state=OrderState.FILLED.value,
                    new_state=OrderState.FILLED.value,
                    qty_filled=position.qty,
                    fill_price=position.avg_entry_price,
                    detail=f"orphan_position_{position.symbol}",
                    recorded_at=now,
                )
            )

        log.warning(
            "orphan_position_detected",
            symbol=position.symbol,
            qty=str(position.qty),
            avg_entry_price=str(position.avg_entry_price),
            correlation_id=correlation_id,
        )
        return True

    async def _force_transition(
        self,
        local_order: OrderStateModel,
        new_state: OrderState,
        broker_order: OrderStatus,
        errors: list[str],
    ) -> None:
        """Atomic state + event write for order reconciliation."""
        old_state = local_order.state
        now = _format_ts(datetime.now(tz=UTC))

        # NULL avg_fill_price guard (Data Integrity Guardian)
        fill_price = broker_order.filled_avg_price
        if new_state == OrderState.FILLED and fill_price is None:
            msg = (
                f"Broker reports FILLED with NULL avg_fill_price "
                f"for local_id={local_order.local_id}, "
                f"broker_id={local_order.broker_id}"
            )
            log.critical("null_fill_price", detail=msg)
            errors.append(msg)
            # Still force the state, but don't set fill price

        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.local_id == local_order.local_id,
                )
            )
            db_order = result.scalar_one()

            db_order.state = new_state.value
            db_order.updated_at = now
            if broker_order.filled_qty > Decimal("0"):
                db_order.qty_filled = broker_order.filled_qty  # type: ignore[assignment]
            if fill_price is not None:
                db_order.avg_fill_price = fill_price  # type: ignore[assignment]

            session.add(
                OrderEventModel(
                    order_local_id=local_order.local_id,
                    event_type="reconciled",
                    old_state=old_state,
                    new_state=new_state.value,
                    qty_filled=broker_order.filled_qty,
                    fill_price=fill_price,
                    broker_id=local_order.broker_id,
                    detail=f"old={old_state}, broker={broker_order.status.value}",
                    recorded_at=now,
                )
            )

        log.info(
            "order_reconciled",
            local_id=local_order.local_id,
            old_state=old_state,
            new_state=new_state.value,
            broker_status=broker_order.status.value,
        )

    async def _force_transition_stale(
        self,
        local_order: OrderStateModel,
    ) -> None:
        """Mark PENDING_SUBMIT order with no broker_id as SUBMIT_FAILED."""
        now = _format_ts(datetime.now(tz=UTC))
        old_state = local_order.state

        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.local_id == local_order.local_id,
                )
            )
            db_order = result.scalar_one()
            db_order.state = OrderState.SUBMIT_FAILED.value
            db_order.updated_at = now

            session.add(
                OrderEventModel(
                    order_local_id=local_order.local_id,
                    event_type="reconciled",
                    old_state=old_state,
                    new_state=OrderState.SUBMIT_FAILED.value,
                    detail="no_broker_id_on_startup",
                    recorded_at=now,
                )
            )

        log.info(
            "stale_order_cleared",
            local_id=local_order.local_id,
        )

    async def _place_emergency_stop(
        self,
        position: Position,
        errors: list[str],
    ) -> bool:
        """Place emergency stop-loss. 3x retry + market sell fallback."""
        # Guard: avg_entry_price must be valid
        if position.avg_entry_price <= Decimal("0"):
            msg = (
                f"Cannot place emergency stop for {position.symbol}: "
                f"avg_entry_price={position.avg_entry_price}"
            )
            log.critical("emergency_stop_skipped", detail=msg)
            errors.append(msg)
            return False

        emergency_price = (
            position.avg_entry_price * (Decimal("1") - self._emergency_stop_pct)
        ).quantize(Decimal("0.01"))

        if emergency_price <= Decimal("0"):
            msg = (
                f"Computed emergency stop price <= 0 for {position.symbol}: "
                f"price={emergency_price}"
            )
            log.critical("emergency_stop_skipped", detail=msg)
            errors.append(msg)
            return False

        # Create OrderStateModel for the emergency stop
        now = _format_ts(datetime.now(tz=UTC))
        local_id = str(uuid4())
        today = datetime.now(tz=UTC).strftime("%Y%m%d")

        # Use orphan correlation if no local entry, else find the entry's correlation
        correlation_id = await self._find_correlation_for_symbol(position.symbol)
        if correlation_id is None:
            correlation_id = f"orphan-{position.symbol}-{today}"

        async with self._session_factory() as session, session.begin():
            order = OrderStateModel(
                local_id=local_id,
                correlation_id=correlation_id,
                symbol=position.symbol,
                side=Side.SELL.value,
                order_type=OrderType.STOP.value,
                order_role=OrderRole.STOP_LOSS.value,
                strategy="unknown",
                qty_requested=position.qty,
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
                        symbol=position.symbol,
                        side=Side.SELL,
                        qty=position.qty,
                        order_type=OrderType.STOP,
                        stop_price=emergency_price,
                        time_in_force=TimeInForce.GTC,
                    )
                )

                # Transition to SUBMITTED
                async with self._session_factory() as session, session.begin():
                    result = await session.execute(
                        select(OrderStateModel).where(
                            OrderStateModel.local_id == local_id,
                        )
                    )
                    db_order = result.scalar_one()
                    db_order.state = OrderState.SUBMITTED.value
                    db_order.broker_id = status.broker_order_id
                    db_order.updated_at = _format_ts(datetime.now(tz=UTC))

                    session.add(
                        OrderEventModel(
                            order_local_id=local_id,
                            event_type="emergency_stop",
                            old_state=OrderState.PENDING_SUBMIT.value,
                            new_state=OrderState.SUBMITTED.value,
                            broker_id=status.broker_order_id,
                            detail=(
                                f"emergency_stop_price={emergency_price}, "
                                f"qty={position.qty}"
                            ),
                            recorded_at=_format_ts(datetime.now(tz=UTC)),
                        )
                    )

                log.critical(
                    "emergency_stop_placed",
                    symbol=position.symbol,
                    qty=str(position.qty),
                    stop_price=str(emergency_price),
                )
                return True

            except Exception as exc:
                last_error = str(exc)
                if attempt < _STOP_RETRY_MAX - 1:
                    await asyncio.sleep(_STOP_RETRY_DELAY)

        # All retries failed: market sell fallback
        log.critical(
            "emergency_stop_fallback_market_sell",
            symbol=position.symbol,
            qty=str(position.qty),
            error=last_error,
        )
        errors.append(
            f"Emergency stop failed for {position.symbol}, "
            f"attempting market sell: {last_error}"
        )

        # Mark stop as failed
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(OrderStateModel).where(
                    OrderStateModel.local_id == local_id,
                )
            )
            db_order = result.scalar_one()
            db_order.state = OrderState.SUBMIT_FAILED.value
            db_order.last_error = last_error
            db_order.updated_at = _format_ts(datetime.now(tz=UTC))

        # Submit market sell as fallback
        try:
            await self._broker.submit_order(
                OrderRequest(
                    symbol=position.symbol,
                    side=Side.SELL,
                    qty=position.qty,
                    order_type=OrderType.MARKET,
                )
            )
        except Exception as exc:
            msg = f"Market sell fallback also failed for {position.symbol}: {exc}"
            log.critical("market_sell_fallback_failed", detail=msg)
            errors.append(msg)

        return True

    async def _find_correlation_for_symbol(self, symbol: str) -> str | None:
        """Find the correlation_id for a FILLED entry order of this symbol."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel.correlation_id).where(
                    OrderStateModel.symbol == symbol,
                    OrderStateModel.order_role == OrderRole.ENTRY.value,
                    OrderStateModel.state == OrderState.FILLED.value,
                )
            )
            row = result.scalar_one_or_none()
            return row
