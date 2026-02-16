---
title: "feat: Step 7 — TradingEngine Orchestrator"
type: feat
date: 2026-02-16
deepened: 2026-02-16
---

# Step 7: TradingEngine Orchestrator

## Enhancement Summary (Deepened 2026-02-16)

**Research agents used:** architecture-strategist, performance-oracle, security-sentinel, code-simplicity-reviewer, pattern-recognition-specialist, kieran-python-reviewer, spec-flow-analyzer, best-practices-researcher, learnings-researcher, framework-docs-researcher + Context7 (exchange_calendars, pytest-asyncio)

**Sections enhanced:** All 6 phases + architecture + risk analysis

### Critical Findings (16 P1 issues — must address before implementation)

| # | Issue | Found By | Section |
|---|-------|----------|---------|
| **P1-1** | `TradeUpdate` has no `correlation_id`, `pnl`, `local_id`, or `fill_price` fields — fill routing code references phantom fields | arch, security, simplicity, patterns, python, spec-flow | Task 3.3 |
| **P1-2** | `_pending_entries` stores `correlation_id` but `OrderManager.get_candles_since_order()` and `cancel_pending_entry()` require `local_id` | patterns, python, spec-flow | Task 3.2 |
| **P1-3** | Pending entry cancellation never calls `OrderManager.cancel_pending_entry()` — phantom buy-stops remain at broker | patterns, python, spec-flow | Task 3.2 |
| **P1-4** | `_supervised_task` calls `await self.shutdown()` inside TaskGroup — deadlock risk (shutdown awaits disconnect which blocks on sibling tasks) | arch, python | Task 2.2 |
| **P1-5** | ~~`loop.add_signal_handler()` raises `NotImplementedError` on Windows~~ **Resolved: Linux-only platform.** Use `loop.add_signal_handler()` directly — no platform conditional needed | arch, security, python, framework-docs | Task 5.1 |
| **P1-6** | TaskGroup cancellation can interrupt stop-loss submission mid-flight — position left unprotected (unlimited downside) | arch | Task 3.3 |
| **P1-7** | `_planned_stops` not persisted — crash between entry submission and fill loses stop price; reconciler uses emergency stop instead of strategy stop | arch, security | Task 2.1 |
| **P1-8** | Paper safety gate: `AccountInfo` has no paper/live field; `_is_paper_account()` is referenced but never defined | security, python | Task 1.3 |
| **P1-9** | No `asyncio.Lock` on shared state — TOCTOU between bar task and trade update task at await boundaries can cause duplicate entries | security, best-practices | Task 2.1 |
| **P1-10** | Supervised task restart calls `subscribe_bars()` which raises `BrokerError("already subscribed")` — engine dies on transient disconnect | security | Task 2.2 |
| **P1-11** | `_get_position()` and `_get_active_stop_correlation()` called but never defined — trailing stops and exits can't work | python, spec-flow | Task 3.2 |
| **P1-12** | `strategy_name` not available in `_handle_entry_fill()` — `_planned_stops` only stores `Decimal`, not strategy context | arch, spec-flow | Task 3.3 |
| **P1-13** | REJECTED/EXPIRED/CANCELED orders leave stale `_pending_entries` — engine only cleans on FILL events, symbol permanently "stuck" | spec-flow | Task 3.3 |
| **P1-14** | `circuit_breaker.reconstruct_from_trades()` never called in `start()` — mid-day restart has zero CB state | spec-flow | Task 2.1 |
| **P1-15** | Shutdown does not verify broker-side stop protection — positions may be left without stops between shutdown and next restart | security, arch | Task 2.1 |
| **P1-16** | `_planned_stops`/`_pending_entries` not rebuilt from DB on startup — crash recovery loses strategy-calculated stop prices | arch | Task 2.1 |

### Key Simplification Recommendations

| # | Recommendation | LOC Saved | Rationale |
|---|---------------|-----------|-----------|
| **S1** | ~~Remove EngineEventBus + LogListener + EngineEventListener — use structlog directly~~ | ~160 | **Applied** — Task 1.2 deleted, all `_event_bus.emit()` replaced with `log.info()`/`log.warning()` |
| **S2** | ~~Inline StaticScanner — `symbols = list(config.watchlist)` replaces file+protocol+tests~~ | ~45 | **Applied** — Scanner protocol removed from Task 1.1, replaced with `symbols = list(config.watchlist)` |
| **S3** | ~~Inline safety check into `TradingEngine.start()` — remove `safety.py`~~ | ~40 | **Applied** — Safety check inlined as `_verify_paper_mode()` in TradingEngine, no separate `safety.py` |
| **S4** | ~~Remove `force_close_eod` Strategy ABC property — Phase 1 is RTH-only~~ | ~10 | **Applied** — `force_close_eod` removed from Task 1.1 and Strategy ABC; Phase 1 always force-closes |
| **S5** | Reduce test target to 35-40 (from 60+) | ~100 | After simplifications, right-sized for an orchestrator |

### Top Performance Recommendations

| # | Issue | Impact | Effort |
|---|-------|--------|--------|
| **PERF-1** | Parallelize warm-up with `asyncio.Semaphore(5)` | 4x faster startup (8s→2s for 20 symbols) | ~15 lines |
| **PERF-2** | Eliminate DB queries in `OrderManager.on_candle()` — store symbol with count | -25-250 DB queries/min | ~10 lines |
| **PERF-3** | Fast-path position count check before `RiskManager.approve()` | Avoids DB+REST on most candles | ~5 lines |
| **PERF-4** | Cache broker `AccountInfo` in RiskManager with 5s TTL | 80-90% fewer Alpaca REST calls | ~15 lines |
| **PERF-5** | Cache `Position` objects in engine, update on fills | Eliminates REST per candle per position | ~25 lines |

### Additional P2 Findings (from late agent runs)

| # | Issue | Found By | Section |
|---|-------|----------|---------|
| **P2-1** | PARTIAL_FILL + CANCELED leaves `_pending_entries` stale — engine ignores non-FILL events | spec-flow | Task 3.3 |
| **P2-2** | EOD force-close clears caches before fill confirmation — should let fills flow, then clean up | security, spec-flow | Task 4.1 |
| **P2-3** | No input validation on bar OHLCV data from WebSocket (high >= low, positive values) | security | Task 3.1 |
| **P2-4** | `asyncio.shield()` needed around stop-loss submission to survive TaskGroup cancellation | arch | Task 3.3 |
| **P2-5** | 2-3s drain period needed in shutdown between cancel and disconnect | arch | Task 2.1 |
| **P2-6** | `_eod_closing` flag needed to pause bar processing during EOD force-close | arch, spec-flow | Task 4.1 |
| **P2-7** | Pending entries NOT canceled when CB trips — could fill creating new position despite breaker | spec-flow | Task 3.2 |
| **P2-8** | Extract `_resolve_strategy()` to shared `backend/app/strategy/registry.py` (used by both BacktestRunner and TradingEngine) | patterns | Task 2.1 |
| **P2-9** | Verify `broker_id` index exists on `order_state` table — prevents table scan on every trade update | perf | Migration |
| **P2-10** | `OrderManager`/`RiskManager`/`CircuitBreaker` construction never shown in plan's `start()` | python | Task 2.1 |
| **P2-11** | Fills between reconciliation completing and trade update stream subscribing are missed (narrow window) | spec-flow | Task 2.1 |
| **P2-12** | CB trip event `CIRCUIT_BREAKER_TRIPPED` defined but never emitted anywhere | spec-flow | Task 3.3 |

### Institutional Learnings Applied (from `docs/solutions/`)

Key learnings that directly impact this plan:
- **Order lifecycle architecture** → P1-1, P1-2, P1-3 (fill routing depends on OrderStateModel lookup)
- **Startup reconciliation** → P1-7, P1-16 (planned stops must be persisted for crash recovery)
- **alpaca-py async threading bridge** → stream reconnection pattern preserved correctly
- **alpaca-py SDK integration bugs** → `subscribe_bars()` has `_subscribed` guard that blocks retry (P1-10)
- **Decimal for money, float for math** → boundary is correctly applied in plan

---

## Overview

Build the TradingEngine — the central orchestrator that wires all existing components together for live/paper trading. The engine connects data streaming, candle aggregation, indicator calculation, strategy evaluation, order management, and risk management into a continuous real-time loop.

**Scope**: TradingEngine class + wire CLI `start` command. No web UI, no HTTP endpoints, no Docker. Those are Step 8+.

**Brainstorm**: `docs/brainstorms/2026-02-16-trading-engine-brainstorm.md`

## Problem Statement / Motivation

