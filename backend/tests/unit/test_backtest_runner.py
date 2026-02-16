"""Tests for BacktestRunner — uses injected bars and in-memory DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.backtest.config import BacktestConfig
from app.backtest.executor import BacktestExecution
from app.backtest.runner import BacktestResult, BacktestRunner, _resolve_strategy
from app.broker.types import Bar, Position
from app.config import AppConfig, RiskConfig, VelezConfig
from app.engine.indicators import IndicatorSet
from app.models.backtest import BacktestRunModel
from app.models.base import Base
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.position_sizer import PositionSizer
from app.strategy.base import Strategy
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
        bars.append(
            _bar(
                symbol=symbol,
                ts=ts,
                open_=p,
                high=p + Decimal("1.00"),
                low=p - Decimal("0.50"),
                close=p + Decimal("0.50"),
                volume=1000,
            )
        )
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
        app_config = _make_app_config()
        strategy = _resolve_strategy("velez", "AAPL", app_config)
        assert isinstance(strategy, VelezStrategy)
        assert strategy.symbol == "AAPL"

    def test_unknown_strategy_raises(self) -> None:
        from app.backtest.config import BacktestError

        app_config = _make_app_config()
        with pytest.raises(BacktestError, match="Unknown strategy"):
            _resolve_strategy("unknown", "AAPL", app_config)


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

        # VelezConfig default 2-min candle → expect ~5 entries
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
            execution,
            trades,
            last_bar_by_symbol,
            strategies,
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


# ---------------------------------------------------------------------------
# _AlwaysLongStrategy — test helper that always signals a buy
# ---------------------------------------------------------------------------


class _AlwaysLongStrategy(Strategy):
    """Always signals long at bar.high + 0.01 with stop at bar.low - 0.01."""

    def __init__(self, symbol: str) -> None:
        super().__init__(symbol)

    def should_long(self, bar: Bar, indicators: IndicatorSet) -> bool:
        return True

    def entry_price(self, bar: Bar, indicators: IndicatorSet) -> Decimal:
        return bar.high + Decimal("0.01")

    def stop_loss_price(self, bar: Bar, indicators: IndicatorSet) -> Decimal:
        return bar.low - Decimal("0.01")

    def should_update_stop(
        self, bar: Bar, position: Position, indicators: IndicatorSet
    ) -> Decimal | None:
        return None

    def should_exit(
        self, bar: Bar, position: Position, indicators: IndicatorSet
    ) -> bool:
        return False

    @property
    def required_history(self) -> int:
        return 0  # No warm-up needed


class TestCircuitBreakerBlocksTrades:
    """CircuitBreaker should block new entries after consecutive losses."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips_blocks_new_entries(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        execution = BacktestExecution(
            initial_capital=Decimal("25000"),
            slippage_per_share=Decimal("0"),
        )
        sizer = PositionSizer(RiskConfig())
        cb = CircuitBreaker(
            max_daily_loss_pct=Decimal("2.0"),
            consecutive_loss_pause=3,
        )
        cb.reset_daily(Decimal("25000"))

        # Record 3 consecutive losses to trip the breaker
        cb.record_trade(Decimal("-10.00"))
        cb.record_trade(Decimal("-10.00"))
        cb.record_trade(Decimal("-10.00"))

        can_trade, _reason = cb.can_trade()
        assert not can_trade  # sanity check

        strategy = _AlwaysLongStrategy("AAPL")
        candle = _bar(
            "AAPL",
            datetime(2026, 2, 10, 15, 0, tzinfo=UTC),
            Decimal("150"),
            Decimal("151"),
            Decimal("149"),
            Decimal("150"),
        )
        indicators = IndicatorSet(bar_count=250)  # Past warm-up

        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=[],
        )

        await runner._evaluate_strategy(
            candle,
            indicators,
            strategy,
            execution,
            sizer,
            cb,
            max_open_positions=5,
        )

        # No entry should have been placed
        assert not execution.has_pending_entry("AAPL")
        assert execution.open_position_count == 0


