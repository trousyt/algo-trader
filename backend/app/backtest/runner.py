"""Backtest runner — orchestrates the full simulation loop.

Wires together: BacktestExecution, CandleAggregator, IndicatorCalculator,
Strategy (VelezStrategy), PositionSizer, CircuitBreaker.
Stores results in backtest_run / backtest_trade DB tables.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC as _UTC
from datetime import date, datetime
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backtest.config import BacktestConfig, BacktestError, BacktestTradeData
from app.backtest.data_loader import BacktestDataLoader
from app.backtest.executor import BacktestExecution, Fill
from app.backtest.metrics import BacktestMetrics, BacktestMetricsData
from app.broker.types import Bar, OrderRequest, OrderType, Side
from app.config import AppConfig, RiskConfig, VelezConfig
from app.engine.candle_aggregator import CandleAggregator
from app.engine.indicators import IndicatorCalculator, IndicatorSet
from app.models.backtest import BacktestRunModel, BacktestTradeModel
from app.orders.types import OrderRole
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.position_sizer import PositionSizer
from app.strategy.base import Strategy
from app.strategy.velez import VelezStrategy

log = structlog.get_logger()

_ZERO = Decimal("0")


@dataclass(frozen=True)
class BacktestResult:
    """Complete results of a backtest run."""

    run_id: int
    metrics: BacktestMetricsData
    trades: list[BacktestTradeData]
    equity_curve: list[tuple[datetime, Decimal]]


class BacktestRunner:
    """Orchestrates a complete backtest run.

    Accepts optional `bars` for testing (bypasses network data loading).
    """

    def __init__(
        self,
        config: BacktestConfig,
        app_config: AppConfig,
        session_factory: async_sessionmaker[AsyncSession],
        bars: list[Bar] | None = None,
    ) -> None:
        self._config = config
        self._app_config = app_config
        self._session_factory = session_factory
        self._bars = bars

    async def run(self) -> BacktestResult:
        """Execute the full backtest pipeline."""
        t0 = time.monotonic()

        # 1. Load historical bars (or use injected bars for testing)
        bars = self._bars if self._bars is not None else await self._load_data()
        log.info("backtest_bars_ready", bar_count=len(bars))

        # 2. Initialize components
        risk_config = self._app_config.risk
        velez_config = self._app_config.velez

        execution = BacktestExecution(
            initial_capital=self._config.initial_capital,
            slippage_per_share=self._config.slippage_per_share,
        )

        aggregators = {
            sym: CandleAggregator(sym, self._config.candle_interval_minutes)
            for sym in self._config.symbols
        }
        indicators = {
            sym: IndicatorCalculator(
                fast_period=velez_config.sma_fast,
                slow_period=velez_config.sma_slow,
            )
            for sym in self._config.symbols
        }
        strategies = {
            sym: _resolve_strategy(self._config.strategy, sym, velez_config)
            for sym in self._config.symbols
        }

        position_sizer = PositionSizer(risk_config)
        circuit_breaker = CircuitBreaker(
            max_daily_loss_pct=risk_config.max_daily_loss_pct,
            consecutive_loss_pause=risk_config.consecutive_loss_pause,
        )
        max_open_positions = risk_config.max_open_positions

        # 3. Main simulation loop
        current_date: date | None = None
        last_bar_by_symbol: dict[str, Bar] = {}
        daily_equity: list[tuple[date, Decimal]] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        completed_trades: list[BacktestTradeData] = []
        day_count = 0

        for bar in bars:
            bar_date = bar.timestamp.date()

            # Day transition
            if bar_date != current_date:
                if current_date is not None:
                    # Flush partial candles
                    for agg in aggregators.values():
                        agg.flush()
                    # Force-close all positions
                    self._close_eod_positions(
                        execution, completed_trades,
                        last_bar_by_symbol, strategies,
                    )
                    # Cancel all pending orders
                    execution.cancel_all_pending()
                    # Record EOD equity
                    daily_equity.append((current_date, execution.equity))
                    day_count += 1
                    log.info(
                        "backtest_day_complete",
                        date=str(current_date),
                        equity=str(execution.equity),
                        day=day_count,
                    )

                current_date = bar_date
                circuit_breaker.reset_daily(execution.equity)

            last_bar_by_symbol[bar.symbol] = bar

            # Check pending orders against this bar
            fills = execution.process_bar(bar)

            # Update position market prices
            execution.update_market_prices(bar)

            # Process fills
            for fill in fills:
                self._handle_fill(
                    fill, execution, circuit_breaker,
                    strategies, completed_trades,
                )

            # Aggregate candle
            candle = aggregators[bar.symbol].process_bar(bar)
            if candle is None:
                continue

            # Calculate indicators
            indicator_set = indicators[bar.symbol].process_candle(candle)

            # Strategy evaluation
            await self._evaluate_strategy(
                candle, indicator_set,
                strategies[bar.symbol], execution,
                position_sizer, circuit_breaker,
                max_open_positions,
            )

            # Record per-candle equity
            equity_curve.append((candle.timestamp, execution.equity))

        # 4. Final day: force-close + final equity
        if current_date is not None:
            for agg in aggregators.values():
                agg.flush()
            self._close_eod_positions(
                execution, completed_trades,
                last_bar_by_symbol, strategies,
            )
            execution.cancel_all_pending()
            daily_equity.append((current_date, execution.equity))

        elapsed = time.monotonic() - t0
        log.info(
            "backtest_complete",
            elapsed_sec=round(elapsed, 2),
            bars_total=len(bars),
            bars_per_sec=round(len(bars) / elapsed, 0) if elapsed > 0 else 0,
            trades=len(completed_trades),
        )

        # 5. Compute metrics
        metrics = BacktestMetrics.calculate(
            trades=completed_trades,
            daily_equity=daily_equity,
            equity_curve=equity_curve,
            initial_capital=self._config.initial_capital,
        )

        # 6. Store results
        run_id = await self._store_results(
            metrics, completed_trades, daily_equity,
        )

        return BacktestResult(
            run_id=run_id,
            metrics=metrics,
            trades=completed_trades,
            equity_curve=equity_curve,
        )

    # ------------------------------------------------------------------
    # Strategy evaluation (per candle)
    # ------------------------------------------------------------------

    async def _evaluate_strategy(
        self,
        candle: Bar,
        indicators: IndicatorSet,
        strategy: Strategy,
        execution: BacktestExecution,
        sizer: PositionSizer,
        cb: CircuitBreaker,
        max_open_positions: int,
    ) -> None:
        symbol = candle.symbol

        if execution.has_position(symbol):
            position = execution.get_position(symbol)
            # Trailing stop update
            new_stop = strategy.should_update_stop(candle, position, indicators)
            if new_stop is not None:
                execution.update_stop(symbol, new_stop)
            # Exit signal
            if strategy.should_exit(candle, position, indicators):
                await execution.submit_order(OrderRequest(
                    symbol=symbol,
                    side=Side.SELL,
                    order_type=OrderType.MARKET,
                    qty=position.qty,
                ))

        elif execution.has_pending_entry(symbol):
            execution.increment_candle_count(symbol)
            if strategy.should_cancel_pending(
                candle, execution.candles_since_order(symbol),
            ):
                execution.cancel_pending_entry(symbol)

        else:
            # New signal detection
            if indicators.bar_count < strategy.required_history:
                return
            if not strategy.should_long(candle, indicators):
                return

            # Risk checks
            can_trade, _reason = cb.can_trade()
            if not can_trade:
                return

            if execution.open_position_count >= max_open_positions:
                return

            entry_price = strategy.entry_price(candle, indicators)
            stop_price = strategy.stop_loss_price(candle, indicators)

            sizing_result = sizer.calculate(
                equity=execution.equity,
                buying_power=execution.cash,
                entry_price=entry_price,
                stop_loss_price=stop_price,
            )
            if sizing_result.qty <= 0:
                return

            # Place buy-stop entry
            await execution.submit_order(OrderRequest(
                symbol=symbol,
                side=Side.BUY,
                order_type=OrderType.STOP,
                qty=sizing_result.qty,
                stop_price=entry_price,
            ))
            execution.set_planned_stop(symbol, stop_price)

    # ------------------------------------------------------------------
    # Fill handling
    # ------------------------------------------------------------------

    def _handle_fill(
        self,
        fill: Fill,
        execution: BacktestExecution,
        circuit_breaker: CircuitBreaker,
        strategies: dict[str, Strategy],
        trades: list[BacktestTradeData],
    ) -> None:
        if fill.order_role == OrderRole.ENTRY:
            # Place stop-loss for the new position
            stop_price = execution.get_planned_stop(fill.symbol)
            # Submit synchronously via the async method (BacktestExecution is
            # in-memory, so we create a pending order directly to avoid needing
            # to await inside a sync method).
            self._submit_stop_sync(execution, fill, stop_price)

        elif fill.order_role in (OrderRole.STOP_LOSS, OrderRole.EXIT_MARKET):
            closed_pos = execution.get_closed_position(fill.symbol)
            pnl = (fill.fill_price - closed_pos.avg_entry_price) * closed_pos.qty
            trade = BacktestTradeData(
                symbol=fill.symbol,
                side="buy",
                qty=closed_pos.qty,
                entry_price=closed_pos.avg_entry_price,
                exit_price=fill.fill_price,
                entry_at=closed_pos.opened_at,
                exit_at=fill.timestamp,
                pnl=pnl,
                duration_seconds=int(
                    (fill.timestamp - closed_pos.opened_at).total_seconds(),
                ),
            )
            trades.append(trade)
            circuit_breaker.record_trade(trade.pnl)
            strategies[fill.symbol].on_position_closed()

    def _submit_stop_sync(
        self,
        execution: BacktestExecution,
        fill: Fill,
        stop_price: Decimal,
    ) -> None:
        """Submit stop-loss order synchronously (avoids async in sync context).

        BacktestExecution.submit_order is async for protocol compliance but
        actually synchronous in-memory. We access internals directly here.
        """
        from app.backtest.executor import _PendingOrder

        oid = execution._next_id()
        execution._pending_orders[oid] = _PendingOrder(
            order_id=oid,
            symbol=fill.symbol,
            side=Side.SELL,
            qty=fill.qty,
            order_type=OrderType.STOP,
            stop_price=stop_price,
            limit_price=None,
            role=OrderRole.STOP_LOSS,
        )

    # ------------------------------------------------------------------
    # EOD force-close
    # ------------------------------------------------------------------

    def _close_eod_positions(
        self,
        execution: BacktestExecution,
        trades: list[BacktestTradeData],
        last_bar_by_symbol: dict[str, Bar],
        strategies: dict[str, Strategy],
    ) -> None:
        """Force-close all open positions at EOD using last bar close."""
        symbols_to_close = list(execution._positions.keys())
        for symbol in symbols_to_close:
            last_bar = last_bar_by_symbol.get(symbol)
            if last_bar is None:
                continue

            pos = execution._positions[symbol]
            # Simulate sell at close - slippage (clamped to bar.low)
            fill_price = max(
                last_bar.close - execution._slippage,
                last_bar.low,
            )
            fill_price = max(fill_price, Decimal("0.01"))

            # Credit cash
            proceeds = pos.qty * fill_price
            execution._cash += proceeds

            # Record closed position
            execution._closed_positions[symbol] = pos
            del execution._positions[symbol]

            # Cancel any pending stop for this symbol
            to_remove = [
                oid for oid, o in execution._pending_orders.items()
                if o.symbol == symbol
            ]
            for oid in to_remove:
                del execution._pending_orders[oid]

            # Record trade
            pnl = (fill_price - pos.avg_entry_price) * pos.qty
            trade = BacktestTradeData(
                symbol=symbol,
                side="buy",
                qty=pos.qty,
                entry_price=pos.avg_entry_price,
                exit_price=fill_price,
                entry_at=pos.opened_at,
                exit_at=last_bar.timestamp,
                pnl=pnl,
                duration_seconds=int(
                    (last_bar.timestamp - pos.opened_at).total_seconds(),
                ),
            )
            trades.append(trade)
            strategies[symbol].on_position_closed()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_data(self) -> list[Bar]:
        loader = BacktestDataLoader(self._app_config.broker)
        return await loader.load_bars(
            symbols=self._config.symbols,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
        )

    # ------------------------------------------------------------------
    # DB storage
    # ------------------------------------------------------------------

    async def _store_results(
        self,
        metrics: BacktestMetricsData,
        trades: list[BacktestTradeData],
        daily_equity: list[tuple[date, Decimal]],
    ) -> int:
        """Store backtest results in database. Returns the run ID."""
        params = {
            "strategy": self._config.strategy,
            "symbols": self._config.symbols,
            "start_date": str(self._config.start_date),
            "end_date": str(self._config.end_date),
            "initial_capital": str(self._config.initial_capital),
            "slippage_per_share": str(self._config.slippage_per_share),
            "candle_interval_minutes": self._config.candle_interval_minutes,
        }

        # EOD equity curve for DB storage (daily granularity)
        eq_curve_json = json.dumps([
            {"date": str(d), "equity": str(eq)}
            for d, eq in daily_equity
        ])

        run = BacktestRunModel(
            strategy=self._config.strategy,
            symbols=json.dumps(self._config.symbols),
            start_date=str(self._config.start_date),
            end_date=str(self._config.end_date),
            initial_capital=self._config.initial_capital,
            params=json.dumps(params),
            total_return=metrics.total_return,
            win_rate=Decimal(str(metrics.win_rate)),
            profit_factor=Decimal(str(metrics.profit_factor)),
            sharpe_ratio=Decimal(str(metrics.sharpe_ratio)),
            max_drawdown=Decimal(str(metrics.max_drawdown)),
            total_trades=metrics.total_trades,
            equity_curve=eq_curve_json,
            created_at=datetime.now(tz=_UTC).isoformat(),
        )

        async with self._session_factory() as session:
            session.add(run)
            await session.flush()
            run_id = run.id

            for t in trades:
                session.add(BacktestTradeModel(
                    run_id=run_id,
                    symbol=t.symbol,
                    side=t.side,
                    qty=t.qty,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    entry_at=t.entry_at.isoformat(),
                    exit_at=t.exit_at.isoformat(),
                    pnl=t.pnl,
                    duration_seconds=t.duration_seconds,
                ))

            await session.commit()

        log.info("backtest_results_stored", run_id=run_id)
        return run_id


def _resolve_strategy(
    name: str, symbol: str, velez_config: VelezConfig,
) -> Strategy:
    """Create strategy instance. Raises BacktestError for unknown names."""
    if name == "velez":
        return VelezStrategy(symbol=symbol, config=velez_config)
    raise BacktestError(f"Unknown strategy: {name!r}. Available: velez")
