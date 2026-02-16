"""Integration tests for StartupReconciler.

Full DB setup with in-memory aiosqlite. Tests cover: crash recovery flow,
CircuitBreaker reconstruction, multi-strategy reconciliation, and
parallel broker fetch verification.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.broker.fake.broker import FakeBrokerAdapter
from app.broker.types import BrokerOrderStatus
from app.models.base import Base
from app.models.order import OrderEventModel, OrderStateModel, TradeModel
from app.orders.startup_reconciler import StartupReconciler
from app.orders.types import OrderRole, OrderState
from app.risk.circuit_breaker import CircuitBreaker
from tests.factories import make_order_status, make_position

_NOW = datetime(2026, 2, 14, 15, 0, tzinfo=UTC)
_EMERGENCY_STOP_PCT = Decimal("0.02")


@pytest.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create in-memory async SQLite with all tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_local_order(
    *,
    local_id: str = "local-001",
    broker_id: str | None = "broker-001",
    correlation_id: str = "corr-001",
    symbol: str = "AAPL",
    side: str = "buy",
    order_type: str = "stop",
    order_role: str = "entry",
    strategy: str = "velez",
    qty_requested: Decimal = Decimal("100"),
    qty_filled: Decimal = Decimal("0"),
    avg_fill_price: Decimal | None = None,
    state: str = "submitted",
) -> OrderStateModel:
    now = "2026-02-14T15:00:00.000000Z"
    return OrderStateModel(
        local_id=local_id,
        broker_id=broker_id,
        correlation_id=correlation_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        order_role=order_role,
        strategy=strategy,
        qty_requested=qty_requested,
        qty_filled=qty_filled,
        avg_fill_price=avg_fill_price,
        state=state,
        created_at=now,
        updated_at=now,
    )


async def _insert_order(
    session_factory: async_sessionmaker[AsyncSession],
    order: OrderStateModel,
) -> None:
    async with session_factory() as session, session.begin():
        session.add(order)


async def _insert_trade(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    trade_id: str = "trade-001",
    correlation_id: str = "corr-001",
    symbol: str = "AAPL",
    pnl: Decimal = Decimal("-50.00"),
    strategy: str = "velez",
) -> None:
    """Insert a trade record for CircuitBreaker testing."""
    now = "2026-02-14T15:00:00.000000Z"
    trade = TradeModel(
        trade_id=trade_id,
        correlation_id=correlation_id,
        symbol=symbol,
        side="long",
        qty=str(Decimal("100")),
        entry_price=str(Decimal("150.00")),
        exit_price=str(Decimal("149.50")),
        entry_at=now,
        exit_at=now,
        pnl=str(pnl),
        pnl_pct=str(pnl / Decimal("15000")),
        strategy=strategy,
        duration_seconds=300,
        commission=str(Decimal("0")),
    )
    async with session_factory() as session, session.begin():
        session.add(trade)


class TestFullCrashRecoveryFlow:
    """End-to-end crash recovery: entry filled while down, no stop."""

    async def test_full_crash_recovery_flow(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry filled while down, no stop -> reconcile + place stop."""
        # Setup: entry order was SUBMITTED when we crashed
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="entry-1",
                broker_id="broker-entry-1",
                state="submitted",
                order_role="entry",
            ),
        )

        # Broker: entry is now FILLED, position exists, no stop
        broker = FakeBrokerAdapter(
            positions=[
                make_position(
                    symbol="AAPL",
                    qty=Decimal("100"),
                    avg_entry_price=Decimal("150.00"),
                ),
            ],
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-entry-1",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("100"),
                    filled_avg_price=Decimal("150.00"),
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        # Entry should be reconciled to FILLED
        assert result.orders_reconciled == 1
        # Emergency stop should be placed
        assert result.emergency_stops_placed == 1
        assert result.errors == []

        # Verify entry order state
        async with db_session_factory() as session:
            entry = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "entry-1",
                    )
                )
            ).scalar_one()
            assert entry.state == OrderState.FILLED.value
            assert Decimal(str(entry.qty_filled)) == Decimal("100")

            # Verify stop order was created
            stops = (
                (
                    await session.execute(
                        select(OrderStateModel).where(
                            OrderStateModel.order_role == OrderRole.STOP_LOSS.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(stops) == 1
            assert stops[0].state == OrderState.SUBMITTED.value
            assert stops[0].symbol == "AAPL"

            # Verify all events logged
            events = (await session.execute(select(OrderEventModel))).scalars().all()
            event_types = {e.event_type for e in events}
            assert "reconciled" in event_types
            assert "emergency_stop" in event_types


class TestReconciliationThenCircuitBreaker:
    """Reconcile + CB reconstruction -> CB state reflects today's trades."""

    async def test_reconciliation_then_circuit_breaker(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Insert some today's trades
        await _insert_trade(
            db_session_factory,
            trade_id="trade-1",
            correlation_id="corr-1",
            pnl=Decimal("-50.00"),
        )
        await _insert_trade(
            db_session_factory,
            trade_id="trade-2",
            correlation_id="corr-2",
            pnl=Decimal("120.00"),
        )
        await _insert_trade(
            db_session_factory,
            trade_id="trade-3",
            correlation_id="corr-3",
            pnl=Decimal("-30.00"),
        )

        # Run reconciliation (clean -- no discrepancies)
        broker = FakeBrokerAdapter()
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()
        assert result.orders_reconciled == 0

        # Reconstruct CircuitBreaker from today's trades
        async with db_session_factory() as session:
            trades = (await session.execute(select(TradeModel))).scalars().all()

        cb = CircuitBreaker(
            max_daily_loss_pct=Decimal("0.03"),
            consecutive_loss_pause=3,
        )
        cb.reconstruct_from_trades(
            list(trades),
            start_of_day_equity=Decimal("100000"),
        )

        # Verify CB state: -50 + 120 - 30 = +40
        assert cb.daily_realized_pnl == Decimal("40")
        # Last trade was a loss, so consecutive_losses = 1
        assert cb.consecutive_losses == 1
        assert cb.is_paused is False


class TestMultiStrategy:
    """Orders from different strategies -> all reconciled correctly."""

    async def test_reconciliation_with_multiple_strategies(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Two strategies, each with a SUBMITTED entry
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="velez-entry",
                broker_id="broker-velez",
                correlation_id="corr-velez",
                symbol="AAPL",
                strategy="velez",
                state="submitted",
            ),
        )
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="momentum-entry",
                broker_id="broker-momentum",
                correlation_id="corr-momentum",
                symbol="TSLA",
                strategy="momentum",
                state="submitted",
            ),
        )

        # Broker: both filled
        broker = FakeBrokerAdapter(
            positions=[
                make_position(symbol="AAPL", qty=Decimal("50")),
                make_position(
                    symbol="TSLA",
                    qty=Decimal("30"),
                    avg_entry_price=Decimal("200.00"),
                ),
            ],
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-velez",
                    symbol="AAPL",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("50"),
                    filled_avg_price=Decimal("150.00"),
                ),
                make_order_status(
                    broker_order_id="broker-momentum",
                    symbol="TSLA",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("30"),
                    filled_avg_price=Decimal("200.00"),
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        # Both entries reconciled
        assert result.orders_reconciled == 2
        # Both need emergency stops
        assert result.emergency_stops_placed == 2

        # Verify both orders are FILLED
        async with db_session_factory() as session:
            orders = (
                (
                    await session.execute(
                        select(OrderStateModel).where(
                            OrderStateModel.order_role == OrderRole.ENTRY.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert all(o.state == OrderState.FILLED.value for o in orders)

            # Verify stop orders created for both symbols
            stops = (
                (
                    await session.execute(
                        select(OrderStateModel).where(
                            OrderStateModel.order_role == OrderRole.STOP_LOSS.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            stop_symbols = {s.symbol for s in stops}
            assert stop_symbols == {"AAPL", "TSLA"}


class TestParallelBrokerFetches:
    """Verify asyncio.gather is used for parallel broker fetches."""

    async def test_parallel_broker_fetches(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Mock latency on broker calls, verify total time < sequential."""
        call_times: list[float] = []

        async def slow_get_positions() -> list[object]:
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)
            call_times.append(asyncio.get_event_loop().time() - start)
            return []

        async def slow_get_open_orders() -> list[object]:
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)
            call_times.append(asyncio.get_event_loop().time() - start)
            return []

        async def slow_get_recent_orders(since_hours: int = 24) -> list[object]:
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)
            call_times.append(asyncio.get_event_loop().time() - start)
            return []

        broker = FakeBrokerAdapter()
        broker.get_positions = slow_get_positions  # type: ignore[assignment]
        broker.get_open_orders = slow_get_open_orders  # type: ignore[assignment]
        broker.get_recent_orders = slow_get_recent_orders  # type: ignore[assignment]

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        start = asyncio.get_event_loop().time()
        result = await reconciler.reconcile()
        total_time = asyncio.get_event_loop().time() - start

        # 3 calls of 100ms each. If parallel: ~100ms. If sequential: ~300ms.
        # Use generous threshold to avoid flaky tests.
        assert total_time < 0.25, f"Took {total_time:.3f}s -- likely sequential"
        assert len(call_times) == 3
        assert result.orders_reconciled == 0
