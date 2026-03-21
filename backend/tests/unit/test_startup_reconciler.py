"""Tests for StartupReconciler -- crash recovery and state correction.

Tests cover: clean startup, order reconciliation (FILLED/CANCELED/stale),
orphan positions, orphan broker orders, emergency stop placement,
idempotency, broker API failure, and NULL fill price guard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.broker.fake.broker import FakeBrokerAdapter
from app.broker.types import (
    BrokerOrderStatus,
    OrderRequest,
    OrderType,
    Side,
)
from app.models.base import Base
from app.models.order import OrderEventModel, OrderStateModel
from app.orders.startup_reconciler import (
    ReconciliationFatalError,
    StartupReconciler,
    map_broker_status,
)
from app.orders.types import OrderRole, OrderState
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
    """Create an OrderStateModel for test insertion."""
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
    """Insert an order into the test database."""
    async with session_factory() as session, session.begin():
        session.add(order)


class TestMapBrokerStatus:
    """STATUS_MAP + map_broker_status()."""

    def test_filled_maps_to_filled(self) -> None:
        assert map_broker_status(BrokerOrderStatus.FILLED) == OrderState.FILLED

    def test_new_maps_to_submitted(self) -> None:
        assert map_broker_status(BrokerOrderStatus.NEW) == OrderState.SUBMITTED

    def test_pending_cancel_returns_none(self) -> None:
        assert map_broker_status(BrokerOrderStatus.PENDING_CANCEL) is None

    def test_replaced_returns_none(self) -> None:
        assert map_broker_status(BrokerOrderStatus.REPLACED) is None

    def test_all_statuses_mapped(self) -> None:
        for status in BrokerOrderStatus:
            result = map_broker_status(status)
            assert result is None or isinstance(result, OrderState)


class TestCleanStartup:
    """No actions needed when DB and broker are empty or already match."""

    async def test_clean_startup_no_actions(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Empty DB, empty broker -> zero actions."""
        broker = FakeBrokerAdapter()
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 0
        assert result.orphans_detected == 0
        assert result.orphan_orders_canceled == 0
        assert result.emergency_stops_placed == 0
        assert result.errors == []

    async def test_clean_restart_no_actions(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DB matches broker -> zero actions."""
        # Local: FILLED entry with active stop
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="entry-1",
                broker_id="broker-entry-1",
                state="filled",
                order_role="entry",
                qty_filled=Decimal("100"),
                avg_fill_price=Decimal("150.00"),
            ),
        )
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="stop-1",
                broker_id="broker-stop-1",
                correlation_id="corr-001",
                state="submitted",
                order_role="stop_loss",
                side="sell",
            ),
        )

        # Broker: matching position + matching open stop
        # stop reports NEW which maps to SUBMITTED (matching local state)
        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="AAPL")],
            open_orders=[
                make_order_status(
                    broker_order_id="broker-stop-1",
                    symbol="AAPL",
                    side=Side.SELL,
                    status=BrokerOrderStatus.NEW,
                ),
            ],
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-entry-1",
                    symbol="AAPL",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("100"),
                    filled_avg_price=Decimal("150.00"),
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 0
        assert result.orphans_detected == 0
        assert result.emergency_stops_placed == 0


class TestOrderReconciliation:
    """Phase 1: Reconcile local orders against broker state."""

    async def test_submitted_but_broker_filled(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Local SUBMITTED, broker FILLED -> force FILLED, record fill."""
        await _insert_order(
            db_session_factory,
            _make_local_order(state="submitted"),
        )

        broker = FakeBrokerAdapter(
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-001",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("100"),
                    filled_avg_price=Decimal("155.20"),
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 1

        # Verify DB state
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "local-001",
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.FILLED.value
            assert Decimal(str(order.qty_filled)) == Decimal("100")
            assert Decimal(str(order.avg_fill_price)) == Decimal("155.20")

            # Verify audit event
            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.order_local_id == "local-001",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert events[0].event_type == "reconciled"
            assert events[0].new_state == OrderState.FILLED.value

    async def test_submitted_but_broker_canceled(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Local SUBMITTED, broker CANCELED -> force CANCELED."""
        await _insert_order(
            db_session_factory,
            _make_local_order(state="submitted"),
        )

        broker = FakeBrokerAdapter(
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-001",
                    status=BrokerOrderStatus.CANCELED,
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 1

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "local-001",
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.CANCELED.value

    async def test_accepted_but_broker_filled(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Local ACCEPTED, broker FILLED -> force FILLED."""
        await _insert_order(
            db_session_factory,
            _make_local_order(state="accepted"),
        )

        broker = FakeBrokerAdapter(
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-001",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("100"),
                    filled_avg_price=Decimal("155.20"),
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 1

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "local-001",
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.FILLED.value

    async def test_pending_submit_no_broker_id(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PENDING_SUBMIT, broker_id=NULL -> SUBMIT_FAILED."""
        await _insert_order(
            db_session_factory,
            _make_local_order(
                state="pending_submit",
                broker_id=None,
            ),
        )

        broker = FakeBrokerAdapter()
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 1

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "local-001",
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.SUBMIT_FAILED.value

            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.order_local_id == "local-001",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert "no_broker_id_on_startup" in (events[0].detail or "")

    async def test_orphan_broker_order_canceled(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Open broker order with no local match -> canceled."""
        broker = FakeBrokerAdapter(
            open_orders=[
                make_order_status(
                    broker_order_id="orphan-broker-order",
                    symbol="TSLA",
                    status=BrokerOrderStatus.ACCEPTED,
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orphan_orders_canceled == 1
        assert "orphan-broker-order" in broker.canceled_order_ids

    async def test_order_older_than_24h_individual_lookup(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Order not in recent batch -> individual get_order_status()."""
        await _insert_order(
            db_session_factory,
            _make_local_order(
                broker_id="old-broker-id",
                state="submitted",
            ),
        )

        # Broker: not in recent_orders, but available via individual lookup
        broker = FakeBrokerAdapter(
            order_statuses={
                "old-broker-id": make_order_status(
                    broker_order_id="old-broker-id",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("100"),
                    filled_avg_price=Decimal("155.00"),
                ),
            },
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 1

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "local-001",
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.FILLED.value


class TestPositionReconciliation:
    """Phase 2: Orphan detection + emergency stop protection."""

    async def test_orphan_position_detected(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Broker position with no local match -> orphan with deterministic ID."""
        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="TSLA", avg_entry_price=Decimal("200.00"))],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orphans_detected == 1
        assert result.emergency_stops_placed == 1

        # Verify orphan record
        async with db_session_factory() as session:
            orders = (
                (
                    await session.execute(
                        select(OrderStateModel).where(
                            OrderStateModel.symbol == "TSLA",
                            OrderStateModel.order_role == OrderRole.ENTRY.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(orders) == 1
            assert orders[0].state == OrderState.FILLED.value
            assert orders[0].strategy == "unknown"
            assert orders[0].correlation_id.startswith("orphan-TSLA-")

            # Verify orphan event
            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.event_type == "orphan_created",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1

    async def test_unprotected_position_gets_stop(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Position with no active stop -> emergency stop placed."""
        # Local: FILLED entry, no stop
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="entry-1",
                broker_id="broker-entry-1",
                state="filled",
                order_role="entry",
                qty_filled=Decimal("100"),
                avg_fill_price=Decimal("150.00"),
            ),
        )

        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="AAPL")],
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

        assert result.emergency_stops_placed == 1
        assert len(broker.submitted_orders) == 1

        # Verify stop order: qty from broker position (D7), price = 150 * 0.98
        stop_order = broker.submitted_orders[0]
        assert isinstance(stop_order, OrderRequest)
        assert stop_order.symbol == "AAPL"
        assert stop_order.side == Side.SELL
        assert stop_order.qty == Decimal("100")
        assert stop_order.stop_price == Decimal("147.00")
        assert stop_order.order_type == OrderType.STOP

        # Verify emergency stop event in DB
        async with db_session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.event_type == "emergency_stop",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1

    async def test_protected_position_no_duplicate_stop(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Position with active stop -> no action (idempotent)."""
        # Local: FILLED entry + active stop
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="entry-1",
                broker_id="broker-entry-1",
                state="filled",
                order_role="entry",
                qty_filled=Decimal("100"),
                avg_fill_price=Decimal("150.00"),
            ),
        )
        await _insert_order(
            db_session_factory,
            _make_local_order(
                local_id="stop-1",
                broker_id="broker-stop-1",
                state="submitted",
                order_role="stop_loss",
                side="sell",
            ),
        )

        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="AAPL")],
            open_orders=[
                make_order_status(
                    broker_order_id="broker-stop-1",
                    symbol="AAPL",
                    side=Side.SELL,
                    status=BrokerOrderStatus.ACCEPTED,
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

        assert result.emergency_stops_placed == 0
        assert len(broker.submitted_orders) == 0

    async def test_null_avg_fill_price_skips_trade(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Broker FILLED with NULL price -> CRITICAL log, error recorded."""
        await _insert_order(
            db_session_factory,
            _make_local_order(state="submitted"),
        )

        broker = FakeBrokerAdapter(
            recent_orders=[
                make_order_status(
                    broker_order_id="broker-001",
                    status=BrokerOrderStatus.FILLED,
                    filled_qty=Decimal("100"),
                    filled_avg_price=None,  # NULL price
                ),
            ],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)
        result = await reconciler.reconcile()

        assert result.orders_reconciled == 1
        assert any("NULL avg_fill_price" in e for e in result.errors)

        # State still forced to FILLED
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == "local-001",
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.FILLED.value
            # But avg_fill_price remains None
            assert order.avg_fill_price is None


class TestIdempotency:
    """Reconciliation must be safe to run multiple times."""

    async def test_idempotent_double_run(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Run reconciliation twice -> second run is no-op."""
        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="TSLA", avg_entry_price=Decimal("200.00"))],
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        # First run: creates orphan + places stop
        result1 = await reconciler.reconcile()
        assert result1.orphans_detected == 1
        assert result1.emergency_stops_placed == 1

        # Second run: everything already correct
        result2 = await reconciler.reconcile()
        assert result2.orphans_detected == 0
        assert result2.emergency_stops_placed == 0
        assert result2.orders_reconciled == 0


class TestBrokerAPIFailure:
    """Broker read failure aborts startup."""

    async def test_broker_api_read_failure_aborts(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """get_positions() fails 3x -> raises ReconciliationFatalError."""
        broker = FakeBrokerAdapter()
        broker.get_positions = AsyncMock(  # type: ignore[method-assign]
            side_effect=ConnectionError("broker down"),
        )

        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        with pytest.raises(ReconciliationFatalError, match="broker down"):
            await reconciler.reconcile()


class TestPositionValidation:
    """Tests for _validate_position() edge cases."""

    async def test_validate_position_rejects_zero_quantity(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Position with qty=0 is rejected as invalid."""
        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="AAPL", qty=Decimal("0"))],
        )
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert result.orphans_detected == 0
        assert any("Invalid position qty" in e for e in result.errors)

    async def test_validate_position_rejects_excessive_quantity(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Position with qty > 100k is rejected as invalid."""
        broker = FakeBrokerAdapter(
            positions=[make_position(symbol="AAPL", qty=Decimal("200000"))],
        )
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert result.orphans_detected == 0
        assert any("Invalid position qty" in e for e in result.errors)

    async def test_validate_position_rejects_negative_avg_entry_price(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Position with negative avg_entry_price is rejected."""
        broker = FakeBrokerAdapter(
            positions=[
                make_position(symbol="AAPL", avg_entry_price=Decimal("-5")),
            ],
        )
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert any("Invalid avg_entry_price" in e for e in result.errors)

    async def test_validate_position_rejects_none_avg_entry_price(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Position with avg_entry_price=None is rejected."""
        from app.broker.types import Position

        position = Position(
            symbol="AAPL",
            qty=Decimal("100"),
            side=Side.BUY,
            avg_entry_price=None,  # type: ignore[arg-type]
            market_value=Decimal("0"),
            unrealized_pl=Decimal("0"),
            unrealized_pl_pct=Decimal("0"),
        )
        broker = FakeBrokerAdapter(positions=[position])
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert any("Invalid avg_entry_price" in e for e in result.errors)


class TestEmergencyStopPriceGuards:
    """Tests for price boundary checks in _place_emergency_stop()."""

    async def test_emergency_stop_skipped_for_zero_computed_price(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When computed stop price <= 0, no stop is placed and error is recorded."""
        broker = FakeBrokerAdapter(
            positions=[
                make_position(
                    symbol="AAPL",
                    qty=Decimal("100"),
                    avg_entry_price=Decimal("0.01"),
                ),
            ],
        )
        # 99% stop offset makes computed price <= 0
        reconciler = StartupReconciler(
            broker,
            db_session_factory,
            emergency_stop_pct=Decimal("0.99"),
        )

        result = await reconciler.reconcile()

        assert any("Computed emergency stop price <= 0" in e for e in result.errors)


class TestEmergencyStopFallback:
    """Tests for retry exhaustion and market sell fallback."""

    @patch("app.orders.startup_reconciler.asyncio.sleep", new_callable=AsyncMock)
    async def test_emergency_stop_retries_exhausted_falls_back_to_market_sell(
        self,
        mock_sleep: AsyncMock,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After 3 failed stop attempts, market sell is attempted (also fails)."""
        broker = FakeBrokerAdapter(
            positions=[
                make_position(
                    symbol="AAPL",
                    qty=Decimal("100"),
                    avg_entry_price=Decimal("150.00"),
                ),
            ],
        )
        broker.submit_order = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("Broker down"),
        )
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert result.emergency_stops_placed == 1
        assert any("Emergency stop failed" in e for e in result.errors)
        assert any("Market sell fallback also failed" in e for e in result.errors)

    @patch("app.orders.startup_reconciler.asyncio.sleep", new_callable=AsyncMock)
    async def test_emergency_stop_market_sell_succeeds_after_stop_fails(
        self,
        mock_sleep: AsyncMock,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Stop fails 3x, but market sell succeeds."""
        broker = FakeBrokerAdapter(
            positions=[
                make_position(
                    symbol="AAPL",
                    qty=Decimal("100"),
                    avg_entry_price=Decimal("150.00"),
                ),
            ],
        )

        call_count = 0

        async def fail_stop_succeed_market(order: OrderRequest) -> BrokerOrderStatus:
            nonlocal call_count
            call_count += 1
            if call_count <= 3:  # 3 stop attempts
                raise RuntimeError("Stop failed")
            return make_order_status(broker_order_id=f"mkt-{call_count}")

        broker.submit_order = fail_stop_succeed_market  # type: ignore[method-assign]
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert any("Emergency stop failed" in e for e in result.errors)
        assert not any("Market sell fallback also failed" in e for e in result.errors)


class TestOrderReconciliationEdgeCases:
    """Edge cases in order reconciliation logic."""

    async def test_individual_order_lookup_failure_records_error(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When individual order lookup raises, error is recorded."""
        local_order = _make_local_order(
            local_id="local-stale",
            broker_id="old-id",
            state="submitted",
        )
        await _insert_order(db_session_factory, local_order)

        broker = FakeBrokerAdapter()
        broker.get_order_status = AsyncMock(  # type: ignore[method-assign]
            side_effect=ConnectionError("timeout"),
        )
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert any("Individual lookup failed" in e for e in result.errors)

    async def test_orphan_broker_order_cancel_failure_records_error(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When cancelling an orphan broker order fails, error is recorded."""
        orphan_order = make_order_status(
            broker_order_id="orphan-001",
            symbol="AAPL",
            status=BrokerOrderStatus.NEW,
        )
        broker = FakeBrokerAdapter(open_orders=[orphan_order])
        broker.cancel_order = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("cancel failed"),
        )
        reconciler = StartupReconciler(broker, db_session_factory, _EMERGENCY_STOP_PCT)

        result = await reconciler.reconcile()

        assert any("Failed to cancel orphan" in e for e in result.errors)