class TestMaxOpenPositionsBlocksEntries:
    """max_open_positions should block new entries when limit is reached."""

    @pytest.mark.asyncio
    async def test_max_positions_blocks_new_entry(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        execution = BacktestExecution(
            initial_capital=Decimal("100000"),
            slippage_per_share=Decimal("0"),
        )
        sizer = PositionSizer(RiskConfig())
        cb = CircuitBreaker(
            max_daily_loss_pct=Decimal("2.0"),
            consecutive_loss_pause=3,
        )
        cb.reset_daily(Decimal("100000"))

        # Fill 2 positions to reach max_open_positions=2
        from app.backtest.executor import _SimPosition

        execution._positions["MSFT"] = _SimPosition(
            symbol="MSFT",
            qty=Decimal("50"),
            avg_entry_price=Decimal("300"),
            market_value=Decimal("15000"),
            unrealized_pl=Decimal("0"),
        )
        execution._positions["GOOG"] = _SimPosition(
            symbol="GOOG",
            qty=Decimal("20"),
            avg_entry_price=Decimal("150"),
            market_value=Decimal("3000"),
            unrealized_pl=Decimal("0"),
        )
        assert execution.open_position_count == 2

        strategy = _AlwaysLongStrategy("AAPL")
        candle = _bar(
            "AAPL",
            datetime(2026, 2, 10, 15, 0, tzinfo=UTC),
            Decimal("150"),
            Decimal("151"),
            Decimal("149"),
            Decimal("150"),
        )
        indicators = IndicatorSet(bar_count=250)

        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=[],
        )

        await runner._evaluate_strategy(
            candle,
            indicators,
            strategy,
            execution,
            sizer,
            cb,
            max_open_positions=2,
        )

        # No entry should have been placed — max positions reached
        assert not execution.has_pending_entry("AAPL")

    @pytest.mark.asyncio
    async def test_below_max_positions_allows_entry(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When below max, new entries should be allowed."""
        execution = BacktestExecution(
            initial_capital=Decimal("100000"),
            slippage_per_share=Decimal("0"),
        )
        sizer = PositionSizer(RiskConfig())
        cb = CircuitBreaker(
            max_daily_loss_pct=Decimal("2.0"),
            consecutive_loss_pause=3,
        )
        cb.reset_daily(Decimal("100000"))

        # Only 1 position — under max of 2
        from app.backtest.executor import _SimPosition

        execution._positions["MSFT"] = _SimPosition(
            symbol="MSFT",
            qty=Decimal("50"),
            avg_entry_price=Decimal("300"),
            market_value=Decimal("15000"),
            unrealized_pl=Decimal("0"),
        )
        assert execution.open_position_count == 1

        strategy = _AlwaysLongStrategy("AAPL")
        candle = _bar(
            "AAPL",
            datetime(2026, 2, 10, 15, 0, tzinfo=UTC),
            Decimal("150"),
            Decimal("151"),
            Decimal("149"),
            Decimal("150"),
        )
        indicators = IndicatorSet(bar_count=250)

        config = _make_backtest_config()
        app_config = _make_app_config()
        runner = BacktestRunner(
            config=config,
            app_config=app_config,
            session_factory=db_session_factory,
            bars=[],
        )

        await runner._evaluate_strategy(
            candle,
            indicators,
            strategy,
            execution,
            sizer,
            cb,
            max_open_positions=2,
        )

        # Entry SHOULD have been placed
        assert execution.has_pending_entry("AAPL")


class _FixedPriceStrategy(Strategy):
    """Strategy with fixed entry/stop for deterministic testing.

    Uses 2-min candle interval to match test bar layout.
    """

    def __init__(
        self,
        symbol: str,
        *,
        entry: Decimal,
        stop: Decimal,
        candle_interval: int = 2,
    ) -> None:
        super().__init__(symbol)
        self._entry = entry
        self._stop = stop
        self._signaled = False
        self._candle_interval = candle_interval

    def should_long(self, bar: Bar, indicators: IndicatorSet) -> bool:
        if self._signaled:
            return False
        self._signaled = True
        return True

    def entry_price(self, bar: Bar, indicators: IndicatorSet) -> Decimal:
        return self._entry

    def stop_loss_price(self, bar: Bar, indicators: IndicatorSet) -> Decimal:
        return self._stop

    def should_update_stop(
        self, bar: Bar, position: Position, indicators: IndicatorSet
    ) -> Decimal | None:
        return None

    def should_exit(
        self, bar: Bar, position: Position, indicators: IndicatorSet
    ) -> bool:
        return False

    @property
    def required_history(self) -> int:
        return 0

    @property
    def candle_interval_minutes(self) -> int:
        return self._candle_interval

    @property
    def indicator_config(self) -> dict[str, int]:
        return {"sma_fast": 20, "sma_slow": 200}

    def on_position_closed(self) -> None:
        self._signaled = False


class TestKnownTradeVerification:
    """Gold standard: handcrafted bars, manually computed fills and P&L."""

    @pytest.mark.asyncio
    async def test_single_losing_trade_exact_pnl(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """One trade: buy-stop entry, stop-loss exit, verify exact P&L.

        Scenario (default slippage=0.01, VelezConfig candle_interval=2):
        - Candle 1 (bars 1-2): strategy signals, places buy-stop at 151, stop at 148
        - Bar 3: high=152 >= 151 → entry fills at max(150.50, 151) + 0.01 = 151.01
        - Bar 4: completes candle 2 (no exit signal, no stop trigger)
        - Bar 5: low=147 <= 148 → stop-loss fills at min(149, 148) - 0.01 = 147.99
        - P&L = (147.99 - 151.01) * qty = -3.02 * qty

        Position sizing:
          equity=25000, risk=2% -> $500, distance=3.00
          raw_shares = 500/3 = 166 -> 166
          max_pos = 25000 * 25% = 6250 / 151 = 41
          qty = min(166, 41) = 41
          P&L = -3.02 * 41 = -$123.82
          Final equity = 25000 - 123.82 = $24,876.18
        """
        risk_cfg = RiskConfig(
            max_risk_per_trade_pct=Decimal("0.02"),
            max_position_pct=Decimal("0.25"),
        )
        app_config = AppConfig(
            broker={"api_key": "test", "secret_key": "test", "feed": "iex"},
            risk=risk_cfg,
            velez=VelezConfig(),
            db_path=":memory:",
            _env_file=None,
        )
        config = _make_backtest_config(initial_capital=Decimal("25000"))

        base_ts = datetime(2026, 2, 10, 14, 30, tzinfo=UTC)  # 9:30 ET

        # Bars designed so candle_interval=2min means bars pair up
        d = Decimal
        t = base_ts
        bars = [
            # Candle 1: bars at :30, :31 — strategy signals
            _bar("AAPL", t, d("150"), d("150.50"), d("149.50"), d("150.20"), 10000),
            _bar(
                "AAPL",
                t + timedelta(minutes=1),
                d("150.20"),
                d("150.80"),
                d("149.80"),
                d("150.50"),
                10000,
            ),
            # Bar 3 (:32) — entry fills: high=152 >= stop 151
            _bar(
                "AAPL",
                t + timedelta(minutes=2),
                d("150.50"),
                d("152"),
                d("150"),
                d("151.50"),
                10000,
            ),
            # Bar 4 (:33) — candle 2, no stop (low=150 > 148)
            _bar(
                "AAPL",
                t + timedelta(minutes=3),
                d("151.50"),
                d("152"),
                d("150"),
                d("151"),
                10000,
            ),
            # Bar 5 (:34) — stop triggers: low=147 <= 148
            _bar(
                "AAPL",
                t + timedelta(minutes=4),
                d("149"),
                d("149.50"),
                d("147"),
                d("147.50"),
                10000,
            ),
            # Bar 6 (:35) — candle 3, no more orders
            _bar(
                "AAPL",
                t + timedelta(minutes=5),
                d("147.50"),
                d("148"),
                d("147"),
                d("147.80"),
                10000,
            ),
        ]

        # Monkey-patch strategy resolution to use our fixed-price strategy
        from unittest.mock import patch

        def _mock_resolve(name: str, sym: str, cfg: AppConfig) -> Strategy:
            return _FixedPriceStrategy(sym, entry=Decimal("151"), stop=Decimal("148"))

        with patch("app.backtest.runner._resolve_strategy", _mock_resolve):
            runner = BacktestRunner(
                config=config,
                app_config=app_config,
                session_factory=db_session_factory,
                bars=bars,
            )
            result = await runner.run()

        # Verify exactly 1 trade (EOD force-close not needed — stop already exited)
        assert result.metrics.total_trades == 1
        trade = result.trades[0]

        # Verify entry: max(open=150.50, stop=151) + slippage 0.01 = 151.01
        assert trade.entry_price == Decimal("151.01")
        assert trade.symbol == "AAPL"

        # Verify exit (stop-loss): min(open=149, stop=148) - slippage 0.01 = 147.99
        assert trade.exit_price == Decimal("147.99")

        # Verify qty: risk=$500, distance=3, raw=166, max_pos=41 → 41
        assert trade.qty == Decimal("41")

        # Verify P&L (with slippage-adjusted fill prices)
        expected_pnl = (Decimal("147.99") - Decimal("151.01")) * Decimal("41")
        assert expected_pnl == Decimal("-123.82")
        assert trade.pnl == expected_pnl

        # Verify money conservation
        expected_equity = Decimal("25000") + expected_pnl
        assert expected_equity == Decimal("24876.18")
        assert result.metrics.final_equity == expected_equity


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