All individual components are built and tested (Steps 1-6), but nothing wires them together for real-time trading. The `algo-trader start` command currently prints "Not yet implemented." The TradingEngine is the missing orchestrator that turns separate components into a working trading system.

## Proposed Solution

A single `TradingEngine` class (~450-550 lines) that:

1. **On startup**: Verifies paper mode, connects broker/data, runs reconciliation, warms indicators, subscribes to streams
2. **While running**: Processes bars → candles → indicators → strategy → orders. Processes trade updates → fills → stops → CircuitBreaker
3. **At EOD**: Force-closes positions, cancels pending orders, resets CircuitBreaker
4. **On shutdown**: Cancels orders, disconnects streams, clean exit

## Technical Approach

### Architecture

```
CLI: algo-trader start
         |
         v
    TradingEngine
    |
    +-- [1] Verify paper mode (safety gate)
    +-- [2] Connect DataProvider + BrokerAdapter
    +-- [3] StartupReconciler.reconcile()
    +-- [4] Warm indicators (REST historical bars)
    +-- [5] asyncio.TaskGroup:
            |
            +-- _run_bar_stream()        # DataProvider.subscribe_bars()
            +-- _run_trade_updates()     # BrokerAdapter.subscribe_trade_updates()
            +-- _run_eod_timer()         # Sleep until market close, trigger force-close
            |
            +-- All wrapped in _supervised_task() (restart with backoff)
    |
    +-- structlog (S1: direct logging, no event bus)
```

### Data Flow Per Bar

```
1-min bar from WS
  |-> Track last_bar_by_symbol[symbol] = bar
  |-> CandleAggregator.process_bar(bar) -> candle | None
  |-> [if candle]:
       |-> IndicatorCalculator.process_candle(candle) -> IndicatorSet
       |-> OrderManager.on_candle(symbol)  # increment pending-entry counter
       |-> _evaluate_strategy(candle, indicators, strategy)
```

### Trade Update Processing

```
TradeUpdate from WS
  |-> OrderManager.handle_trade_update(update)
  |-> [if ENTRY fill]:
       |-> Retrieve planned_stop from _planned_stops[correlation_id]
       |-> OrderManager.submit_stop_loss(...)
       |-> Update _positions cache
       |-> Notify listeners (on_entry_fill)
  |
  |-> [if STOP_LOSS or EXIT_MARKET fill]:
       |-> Compute P&L from Trade record
       |-> CircuitBreaker.record_trade(pnl)
       |-> Strategy.on_position_closed()
       |-> Update _positions cache (remove)
       |-> Notify listeners (on_trade_closed)
```

### Research Insights: Architecture

**asyncio.TaskGroup semantics (framework-docs-researcher):**
- When ANY task raises an unhandled exception, TaskGroup **cancels ALL remaining tasks** and raises `ExceptionGroup`
- This means the supervised task wrapper MUST catch all exceptions internally — only re-raise to kill the entire engine
- `CancelledError` MUST propagate (never swallow it) — TaskGroup needs it for orderly shutdown
- Use a **coro_factory** (callable returning coroutine), not a raw coroutine — consumed coroutines can't be restarted

**Shutdown coordination (best-practices-researcher):**
- Use `asyncio.Event` as the shutdown signal primitive, not a boolean flag
- `asyncio.Event.wait()` is awaitable and interruptible; `while not flag:` requires polling
- `asyncio.wait_for(event.wait(), timeout=60)` gives chunked sleep for the EOD timer

**asyncio.Lock for shared state (best-practices-researcher, security-sentinel):**
- Bar stream and trade update tasks both modify `_positions`, `_pending_entries`, `_planned_stops`
- At any `await` point, the other task can run — classic TOCTOU
- Single `asyncio.Lock` around `_evaluate_strategy` and `_process_trade_update` eliminates this class of bug
- Contention is negligible (bars arrive every 60s, fills are less frequent)

**exchange_calendars (framework-docs-researcher, Context7):**
- Library already in `pyproject.toml` (`exchange-calendars>=4.12`)
- NYSE code: `"XNYS"` (ISO MIC). All times in UTC
- `schedule.loc[date]["market_close"]` handles early closes automatically — no special-case logic
- Half-days: July 3, Black Friday, Christmas Eve → close at 1:00 PM ET (17:00 UTC)
- Wrap in thin `MarketCalendar` class (~30 lines) for testability. **Constrained to exactly 2 methods: `next_close(now) -> datetime` and `is_open(now) -> bool`. Do not expand this interface — use `exchange_calendars` directly for anything else.**

**alpaca-py WebSocket auto-reconnect (framework-docs-researcher, source code analysis):**
- Both `StockDataStream` and `TradingStream` auto-reconnect on `WebSocketException`
- Auto-resubscribe after reconnect (handlers preserved internally)
- `stop()` has up to 5-second latency (checks stop queue on `recv()` timeout)
- `stop()` crashes if `_loop` is None (stream never started) — existing guard in codebase is correct

**Pattern consistency (pattern-recognition-specialist):**
- Plan correctly mirrors BacktestRunner orchestrator pattern
- `_handle_*` for event handlers, `_process_*` for data processing, `_run_*` for long-running tasks — all consistent
- One naming inconsistency: plan uses `_get_position` but codebase convention is `_find_*` for lookups that may return None

### Key Design Decisions (Resolved from Brainstorm + SpecFlow)

#### D1: Entry Fill → Stop-Loss Wiring

TradingEngine owns the trade update processing loop (not OrderManager). After calling `OrderManager.handle_trade_update()`, the engine inspects the update type. On an entry fill, it retrieves the planned stop price from `_planned_stops[correlation_id]` and calls `OrderManager.submit_stop_loss()`.

**Why TradingEngine owns this**: The stop price comes from strategy evaluation (which only TradingEngine knows). OrderManager is a lifecycle orchestrator — it doesn't know strategy context.

> **DEEPENED (P1-1):** `TradeUpdate` has no `correlation_id` field. Its fields are: `event`, `order_id` (broker order ID), `symbol`, `side`, `qty`, `filled_qty`, `filled_avg_price`, `timestamp`. After `OrderManager.handle_trade_update(update)`, the engine must look up the `OrderStateModel` by `update.order_id` (which maps to `broker_id`) to get `correlation_id`, `order_role`, and `local_id`. Recommended: either add a public `find_order_by_broker_id()` method to OrderManager, or have `handle_trade_update()` return a `TradeUpdateResult` dataclass with `order_role`, `correlation_id`, `local_id`, and `filled: bool`.

#### D2: In-Memory State Cache

TradingEngine maintains lightweight in-memory state:
- `_positions: dict[str, Position]` — symbol → Position object (updated on fills, market price from last bar)
- `_pending_entries: dict[str, _PendingEntryRef]` — symbol → `_PendingEntryRef(local_id, correlation_id)` for pending entry orders
- `_planned_stops: dict[str, PlannedStop]` — correlation_id → `PlannedStop(stop_price, strategy_name)` (between signal and fill)
- `_active_stop_corr: dict[str, str]` — symbol → correlation_id for active stop-loss orders (for trailing stop updates and exit signals)
- `_last_bar_by_symbol: dict[str, Bar]` — latest bar per symbol (for EOD close price)

Initialized from DB/broker on startup, updated incrementally by fill events.

> **DEEPENED (P1-2, P1-11, P1-12, PERF-5):** Multiple reviewers found that the original `dict[str, str]` and `dict[str, Decimal]` types lost critical information needed by downstream methods. Changes:
> - `_positions` upgraded from `set[str]` to `dict[str, Position]` — avoids REST call per candle per held position (PERF-5). Populate from broker on startup, update entry price from fills, market price from last bar close.
> - `_pending_entries` upgraded to store `_PendingEntryRef(local_id, correlation_id)` — `OrderManager.get_candles_since_order()` and `cancel_pending_entry()` both require `local_id`, not `correlation_id` (P1-2).
> - `_planned_stops` upgraded to store `PlannedStop(stop_price, strategy_name)` — `strategy_name` is needed by `submit_stop_loss()` but was inaccessible from the fill handler (P1-12).
> - `_active_stop_corr` added — `_get_active_stop_correlation(symbol)` was called but never defined (P1-11). Cache eliminates DB query per candle per held position.
>
> ```python
> @dataclass(frozen=True)
> class _PendingEntryRef:
>     local_id: str
>     correlation_id: str
>
> @dataclass(frozen=True)
> class PlannedStop:
>     stop_price: Decimal
>     strategy_name: str
> ```
>
> **Crash recovery (P1-7, S14: deferred to Step 8+):** `_planned_stops` is in-memory only. If the engine crashes between entry submission and fill, the stop price is lost. The reconciler uses `emergency_stop_pct` (a safety net) instead of the strategy-calculated stop. **Step 7 accepts the `emergency_stop_pct` fallback** — wider than optimal but safe. **Step 8+:** Persist `planned_stop_price` in `OrderStateModel` (add column) so the reconciler can reconstruct the strategy's intended stop on restart.
>
> **asyncio.Lock (P1-9):** Add a single `asyncio.Lock` (`_state_lock`) acquired around `_evaluate_strategy()` and `_process_trade_update()` to prevent TOCTOU between bar and trade update tasks at await boundaries.

