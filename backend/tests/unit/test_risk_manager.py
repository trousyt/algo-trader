"""Tests for RiskManager -- pre-order approval facade."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.broker.fake.broker import FakeBrokerAdapter
from app.config import RiskConfig
from app.models.base import Base
from app.models.order import OrderStateModel
from app.orders.types import OrderRole, OrderState
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.position_sizer import PositionSizer
from app.risk.risk_manager import RiskManager
from app.utils.time import format_timestamp, utc_now
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


@pytest.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create in-memory async SQLite with all tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory


async def _insert_open_entry(
    session_factory: async_sessionmaker[AsyncSession],
    symbol: str = "AAPL",
    state: str = "accepted",
) -> None:
    """Insert a non-terminal entry order into the DB."""
    now = format_timestamp(utc_now())
    async with session_factory() as session:
        async with session.begin():
            session.add(
                OrderStateModel(
                    local_id=f"ord-{symbol}-{state}-{now}",
                    correlation_id=f"corr-{symbol}",
                    symbol=symbol,
                    side="buy",
                    order_type="stop",
                    order_role=OrderRole.ENTRY.value,
                    qty_requested=Decimal("10"),
                    state=state,
                    created_at=now,
                    updated_at=now,
                )
            )


class TestRiskManagerApproved:
    """Approved signal with valid sizing."""

    async def test_approved_signal(
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

        signal = make_signal()
        result = await rm.approve(signal)

        assert result.approved is True
        assert result.qty > Decimal("0")
        assert result.reason == ""


class TestRiskManagerRejections:
    """Rejection scenarios."""

    async def test_rejected_circuit_breaker_tripped(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config()
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)

        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)
        # Trip the circuit breaker
        cb.record_trade(Decimal("-100"))
        cb.record_trade(Decimal("-100"))
        cb.record_trade(Decimal("-100"))

        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        result = await rm.approve(make_signal())
        assert result.approved is False
        assert "Consecutive loss limit" in result.reason

    async def test_rejected_max_open_positions(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config(max_open_positions=2)
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)

        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)

        # Insert 2 open entries
        await _insert_open_entry(db_session_factory, "AAPL")
        await _insert_open_entry(db_session_factory, "TSLA")

        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        result = await rm.approve(make_signal(symbol="NVDA"))
        assert result.approved is False
        assert "Max open positions" in result.reason

    async def test_rejected_insufficient_buying_power(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config()
        account = make_account_info(buying_power=Decimal("10"))
        broker = FakeBrokerAdapter(account=account)

        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)

        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        result = await rm.approve(make_signal())
        assert result.approved is False
        assert "buying power" in result.reason.lower()

    async def test_rejected_position_size_rounds_to_zero(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Very small equity + wide stop = zero shares."""
        config = _risk_config()
        account = make_account_info(
            equity=Decimal("1000"),
            buying_power=Decimal("2000"),
        )
        broker = FakeBrokerAdapter(account=account)

        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)

        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        signal = make_signal(
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("85.00"),
        )
        result = await rm.approve(signal)
        assert result.approved is False
        assert "Risk budget too small" in result.reason


class TestRiskManagerNoAccountCache:
    """Each call hits the broker (no cache)."""

    async def test_each_call_fetches_account(
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

        # First call succeeds
        result1 = await rm.approve(make_signal())
        assert result1.approved is True

        # Change account to low buying power
        broker._account = make_account_info(buying_power=Decimal("10"))

        # Second call should see the new account data
        result2 = await rm.approve(make_signal())
        assert result2.approved is False
        assert "buying power" in result2.reason.lower()


class TestRiskManagerTerminalOrdersNotCounted:
    """Terminal orders are not counted as open positions."""

    async def test_filled_orders_not_counted(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = _risk_config(max_open_positions=1)
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)

        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)

        # Insert a terminal (filled) entry
        await _insert_open_entry(
            db_session_factory,
            "AAPL",
            state=OrderState.FILLED.value,
        )

        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        # Should approve -- filled order doesn't count
        result = await rm.approve(make_signal(symbol="TSLA"))
        assert result.approved is True

    async def test_stop_loss_orders_not_counted(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Stop-loss orders are not counted as open positions."""
        config = _risk_config(max_open_positions=1)
        account = make_account_info()
        broker = FakeBrokerAdapter(account=account)

        cb = CircuitBreaker(config.max_daily_loss_pct, config.consecutive_loss_pause)
        cb.reset_daily(account.equity)

        # Insert a stop-loss order (not entry)
        now = format_timestamp(utc_now())
        async with db_session_factory() as session:
            async with session.begin():
                session.add(
                    OrderStateModel(
                        local_id="ord-stop-1",
                        correlation_id="corr-1",
                        symbol="AAPL",
                        side="sell",
                        order_type="stop",
                        order_role=OrderRole.STOP_LOSS.value,
                        qty_requested=Decimal("10"),
                        state=OrderState.ACCEPTED.value,
                        created_at=now,
                        updated_at=now,
                    )
                )

        sizer = PositionSizer(config)
        rm = RiskManager(config, broker, cb, sizer, db_session_factory)

        result = await rm.approve(make_signal())
        assert result.approved is True
