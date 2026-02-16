---
title: "feat: Add backtesting engine with simulated fills and performance metrics"
type: feat
date: 2026-02-15
step: 6
phase_1_plan: docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md
deepened: 2026-02-15
---

# Backtesting Engine (Step 6)

## Enhancement Summary

**Deepened on:** 2026-02-15
**Research agents used:** 11 (architecture-strategist, performance-oracle, kieran-python-reviewer, pattern-recognition-specialist, code-simplicity-reviewer, security-sentinel, spec-flow-analyzer, best-practices-researcher, framework-docs-researcher, learnings-researcher, repo-research-analyst)
**Additional sources:** Context7 (alpaca-py, Pydantic, Click), 6 web searches

### Critical Fixes (P1 — will cause runtime errors if not addressed)

1. **PositionSizer.calculate() signature wrong** — plan calls `(equity, entry_price, stop_distance)`, actual is `(equity, buying_power, entry_price, stop_loss_price) -> SizingResult`. Missing `buying_power`, wrong parameter.
2. **CircuitBreaker constructor wrong** — plan passes `RiskConfig` object, actual takes `(max_daily_loss_pct: Decimal, consecutive_loss_pause: int)`.
3. **Missing max_open_positions enforcement** — live system caps concurrent positions, backtest has no equivalent.
4. **EOD force-close has no price source** — `_close_eod_positions()` receives date but no bar close price per symbol.
5. **Incomplete BrokerAdapter implementation** — missing 6 of 13 protocol methods.
6. **Async/sync confusion** — `_evaluate_strategy` calls async methods without `await`.

### Key Research Insights

1. **alpaca-py auto-paginates** — SDK handles 10K page limit internally with `limit=None`. No manual pagination loop needed.
2. **Must use `Adjustment.ALL`** — unadjusted prices break P&L on split/dividend dates.
3. **Fill prices must clamp to bar boundaries** — slippage should never produce prices outside `[bar.low, bar.high]`.
4. **Sharpe must use sample std (n-1)** — population std inflates ratio for small samples.
5. **Profit factor `Decimal("Infinity")` breaks JSON** — cap at `Decimal("9999.99")` or serialize as string.
6. **Memory estimate wrong** — actual Bar objects are ~650 bytes (not 100), so 1yr/5sym ≈ 370MB. Needs streaming for multi-year.
7. **Primary performance bottleneck** — `CandleAggregator._is_market_hours()` does 8 pandas operations per bar. Cache market open/close per date for 3-5x speedup.

### Simplification Opportunities (applied)

1. Strategy registry replaced with simple validation (YAGNI — only 1 strategy)
2. `commission_per_share` removed from config/CLI/executor (Alpaca is commission-free, add when needed)
3. `click.progressbar()` removed (structlog already logs day transitions)
4. Metrics types corrected: `float` for ratios (Sharpe, win_rate, drawdown), `Decimal` for money only

---

## Overview

Build a backtesting engine that replays historical market data through the same strategy, indicator, and risk management components used in live/paper trading, but with simulated order fills. The engine loads 1-min bars from Alpaca for a configurable date range, feeds them through the existing CandleAggregator → IndicatorCalculator → Strategy pipeline, simulates order execution with configurable slippage, and computes standard performance metrics (total return, win rate, profit factor, Sharpe ratio, max drawdown). Results are stored in the existing `backtest_run`/`backtest_trade` database tables and displayed via CLI output.

## Problem Statement / Motivation

We have a working strategy engine (VelezStrategy), order management, and risk management — but no way to test whether a strategy is profitable without deploying to paper trading and waiting. Backtesting lets us:

1. **Validate strategy logic** before risking real capital (even paper)
2. **Tune hyperparameters** (SMA periods, tightness threshold, stop buffer) against historical data
3. **Benchmark performance** — does the strategy beat buy-and-hold?
4. **Verify risk controls** — does CircuitBreaker trigger appropriately? Is position sizing correct?
5. **Regression test** — after code changes, verify the strategy still produces the same trades on the same data

## Proposed Solution

A purpose-built backtest loop that reuses existing components (Strategy, IndicatorCalculator, CandleAggregator, PositionSizer, CircuitBreaker) with a simulated broker (BacktestExecution) implementing the BrokerAdapter protocol. This ensures the strategy code path is identical between backtest and live trading (Jesse model: same code, different adapter).

**New files (5):**
- `backend/app/backtest/config.py` — BacktestConfig
- `backend/app/backtest/data_loader.py` — BacktestDataLoader
- `backend/app/backtest/executor.py` — BacktestExecution (BrokerAdapter impl)
- `backend/app/backtest/runner.py` — BacktestRunner
- `backend/app/backtest/metrics.py` — BacktestMetrics

**Modified files (2):**
- `backend/app/config.py` — Add BacktestConfig to AppConfig (optional)
- `backend/app/cli/commands.py` — Add `backtest` CLI command

**No new migrations** — BacktestRunModel and BacktestTradeModel already exist in migration 001.

---

## Technical Approach

### Architecture

```
CLI: algo-trader backtest --strategy velez --symbols AAPL --start 2025-01-01 --end 2025-12-31

┌─────────────────────────────────────────────────────────────────┐
│                       BacktestRunner                            │
│                                                                 │
│  1. Load Data                                                   │
│  ┌──────────────────┐                                           │
│  │ BacktestDataLoader│──→ Alpaca REST (1-min bars, date range)  │
│  └────────┬─────────┘                                           │
│           │ list[Bar] sorted by timestamp (all symbols merged)  │
│           ▼                                                     │
│  2. Simulate                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  for each 1-min bar (chronological):                     │   │
│  │                                                          │   │
│  │  ┌──────────────────┐                                    │   │
│  │  │ BacktestExecution │ ← check pending orders vs bar     │   │
│  │  │ (fill simulation) │ ← emit fills (TradeUpdate-like)   │   │
│  │  └──────────────────┘                                    │   │
│  │           │                                              │   │
│  │           ▼                                              │   │
│  │  Process fills → update positions, record trades,        │   │
│  │  feed CircuitBreaker.record_trade()                      │   │
│  │           │                                              │   │
│  │           ▼                                              │   │
│  │  ┌──────────────────┐  ┌────────────────────┐           │   │
│  │  │ CandleAggregator │→ │ IndicatorCalculator │           │   │
│  │  │ (1m → 2m/5m/etc) │  │ (SMA-20, SMA-200)  │           │   │
│  │  └──────────────────┘  └────────┬───────────┘           │   │
│  │                                  │ IndicatorSet          │   │
│  │                                  ▼                       │   │
│  │                        ┌──────────────┐                  │   │
│  │                        │   Strategy   │                  │   │
│  │                        │  (Velez)     │                  │   │
│  │                        └──────┬───────┘                  │   │
│  │                               │ Signal?                  │   │
│  │                               ▼                          │   │
│  │                     ┌──────────────────┐                 │   │
│  │                     │ PositionSizer +  │                 │   │
│  │                     │ CircuitBreaker + │                 │   │
│  │                     │ max_open_pos chk │                 │   │
│  │                     └────────┬─────────┘                 │   │
│  │                              │ OrderRequest              │   │
│  │                              ▼                           │   │
│  │                    BacktestExecution.submit_order()       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  3. Compute Metrics                                             │
│  ┌──────────────────┐                                           │
│  │ BacktestMetrics   │ → equity curve, Sharpe, drawdown, etc.  │
│  └──────────────────┘                                           │
│                                                                 │
│  4. Store Results                                               │
│  BacktestRunModel + BacktestTradeModel → SQLite                 │
└─────────────────────────────────────────────────────────────────┘
```

**Data flow (per 1-min bar):**
1. `BacktestExecution.process_bar(bar)` — check all pending stop-orders against this bar's OHLC. Returns list of fills.
2. `BacktestExecution.update_market_prices(bar)` — update position unrealized P&L and equity.
3. Process fills: update simulated positions/account, record completed trades, update CircuitBreaker.
4. `CandleAggregator.process_bar(bar)` — aggregate into multi-minute candle (returns candle or None).
5. If candle emitted: `IndicatorCalculator.process_candle(candle)` — returns `IndicatorSet`.
6. Strategy evaluation: check signals, trailing stops, exits.
7. If signal: check `max_open_positions`, run through PositionSizer, submit to BacktestExecution.