#### D3: EOD Force-Close Timing

A dedicated `_run_eod_timer()` task:
1. On start (and after each day reset), compute `market_close_time` for today (4:00 PM ET for normal days)
2. `asyncio.sleep` until `market_close_time - 30 seconds` (buffer for order execution)
3. Trigger `_force_close_eod()` — parallel cancel-then-sell for all open positions
4. After close, sleep until next market open, then `circuit_breaker.reset_daily(equity)`

**Why timer, not bar-timestamp check**: A bar-timestamp check only fires when bars arrive. If the stream lags or the last bar is at 3:58 PM, force-close would never trigger. A timer is deterministic.

**Market calendar**: Use `exchange_calendars` library (already in pyproject.toml as `exchange-calendars>=4.12`) for half-days and holidays. NYSE code: `"XNYS"`. Schedule handles early closes automatically — `schedule.loc[date]["market_close"]` returns correct time for both regular and half-day sessions.

> **DEEPENED (framework-docs):** Half-days happen ~4x/year (July 3, Black Friday, Christmas Eve) with 1:00 PM ET close. Without the library, positions stay open 3 hours past actual close. Since the library is already a dependency, use it. Wrap in thin `MarketCalendar` class for testability (exactly 2 methods: `next_close()`, `is_open()` — S8). All times from the library are UTC — convert to ET for logging.
>
> **EOD timer pattern (best-practices):** Use chunked sleep with `asyncio.Event` instead of single long sleep:
> - Sleep in 60s chunks via `asyncio.wait_for(shutdown_event.wait(), timeout=60)` when far from close
> - Switch to precise sleep when within 5 minutes of target
> - Re-verify wall-clock time after wake (handles laptop suspend/resume drift)
> - DST transitions happen at 2:00 AM ET, never during market hours — no drift risk for EOD

#### D4: Paper Trading Safety Gate

Two-layer check on startup:
1. **Config check**: `config.broker.paper` must be `True`. If `False`, raise `EngineError("Live trading is disabled. Set ALGO_BROKER__PAPER=true")`
2. **Broker verification**: After connecting, call `broker.get_account()`. If the account is not a paper account (Alpaca paper URL check or account metadata), raise `EngineError`

Test: Mock config with `paper=False`, assert engine raises. Mock broker returning live account, assert engine raises.

> **DEEPENED (P1-8):** `AccountInfo` in `broker/types.py` has no `is_paper` or `account_type` field. The `_is_paper_account()` function referenced here is never defined. **Fix:** Add `is_paper: bool` field to `AccountInfo`, populated by `AlpacaBrokerAdapter` based on whether it connected to `paper-api.alpaca.markets` or `api.alpaca.markets`. This is the most reliable indicator (Alpaca API keys are scoped to paper or live endpoint).

#### D5: Engine State Machine

Simple enum, not a formal state machine:
```python
class EngineState(str, Enum):
    INITIALIZING = "initializing"
    RECONCILING = "reconciling"
    WARMING_UP = "warming_up"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"
```

Used for: logging context, CLI `status` response, preventing operations in wrong state (e.g., no strategy evaluation during WARMING_UP).

#### D6: CircuitBreaker Start-of-Day Equity on Mid-Day Restart

On restart, the StartupReconciler's Phase 3 calls `circuit_breaker.reconstruct_from_trades()`. The start-of-day equity is estimated as: `current_equity - sum(today's realized P&L from Trade table)`. This is imprecise but conservative. Log a WARNING.

#### D7: Strategy Exception Isolation

All strategy calls (`should_long`, `should_exit`, `should_update_stop`) wrapped in try/except. On exception: log ERROR with symbol + traceback, skip that candle's evaluation for that symbol, continue with other symbols.

#### D8: Bar Stream Guards

- Unknown symbol: Log WARNING, skip bar (don't KeyError)
- Out-of-order bars: Already handled by CandleAggregator (drops bars with `timestamp <= last`)
- Missing bar REST fallback: **Deferred to future step**. For Step 7, log WARNING when candle completes with fewer bars than expected. The 90-second REST fallback adds significant complexity and is not needed for Phase 1 correctness.

#### D9: No EngineConfig — Use AppConfig Directly

No new config section. TradingEngine reads from `AppConfig` directly (watchlist, broker, risk, velez, web). If engine-specific settings emerge during implementation (warm-up timeout, shutdown timeout), add as constants first, promote to config only if they need to be user-configurable.

#### D10: Shutdown Idempotency

`_shutdown_event: asyncio.Event()`. Both signal handlers and HTTP endpoint call `.set()`. Shutdown checks `_shutdown_event.is_set()`. Second signal calls `sys.exit(1)` for force exit.

#### D11: Shutdown During Warm-Up

Warm-up checks `_shutdown_event.is_set()` between each symbol. If shutdown requested, abort warm-up immediately and proceed to disconnect.

#### D13: No Heartbeat Task in Step 7

Heartbeat is for WebSocket clients (Step 8). No heartbeat task in Step 7.

#### D13: Single Strategy, Phase 1

Phase 1 uses VelezStrategy for all symbols in `config.watchlist`. No route table — `symbols = list(config.watchlist)` and single strategy hardwired. Multi-strategy routing is a future step.

## Implementation Phases

### Phase 1: Foundation (~3 tasks)

#### Task 1.1: EngineState Enum + Paper Safety Gate

**Files:**
- `backend/app/engine/engine_state.py` — NEW: EngineState enum (~15 lines)
- `backend/tests/unit/test_engine_safety.py` — NEW: Safety gate tests (~50 lines)

**S2 applied:** No Scanner protocol. Symbols come from `symbols = list(config.watchlist)`.
**S4 applied:** No `force_close_eod` property. Phase 1 always force-closes at EOD.

```python
# engine/engine_state.py
class EngineState(str, Enum):
    INITIALIZING = "initializing"
    RECONCILING = "reconciling"
    WARMING_UP = "warming_up"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"
```

Paper safety gate is inlined into `TradingEngine.start()` as `_verify_paper_mode()` (S3 applied — no separate `safety.py`):
```python
async def _verify_paper_mode(self) -> None:
    """Two-layer paper trading verification. Raises EngineError on failure."""
    if not self._config.broker.paper:
        raise EngineError(
            "Live trading is disabled. Set ALGO_BROKER__PAPER=true"
        )
    account = await self._broker.get_account()
    if not account.is_paper:
        raise EngineError(
            "API keys point to a live trading account but paper mode is enabled."
        )
