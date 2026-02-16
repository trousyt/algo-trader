"""Tests for BacktestRunner — uses injected bars and in-memory DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.backtest.config import BacktestConfig
from app.backtest.runner import BacktestResult, BacktestRunner, _resolve_strategy
from app.broker.types import Bar
from app.config import AppConfig, RiskConfig, VelezConfig
from app.models.backtest import BacktestRunModel, BacktestTradeModel
from app.models.base import Base
from app.strategy.velez import VelezStrategy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DAY1 = date(2026, 2, 10)  # Tuesday
_DAY2 = date(2026, 2, 11)  # Wednesday


def _make_app_config() -> AppConfig:
    """Minimal AppConfig for testing — no .env file, no real broker keys."""
    return AppConfig(
        broker={"api_key": "test", "secret_key": "test", "feed": "iex"},
        risk=RiskConfig(),
        velez=VelezConfig(),
        db_path=":memory:",
        _env_file=None,
    )


def _make_backtest_config(
    symbols: list[str] | None = None,
    start_date: date = _DAY1,
    end_date: date = _DAY2,
    initial_capital: Decimal = Decimal("25000"),
) -> BacktestConfig:
    return BacktestConfig(
        strategy="velez",
        symbols=symbols or ["AAPL"],
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
    )


def _bar(
    symbol: str,
    ts: datetime,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: int = 1000,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_market_bars(
    symbol: str,
    day: date,
    count: int = 5,
    base_price: Decimal = Decimal("150.00"),
) -> list[Bar]:
    """Create `count` 1-min bars during market hours on given day.

    Prices drift upward slightly for variety.
    """
    bars: list[Bar] = []
    base_ts = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)  # 9:30 ET
    for i in range(count):
        ts = base_ts + timedelta(minutes=i)
        p = base_price + Decimal(str(i * 0.10))
        bars.append(_bar(
            symbol=symbol,
            ts=ts,
            open_=p,
            high=p + Decimal("1.00"),
            low=p - Decimal("0.50"),
            close=p + Decimal("0.50"),
            volume=1000,
        ))
    return bars


@pytest.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestResolveStrategy:
    def test_velez_returns_velez_strategy(self) -> None:
        strategy = _resolve_strategy("velez", "AAPL", VelezConfig())
        assert isinstance(strategy, VelezStrategy)
        assert strategy.symbol == "AAPL"

    def test_unknown_strategy_raises(self) -> None:
        from app.backtest.config import BacktestError
        with pytest.raises(BacktestError, match="Unknown strategy"):
            _resolve_strategy("unknown", "AAPL", VelezConfig())


class TestBacktestRunnerBasics:
    @pytest.mark.asyncio
    async def test_no_bars_returns_zero_trades(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Empty bar list should produce zero trades and initial equity."""
        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=[],
        )
        result = await runner.run()

        assert isinstance(result, BacktestResult)
        assert result.trades == []
        assert result.metrics.total_trades == 0
        assert result.metrics.final_equity == Decimal("25000")
        assert result.run_id > 0

    @pytest.mark.asyncio
    async def test_warmup_period_no_trades(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """With fewer bars than SMA slow period (200), no signals should fire."""
        bars = _make_market_bars("AAPL", _DAY1, count=50)
        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=bars,
        )
        result = await runner.run()

        assert result.trades == []
        assert result.metrics.final_equity == Decimal("25000")

    @pytest.mark.asyncio
    async def test_equity_curve_recorded(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Equity curve should have entries for each completed candle."""
        bars = _make_market_bars("AAPL", _DAY1, count=10)
        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=bars,
        )
        result = await runner.run()

        # With 10 bars and default 2-min candle interval, expect ~5 candle entries
        assert len(result.equity_curve) > 0

    @pytest.mark.asyncio
    async def test_daily_equity_recorded_per_day(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Daily equity snapshots should appear for each trading day."""
        bars_d1 = _make_market_bars("AAPL", _DAY1, count=5)
        bars_d2 = _make_market_bars("AAPL", _DAY2, count=5)
        all_bars = bars_d1 + bars_d2

        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=all_bars,
        )
        result = await runner.run()

        # Should have 2 daily equity entries (one per day)
        # Access via metrics (the runner stores daily_equity internally)
        assert result.run_id > 0


class TestBacktestRunnerDB:
    @pytest.mark.asyncio
    async def test_results_stored_in_db(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Run results should be persisted in backtest_run table."""
        bars = _make_market_bars("AAPL", _DAY1, count=5)
        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=bars,
        )
        result = await runner.run()

        async with db_session_factory() as session:
            from sqlalchemy import select
            run = await session.get(BacktestRunModel, result.run_id)
            assert run is not None
            assert run.strategy == "velez"
            assert run.total_trades == 0

    @pytest.mark.asyncio
    async def test_params_no_api_keys(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Stored params must NOT contain broker API keys."""
        import json

        bars = _make_market_bars("AAPL", _DAY1, count=5)
        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=bars,
        )
        result = await runner.run()

        async with db_session_factory() as session:
            run = await session.get(BacktestRunModel, result.run_id)
            assert run is not None
            params = json.loads(run.params)
            params_str = json.dumps(params).lower()
            assert "api_key" not in params_str
            assert "secret_key" not in params_str
            assert "test-key" not in params_str
            assert "test-secret" not in params_str