### Research Insights: Architecture

**Best Practices (from Backtrader, Zipline, LEAN):**
- Bar-by-bar processing structurally prevents look-ahead bias — strategy code at time `t` never has access to bars at `t+1`. This is the industry standard for event-driven backtesting.
- Protective orders (stop-losses) must always be checked before entry orders. Backtrader's broker emulator follows this same priority.
- Same-bar entry + exit prevention is critical. Backtrader delays child orders (stops, take-profits) until the next evaluation cycle after parent fills.
- The "same code, different adapter" model (Jesse/LEAN approach) is the gold standard for ensuring backtest-live equivalence.

**Code Duplication Risk:**
- `_evaluate_strategy()` (~55 lines) encodes the full signal-to-order pipeline. The future `TradingEngine` will need identical logic. This is documented as known tech debt — extract into a shared `engine/strategy_evaluator.py` when TradingEngine is built.

---

### Data Loading (`backtest/data_loader.py`)

```python
class BacktestDataLoader:
    """Fetches historical 1-min bars from Alpaca REST for backtesting."""

    def __init__(self, broker_config: BrokerConfig) -> None:
        """Accept BrokerConfig (not raw keys) to limit credential exposure."""
        ...

    async def load_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[Bar]:
        """Fetch 1-min bars for all symbols, merged and sorted by timestamp.

        Returns oldest-first. SDK auto-paginates (no manual loop needed).
        """
        ...
```

**Key behaviors:**
- Uses `alpaca.data.StockBarsRequest` with `start`/`end`, `timeframe=TimeFrame(1, TimeFrameUnit.Minute)`, and `adjustment=Adjustment.ALL`
- **SDK auto-paginates:** Pass `limit=None` and the SDK loops internally via `next_page_token` (10K bars/page). No manual pagination code needed.
- Converts Alpaca Bar objects to our `broker.types.Bar` dataclass (Decimal prices via existing `alpaca_bar_to_bar()` mapper)
- Fetches symbols concurrently via `asyncio.gather()` for ~5x speedup (run_in_executor since SDK is sync)
- Merges all symbols into one list, sorted by `(timestamp, symbol)` — chronological interleaving
- Filters to market hours only (9:30-16:00 ET) using `zoneinfo.ZoneInfo("America/New_York")` — simple time comparison, not exchange-calendars (CandleAggregator already handles calendar logic)
- Passes timezone-aware datetimes to SDK (naive datetimes are assumed UTC, causing wrong data)
- Logs progress: "Loading AAPL: 2025-01-01 to 2025-12-31 (fetched 98,200 bars)"
- Raises `BacktestError` if zero bars returned for any symbol

### Research Insights: Data Loading

**alpaca-py SDK Details (from Context7 + framework-docs-researcher):**
```python
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import Adjustment, DataFeed

request = StockBarsRequest(
    symbol_or_symbols=["AAPL"],     # MUST be list, not bare string
    timeframe=TimeFrame(1, TimeFrameUnit.Minute),
    start=start_dt,                  # REQUIRED - limit alone returns empty
    end=end_dt,
    limit=None,                      # None = fetch all, SDK auto-paginates
    adjustment=Adjustment.ALL,       # MUST use for backtesting (splits+dividends)
    feed=DataFeed.IEX,               # Free tier; SIP requires paid plan
)
bar_set = client.get_stock_bars(request)
bars = bar_set.data.get("AAPL", [])  # .data.get(), NOT direct dict access
```

**Known SDK Gotchas (from learnings + research):**
- `start` is required — `limit` alone returns empty `BarSet`
- `symbol_or_symbols` must be `[symbol]` list, not bare string
- Response is `BarSet` Pydantic model with `.data` dict — use `.data.get()`, not `[]`
- Alpaca bar fields (`open`, `high`, `low`, `close`) are `float`, not Decimal — must convert
- `trade_count` and `vwap` may be `None` on some bars
- Naive datetimes assumed UTC — always pass timezone-aware
- `limit` applies across ALL symbols (10K total, not per symbol) — use `None` for backtesting
- Built-in retry: 3 attempts, 3-second waits on 429/504 errors. No custom backoff needed.
- SDK is synchronous/blocking — wrap in `run_in_executor()` for async context

**IEX vs SIP:** IEX (free, ~2% market volume) is adequate for AAPL/TSLA/large-caps. Significant gaps on mid/small-caps. 15-minute delay applies to streaming only, not historical REST.

**Rate Limits:** 200 req/min on free tier. A 5-symbol yearly backtest = ~50 requests. Comfortable margin.

---

### Fill Simulation (`backtest/executor.py`)

`BacktestExecution` implements the `BrokerAdapter` protocol (all 13 methods) plus backtest-specific `process_bar()` and `update_market_prices()`.

```python
from app.orders.types import OrderRole  # Reuse existing enum, not magic strings

@dataclass(frozen=True)
class Fill:
    """Result of a simulated fill."""
    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    fill_price: Decimal
    timestamp: datetime
    order_role: OrderRole  # OrderRole.ENTRY, OrderRole.STOP_LOSS, etc.


class BacktestExecution:
    """Simulated broker for backtesting. Implements BrokerAdapter protocol."""

    def __init__(
        self,
        initial_capital: Decimal,
        slippage_per_share: Decimal = Decimal("0.01"),
    ) -> None:
        self._cash = initial_capital
        self._slippage = slippage_per_share

        # Internal state
        self._pending_orders: dict[str, _PendingOrder] = {}  # order_id -> order
        self._positions: dict[str, _SimPosition] = {}  # symbol -> position
        self._filled_orders: list[OrderStatus] = []
        self._next_order_id: int = 0

    def process_bar(self, bar: Bar) -> list[Fill]:
        """Check all pending orders against this bar. Returns list of fills.

        Called by BacktestRunner for each 1-min bar BEFORE strategy evaluation.
        Order of checks: stop-losses first, then entries, then market orders.
        """
        ...

    def update_market_prices(self, bar: Bar) -> None:
        """Update position unrealized P&L from latest bar close."""
        ...

    # Synchronous convenience methods for hot loop (avoids async overhead)
    @property
    def equity(self) -> Decimal:
        """Cash + sum of position market values. Sync access for runner."""
        ...

    @property
    def cash(self) -> Decimal: ...

    @property
    def open_position_count(self) -> int: ...

    # --- BrokerAdapter protocol methods (all 13) ---
    async def connect(self) -> None: pass  # no-op
    async def disconnect(self) -> None: pass  # no-op
    async def submit_order(self, order: OrderRequest) -> OrderStatus: ...
    async def cancel_order(self, broker_order_id: str) -> None: ...
    async def replace_order(self, broker_order_id: str, ...) -> OrderStatus: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_account(self) -> AccountInfo: ...
    async def get_open_orders(self) -> list[OrderStatus]: ...
    async def get_order_status(self, broker_order_id: str) -> OrderStatus: ...
    async def get_recent_orders(self, limit: int = 100) -> list[OrderStatus]: ...
    async def subscribe_trade_updates(self, callback) -> None: pass  # no-op
    async def __aenter__(self) -> Self: return self
    async def __aexit__(self, *args) -> None: pass
```

**Fill trigger logic (checked per 1-min bar):**

| Order Type | Side | Trigger Condition | Fill Price |
|---|---|---|---|
| STOP (buy-stop entry) | BUY | `bar.high >= order.stop_price` | `min(max(bar.open, order.stop_price) + slippage, bar.high)` |
| STOP (stop-loss) | SELL | `bar.low <= order.stop_price` | `max(min(bar.open, order.stop_price) - slippage, bar.low)` |
| MARKET | BUY | Immediately on next bar | `min(bar.open + slippage, bar.high)` |
| MARKET | SELL | Immediately on next bar | `max(bar.open - slippage, bar.low)` |
| LIMIT | BUY | `bar.low <= order.limit_price` | `min(bar.open, order.limit_price)` |
| LIMIT | SELL | `bar.high >= order.limit_price` | `max(bar.open, order.limit_price)` |