```

- [ ] Create EngineState enum (6 states)
- [ ] Inline `_verify_paper_mode()` in TradingEngine (S3: no separate safety.py)
- [ ] Unit test: config.paper=False raises EngineError
- [ ] Unit test: config.paper=True but broker returns live account raises
- [ ] Unit test: config.paper=True and broker returns paper account passes

**S1 applied:** Task 1.2 (EngineEventBus + LogListener) deleted. All event notifications use structlog directly.
**S3 applied:** No separate `safety.py` file. Paper safety gate inlined as `_verify_paper_mode()` in TradingEngine.

### Phase 2: Core Engine (~3 tasks)

#### Task 2.1: TradingEngine Class — Init + Start + Shutdown

**Files:**
- `backend/app/engine/trading_engine.py` — NEW: Core engine class (~200 lines initial)
- `backend/tests/unit/test_trading_engine.py` — NEW: Engine tests (~150 lines initial)

**Constructor:**
```python
class TradingEngine:
    def __init__(
        self,
        config: AppConfig,
        data_provider: DataProvider,
        broker: BrokerAdapter,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._config = config
        self._data = data_provider
        self._broker = broker
        self._session_factory = session_factory

        # State
        self._state = EngineState.INITIALIZING
        self._eod_closing = False  # P2-6: blocks bar processing during EOD close
        self._shutdown_event = asyncio.Event()  # S13: sole shutdown signal — .is_set() for bool, .wait() for sleep
        self._state_lock = asyncio.Lock()  # P1-9: protects shared state at await boundaries

        # S1: No EngineEventBus/LogListener — use structlog directly

        # Components (created in start())
        self._strategies: dict[str, Strategy] = {}
        self._aggregators: dict[str, CandleAggregator] = {}
        self._indicators: dict[str, IndicatorCalculator] = {}

        # In-memory cache (types per DEEPENED corrections)
        self._positions: dict[str, Position] = {}  # PERF-5: symbol → Position
        self._pending_entries: dict[str, _PendingEntryRef] = {}  # P1-2: symbol → ref
        self._planned_stops: dict[str, PlannedStop] = {}  # P1-12: corr_id → PlannedStop
        self._active_stop_corr: dict[str, str] = {}  # P1-11: symbol → stop corr_id
        self._last_bar_by_symbol: dict[str, Bar] = {}
```

**Start sequence:**
```python
async def start(self) -> None:
    # 1. Paper safety gate
    await verify_paper_mode(self._config.broker, self._broker)

    # 2. Create components (P2-10: includes OrderManager, RiskManager, CircuitBreaker)
    symbols = list(self._config.watchlist)
    if not symbols:
        raise EngineError("Watchlist is empty")
    self._create_components(symbols)

    # 3. Reconcile
    self._set_state(EngineState.RECONCILING)
    reconciler = StartupReconciler(...)
    result = await reconciler.reconcile()

    # 4. Reconstruct CircuitBreaker from today's trades (P1-14)
    # Real signature: reconstruct_from_trades(today_trades, start_of_day_equity) — sync, not async
    async with self._session_factory() as session:
        today_trades = await session.execute(
            select(TradeModel).where(TradeModel.closed_at >= today_start)
        )
        today_trades = list(today_trades.scalars().all())
    account = await self._broker.get_account()
    realized_today = sum(Decimal(str(t.pnl)) for t in today_trades)
    start_of_day_equity = account.equity - realized_today
    self._circuit_breaker.reconstruct_from_trades(today_trades, start_of_day_equity)

    # 5. Initialize caches from broker + DB (PERF-5, P1-16)
    positions = await self._broker.get_positions()
    self._positions = {p.symbol: p for p in positions}  # PERF-5: dict[str, Position]
    await self._rebuild_pending_caches_from_db()  # P1-16: rebuild planned stops

    # 6. Warm indicators
    self._set_state(EngineState.WARMING_UP)
    await self._warm_indicators(symbols)

    # 7. Run supervised tasks (with finally-based cleanup per P1-4)
    # P2-11: Known limitation — fills occurring between reconciliation (step 3)
    # and trade_updates stream (step 7) are missed. Narrow window (~seconds).
    # Reconciler handles on next restart. Document as accepted risk for Phase 1.
    self._set_state(EngineState.RUNNING)
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._supervised_task(self._run_bar_stream, "bar_stream"))
            tg.create_task(self._supervised_task(self._run_trade_updates, "trade_updates"))
            tg.create_task(self._supervised_task(self._run_eod_timer, "eod_timer"))
    except* Exception as eg:
        log.error("task_group_failed", errors=[str(e) for e in eg.exceptions])
    finally:
        await self._cleanup()  # disconnect, verify stop protection
```

**Shutdown:**
```python
async def shutdown(self) -> None:
    if self._shutdown_event.is_set():
        return  # S13: idempotent — single shutdown signal
    self._shutdown_event.set()  # S13: sole signal — wakes sleeping tasks + bool check
    self._set_state(EngineState.SHUTTING_DOWN)

    # 1. Cancel pending entries (S9: no loop, single call)
    try:
        await self._order_manager.cancel_all_pending()
    except Exception:
        log.exception("shutdown_cancel_failed")

    # 2. Drain in-flight fills (P2-5: brief pause for fills to process)
    await asyncio.sleep(2.0)

    # 3. Verify stop protection (P1-15: check broker positions have active stops)
    await self._verify_stop_protection()

    # 4. Don't force-close on shutdown — leave positions with broker-side stops
    #    (StartupReconciler handles on next start)

    # 5. Disconnect
    await self._data.disconnect()
    await self._broker.disconnect()

    self._set_state(EngineState.STOPPED)

async def _verify_stop_protection(self) -> None:
    """P1-15: Before disconnect, verify all positions have broker-side stops."""
    try:
        positions = await self._broker.get_positions()
        for pos in positions:
            # Check that an active stop-loss exists for this position
            # If not, place an emergency stop
            # (same logic as StartupReconciler._reconcile_positions)
            pass  # Implementation detail
    except Exception:
        log.exception("stop_verification_failed_on_shutdown")

async def _rebuild_pending_caches_from_db(self) -> None:
    """P1-16: Rebuild _pending_entries and _planned_stops from DB on startup."""
    # Query non-terminal entry orders to rebuild _pending_entries
    # Query OrderStateModel.stop_price (new column) to rebuild _planned_stops
    # This ensures crash recovery preserves strategy-calculated stop prices
    pass  # Implementation detail
```

- [ ] TradingEngine `__init__` with all state fields
- [ ] `start()` method: safety gate → components → reconcile → warm → TaskGroup
- [ ] `shutdown()` method: idempotent, cancel pending, disconnect
- [ ] `_create_components()`: use `resolve_strategy()` from shared `backend/app/strategy/registry.py` (P2-8), create aggregators + indicators per symbol. Also refactor `BacktestRunner._resolve_strategy()` to use same registry
- [ ] `_set_state()` with structlog notification (S1: no event bus)
- [ ] Signal handlers (SIGINT/SIGTERM) → `shutdown()`
- [ ] Unit test: start calls safety gate, reconciler, warm-up in order
- [ ] Unit test: shutdown is idempotent (second call is no-op)
- [ ] Unit test: SIGINT triggers shutdown

#### Task 2.2: Supervised Task Wrapper

**Files:**
- `backend/app/engine/trading_engine.py` — Add `_supervised_task` method (~30 lines)
- `backend/tests/unit/test_trading_engine.py` — Add supervisor tests (~40 lines)

```python
async def _supervised_task(
    self,
    coro_func: Callable[[], Coroutine[Any, Any, None]],
    name: str,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
) -> None:
    """Restart a task on failure with backoff. P1-4: never call shutdown() from inside TaskGroup."""
    retries = 0
    backoff = initial_backoff
    while not self._shutdown_event.is_set():
        try:
            await coro_func()
            return  # Clean exit
        except asyncio.CancelledError:
            raise  # Must propagate for TaskGroup shutdown
        except Exception:
            retries += 1
            log.exception("task_failed", task=name, retry=retries)
            if retries >= max_retries:
                log.critical("task_max_retries", task=name)
                self._shutdown_event.set()  # P1-4: signal shutdown, don't call shutdown()
                raise  # Propagate to TaskGroup — cleanup in finally block outside
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
```

**Key design notes:**
- **P1-4:** Never `await self.shutdown()` inside TaskGroup — deadlocks. Set event + raise instead.
- **P1-10:** `subscribe_bars()` has `_subscribed` guard blocking retry. Fix: move subscription to `start()`, tasks consume existing queue. Or add `reset_subscription()`.
- TaskGroup `except*` + `finally` pattern handles cleanup outside the group.

- [ ] `_supervised_task` with exponential backoff
- [ ] Clean exit on CancelledError (no retry — must propagate for TaskGroup)
- [ ] Max retries: `_shutdown_event.set()` + raise (P1-4: no `self.shutdown()` inside TaskGroup)
- [ ] Respects `_shutdown_event.is_set()` (not bool flag)
- [ ] Unit test: transient failure retries with backoff
- [ ] Unit test: 3 failures sets shutdown event and raises
- [ ] Unit test: CancelledError propagates immediately

#### Task 2.3: Indicator Warm-Up

**Files:**
- `backend/app/engine/trading_engine.py` — Add `_warm_indicators` method (~35 lines)
- `backend/tests/unit/test_trading_engine.py` — Add warm-up tests (~40 lines)

```python
async def _warm_indicators(self, symbols: list[str]) -> None:
    """Fetch historical bars and feed through aggregator + indicators."""
    sample_strategy = next(iter(self._strategies.values()))
    bars_needed = sample_strategy.required_history * sample_strategy.candle_interval_minutes

    for symbol in symbols:
        if self._shutdown_event.is_set():
            return  # Abort warm-up on shutdown

        try:
            bars = await self._data.get_historical_bars(
                symbol=symbol,
                count=bars_needed,
                timeframe="1Min",
            )
        except Exception:
            log.warning("warmup_failed", symbol=symbol)
            continue  # Strategy skips until organically warm

        for bar in bars:
            candle = self._aggregators[symbol].process_bar(bar)
            if candle is not None:
                self._indicators[symbol].process_candle(candle)

        log.info(
            "warmup_complete",
            symbol=symbol,
            bars_fed=len(bars),
            indicator_warm=self._indicators[symbol].is_warm,
        )