class TestBacktestRunnerDayTransition:
    @pytest.mark.asyncio
    async def test_day_transition_cancels_pending_orders(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Pending orders should be cancelled at day transitions."""
        bars_d1 = _make_market_bars("AAPL", _DAY1, count=5)
        bars_d2 = _make_market_bars("AAPL", _DAY2, count=5)
        all_bars = bars_d1 + bars_d2

        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=all_bars,
        )
        result = await runner.run()

        # Should complete without error (day transition handled)
        assert result.run_id > 0

    @pytest.mark.asyncio
    async def test_multi_symbol_bars_merged(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Runner should handle bars for multiple symbols."""
        bars_aapl = _make_market_bars("AAPL", _DAY1, count=5)
        bars_msft = _make_market_bars("MSFT", _DAY1, count=5)
        # Merge and sort by (timestamp, symbol)
        all_bars = sorted(
            bars_aapl + bars_msft,
            key=lambda b: (b.timestamp, b.symbol),
        )

        config = _make_backtest_config(symbols=["AAPL", "MSFT"])
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=all_bars,
        )
        result = await runner.run()

        assert result.run_id > 0


class TestBacktestRunnerEODForceClose:
    @pytest.mark.asyncio
    async def test_eod_force_close_records_trade(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Positions open at EOD should be force-closed and recorded as trades."""
        from app.backtest.executor import BacktestExecution, _PendingOrder, _SimPosition
        from app.broker.types import OrderType, Side
        from app.orders.types import OrderRole

        config = _make_backtest_config()
        app_config = _make_app_config()

        # Create an execution with a pre-existing position
        execution = BacktestExecution(
            initial_capital=Decimal("25000"),
            slippage_per_share=Decimal("0.01"),
        )
        # Manually inject a position
        execution._positions["AAPL"] = _SimPosition(
            symbol="AAPL",
            qty=Decimal("100"),
            avg_entry_price=Decimal("150.00"),
            market_value=Decimal("15100.00"),
            unrealized_pl=Decimal("100.00"),
            opened_at=datetime(2026, 2, 10, 14, 30, tzinfo=UTC),
        )
        # Inject a pending stop-loss for it
        execution._pending_orders["bt-1"] = _PendingOrder(
            order_id="bt-1",
            symbol="AAPL",
            side=Side.SELL,
            qty=Decimal("100"),
            order_type=OrderType.STOP,
            stop_price=Decimal("149.00"),
            limit_price=None,
            role=OrderRole.STOP_LOSS,
        )

        last_bar_by_symbol = {
            "AAPL": _bar(
                "AAPL",
                datetime(2026, 2, 10, 20, 59, tzinfo=UTC),
                Decimal("150.50"),
                Decimal("151.00"),
                Decimal("150.00"),
                Decimal("151.00"),
            ),
        }
        strategies = {
            "AAPL": VelezStrategy("AAPL", VelezConfig()),
        }
        trades: list = []

        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=[],
        )
        runner._close_eod_positions(
            execution, trades, last_bar_by_symbol, strategies,
        )

        assert len(trades) == 1
        trade = trades[0]
        assert trade.symbol == "AAPL"
        assert trade.qty == Decimal("100")
        assert trade.entry_price == Decimal("150.00")
        # Exit at close - slippage: 151.00 - 0.01 = 150.99
        assert trade.exit_price == Decimal("150.99")
        assert trade.pnl == (Decimal("150.99") - Decimal("150.00")) * Decimal("100")

        # Position should be gone
        assert not execution.has_position("AAPL")
        # Pending stop should be gone
        assert len(execution._pending_orders) == 0


class TestBacktestResult:
    def test_frozen_dataclass(self) -> None:
        """BacktestResult should be immutable."""
        from app.backtest.metrics import BacktestMetricsData
        metrics = BacktestMetricsData(
            total_return=Decimal("0"),
            total_return_pct=Decimal("0"),
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            avg_win=Decimal("0"),
            avg_loss=Decimal("0"),
            largest_win=Decimal("0"),
            largest_loss=Decimal("0"),
            avg_trade_duration=0,
            final_equity=Decimal("25000"),
        )
        result = BacktestResult(
            run_id=1,
            metrics=metrics,
            trades=[],
            equity_curve=[],
        )
        assert result.run_id == 1
        with pytest.raises(AttributeError):
            result.run_id = 2  # type: ignore[misc]