### Research Insights: Fill Simulation

**Fill price clamping (from best-practices-researcher):**
- Slippage must NEVER produce fill prices outside the bar's `[low, high]` range — that would represent an impossible trade.
- Backtrader calls this `slip_match`: after applying slippage, clamp buy fills to `bar.high` and sell fills to `bar.low`.
- Implementation: `_apply_slippage(base_price, side, bar)` method applies slippage then clamps.

**Fill price floor (from security-sentinel):**
- Stop-loss at $3 with $5 slippage produces fill at -$2. Add `max(fill_price, Decimal("0.01"))` floor.

**Volume fraction warning (from best-practices-researcher):**
- Log a warning when `fill.qty > bar.volume * Decimal("0.10")` — flags unrealistic fills on low-liquidity names.
- Zipline defaults to capping at 2.5-10% of bar volume. For Phase 1, warning only is correct.

**Cross-day gap test (from best-practices-researcher):**
- Add specific test: Friday close $100, Monday open $105, buy-stop at $102 fills at $105 + slippage (clamped to Monday's high).

**Gap fill handling:**
- Buy-stop at $100, bar opens at $102 (gap up): fill at $102 + slippage (worse price, clamped to bar.high)
- Stop-loss at $95, bar opens at $93 (gap down): fill at $93 - slippage (worse price, clamped to bar.low)
- This models real slippage through gaps

**Order processing rules:**
1. Stop-losses checked FIRST (protective orders take priority)
2. Entry buy-stops checked SECOND
3. Market orders checked THIRD
4. No same-bar entry + stop for the SAME symbol — stop-loss becomes effective starting from the bar AFTER entry fill
5. Different symbols are independent — AAPL stop can trigger on the same bar as TSLA entry

**Position tracking:**
- One position per symbol (long-only Phase 1)
- Entry fill: create position, update cash (debit `qty * fill_price`)
- Exit fill: close position, update cash (credit `qty * fill_price`), compute realized P&L
- `equity` property returns: cash + sum(position_market_values)
- `buying_power` = cash (no margin Phase 1)

**Order ID generation:**
- Sequential: `"bt-1"`, `"bt-2"`, ... (prefix avoids collision with real broker IDs, deterministic for reproducibility)

---

### Orchestration (`backtest/runner.py`)

```python
@dataclass(frozen=True)
class BacktestTradeData:
    """One completed round-trip trade in a backtest."""
    symbol: str
    side: str  # "buy" (matches Side enum values, not "long")
    qty: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_at: datetime
    exit_at: datetime
    pnl: Decimal
    duration_seconds: int


@dataclass(frozen=True)
class BacktestResult:
    """Complete results of a backtest run."""
    run_id: int  # DB ID of BacktestRunModel
    metrics: BacktestMetricsData
    trades: list[BacktestTradeData]
    equity_curve: list[tuple[datetime, Decimal]]  # (timestamp, equity)


class BacktestRunner:
    """Orchestrates a complete backtest run."""

    def __init__(
        self,
        config: BacktestConfig,
        db_session_factory: async_sessionmaker[AsyncSession],
        bars: list[Bar] | None = None,  # injectable for testing (avoids network)
    ) -> None:
        ...

    async def run(self) -> BacktestResult:
        """Execute the full backtest pipeline."""
        # 1. Load historical bars (or use injected bars for testing)
        bars = self._bars or await self._load_data()

        # 2. Initialize components
        execution = BacktestExecution(
            initial_capital=self.config.initial_capital,
            slippage_per_share=self.config.slippage_per_share,
        )
        aggregators = self._create_aggregators()
        indicators = self._create_indicators()
        strategies = self._create_strategies()  # VelezStrategy(symbol, VelezConfig())
        position_sizer = PositionSizer(
            max_risk_per_trade_pct=risk_config.max_risk_per_trade_pct,
            max_position_pct=risk_config.max_position_pct,
        )
        circuit_breaker = CircuitBreaker(
            max_daily_loss_pct=risk_config.max_daily_loss_pct,
            consecutive_loss_pause=risk_config.consecutive_loss_pause,
        )
        max_open_positions = risk_config.max_open_positions  # default 5

        # 3. Main simulation loop
        current_date: date | None = None
        last_bar_by_symbol: dict[str, Bar] = {}  # for EOD force-close price
        daily_equity: list[tuple[date, Decimal]] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        completed_trades: list[BacktestTradeData] = []

        for bar in bars:
            bar_date = bar.timestamp.date()

            # Day transition: flush aggregators, force-close, reset
            if bar_date != current_date:
                if current_date is not None:
                    # Flush partial candles at EOD
                    for sym, agg in aggregators.items():
                        agg.flush()
                    # Force-close all positions at last bar's close - slippage
                    self._close_eod_positions(
                        execution, completed_trades,
                        last_bar_by_symbol, strategies,
                    )
                    # Cancel all pending orders
                    execution.cancel_all_pending()
                    # Record EOD equity
                    daily_equity.append((current_date, execution.equity))
                current_date = bar_date
                circuit_breaker.reset_daily(execution.equity)

            last_bar_by_symbol[bar.symbol] = bar  # track for EOD close price

            # Check pending orders against this bar
            fills = execution.process_bar(bar)

            # Update position market prices for equity tracking
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

            # Record end-of-candle equity
            equity_curve.append((candle.timestamp, execution.equity))

        # 4. Final day: force-close + final equity
        if current_date is not None:
            for sym, agg in aggregators.items():
                agg.flush()
            self._close_eod_positions(
                execution, completed_trades,
                last_bar_by_symbol, strategies,
            )
            daily_equity.append((current_date, execution.equity))

        # 5. Compute metrics
        metrics = BacktestMetrics.calculate(
            trades=completed_trades,
            daily_equity=daily_equity,
            equity_curve=equity_curve,
            initial_capital=self.config.initial_capital,
        )

        # 6. Store results
        run_id = await self._store_results(metrics, completed_trades, daily_equity)

        return BacktestResult(
            run_id=run_id,
            metrics=metrics,
            trades=completed_trades,
            equity_curve=equity_curve,
        )
```

**Strategy evaluation logic (per candle) — CORRECTED:**

```python
async def _evaluate_strategy(
    self, candle, indicators, strategy, execution, sizer, cb, max_open_positions,
):
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
                symbol=symbol, side=Side.SELL,
                order_type=OrderType.MARKET, qty=position.qty,
            ))

    elif execution.has_pending_entry(symbol):
        # Candle counter for buy-stop expiry
        execution.increment_candle_count(symbol)
        if strategy.should_cancel_pending(candle, execution.candles_since_order(symbol)):
            execution.cancel_pending_entry(symbol)

    else:
        # New signal detection
        if indicators.bar_count < strategy.required_history:
            return  # Not warmed up yet
        if not strategy.should_long(candle, indicators):
            return  # No signal

        # Risk checks
        can_trade, reason = cb.can_trade()
        if not can_trade:
            return

        # CORRECTED: max_open_positions enforcement
        if execution.open_position_count >= max_open_positions:
            return

        entry_price = strategy.entry_price(candle, indicators)
        stop_price = strategy.stop_loss_price(candle, indicators)

        # CORRECTED: PositionSizer.calculate() actual signature
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
            symbol=symbol, side=Side.BUY,
            order_type=OrderType.STOP, qty=sizing_result.qty,
            stop_price=entry_price,
        ))
        # Store stop-loss price for when entry fills
        execution.set_planned_stop(symbol, stop_price)
```

**Fill handling logic — CORRECTED:**

```python
async def _handle_fill(self, fill, execution, circuit_breaker, strategies, trades):
    if fill.order_role == OrderRole.ENTRY:
        # Place stop-loss order
        stop_price = execution.get_planned_stop(fill.symbol)
        await execution.submit_order(OrderRequest(
            symbol=fill.symbol, side=Side.SELL,
            order_type=OrderType.STOP, qty=fill.qty,
            stop_price=stop_price,
        ))

    elif fill.order_role in (OrderRole.STOP_LOSS, OrderRole.EXIT):
        # Record completed trade
        position = execution.get_closed_position(fill.symbol)
        trade = BacktestTradeData(
            symbol=fill.symbol,
            side="buy",  # CORRECTED: matches Side enum, not "long"
            qty=position.qty,
            entry_price=position.avg_entry_price,
            exit_price=fill.fill_price,
            entry_at=position.opened_at,
            exit_at=fill.timestamp,
            pnl=(fill.fill_price - position.avg_entry_price) * position.qty,
            duration_seconds=int((fill.timestamp - position.opened_at).total_seconds()),
        )
        trades.append(trade)
        circuit_breaker.record_trade(trade.pnl)
        strategies[fill.symbol].on_position_closed()
```

### Research Insights: Orchestration

**Strategy instantiation (from repo-research-analyst):**
- `VelezStrategy.__init__` requires `(symbol: str, config: VelezConfig)`. The runner must create one instance per symbol: `VelezStrategy(symbol="AAPL", config=VelezConfig())`

**PositionSizer actual interface (from repo-research-analyst):**
- `calculate(equity, buying_power, entry_price, stop_loss_price) -> SizingResult`
- Returns `SizingResult` with `.qty` field, NOT a bare Decimal
- Computes stop_distance internally — pass the raw stop_loss_price, not the distance
- Truncates qty DOWN via `Decimal(int(qty))` — never rounds up (conservative, real money)

**CircuitBreaker actual interface:**
- Constructor: `CircuitBreaker(max_daily_loss_pct=Decimal, consecutive_loss_pause=int)` — not a RiskConfig object
- `reset_daily(equity: Decimal)` — call at each new trading day
- `can_trade() -> tuple[bool, str]` — returns (allowed, reason)
- `record_trade(pnl: Decimal)` — realized P&L only (unrealized too volatile)

**CandleAggregator.flush() (from architecture-strategist):**
- The aggregator has a `flush()` method for emitting partial candles at market close. Must call at day transitions to avoid losing the last partial candle window.

**BacktestRunner testability (from architecture-strategist):**
- Accept `bars: list[Bar] | None = None` in constructor so unit tests can inject canned bars directly without network calls.

---

### Performance Metrics (`backtest/metrics.py`)

Pure functions — no I/O, no side effects. Monetary inputs are `Decimal`, ratios are `float`.

```python
@dataclass(frozen=True)
class BacktestMetricsData:
    total_return: Decimal        # (final_equity - initial) / initial
    total_return_pct: Decimal    # total_return * 100
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float              # winning / total (0-1) — float for ratio
    profit_factor: float         # gross_profit / gross_loss (> 1 = profitable)
    sharpe_ratio: float          # annualized risk-adjusted return
    max_drawdown: float          # largest peak-to-trough decline (0-1)
    max_drawdown_pct: float      # max_drawdown * 100
    avg_win: Decimal             # average winning trade P&L
    avg_loss: Decimal            # average losing trade P&L (negative)
    largest_win: Decimal
    largest_loss: Decimal
    avg_trade_duration: int      # seconds
    final_equity: Decimal


class BacktestMetrics:
    @staticmethod
    def calculate(
        trades: list[BacktestTradeData],
        daily_equity: list[tuple[date, Decimal]],
        equity_curve: list[tuple[datetime, Decimal]],
        initial_capital: Decimal,
    ) -> BacktestMetricsData:
        """Compute all metrics.

        daily_equity: EOD snapshots for Sharpe ratio (daily returns).
        equity_curve: Per-candle snapshots for max drawdown (intra-day).
        """
        ...
```

**Metric formulas:**

| Metric | Formula |
|---|---|
| Total Return | `(final_equity - initial_capital) / initial_capital` |
| Win Rate | `winning_trades / total_trades` (0.0 if no trades) |
| Profit Factor | `sum(winning_pnl) / abs(sum(losing_pnl))` (9999.99 if no losses, 0.0 if no wins) |
| Sharpe Ratio | `mean(daily_returns) / stdev(daily_returns, ddof=1) * sqrt(252)` |
| Max Drawdown | `max((peak - trough) / peak)` over per-candle equity curve |
| Avg Win | `sum(winning_pnl) / winning_trades` (Decimal("0") if no winners) |
| Avg Loss | `sum(losing_pnl) / losing_trades` (Decimal("0") if no losers) |

### Research Insights: Metrics

**Sharpe ratio gotchas (from best-practices-researcher + web search):**
- Use **sample standard deviation** (`ddof=1`), not population (`ddof=0`). Small sample sizes (10-20 trading days) are significantly affected.
- Only include **actual trading days**. If weekends/holidays sneak in as zero-return days, std shrinks and Sharpe inflates artificially.
- Always use **daily returns from EOD equity**, never per-trade returns. Per-trade returns have no fixed frequency, so `sqrt(252)` annualization produces meaningless numbers.
- Risk-free rate = 0 is acceptable for Phase 1 (industry standard when rates are near zero).
- Serial correlation can overstate Sharpe by >65% (advanced concern, not Phase 1).

**Profit factor edge cases (from best-practices-researcher):**
- `float("inf")` (no losses) breaks JSON serialization. Cap at `9999.99` instead.
- With zero trades: return `0.0`.
- Break-even trades (P&L = 0): counted as neither winners nor losers.

**Max drawdown (from web search):**
- Compute from per-candle equity curve (captures intra-day drawdowns that EOD snapshots miss).
- Use high-water-mark approach: track running peak, compute `(peak - current) / peak` at each point.

**Division-by-zero edge cases (from spec-flow-analyzer):**
- `avg_win` with zero winners → `Decimal("0")`
- `avg_loss` with zero losers → `Decimal("0")`
- `win_rate` with zero trades → `0.0`
- All break-even trades (neither win nor loss) → profit_factor = `0.0`

---

### Configuration (`backtest/config.py`)

```python
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator
from app.config import VALID_CANDLE_INTERVALS  # Import, don't duplicate

MAX_BACKTEST_DAYS = 365
MAX_BACKTEST_SYMBOLS = 10

class BacktestConfig(BaseModel):
    """Configuration for a single backtest run."""
    strategy: str = "velez"
    symbols: list[str]
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(default=Decimal("25000"), ge=Decimal("1000"), le=Decimal("10000000"))
    slippage_per_share: Decimal = Field(default=Decimal("0.01"), ge=Decimal("0"), le=Decimal("1"))
    candle_interval_minutes: int = Field(default=2)

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Fail fast on unknown strategy (before expensive data loading)."""
        valid = {"velez"}
        if v not in valid:
            raise ValueError(f"Unknown strategy: {v!r}. Available: {', '.join(valid)}")
        return v

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        import re
        if not v:
            raise ValueError("At least one symbol required")
        if len(v) > MAX_BACKTEST_SYMBOLS:
            raise ValueError(f"Maximum {MAX_BACKTEST_SYMBOLS} symbols per backtest")
        for s in v:
            if not re.match(r"^[A-Z]{1,5}$", s):
                raise ValueError(f"Invalid symbol: {s}")
        return v

    @field_validator("candle_interval_minutes")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v not in VALID_CANDLE_INTERVALS:
            raise ValueError(f"Invalid interval: {v}. Must be one of {VALID_CANDLE_INTERVALS}")
        return v

    @model_validator(mode="after")
    def validate_date_range(self) -> "BacktestConfig":
        """Cross-field validation using model_validator (not fragile field ordering)."""
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        delta = (self.end_date - self.start_date).days
        if delta > MAX_BACKTEST_DAYS:
            raise ValueError(f"Date range exceeds {MAX_BACKTEST_DAYS} days ({delta} days)")
        return self
```

### Research Insights: Configuration

**Pydantic patterns (from Pydantic reviewer + Context7):**
- Use `@model_validator(mode="after")` for cross-field validation instead of `@field_validator("end_date")` with fragile `info.data` access. This is the idiomatic Pydantic v2 approach.
- Import `VALID_CANDLE_INTERVALS` from `config.py` instead of hardcoding `{1, 2, 5, 10}` (no magic numbers).
- Add upper bounds on Decimal fields (`le=`) to prevent nonsensical configs.

**Security (from security-sentinel):**
- Add `MAX_BACKTEST_DAYS` (365) and `MAX_BACKTEST_SYMBOLS` (10) caps to prevent resource exhaustion.
- Validate strategy name in config (fail fast) instead of in runner (after expensive data loading).

---

### CLI Integration (`cli/commands.py`)

```python
@cli.command()
@click.option("--strategy", default="velez", help="Strategy name")
@click.option("--symbols", required=True, help="Comma-separated symbols (e.g., AAPL,TSLA)")
@click.option("--start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]), help="Start date")
@click.option("--end", required=True, type=click.DateTime(formats=["%Y-%m-%d"]), help="End date")
@click.option("--capital", default="25000", type=str, help="Initial capital")
@click.option("--slippage", default="0.01", type=str, help="Slippage per share")
def backtest(strategy, symbols, start, end, capital, slippage):
    """Run a backtest against historical data."""
    config = BacktestConfig(
        strategy=strategy,
        symbols=[s.strip() for s in symbols.split(",")],
        start_date=start.date(),
        end_date=end.date(),
        initial_capital=Decimal(capital),    # str → Decimal directly (no float artifacts)
        slippage_per_share=Decimal(slippage),
    )
    result = asyncio.run(_run_backtest(config))
    _print_results(result)
```

### Research Insights: CLI

**Click patterns (from Python reviewer + Context7):**
- `--capital` and `--slippage` should use `type=str` then convert directly to `Decimal(capital)`. Using `type=float` introduces float representation artifacts (e.g., `0.01` → `0.010000000000000000208...`).
- `candle_interval_minutes` and `commission_per_share` removed from CLI (YAGNI: use defaults, add when needed).
- `click.progressbar()` removed — structlog day-transition logging is sufficient for Phase 1.
- Check existing CLI stub at `backend/app/cli/commands.py` for option naming conventions (`--start-date` vs `--start`).
- `asyncio.run()` wrapping is the standard Click + async pattern. AsyncClick is not needed for one command.

**Output format (CLI):**

```
Backtest Results: VelezStrategy
Period: 2025-01-02 to 2025-12-31 (252 trading days)
Symbols: AAPL, TSLA
Initial Capital: $25,000.00

Performance:
  Total Return:    $2,340.50 (9.36%)
  Final Equity:    $27,340.50
  Sharpe Ratio:    1.24
  Max Drawdown:    -4.21%
  Profit Factor:   1.85

Trades:
  Total:           47
  Winners:         28 (59.6%)
  Losers:          19 (40.4%)
  Avg Win:         $156.20
  Avg Loss:        -$98.40
  Largest Win:     $520.00
  Largest Loss:    -$310.50
  Avg Duration:    42 min

Results saved to database (run_id: 15)
```

---

### SpecFlow-Identified Design Details

These details were identified by the SpecFlow analyzer and are incorporated throughout the plan.

**Strategy resolution (simplified from registry):**

```python
# backend/app/backtest/runner.py
def _resolve_strategy(name: str, symbol: str) -> Strategy:
    """Create strategy instance. Raises BacktestError for unknown names."""
    if name == "velez":
        return VelezStrategy(symbol=symbol, config=VelezConfig())
    raise BacktestError(
        f"Unknown strategy: {name!r}. Available: velez"
    )
```

**Position objects maintained per bar:**
- BacktestExecution must update `Position.market_value`, `Position.unrealized_pl`, `Position.unrealized_pl_pct` on every bar (not just on fills)
- `update_market_prices(bar)` method called after `process_bar()`, before strategy evaluation
- Strategy's `should_update_stop(bar, position, indicators)` and `should_exit(bar, position, indicators)` receive Position with up-to-date unrealized P&L
- Note: `Position` type fields are `market_value`, `unrealized_pl`, `unrealized_pl_pct` — there is no `current_price` field

**Multi-symbol bar ordering (tie-breaking):**
- Bars sorted by `(timestamp, symbol)` — alphabetical tie-breaking
- When AAPL and TSLA both have a bar at 09:30, AAPL processes first
- First signal at a given timestamp consumes buying power before second is evaluated
- This is deterministic and reproducible

**End-of-day position handling:**
- Velez is a day-trading strategy — positions MUST NOT carry overnight
- At each day transition (detected by bar date change), force-close all open positions using `last_bar_by_symbol[symbol].close - slippage` as fill price
- Record forced exits as trades with P&L
- Call `strategy.on_position_closed()` for each force-closed position
- Cancel ALL pending orders (entries AND stops) via `execution.cancel_all_pending()`
- Flush all CandleAggregators to emit partial candles

**Equity curve storage:**
- **In-memory (per candle):** Full granularity for accurate intra-day max drawdown during the run
- **In DB (`backtest_run.equity_curve`):** End-of-day snapshots only (252 points/year, not 50K+)
- **Sharpe ratio:** Computed from end-of-day equity snapshots (daily returns)
- **Max drawdown:** Computed from per-candle equity curve (captures intra-day drawdowns)

**`params` column content in BacktestRunModel:**

```json
{
  "strategy": "velez",
  "symbols": ["AAPL", "TSLA"],
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "initial_capital": "25000",
  "slippage_per_share": "0.01",
  "candle_interval_minutes": 2,
  "strategy_config": { "sma_fast": 20, "sma_slow": 200 },
  "risk_config": { "max_risk_per_trade_pct": "0.01", "max_daily_loss_pct": "0.03", "max_open_positions": 5 }
}
```
Full reproduction info — serialize `BacktestConfig.model_dump()` plus VelezConfig + RiskConfig. **MUST NOT contain API keys** — add a test that asserts no credentials in stored params.

**Same-bar stop + exit ordering:**
- If stop-loss triggers on a bar, the position is closed at the stop price
- `should_exit()` is NOT called for that symbol on the same bar (position already closed)
- The strategy evaluation block checks `execution.has_position(symbol)` first — after stop-loss fill, this returns False

**Progress reporting:**
- Use `structlog` progress logging: `"Processing {date}... {n}/{total} trading days"` at each day transition
- Log total elapsed time and bars/sec at completion

**CLI date interpretation:**
- `--start` and `--end` are calendar dates (ET business days), not UTC
- The BacktestDataLoader converts to UTC-aware datetimes using `zoneinfo.ZoneInfo("America/New_York")`

**DB connection:**
- Backtest CLI uses same `db_path` from `AppConfig`
- SQLite WAL mode supports concurrent reads; single writer at a time

---

## Implementation Steps

### Step 6A: BacktestConfig + BacktestMetrics + BacktestTradeData

**Files:**
- `backend/app/backtest/config.py` (new)
- `backend/app/backtest/metrics.py` (new)
- `backend/app/backtest/__init__.py` (update exports)
- `backend/tests/unit/test_backtest_config.py` (new)
- `backend/tests/unit/test_backtest_metrics.py` (new)

**Tasks:**
- [x] Create `BacktestConfig` Pydantic BaseModel with validation (model_validator for cross-field)
- [x] Create `BacktestTradeData` frozen dataclass (define it here, used by metrics + runner)
- [x] Create `BacktestMetricsData` frozen dataclass (float for ratios, Decimal for money)
- [x] Implement `BacktestMetrics.calculate()` with separate `daily_equity` and `equity_curve` params
- [x] Handle all division-by-zero edge cases: zero trades, zero winners, zero losers, all break-even
- [x] Cap profit_factor at 9999.99 (not infinity) for JSON serialization
- [x] Sharpe: sample std (ddof=1), daily returns from EOD equity, annualize * sqrt(252)
- [x] Max drawdown: high-water-mark from per-candle equity curve
- [x] Import `VALID_CANDLE_INTERVALS` from config.py, don't hardcode
- [x] Add MAX_BACKTEST_DAYS and MAX_BACKTEST_SYMBOLS caps
- [x] Strategy name validated in config (fail fast)
- [x] Unit tests for config validation (valid/invalid symbols, dates, intervals, capital, date range cap, symbol count cap)
- [x] Unit tests for metrics: zero trades, all wins, all losses, mixed, single trade, break-even trades
- [x] Unit test for Sharpe ratio: known dataset with manual verification, verify ddof=1
- [x] Unit test for max drawdown: known equity curve with manual verification
- [x] Unit test for profit_factor cap (not infinity)

**Acceptance:**
- All config validation rules enforced including caps
- Metrics match hand-calculated values on test dataset
- Use `pytest.approx()` for float metrics, exact equality for Decimal metrics

### Step 6B: BacktestExecution (fill simulation)

**Files:**
- `backend/app/backtest/executor.py` (new)
- `backend/tests/unit/test_backtest_executor.py` (new)

**Tasks:**
- [x] Implement `BacktestExecution` class with internal order book and position tracking
- [x] Implement ALL 13 BrokerAdapter protocol methods (match FakeBrokerAdapter pattern)
- [x] Add sync convenience properties: `equity`, `cash`, `open_position_count` (avoid async in hot loop)
- [x] Use `OrderRole` enum (not magic strings) for fill.order_role
- [x] Implement `process_bar()` — stop-loss check, buy-stop check, market order check (priority order)
- [x] Implement `update_market_prices(bar)` — updates position unrealized P&L each bar
- [x] Fill price clamping: after slippage, clamp buy fills to `bar.high`, sell fills to `bar.low`
- [x] Fill price floor: `max(fill_price, Decimal("0.01"))` to prevent negative prices
- [x] Volume fraction warning: log when `fill.qty > bar.volume * 0.10`
- [x] Buy-stop fill: trigger when `bar.high >= stop_price`, fill at `min(max(bar.open, stop_price) + slippage, bar.high)`
- [x] Stop-loss fill: trigger when `bar.low <= stop_price`, fill at `max(min(bar.open, stop_price) - slippage, bar.low)`
- [x] Market fill: fill at `bar.open ± slippage` (clamped to bar range)
- [x] Gap fill handling: gap past trigger → fill at open (clamped, worse price)
- [x] Position tracking: open/close, compute unrealized P&L from latest bar
- [x] Account tracking: cash, equity = cash + position market values, buying_power = cash
- [x] `cancel_all_pending()` method for EOD cleanup
- [x] Order cancellation removes from pending book
- [x] Unit tests: buy-stop triggers at exact price, above price, below price (no fill)
- [x] Unit tests: stop-loss triggers at exact price, below price, above price (no fill)
- [x] Unit tests: gap up fill, gap down fill, cross-day gap (Friday→Monday)
- [x] Unit tests: slippage clamped to bar boundaries
- [x] Unit tests: fill price floor (no negative prices)
- [x] Unit tests: position opens and closes correctly, P&L calculation
- [x] Unit tests: account equity tracks position value
- [x] Unit tests: multiple symbols independent
- [x] Unit tests: stop-loss not triggered on same bar as entry (for same symbol)
- [x] Unit tests: market orders fill on next bar
- [x] Unit tests: cancel order removes from pending
- ~~Parameterize fill-trigger tests~~ — REMOVED: pure refactor of passing tests, no correctness gap

**Acceptance:**
- All fill scenarios produce correct prices within bar boundaries
- Position tracking matches expected P&L
- Account equity = cash + position market value

### Step 6C: BacktestDataLoader

**Files:**
- `backend/app/backtest/data_loader.py` (new)
- `backend/tests/unit/test_backtest_data_loader.py` (new)
- `backend/tests/integration/test_backtest_data_loader.py` (new, marked @integration)

**Tasks:**
- [x] Implement `BacktestDataLoader` accepting `BrokerConfig` (not raw API keys)
- [x] Use `StockHistoricalDataClient` with `limit=None` (SDK auto-paginates, no manual loop)
- [x] `adjustment=Adjustment.ALL` (split + dividend adjusted) — REQUIRED for correct backtesting
- [x] `feed=DataFeed.IEX` (from config)
- [x] Pass timezone-aware datetimes to SDK (not naive — naive assumed UTC)
- [x] Convert alpaca-py Bar → our `broker.types.Bar` (Decimal prices)
- [x] Concurrent per-symbol fetching via `asyncio.gather()` + `run_in_executor()`
- [x] Multi-symbol merge into single list sorted by `(timestamp, symbol)`
- [x] Market hours filtering (9:30-16:00 ET) via `zoneinfo` time comparison
- [x] Raise `BacktestError` if zero bars for any symbol
- [x] Unit tests with mocked client: conversion, sorting, filtering, zero-bars error
- [x] Unit test: mock using `SimpleNamespace(data={"AAPL": [...]})` for BarSet
- [x] Integration test (marked @integration): fetch 1 week AAPL from Alpaca, verify non-empty and sorted

**Acceptance:**
- Returns correctly sorted, merged bars for multiple symbols
- SDK handles pagination transparently (no manual code)
- Converts to project Bar type with Decimal prices

### Step 6D: BacktestRunner (orchestration + result storage)

**Files:**
- `backend/app/backtest/runner.py` (new)
- `backend/app/backtest/__init__.py` (update exports)
- `backend/tests/unit/test_backtest_runner.py` (new)
- `backend/tests/integration/test_backtest_full_run.py` (new)

**Tasks:**
- [x] Implement `BacktestRunner.run()` orchestration loop with injectable bars for testing
- [x] Wire all components with CORRECT constructor signatures (see Enhancement Summary P1 fixes)
- [x] `VelezStrategy(symbol=symbol, config=VelezConfig())` — correct instantiation
- [x] `PositionSizer(max_risk_per_trade_pct=..., max_position_pct=...)` — from risk config
- [x] `CircuitBreaker(max_daily_loss_pct=..., consecutive_loss_pause=...)` — two primitives
- [x] `sizer.calculate(equity, buying_power, entry_price, stop_loss_price)` → `SizingResult.qty`
- [x] `max_open_positions` enforcement before signal processing
- [x] EOD force-close using `last_bar_by_symbol[symbol].close - slippage` as price
- [x] EOD: flush all CandleAggregators, cancel all pending orders
- [x] Daily CircuitBreaker reset at each new trading date
- [x] Trailing stop updates + exit signal handling
- [x] Buy-stop expiry: candle counter + `should_cancel_pending()`
- [x] Track `last_bar_by_symbol: dict[str, Bar]` for EOD close price
- [x] Equity curve: per-candle in memory, EOD in DB
- [x] Store results in DB, including params JSON (verify no credentials stored)
- [x] Progress logging: day count at transitions, total elapsed + bars/sec at end
- [x] Error handling: try/except around strategy evaluation (log and skip, don't crash)
- [x] Unit test: known-trade verification (handcraft 5-10 bars, manually calculate every fill)
- [x] Unit test: warm-up period (no signals until `bar_count >= required_history`)
- [x] Unit test: CircuitBreaker trips mid-backtest
- [x] Unit test: max_open_positions blocks new entries
- [x] Unit test: EOD force-close with correct price from last_bar_by_symbol
- [x] Unit test: pending orders canceled at EOD
- [x] Unit test: zero-trade backtest stores run with zero metrics
- [x] Unit test: multi-symbol capital contention
- [x] Unit test: params JSON does NOT contain API keys
- ~~Property test (hypothesis): money conservation~~ — REMOVED: hard to generate meaningful random bars; covered deterministically by known-trade verification test
- ~~Integration test: full run with known dataset~~ — REMOVED: redundant with known-trade verification test above

**Acceptance:**
- Full pipeline runs end-to-end with canned bars (no network)
- Correct constructor signatures verified by compilation
- Money conservation invariant holds for all runs
- Results persisted in DB

### Step 6E: CLI command + final integration

**Files:**
- `backend/app/cli/commands.py` (modify — add `backtest` command)
- `backend/tests/unit/test_cli_backtest.py` (new)

**Tasks:**
- [x] Add `backtest` CLI command with `--strategy`, `--symbols`, `--start`, `--end`, `--capital`, `--slippage`
- [x] `--capital` and `--slippage` as `type=str` → `Decimal()` directly (no float intermediary)
- [x] Run backtest via `asyncio.run()`
- [x] Format and print results table
- [x] Handle errors: invalid config → user-friendly message, no data → clear error
- [x] Unit test: CLI argument parsing (valid and invalid inputs)
- ~~Unit test: output formatting (zero trades, normal trades)~~ — REMOVED: cosmetic, verified by CLI smoke test

**Acceptance:**
- `algo-trader backtest --strategy velez --symbols AAPL --start 2025-01-01 --end 2025-03-31` runs and prints results
- Invalid args produce clear error messages
- Results saved to database

---

## Alternative Approaches Considered

### 1. Reuse OrderManager for backtest (rejected)

OrderManager is 920 lines of async code with DB sessions, asyncio.Event waits, retry logic, and cancel-then-sell patterns. All of this is for real broker communication. Reusing it for backtesting would:
- Add unnecessary I/O overhead (async DB writes per order)
- Require the asyncio.Event wait/notify patterns (designed for real-time, not simulation)
- Slow down backtests significantly

Instead, BacktestExecution handles fill simulation in-memory. The same *components* (Strategy, Indicators, PositionSizer, CircuitBreaker) are reused, but the *orchestration* is purpose-built for simulation speed.

**Trade-off**: Slightly different code path from live. Mitigated by comprehensive testing and the fact that Strategy + PositionSizer + CircuitBreaker logic is identical.

### 2. Synchronous backtest engine (rejected)

Could build the entire backtest as synchronous code. Rejected because:
- BrokerAdapter protocol is async — BacktestExecution needs to satisfy it
- BacktestDataLoader needs async HTTP for Alpaca API (via run_in_executor)
- `asyncio.run()` wrapping is trivial

Using async throughout keeps consistency with the rest of the codebase.

### 3. Event-driven architecture with queues (rejected — over-engineered)

Could use asyncio.Queue between components like the live engine will. Rejected for backtesting because:
- Sequential bar processing is simpler and faster
- No real concurrency in backtesting (one bar at a time)
- Queues add complexity without benefit for simulation

### 4. Pandas/vectorized backtesting (rejected — wrong abstraction)

Could compute all signals at once using pandas vectorized operations (much faster). Rejected because:
- Violates "same code in backtest and live" principle
- Strategy class uses per-bar evaluation with internal state (Velez 3-state machine)
- Position sizing depends on current equity (changes after each trade)
- CircuitBreaker state changes after each trade
- Would need a completely separate strategy implementation

**Trade-off**: Bar-by-bar simulation is slower (~1K-5K bars/sec vs ~100K+/sec for vectorized). Acceptable for Phase 1 — a 1-year backtest of 5 symbols is ~500K 1-min bars, completing in ~2-5 minutes.

---

## Performance Optimization Guide

### Research Insights (from performance-oracle)

**Primary bottleneck: `CandleAggregator._is_market_hours()`**
- Calls `market_open()` and `market_close()` per bar, each constructing pandas Timestamps via exchange-calendars.
- ~8 pandas operations per bar per symbol ≈ 200-800μs per timestamp group.
- **Fix**: Cache market open/close times per date in the aggregator. ~10 lines of code, 3-5x throughput improvement.

**Memory estimates (corrected):**
- Plan estimated 100 bytes/bar. Actual Python `Bar` is ~650 bytes (5 Decimal objects at ~110 bytes each, datetime ~56 bytes, dataclass overhead).
- 500K bars × 650 bytes = ~325MB bar list alone.
- Per-candle equity curve adds ~45MB.
- **Total for 1yr/5sym: ~370MB** (exceeds 200MB target).
- **Mitigation for Phase 1**: Accept higher memory. For multi-year, switch to streaming bars per-day.

**Data loading optimization:**
- Sequential pagination: ~87 seconds for 500K bars (250 requests × 350ms).
- With `asyncio.gather()` across 5 symbols: ~17 seconds (5x improvement).
- SDK auto-paginates, so no code complexity increase — just concurrent per-symbol calls.

**Top 3 optimizations to implement:**
1. Cache market open/close per date in CandleAggregator (3-5x throughput, ~10 lines)
2. Concurrent per-symbol data loading via `asyncio.gather()` (~5x data load speed, ~15 lines)
3. Use sync `execution.equity` property in hot loop (avoids coroutine creation overhead)

**Scaling limits:**
- 5-year backtest: ~2.5M bars = ~1.6GB memory → requires streaming
- 50 symbols: 25K Alpaca requests hits 200 req/min rate limit → requires local bar cache

---

## Acceptance Criteria

### Functional Requirements

- [x] Backtest loads 1-min bars from Alpaca with `Adjustment.ALL` (split/dividend adjusted)
- [x] Bars are merged chronologically across all symbols
- [x] CandleAggregator produces correct multi-minute candles (1m/2m/5m/10m)
- [x] CandleAggregator.flush() called at EOD (no lost partial candles)
- [x] Indicator warm-up respected: no signals until `bar_count >= required_history`
- [x] VelezStrategy instantiated with `(symbol, VelezConfig())` — correct constructor
- [x] VelezStrategy detects signals identically to live (same IndicatorSet, same logic)
- [x] Buy-stop entry fills correctly: trigger on high >= stop_price, fill at max(open, stop_price) + slippage, clamped to bar.high
- [x] Stop-loss exit fills correctly: trigger on low <= stop_price, fill at min(open, stop_price) - slippage, clamped to bar.low
- [x] Market orders fill at next bar open ± slippage, clamped to bar range
- [x] Fill prices never negative (minimum $0.01 floor)
- [x] Gap fills handled: price gaps past order trigger → fill at open (worse price, clamped)
- [x] Position sizing uses correct `PositionSizer.calculate(equity, buying_power, entry_price, stop_loss_price)` signature
- [x] `max_open_positions` enforced (default 5) — matches live risk controls
- [x] CircuitBreaker constructed with two primitives (not RiskConfig object)
- [x] CircuitBreaker resets daily and tracks consecutive losses during backtest
- [x] Trailing stop updates work through Velez 3-state machine
- [x] Buy-stop canceled after 1 candle if not filled (`should_cancel_pending`)
- [x] EOD force-close: all open positions closed at `last_bar.close - slippage` each trading day
- [x] EOD: ALL pending orders canceled (entries AND stops)
- [x] Remaining positions force-closed at final bar of backtest
- [x] Equity curve: per-candle in memory (max drawdown), end-of-day in DB (Sharpe)
- [x] Total return, win rate (float), profit factor (float, capped at 9999.99), Sharpe ratio (float, sample std), max drawdown (float) computed correctly
- [x] Sharpe ratio: annualized from daily returns with sample std (ddof=1), risk-free rate = 0
- [x] Max drawdown: computed from per-candle equity curve using high-water-mark
- [x] Results stored in `backtest_run` and `backtest_trade` tables
- [x] `params` JSON stores full config for reproduction — MUST NOT contain API keys
- [x] Unknown strategy name produces clear error in config validation (fail fast)
- [x] Multi-symbol: bars interleaved by `(timestamp, symbol)`, buying power consumed sequentially
- [x] Position objects updated each bar (unrealized P&L, market value)
- [x] Same-bar stop+exit: stop triggers first, `should_exit()` not called
- [x] Zero-trade backtest: stores run with zero metrics, prints "no trades" summary
- [x] CLI `algo-trader backtest` command works with all options
- [x] CLI `--capital` and `--slippage` accept string, convert to Decimal directly

### Non-Functional Requirements

- [x] 1-year single-symbol backtest completes in < 60 seconds
- ~~Memory usage documentation in CLI help~~ — REMOVED: premature, document when memory is actually an issue
- [x] All monetary calculations use Decimal (no float for prices, P&L, position sizing)
- [x] Ratios (Sharpe, win_rate, drawdown, profit_factor) use float (project convention)
- [x] mypy strict passes on all new code
- [x] ruff check + format passes on all new code

### Quality Gates

- [x] All unit tests pass (config, metrics, executor, runner)
- [x] Known-trade verification test: handcrafted bars, manually verified fills and P&L
- ~~Money conservation property test~~ — REMOVED: covered deterministically by known-trade test
- ~~Integration test: full backtest run with known dataset~~ — REMOVED: redundant with known-trade test
- [x] Integration test: BacktestDataLoader fetches real Alpaca data with Adjustment.ALL
- [x] Params JSON credential exclusion test

---

## Applicable Learnings from docs/solutions/

| Learning | Impact | Where Applied |
|----------|--------|---------------|
| `decimal-for-money-float-for-math.md` | Decimal for prices/P&L, float for Sharpe/indicators | Metrics types corrected to float for ratios |
| `alpaca-sdk-real-api-integration-bugs.md` | SDK requires `start` datetime, list symbols, `.data.get()` | Data loader implementation notes |
| `order-lifecycle-and-risk-architecture.md` | Position sizing truncates DOWN, CircuitBreaker realized-only | Runner strategy evaluation corrected |
| `applying-decimal-float-boundary-refactor.md` | `pytest.approx()` for floats, exact equality for Decimal | Test strategy for metrics |
| `alpaca-py-async-threading-bridge.md` | `run_in_executor()` for sync SDK in async context | Data loader async pattern |
| `alpaca-py-api-error-mocking.md` | `_make_api_error()` helper for SDK error mocking | Data loader unit tests |
| `ring-buffer-generalizes-to-all-indicators.md` | Indicator architecture context | Indicator warm-up handling |
| `indicator-extensibility-requirement.md` | Current SMA-only is acceptable for Phase 1 Velez | Known limitations section |
| `ruff-up042-str-enum-convention.md` | Use `(str, Enum)` not `StrEnum` | OrderRole enum pattern |
| `jesse-routes-vs-freqtrade-bots.md` | Jesse model confirmed: same strategy code, different adapter | Architecture validation |
| `startup-reconciliation-crash-recovery.md` | Deterministic IDs, idempotent patterns | `"bt-1"` order IDs for reproducibility |
| `alpaca-py-replace-order-qty-type.md` | `int(qty)` for Alpaca orders | Not directly applicable (backtest doesn't call real API) |

---

## Known Limitations / Future Work

1. **Indicator extensibility** — Current IndicatorCalculator is hardcoded for SMA-20/200. The backtest uses this as-is. When the indicator declaration pattern lands, both live and backtest benefit automatically. Not blocking for Phase 1 VelezStrategy.

2. **Single strategy per run** — Phase 1 backtests run one strategy. Multi-strategy comparison is Phase 2.

3. **No short selling** — VelezStrategy is long-only Phase 1. BacktestExecution's SELL only works for closing long positions.

4. **No data caching** — Every backtest run re-fetches from Alpaca REST. Local bar cache (Parquet) would speed up iteration. Defer until it becomes a pain point.

5. **No strategy parameter overrides via CLI** — User cannot pass `--sma-fast 10`. Must edit config/env vars. Phase 2 feature.

6. **Buying power = cash (no margin)** — Does not model 2x margin. Conservative for position sizing.

7. **Memory scales linearly with bar count** — ~650 bytes/bar means multi-year backtests need streaming (not in-memory). Phase 1 target is 1-year max.

---

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Alpaca rate limiting on large data fetches | Low | Low | SDK auto-paginates with built-in retry; 200 req/min limit, 5-symbol = ~50 requests |
| BacktestExecution fill logic diverges from real fills | Medium | High | Fill price clamping to bar boundaries; known-trade verification tests; compare vs paper trading |
| Sharpe ratio / metrics calculation errors | Medium | Medium | Sample std (ddof=1); hand-verified test datasets; profit_factor capped (no infinity) |
| Out-of-memory on large backtests | Medium | Medium | ~370MB for 1yr/5sym (corrected from 50MB estimate); add MAX_BACKTEST_DAYS cap |
| Strategy state not properly reset between symbols | Medium | Medium | `on_position_closed()` called on every exit; unit test verifies state reset |
| Time zone bugs (UTC vs ET for market hours) | Medium | High | Pass timezone-aware datetimes to SDK; filter with `zoneinfo` |
| Unadjusted prices (splits/dividends) corrupt P&L | High | High | `Adjustment.ALL` in StockBarsRequest (mandatory) |
| API keys leaked into params JSON | Low | High | Explicit field allowlist in serialization; test assertion |
| Negative fill prices on penny stocks with high slippage | Low | Medium | Fill price floor `max(price, Decimal("0.01"))` |
| PositionSizer/CircuitBreaker API mismatch | High | High | CORRECTED in this plan — verified against actual source code |

---

## Testing Strategy Enhancement

### Research Insights: Four-Layer Testing (from best-practices-researcher)

**Layer 1: Known-Trade Verification (highest value)**
Handcraft a 5-10 bar dataset where you manually calculate every entry, fill price, stop trigger, and P&L. Assert exact Decimal match. This catches fill logic bugs, slippage errors, and off-by-one issues simultaneously.

**Layer 2: Invariant/Property Tests (hypothesis)**
Generate random bar sequences and verify:
- Final equity = initial_capital + sum(all realized P&L) — money conservation
- Cash never goes negative
- No position exists after EOD close
- Fill prices are always within `[bar.low, bar.high]`

**Layer 3: Regression Fixtures**
After verifying a full backtest manually, save trades as a JSON fixture. Re-run after every code change and assert exact match. Catches unintended behavior changes during refactoring.

**Layer 4: Look-Ahead Validation**
Run the same backtest on two datasets identical except for the final bar. All trades before that bar must be identical. Structurally proves strategy cannot see future data.

### Test Patterns from Project Learnings
- Use `pytest.approx()` for float metrics, exact equality for Decimal
- Use `make_bar()`, `make_green_bar()`, `make_red_bar()` factories from `tests/factories.py`
- Add `make_fill()` and `make_backtest_trade()` factories
- Use `SimpleNamespace(data={"AAPL": [...]})` for mock BarSet responses
- Copy `_make_api_error()` helper for SDK error mocking

---

## References

### Internal
- Phase 1 Plan: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md` (Step 6 spec, slippage model, DB schemas)
- Strategy ABC: `backend/app/strategy/base.py`
- VelezStrategy: `backend/app/strategy/velez.py`
- BrokerAdapter Protocol: `backend/app/broker/broker_adapter.py`
- DataProvider Protocol: `backend/app/broker/data_provider.py`
- Shared Types: `backend/app/broker/types.py`
- IndicatorCalculator: `backend/app/engine/indicators.py`
- CandleAggregator: `backend/app/engine/candle_aggregator.py`
- PositionSizer: `backend/app/risk/position_sizer.py`
- CircuitBreaker: `backend/app/risk/circuit_breaker.py`
- BacktestRunModel: `backend/app/models/backtest.py`
- FakeBrokerAdapter: `backend/app/broker/fake/broker.py` (test pattern reference)
- Test factories: `backend/tests/factories.py`
- Decimal-for-money learnings: `docs/solutions/architecture-decisions/decimal-for-money-float-for-math.md`
- Order lifecycle learnings: `docs/solutions/architecture-decisions/order-lifecycle-and-risk-architecture.md`
- Alpaca SDK bugs: `docs/solutions/integration-issues/alpaca-sdk-real-api-integration-bugs.md`

### External
- [Alpaca Historical Data API](https://docs.alpaca.markets/docs/stock-pricing-data)
- [alpaca-py StockHistoricalDataClient](https://github.com/alpacahq/alpaca-py)
- [Sharpe Ratio (Wikipedia)](https://en.wikipedia.org/wiki/Sharpe_ratio)
- [Maximum Drawdown](https://en.wikipedia.org/wiki/Drawdown_(economics))
- [Backtrader Slippage Documentation](https://www.backtrader.com/docu/slippage/slippage/)
- [Zipline Slippage Models](https://github.com/quantopian/zipline/blob/master/zipline/finance/slippage.py)
- [QuantStart: Sharpe Ratio for Algo Trading](https://www.quantstart.com/articles/Sharpe-Ratio-for-Algorithmic-Trading-Performance-Measurement/)
- [QuantStart: Event-Driven Backtesting Performance](https://www.quantstart.com/articles/Event-Driven-Backtesting-with-Python-Part-VII/)
- [Backtrader: Entry and Exit Same Bar](https://community.backtrader.com/topic/3046/entry-and-exit-in-the-same-bar-using-bracket-orders)
- [exchange_calendars (GitHub)](https://github.com/gerrymanoim/exchange_calendars)