```

- [ ] Fetch `required_history * candle_interval_minutes` 1-min bars per symbol
- [ ] Feed through aggregator + indicator calculator
- [ ] **Parallelize with `asyncio.Semaphore(5)` and `asyncio.gather` (PERF-1)** — 4x faster startup
- [ ] Graceful degradation: if REST fails for one symbol, log WARNING and continue
- [ ] **If ALL symbols fail warm-up, log CRITICAL (spec-flow)** — engine will appear running but generate no signals
- [ ] Check `_shutdown_event.is_set()` between symbols (S13: interruptible)
- [ ] Guard `next(iter(self._strategies.values()))` against empty dict (**P2, python-reviewer**)
- [ ] Unit test: warm-up feeds bars through pipeline correctly
- [ ] Unit test: REST failure for one symbol doesn't block others
- [ ] Unit test: shutdown during warm-up aborts

> **DEEPENED (PERF-1):** Sequential warm-up is O(N) REST calls: 20 symbols × 400ms avg = 8 seconds. Parallelize with bounded concurrency matching the ThreadPoolExecutor capacity:
> ```python
> async def _warm_indicators(self, symbols: list[str]) -> None:
>     if not self._strategies:
>         log.warning("no_strategies_configured")
>         return
>     sample_strategy = next(iter(self._strategies.values()))
>     bars_needed = sample_strategy.required_history * sample_strategy.candle_interval_minutes
>     sem = asyncio.Semaphore(5)
>
>     async def warm_one(symbol: str) -> None:
>         if self._shutdown_event.is_set():
>             return
>         async with sem:
>             try:
>                 bars = await self._data.get_historical_bars(symbol=symbol, count=bars_needed, timeframe="1Min")
>             except Exception:
>                 log.warning("warmup_failed", symbol=symbol)
>                 return
>             for bar in bars:
>                 candle = self._aggregators[symbol].process_bar(bar)
>                 if candle is not None:
>                     self._indicators[symbol].process_candle(candle)
>             log.info("warmup_complete", symbol=symbol, bars_fed=len(bars),
>                      indicator_warm=self._indicators[symbol].is_warm)
>
>     await asyncio.gather(*[warm_one(sym) for sym in symbols])
> ```

### Phase 3: Trading Loop (~3 tasks)

#### Task 3.1: Bar Stream Processing

**Files:**
- `backend/app/engine/trading_engine.py` — Add `_run_bar_stream` method (~25 lines)
- `backend/tests/unit/test_trading_engine.py` — Add bar processing tests (~60 lines)

```python
async def _run_bar_stream(self) -> None:
    symbols = list(self._strategies.keys())
    async for bar in await self._data.subscribe_bars(symbols):
        if self._shutdown_event.is_set():
            return

        # Guard: unknown symbol
        if bar.symbol not in self._strategies:
            log.warning("unknown_symbol_bar", symbol=bar.symbol)
            continue

        # P2-3: Validate bar OHLCV (bad data from WebSocket)
        if bar.high < bar.low or bar.close <= 0 or bar.volume < 0:
            log.warning("invalid_bar_data", symbol=bar.symbol,
                        high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)
            continue

        # P2-6: Block strategy evaluation during EOD close window
        if self._eod_closing:
            continue

        self._last_bar_by_symbol[bar.symbol] = bar

        # Aggregate
        candle = self._aggregators[bar.symbol].process_bar(bar)
        if candle is None:
            continue

        # Indicators
        indicator_set = self._indicators[bar.symbol].process_candle(candle)

        # Notify OrderManager of new candle (for pending entry expiry)
        await self._order_manager.on_candle(bar.symbol)

        # Evaluate strategy
        try:
            async with self._state_lock:  # P1-9: protect shared state
                await self._evaluate_strategy(
                    candle, indicator_set, self._strategies[bar.symbol]
                )
        except Exception:
            log.exception("strategy_eval_error", symbol=bar.symbol)
```

- [ ] Subscribe to bar stream for all symbols
- [ ] Unknown symbol guard (log WARNING, skip)
- [ ] **Bar OHLCV validation (P2-3):** reject bars where `high < low` or `close <= 0` or `volume < 0`
- [ ] **`_eod_closing` guard (P2-6):** skip strategy evaluation during EOD close window
- [ ] **`self._state_lock` around `_evaluate_strategy` (P1-9):** prevent TOCTOU with trade update task
- [ ] Track last bar per symbol
- [ ] Aggregate → indicators → strategy evaluation
- [ ] Call OrderManager.on_candle for pending entry expiry
- [ ] Strategy exception isolation (try/except per symbol)
- [ ] Unit test: bars flow through aggregator → indicators → strategy
- [ ] Unit test: unknown symbol logged and skipped
- [ ] Unit test: invalid bar data logged and skipped
- [ ] Unit test: strategy exception doesn't crash loop
- [ ] Unit test: bars skipped when `_eod_closing` is True

#### Task 3.2: Strategy Evaluation (Mirror BacktestRunner)

**Files:**
- `backend/app/engine/trading_engine.py` — Add `_evaluate_strategy` method (~65 lines)
- `backend/tests/unit/test_trading_engine.py` — Add strategy eval tests (~80 lines)

```python
async def _evaluate_strategy(
    self,
    candle: Bar,
    indicators: IndicatorSet,
    strategy: Strategy,
) -> None:
    """Evaluate strategy for one symbol. Mirrors BacktestRunner._evaluate_strategy.

    SYNC OBLIGATION: This method MUST stay in sync with
    BacktestRunner._evaluate_strategy (backend/app/backtest/runner.py:243-317).
    When modifying evaluation logic here, update the backtest version too.

    Parameter mapping:
        BacktestRunner              TradingEngine
        positions dict              self._positions
        pending_entries dict        self._pending_entries
        planned_stops dict          self._planned_stops
        executor.submit_order()     self._order_manager.submit_entry()
    """
    symbol = candle.symbol

    # Case 1: Has open position
    if symbol in self._positions:
        position = self._positions[symbol]  # PERF-5: from cache, no REST

        # Trailing stop update
        new_stop = strategy.should_update_stop(candle, position, indicators)
        if new_stop is not None:
            corr_id = self._active_stop_corr.get(symbol)  # P1-11: from cache
            if corr_id:
                await self._order_manager.update_stop_loss(corr_id, new_stop)
                log.info("stop_moved", symbol=symbol, new_stop=str(new_stop))

        # Exit signal
        if strategy.should_exit(candle, position, indicators):
            corr_id = self._active_stop_corr.get(symbol)
            if corr_id:
                await self._order_manager.request_exit(symbol, corr_id)

    # Case 2: Has pending entry (P1-2: use _PendingEntryRef, P1-3: cancel at broker)
    elif symbol in self._pending_entries:
        ref = self._pending_entries[symbol]  # P1-2: _PendingEntryRef(local_id, correlation_id)
        candles_since = self._order_manager.get_candles_since_order(ref.local_id)
        if strategy.should_cancel_pending(candle, candles_since):
            await self._order_manager.cancel_pending_entry(ref.local_id)  # P1-3: cancel at broker
            del self._pending_entries[symbol]
            self._planned_stops.pop(ref.correlation_id, None)

    # Case 3: No position, no pending → signal detection
    else:
        if indicators.bar_count < strategy.required_history:
            return
        if not strategy.should_long(candle, indicators):
            return

        # PERF-3: Fast-path position count check before risk approval
        if len(self._positions) + len(self._pending_entries) >= self._config.risk.max_open_positions:
            return  # No DB or REST call needed

        entry_price = strategy.entry_price(candle, indicators)
        stop_price = strategy.stop_loss_price(candle, indicators)

        signal = Signal(
            symbol=symbol,
            side=Side.BUY,
            entry_price=entry_price,
            stop_loss_price=stop_price,
            order_type=OrderType.STOP,
            strategy_name=type(strategy).__name__.lower(),
            timestamp=candle.timestamp,
        )

        approval = await self._risk_manager.approve(signal)
        if not approval.approved:
            return

        log.info("signal_detected", symbol=symbol, entry=str(entry_price), stop=str(stop_price))

        result = await self._order_manager.submit_entry(signal, approval)
        if result.state == OrderState.SUBMITTED:
            self._pending_entries[symbol] = _PendingEntryRef(
                local_id=result.local_id,
                correlation_id=result.correlation_id,
            )  # P1-2
            self._planned_stops[result.correlation_id] = PlannedStop(
                stop_price=stop_price,
                strategy_name=type(strategy).__name__.lower(),
            )  # P1-12
            log.info("order_submitted", symbol=symbol, local_id=result.local_id)
