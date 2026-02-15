"""Integration tests: full signal -> approve -> submit -> fill -> trade lifecycle.

These tests wire together RiskManager, OrderManager, and FakeBrokerAdapter
with an in-memory async SQLite database to exercise the complete order flow.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.broker.fake.broker import FakeBrokerAdapter
from app.broker.types import (
    Side,
    TradeEventType,
    TradeUpdate,
)
from app.config import RiskConfig
from app.models.base import Base
from app.models.order import OrderStateModel, TradeModel
from app.orders.order_manager import OrderManager
from app.orders.types import OrderState
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.position_sizer import PositionSizer
from app.risk.risk_manager import RiskManager
from app.utils.time import utc_now
from tests.factories import make_account_info, make_signal


def _risk_config(**overrides: object) -> RiskConfig:
    defaults = {
        "max_risk_per_trade_pct": Decimal("0.01"),
        "max_risk_per_trade_abs": Decimal("500"),
        "max_position_pct": Decimal("0.05"),
        "max_daily_loss_pct": Decimal("0.03"),
        "max_open_positions": 5,
        "consecutive_loss_pause": 3,
    }
    defaults.update(overrides)
    return RiskConfig(**defaults)  # type: ignore[arg-type]


def _make_trade_update(
    *,
    event: TradeEventType,
    order_id: str,
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    qty: Decimal = Decimal("10"),
    filled_qty: Decimal = Decimal("10"),
    filled_avg_price: Decimal | None = Decimal("155.20"),
) -> TradeUpdate:
    return TradeUpdate(
        event=event,
        order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
        timestamp=utc_now(),
    )


@pytest.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


class TestHappyPathLifecycle:
    """Full happy path: signal -> risk -> submit -> fill -> stop -> trade."""

    async def test_signal_to_trade_record(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config()
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)
        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)
        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)
        om = OrderManager(broker, db_session_factory)

        # 1. Strategy generates signal
        signal = make_signal(
            symbol="AAPL",
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("154.70"),
        )

        # 2. Risk manager approves
        approval = await rm.approve(signal)
        assert approval.approved is True
        assert approval.qty > Decimal("0")

        # 3. Submit entry order
        entry_result = await om.submit_entry(signal, approval)
        assert entry_result.state == OrderState.SUBMITTED

        # Get broker_id for fill simulation
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == entry_result.local_id,
                    )
                )
            ).scalar_one()
            entry_broker_id = order.broker_id

        # 4. Broker fills entry
        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.FILL,
                order_id=entry_broker_id,
                filled_qty=approval.qty,
                filled_avg_price=signal.entry_price,
            )
        )

        # Verify entry is FILLED
        async with db_session_factory() as session:
            entry = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == entry_result.local_id,
                    )
                )
            ).scalar_one()
            assert entry.state == OrderState.FILLED.value

        # 5. TradingEngine submits stop-loss after fill
        stop_result = await om.submit_stop_loss(
            correlation_id=entry_result.correlation_id,
            symbol="AAPL",
            qty=approval.qty,
            stop_price=signal.stop_loss_price,
            parent_local_id=entry_result.local_id,
            strategy_name="velez",
        )
        assert stop_result.state == OrderState.SUBMITTED

        # Get stop broker_id
        async with db_session_factory() as session:
            stop = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == stop_result.local_id,
                    )
                )
            ).scalar_one()
            stop_broker_id = stop.broker_id

        # 6. Broker fills stop-loss (stop triggered)
        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.FILL,
                order_id=stop_broker_id,
                symbol="AAPL",
                side=Side.SELL,
                filled_qty=approval.qty,
                filled_avg_price=signal.stop_loss_price,
            )
        )

        # 7. Verify trade record created
        async with db_session_factory() as session:
            trades = (
                (
                    await session.execute(
                        select(TradeModel).where(
                            TradeModel.correlation_id == entry_result.correlation_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(trades) == 1
            trade = trades[0]
            assert trade.symbol == "AAPL"
            assert trade.side == "long"
            assert trade.entry_price == signal.entry_price
            assert trade.exit_price == signal.stop_loss_price

            # P&L = (154.70 - 155.20) * qty = -0.50 * qty
            expected_pnl = (signal.stop_loss_price - signal.entry_price) * approval.qty
            assert trade.pnl == expected_pnl
            assert trade.strategy == "velez"

        # 8. Circuit breaker is not auto-wired to OrderManager --
        # TradingEngine (Step 5) calls cb.record_trade() after trade creation.
        # Verify manual integration works:
        cb.record_trade(expected_pnl)
        assert cb.daily_realized_pnl == expected_pnl
        assert cb.consecutive_losses == 1


class TestCircuitBreakerBlocksSignal:
    """Circuit breaker trips -> rejects subsequent signals."""

    async def test_rejection_after_consecutive_losses(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config(consecutive_loss_pause=2)
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)
        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)
        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        # Trip the circuit breaker with 2 losses
        cb.record_trade(Decimal("-100"))
        cb.record_trade(Decimal("-100"))

        assert cb.is_paused is True

        # Next signal should be rejected
        signal = make_signal()
        approval = await rm.approve(signal)
        assert approval.approved is False
        assert "Consecutive loss limit" in approval.reason


class TestMaxOpenPositionsEnforced:
    """Max open positions limit blocks new entries."""

    async def test_blocked_when_at_limit(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config(max_open_positions=1)
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)
        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)
        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)
        om = OrderManager(broker, db_session_factory)

        # Submit first entry (fills the slot)
        signal1 = make_signal(symbol="AAPL")
        approval1 = await rm.approve(signal1)
        assert approval1.approved is True
        await om.submit_entry(signal1, approval1)

        # Second signal should be rejected (1 open position at limit)
        signal2 = make_signal(symbol="TSLA")
        approval2 = await rm.approve(signal2)
        assert approval2.approved is False
        assert "Max open positions" in approval2.reason


class TestMigration002:
    """Migration 002 creates expected schema changes."""

    def test_migration_002_order_role_column(self) -> None:
        """Covered by existing test_migrations.py:test_upgrade_from_empty
        which runs 'alembic upgrade head' and verifies all tables exist.
        The unit test TestTableCreation already verifies order_role column."""

    def test_migration_002_strategy_column(self) -> None:
        """Covered by TestTableCreation.test_order_state_columns which
        checks for 'strategy' in the column set."""

    def test_migration_002_parent_id_index(self) -> None:
        """Covered by TestTableCreation.test_order_state_columns and
        the migrated_engine fixture that runs upgrade head."""