```

- [ ] Case 1: Position from `self._positions` cache (PERF-5), stop corr from `self._active_stop_corr` (P1-11)
- [ ] Case 2: Use `ref.local_id` from `_PendingEntryRef` (P1-2), cancel at broker (P1-3)
- [ ] Case 3: Fast-path position count check (PERF-3) → risk approval → submit entry
- [ ] Store `PlannedStop(stop_price, strategy_name)` on entry submission (P1-12)
- [ ] Store `_PendingEntryRef(local_id, correlation_id)` in `_pending_entries` (P1-2)
- [ ] All events via structlog directly (S1)
- [ ] SYNC OBLIGATION docstring with file reference + parameter mapping table
- [ ] Extract `_resolve_strategy` to shared `backend/app/strategy/registry.py` (P2-8)
- [ ] Unit test: signal detection → risk approval → entry submission
- [ ] Unit test: trailing stop update on position
- [ ] Unit test: exit signal on position
- [ ] Unit test: pending entry cancellation calls `cancel_pending_entry()` and clears cache
- [ ] Unit test: warm-up skip (bar_count < required_history)
- [ ] Unit test: risk rejection skips entry
- [ ] Unit test: PERF-3 fast-path rejects at position limit

#### Task 3.3: Trade Update Processing + Fill Handling

**Files:**
- `backend/app/engine/trading_engine.py` — Add trade update methods (~70 lines)
- `backend/tests/unit/test_trading_engine.py` — Add fill handling tests (~80 lines)

```python
async def _run_trade_updates(self) -> None:
    async for update in await self._broker.subscribe_trade_updates():
        if self._shutdown_event.is_set():
            return
        try:
            await self._process_trade_update(update)
        except Exception:
            log.exception("trade_update_error", update=str(update))

async def _process_trade_update(self, update: TradeUpdate) -> None:
    """Delegate lifecycle to OrderManager, then route fills/terminals."""
    async with self._state_lock:  # P1-9: protect shared state
        await self._order_manager.handle_trade_update(update)
        if update.event == TradeEventType.FILL:
            await self._handle_fill(update)
        elif update.event in (
            TradeEventType.REJECTED,
            TradeEventType.CANCELED,
            TradeEventType.EXPIRED,
        ):
            await self._handle_terminal_non_fill(update)  # P1-13

async def _handle_fill(self, update: TradeUpdate) -> None:
    # Look up local order by broker order ID (P1-1: TradeUpdate has no correlation_id)
    order = await self._find_order_by_broker_id(update.order_id)
    if order is None:
        log.warning("fill_for_unknown_order", broker_order_id=update.order_id)
        return

    role = OrderRole(order.order_role)
    correlation_id = order.correlation_id

    if role == OrderRole.ENTRY and correlation_id in self._planned_stops:
        await self._handle_entry_fill(update, order)
    elif role in (OrderRole.STOP_LOSS, OrderRole.EXIT_MARKET):
        await self._handle_exit_fill(update, order)

async def _handle_entry_fill(self, update: TradeUpdate, order: OrderStateModel) -> None:
    """Stop-loss submission is TradingEngine's responsibility (not OrderManager)."""
    planned = self._planned_stops.pop(order.correlation_id)
    self._pending_entries.pop(update.symbol, None)
    self._positions[update.symbol] = Position(
        symbol=update.symbol, qty=update.filled_qty,
        side=Side.BUY, avg_entry_price=update.filled_avg_price or Decimal("0"),
        market_value=Decimal("0"), unrealized_pl=Decimal("0"), unrealized_pl_pct=Decimal("0"),
    )

    # P1-6: Shield from TaskGroup cancellation — unprotected position is worst state
    await asyncio.shield(
        self._order_manager.submit_stop_loss(
            correlation_id=order.correlation_id,
            symbol=update.symbol,
            qty=update.filled_qty,
            stop_price=planned.stop_price,
            parent_local_id=order.local_id,
            strategy_name=planned.strategy_name,  # P1-12: from PlannedStop
        )
    )
    self._active_stop_corr[update.symbol] = order.correlation_id
    log.info("entry_fill", symbol=update.symbol,
             qty=str(update.filled_qty), stop=str(planned.stop_price))

async def _handle_exit_fill(self, update: TradeUpdate, order: OrderStateModel) -> None:
    self._positions.pop(update.symbol, None)
    self._active_stop_corr.pop(update.symbol, None)

    # P&L from Trade record (P1-1: not available on TradeUpdate)
    trade = await self._find_trade_by_correlation(order.correlation_id)
    if trade is not None:
        self._circuit_breaker.record_trade(Decimal(str(trade.pnl)))
        # P2-12: Log CB trip (structlog per S1)
        if self._circuit_breaker.is_tripped:
            log.warning("circuit_breaker_tripped", daily_pnl=str(self._circuit_breaker.daily_pnl))
            # P2-7: Cancel pending entries to prevent new positions
            for sym in list(self._pending_entries.keys()):
                ref = self._pending_entries[sym]
                try:
                    await self._order_manager.cancel_pending_entry(ref.local_id)
                except Exception:
                    log.exception("cb_cancel_pending_failed", symbol=sym)
            self._pending_entries.clear()
            self._planned_stops.clear()

    strategy = self._strategies.get(update.symbol)
    if strategy:
        strategy.on_position_closed()
    log.info("trade_closed", symbol=update.symbol,
             pnl=str(trade.pnl) if trade else "unknown")

async def _handle_terminal_non_fill(self, update: TradeUpdate) -> None:
    """P1-13: Clean caches when entry orders are REJECTED/CANCELED/EXPIRED."""
    order = await self._find_order_by_broker_id(update.order_id)
    if order is None:
        return
    role = OrderRole(order.order_role)
    if role == OrderRole.ENTRY:
        corr_id = order.correlation_id
        self._pending_entries.pop(update.symbol, None)
        self._planned_stops.pop(corr_id, None)
        log.info("entry_order_terminal", symbol=update.symbol,
                 event=update.event.value, correlation_id=corr_id)
```

**Partial fill handling (P2-1):** The plan only handles `FILL` events. `PARTIAL_FILL` events are handled by `OrderManager._handle_partial_fill()` internally but the engine does not submit a stop for the partial qty. Additionally, a PARTIAL_FILL followed by CANCELED leaves caches stale. For Phase 1, document this as a known limitation — partial fills are rare for market orders and stop orders on liquid equities. If needed, add partial fill stop-loss submission in a follow-up.

### Phase 4: EOD + Day Transitions (~1 task)

#### Task 4.1: EOD Timer + Force-Close

**Files:**
- `backend/app/engine/trading_engine.py` — Add EOD methods (~60 lines)
- `backend/tests/unit/test_trading_engine.py` — Add EOD tests (~50 lines)

```python
_EOD_CLOSE_BUFFER_SECONDS = 30  # How far before market close to trigger force-close

async def _run_eod_timer(self) -> None:
    """Timer task: fire force-close at market close, reset CB at market open."""
    while not self._shutdown_event.is_set():
        now = datetime.now(tz=ZoneInfo("America/New_York"))
        close_time = self._calendar.next_close(now)  # S8: MarketCalendar, 2 methods only

        if close_time is None:
            # Not a trading day (weekend/holiday)
            await self._sleep_until_next_trading_day()
            continue

        # Wait until _EOD_CLOSE_BUFFER_SECONDS before close (chunked sleep)
        trigger_time = close_time - timedelta(seconds=_EOD_CLOSE_BUFFER_SECONDS)
        while datetime.now(tz=ZoneInfo("America/New_York")) < trigger_time:
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=60.0)
                return  # Shutdown requested
            except TimeoutError:
                pass  # Re-check time

        # P2-6: Block new entries during EOD close
        self._eod_closing = True

        # Log drift for monitoring (performance-oracle)
        actual = datetime.now(tz=ZoneInfo("America/New_York"))
        drift_ms = (actual - trigger_time).total_seconds() * 1000
        log.info("eod_timer_triggered", drift_ms=drift_ms)

        # Force-close
        await self._force_close_eod()

        # Wait until next market open for CB reset
        # ...sleep until next trading day...
        account = await self._broker.get_account()
        self._circuit_breaker.reset_daily(account.equity)
        self._eod_closing = False

async def _force_close_eod(self) -> None:
    """Force-close all positions (S4: Phase 1 always closes — no force_close_eod filter)."""
    symbols_to_close = list(self._positions.keys())
    if not symbols_to_close:
        return

    # Parallel cancel-then-sell
    tasks = [
        self._close_position_eod(symbol)
        for symbol in symbols_to_close
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for symbol, result in zip(symbols_to_close, results):
        if isinstance(result, Exception):
            log.error("eod_close_failed", symbol=symbol, error=str(result))

    # P2-2: Do NOT clear caches here — let fills flow through _process_trade_update
    # which will clean up _pending_entries/_planned_stops/_positions on each FILL/CANCEL.
    # Clearing before confirmation leaves engine blind to in-flight fill events.

    # Cancel remaining pending entries via OrderManager (broker-side cancel)
    try:
        await self._order_manager.cancel_all_pending()
    except Exception:
        log.exception("eod_cancel_pending_failed")

    # Flush aggregators
    for agg in self._aggregators.values():
        agg.flush()

    log.info("eod_close_complete", symbols_closed=symbols_to_close)
```

- [ ] `_run_eod_timer`: **chunked sleep via `asyncio.wait_for(shutdown_event.wait(), timeout=60)`** — re-verify time after wake
- [ ] `_force_close_eod`: parallel close for all positions (**remove `force_close_eod` filter — S4, Phase 1 always closes**)
- [ ] `_close_position_eod`: cancel stop → market sell (using OrderManager.request_exit)
- [ ] **Don't clear `_pending_entries`/`_planned_stops` until fills confirmed (python-reviewer, security)** — failed closes need their cache intact
- [ ] CB reset at next market open
- [ ] Handle weekends/holidays via `exchange_calendars` `next_session()`
- [ ] **Block new entry fills during EOD close window (arch-strategist)** — `_eod_closing` flag
- [ ] Flush aggregators after EOD
- [ ] **Log EOD timer drift for monitoring (performance-oracle):** `drift_ms = (actual - planned).total_seconds() * 1000`
- [ ] Extract `_EOD_CLOSE_BUFFER_SECONDS = 30` named constant (**python-reviewer: no magic numbers**)
- [ ] Unit test: force-close triggers for all open positions
- [ ] Unit test: CB reset after EOD
- [ ] Unit test: failed close leaves cache intact for reconciler

### Phase 5: CLI Wiring + Integration (~2 tasks)

#### Task 5.1: Wire CLI `start` Command

**Files:**
- `backend/app/cli/commands.py` — Implement `start` command (~40 lines)

```python
@cli.command()
def start() -> None:
    """Start the trading engine."""
    config = AppConfig()
    click.echo("Starting algo-trader engine...")
    click.echo(f"  Mode:      {'Paper' if config.broker.paper else 'LIVE'}")
    click.echo(f"  Watchlist: {', '.join(config.watchlist)}")
    click.echo(f"  Strategy:  velez")

    try:
        asyncio.run(_start_engine(config))
    except LiveTradingBlockedError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt:
        click.echo("\nEngine stopped.")
    except Exception as e:
        raise click.ClickException(f"Engine failed: {e}") from e

async def _start_engine(config: AppConfig) -> None:
    from app.broker.alpaca.broker import AlpacaBrokerAdapter
    from app.broker.alpaca.data import AlpacaDataProvider

    # Create providers
    data_provider = AlpacaDataProvider(config.broker)
    broker_adapter = AlpacaBrokerAdapter(config.broker)

    # DB engine
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{config.db_path}")
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # Run migrations (ensure tables exist)
    # ...

    async with data_provider, broker_adapter:
        engine = TradingEngine(
            config=config,
            data_provider=data_provider,
            broker=broker_adapter,
            session_factory=session_factory,
        )

        # Install signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.shutdown()))

        await engine.start()
```

- [ ] Implement `start` command with config display
- [ ] Create providers, DB engine, session factory
- [ ] Signal handlers via `loop.add_signal_handler()` for SIGINT + SIGTERM (Linux-only platform — no Windows conditional needed)
- [ ] Clean error handling for `EngineError` (simplified from LiveTradingBlockedError — **S3**)
- [ ] KeyboardInterrupt handling for clean Ctrl+C
- [ ] **Document idempotent disconnect (python-reviewer):** Both `engine.shutdown()` and `async with` exit call `disconnect()` — adapters must be idempotent

> **DEEPENED (P1-5) — Signal handling (Linux-only):**
> ```python
> loop = asyncio.get_running_loop()
> _first_signal = True
>
> def request_shutdown() -> None:
>     nonlocal _first_signal
>     if _first_signal:
>         _first_signal = False
>         shutdown_event.set()
>     else:
>         sys.exit(1)  # Second signal = force exit
>
> for sig in (signal.SIGINT, signal.SIGTERM):
>     loop.add_signal_handler(sig, request_shutdown)
> ```
>
> Double signal pattern: first sets event for graceful shutdown, second calls `sys.exit(1)` for force exit. No platform conditionals — dev and prod both run on Linux (Docker).

#### Task 5.2: Integration Tests

**Files:**
- `backend/tests/unit/test_trading_engine.py` — Complete unit test suite
- `backend/tests/integration/test_trading_engine_integration.py` — NEW: Integration tests (~100 lines)

**Integration test approach**: Use `FakeBrokerAdapter` and `FakeDataProvider` (in-memory implementations) to test the full engine pipeline without real API calls.

```python
class FakeDataProvider:
    """In-memory data provider for integration tests."""
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    async def subscribe_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        for bar in self._bars:
            yield bar

    async def get_historical_bars(self, symbol, count, timeframe="1Min"):
        return [b for b in self._bars if b.symbol == symbol][:count]

    # ... other protocol methods ...
```

**Key integration tests:**
1. Full flow: bars → signal → risk → entry → fill → stop → exit → CB
2. Paper safety gate: live account config raises
3. EOD force-close at end of day bars
4. Strategy exception doesn't crash engine
5. Shutdown during processing

- [ ] Create FakeDataProvider for integration tests
- [ ] Create FakeBrokerAdapter extensions for integration tests (existing one may suffice)
- [ ] Integration test: full signal-to-trade lifecycle
- [ ] Integration test: paper safety gate blocks live
- [ ] Integration test: EOD force-close works
- [ ] Integration test: strategy exception isolation
- [ ] Integration test: graceful shutdown mid-processing

### Phase 6: Quality + Polish (~1 task)

#### Task 6.1: Lint, Type Check, Full Test Suite

- [ ] `ruff check app/ tests/` — clean
- [ ] `ruff format --check app/ tests/` — clean
- [ ] `mypy --strict app/` — clean
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Review SYNC OBLIGATION: compare `_evaluate_strategy` in TradingEngine vs BacktestRunner
- [ ] **Add reciprocal SYNC OBLIGATION to BacktestRunner (pattern-specialist)**
- [ ] CLI smoke test: `algo-trader start` with paper config (verify it starts, Ctrl+C to stop)
- [ ] CLI smoke test: `algo-trader config` still works
- [ ] Update CLI `start` command output test
- [ ] **Verify `broker_id` index exists on `order_state` table (PERF-6)** — add index + migration if missing

> **Performance instrumentation (S10: only warm-up timing for Step 7):**
> Add `time.monotonic()` around `_warm_indicators()`. Log total + per-symbol warm-up duration.
> **Deferred to Step 8+:** Bar processing latency, signal-to-order latency, queue depth monitoring — premature without a running baseline. Correctness first, optimize later.
>
> **Testing approach (best-practices, python-reviewer):**
> - Use `asyncio_mode = "auto"` in pyproject.toml to avoid forgetting `@pytest.mark.asyncio`
> - Wrap long-running test scenarios in `async with asyncio.timeout(5.0)` to prevent hanging tests
> - Use fast backoff values in tests (0.01s instead of 1.0s)
> - Test shutdown via the `shutdown()` method directly, not by simulating OS signals
> - Use `AsyncMock` for broker and data provider dependencies

## Acceptance Criteria

### Functional Requirements

- [ ] `algo-trader start` launches the TradingEngine with real Alpaca data streams
- [ ] Paper trading safety gate: engine refuses to start with `paper=False` or live API keys
- [ ] Paper safety gate has tests proving it works (unit + integration)
- [ ] StartupReconciler runs on every engine start
- [ ] Indicators warm from REST historical bars before live trading begins
- [ ] 1-min bars aggregate to N-min candles per strategy configuration
- [ ] Strategy evaluation follows same logic as BacktestRunner (SYNC OBLIGATION documented)
- [ ] Entry signal → risk approval → order submission → stop-loss on fill
- [ ] Trailing stop updates propagate to broker via OrderManager
- [ ] Exit signals trigger cancel-then-sell flow via OrderManager
- [ ] CircuitBreaker.record_trade() called by engine after exit fills
- [ ] EOD force-close at market close for all open positions (**S4: Phase 1 always closes**)
- [ ] CircuitBreaker resets at next market open
- [ ] SIGINT/SIGTERM triggers graceful shutdown
- [ ] Shutdown is idempotent (multiple signals don't conflict)
- [ ] Strategy exceptions don't crash the trading loop
- [ ] Unknown symbols from bar stream are logged and skipped
- [ ] All key lifecycle points logged via structlog directly (**S1: no EngineEventBus/LogListener**)
- [ ] **P2-7 design decision:** Document whether CB trip should cancel pending entries (Phase 1 accepted risk vs. full implementation)

### Non-Functional Requirements

- [ ] TradingEngine class < 600 lines (after simplifications S1-S4, target ~400 lines)
- [ ] All new files have mypy strict compliance
- [ ] All new files pass ruff check + format
- [ ] No new dependencies beyond what's in pyproject.toml (exchange_calendars is already listed)
- [ ] **asyncio.Lock protects all shared state mutations (P1-9)**
- [ ] **asyncio.shield() protects stop-loss submission (P1-6)**
- [ ] Signal handling via `loop.add_signal_handler()` — Linux only, no platform conditionals

### Quality Gates

- [ ] Unit tests for all public methods (target: 35-40 new tests — **S5, right-sized after simplifications**)
- [ ] Integration test: full signal-to-trade lifecycle with FakeDataProvider
- [ ] Integration test: paper safety gate (verify `is_paper` field detection — **P1-8**)
- [ ] Integration test: mid-day restart with CircuitBreaker reconstruction (**spec-flow**)
- [ ] CLI smoke test: engine starts in paper mode, accepts Ctrl+C / SIGTERM
- [ ] Ruff + mypy clean on full codebase
- [ ] SYNC OBLIGATION documented with file:line references + parameter mapping

## Dependencies & Prerequisites

- Steps 1-6 merged to main (confirmed)
- Alpaca paper trading API keys in `.env`
- Python 3.12+, all existing deps

## Risk Analysis & Mitigation (Updated by Deepen)

| Risk | Likelihood | Impact | Mitigation | Status |
|------|-----------|--------|------------|--------|
| TradeUpdate lacks correlation_id, pnl, local_id, fill_price | **Confirmed** | **Critical** | Look up OrderStateModel by `update.order_id` (broker_id) after `handle_trade_update()`. Add public query method or return type to OrderManager | **P1-1: Must fix** |
| `_pending_entries` stores correlation_id but OrderManager needs local_id | **Confirmed** | **High** | Use `_PendingEntryRef(local_id, correlation_id)` dataclass | **P1-2: Must fix** |
| Pending entry cancel never calls `cancel_pending_entry()` at broker | **Confirmed** | **High** | Add `await self._order_manager.cancel_pending_entry(ref.local_id)` call | **P1-3: Must fix** |
| `shutdown()` inside TaskGroup deadlocks | **Confirmed** | **High** | Set flag and raise; cleanup in `finally` outside TaskGroup | **P1-4: Must fix** |
| ~~`add_signal_handler` crashes on Windows~~ | N/A | N/A | Linux-only platform — use `loop.add_signal_handler()` directly | **P1-5: Resolved** |
| TaskGroup cancellation interrupts stop-loss submission | Medium | **Critical** | `asyncio.shield()` around stop-loss submission | **P1-6: Must fix** |
| `_planned_stops` lost on crash — no stop on restart fill | Medium | **Critical** | **S14: Deferred to Step 8+** — `emergency_stop_pct` fallback is safe. Persist `planned_stop_price` column later | **P1-7: Deferred** |
| Paper safety gate: `AccountInfo` has no paper indicator | **Confirmed** | **Critical** | Add `is_paper: bool` to AccountInfo, set by AlpacaBrokerAdapter | **P1-8: Must fix** |
| TOCTOU race between bar and trade update tasks | Medium | High | Single `asyncio.Lock` around `_evaluate_strategy` and `_process_trade_update` | **P1-9: Must fix** |
| Stream resubscription blocked by `_subscribed` guard | **Confirmed** | High | Move subscription to `start()`, tasks only consume queue. Or add `reset_subscription()` | **P1-10: Must fix** |
| `_get_position()` and `_get_active_stop_correlation()` undefined | **Confirmed** | High | Define helpers + maintain `_active_stop_corr` cache | **P1-11: Must fix** |
| `strategy_name` inaccessible in fill handler | **Confirmed** | Medium | Store `PlannedStop(stop_price, strategy_name)` | **P1-12: Must fix** |
| REJECTED/EXPIRED/CANCELED leave stale caches | **Confirmed** | **High** | Handle non-FILL terminal events in `_process_trade_update` to clean caches | **P1-13: Must fix** |
| CB has zero state after mid-day restart | **Confirmed** | **High** | Call `circuit_breaker.reconstruct_from_trades()` in `start()` | **P1-14: Must fix** |
| Shutdown leaves positions without broker-side stops | Medium | **Critical** | `_verify_stop_protection()` in shutdown checks broker positions have active stops | **P1-15: Must fix** |
| Crash loses `_planned_stops` — reconciler uses emergency stop | Medium | **Critical** | **S14: Deferred to Step 8+** — `emergency_stop_pct` fallback is safe | **P1-16: Deferred** |
| Fills between reconciliation and stream subscribe | Low | Medium | Narrow window — document as known limitation. Reconciler handles on next restart | **P2-11: Accepted** |
| Pending entries not canceled when CB trips | Low | High | Cancel pending entries in `_circuit_breaker.record_trade()` callback if tripped | **P2-7: Design note** |
| Alpaca bar stream latency > 3s | Medium | Medium | Log WARNING on stale bars. No automated fallback in Phase 1 | Unchanged |
| Half-day market close missed | Low | Medium | Use `exchange_calendars` (already in pyproject.toml) | **Resolved** |
| OrderManager.on_candle issues N DB queries per candle | **Confirmed** | Medium | Store symbol with count in `_candle_counts` dict (PERF-2) | **Perf fix** |
| RiskManager.approve() hits DB + REST on every signal | **Confirmed** | Medium | Fast-path position count + AccountInfo TTL cache (PERF-3, PERF-4) | **Perf fix** |

## Future Considerations

- **Step 8**: CLI enhancements, HTTP endpoints (status, shutdown, WebSocket), web UI dashboard
- **Step 8+ (deferred from Step 7)**: `planned_stop_price` column on `order_state` (S14) — enables precise crash recovery instead of `emergency_stop_pct` fallback. Also: bar processing latency, signal-to-order latency, queue depth instrumentation (S10)
- **Step 9**: Docker + deployment
- **ETH support**: `force_close_eod=False` + LIMIT-only orders + ETH data feed
- **Dynamic scanners**: `GapUpScanner`, `VolumeScanner` with Scanner protocol (add protocol when second implementation exists)
- **Multi-strategy per symbol**: Position partitioning
- **Missing bar REST fallback**: 90-second timeout + REST fetch
- **AI advisory**: Analysis pipeline before/after strategy evaluation

## References

### Internal References

- Brainstorm: `docs/brainstorms/2026-02-16-trading-engine-brainstorm.md`
- Phase 1 Plan: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md`
- BacktestRunner (wiring pattern): `backend/app/backtest/runner.py:70-237`
- BacktestRunner._evaluate_strategy: `backend/app/backtest/runner.py:243-317`
- Strategy ABC: `backend/app/strategy/base.py:16-114`
- BrokerAdapter protocol: `backend/app/broker/broker_adapter.py:23-109`
- DataProvider protocol: `backend/app/broker/data_provider.py:15-87`
- OrderManager: `backend/app/orders/order_manager.py:50-130`
- RiskManager: `backend/app/risk/risk_manager.py:26-121`
- CircuitBreaker: `backend/app/risk/circuit_breaker.py:18-142`
- StartupReconciler: `backend/app/orders/startup_reconciler.py:1-50`
- IndicatorCalculator: `backend/app/engine/indicators.py:78-125`
- CandleAggregator: `backend/app/engine/candle_aggregator.py:17-122`
- CLI commands: `backend/app/cli/commands.py:26-31`
- Config: `backend/app/config.py:107-166`

### Compound Learnings

- `docs/solutions/architecture-decisions/backtesting-engine-architecture.md`
- `docs/solutions/architecture-decisions/strategy-core-decoupling.md`
- `docs/solutions/architecture-decisions/backtest-fill-simulation-patterns.md`
- `docs/solutions/architecture-decisions/order-lifecycle-and-risk-architecture.md`
- `docs/solutions/architecture-decisions/startup-reconciliation-crash-recovery.md`
- `docs/solutions/integration-issues/alpaca-py-async-threading-bridge.md`
