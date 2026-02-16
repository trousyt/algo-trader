# TradingEngine Brainstorm

**Date**: 2026-02-16
**Status**: Complete

---

## What We're Building

The TradingEngine — the central orchestrator that wires all existing components together for live/paper trading. This is the "brain" that connects the data stream, candle aggregation, indicator calculation, strategy evaluation, order management, and risk management into a continuous real-time loop.

### Scope Decision

Step 7 was originally "CLI + Web UI + TradingEngine". We split it:

- **Step 7** = TradingEngine only (this brainstorm)
- **Step 8** = CLI + Web UI
- **Step 9** = Docker Smoke Test

**Rationale**: TradingEngine is complex enough to stand alone. Mixing it with UI work would make the step too large and muddy the focus.

---

## Why This Approach

### Architecture: Engine-Centric Orchestrator

**Chosen over** a microservice or event-sourcing approach.

**Rationale**:
- Follows the Jesse-inspired model established in previous steps
- All components already exist and expose clean protocols/ABCs
- BacktestRunner already proved the wiring pattern works
- Single-process design keeps latency low for 2-minute candle strategies

### How It Connects Everything

```
                    ┌─────────────────────────────────────────────┐
                    │              TradingEngine                   │
                    │                                              │
  Alpaca WS ──────>│  DataStream ──> CandleAggregator             │
  (1-min bars)     │                      │                        │
                   │                      v                        │
                   │              IndicatorCalculator               │
                   │                      │                        │
                   │                      v                        │
                   │                  Strategy                     │
                   │                 /    |    \                    │
                   │           signal  trail  exit                 │
                   │              │      │      │                  │
                   │              v      v      v                  │
                   │             RiskManager                       │
                   │                  │                             │
                   │                  v                             │
                   │             OrderManager ──> BrokerAdapter     │
                   │                                   │           │
                   │             CircuitBreaker <──────┘           │
                   │                                              │
                   │  ┌──────────────────────────────────────┐    │
                   │  │ EventBus (Observer/Listener)          │    │
                   │  │  -> LogListener                       │    │
                   │  │  -> (future: DiscordListener, UIWs)   │    │
                   │  └──────────────────────────────────────┘    │
                   └──────────────────────────────────────────────┘
```

### Lifecycle

1. **Startup**: Load config, create components, run StartupReconciler, warm up indicators
2. **Trading Loop**: Receive bars -> aggregate candles -> calculate indicators -> evaluate strategy -> manage orders
3. **EOD**: Force-close open positions (RTH Phase 1), reset circuit breaker
4. **Shutdown**: Cancel open orders, disconnect streams, clean exit

---

## Key Decisions

### 1. RTH-Only Phase 1, ETH Extension Point

**Decision**: Regular Trading Hours only (9:30 AM - 4:00 PM ET). Add `force_close_eod` property to Strategy ABC (default `True`) for future ETH support.

**Why**: ETH has significant constraints (LIMIT orders only, no STOP protection, wider spreads, lower liquidity). Adding ETH support touches too many components for Phase 1.

**Extension point**: When `force_close_eod = False`, the engine skips EOD force-close for that strategy. ETH-specific order constraints handled in a future step.

**Evidence**: Analyzed RIME 2026-02-13 data — RTH close $3.50, ETH high $6.22 (+78%). ETH is lucrative but risky. Design for it, don't build it yet.

### 2. Task Supervision: asyncio.TaskGroup + Restart Wrapper

**Decision**: Use `asyncio.TaskGroup` with a thin restart wrapper (~50 lines). No APScheduler.

**Why**: The engine runs 3-4 concurrent tasks (data stream, trade updates, heartbeat, possibly HTTP shutdown). TaskGroup handles structured concurrency natively. A restart wrapper (retry with backoff, max retries) handles transient failures. APScheduler would be a heavy dependency for simple task management.

### 3. Engine Events: Observer/Listener Protocol

**Decision**: Observer/Listener pattern for engine events (signals, fills, errors, state changes).

**Why**: We know Discord notifications are coming soon — that's a second consumer beyond logging. The Observer pattern costs ~30 lines for the protocol + registry and cleanly separates event production from consumption.

**Note**: This was a deliberate design choice despite YAGNI concerns. We have a concrete near-term consumer (Discord) and the cost is minimal. The simplicity reviewer may flag this — the justification is: we will definitely have more than 1 consumer, and retrofitting events later would require touching every emit site.

### 4. Indicator Warm-Up: Block Until Warm

**Decision**: On startup, fetch historical 1-min bars via REST (enough to fill the slowest indicator buffer, e.g., 200 bars for SMA-200), feed them through CandleAggregator + IndicatorCalculator, then start the live stream.

**Why**: Simplest correct approach. Strategy signals are meaningless without warm indicators. The alternative (stream and skip signals) wastes the first ~7 hours of trading waiting for 200 two-minute candles.

### 5. One Strategy Per Symbol (Phase 1)

**Decision**: Each symbol runs exactly one strategy. No multi-strategy-per-symbol.

**Why**: Simplifies position management (one position per symbol), order attribution, and P&L tracking. Multi-strategy-per-symbol requires position partitioning — Phase 2 concern.

### 6. Dual Shutdown Triggers

**Decision**: Support both SIGINT/SIGTERM signal handlers AND an HTTP shutdown endpoint.

**Why**: Signal handlers cover CLI and Docker. HTTP endpoint covers the web UI (Step 8) and programmatic shutdown. Both trigger the same graceful shutdown sequence: cancel pending orders, wait for fills, force-close positions, disconnect streams.

### 7. Scanner Protocol + StaticScanner

**Decision**: Define a `Scanner` protocol (ABC) with a `StaticScanner` implementation for Phase 1. StaticScanner returns a fixed list of symbols from config.

**Why**: The user's vision is scanners paired with strategies — e.g., a gap-up scanner feeding symbols to VelezStrategy. The Scanner protocol captures this intent without building the dynamic scanner yet. StaticScanner is trivial (~15 lines) and satisfies Phase 1 needs.

**Future**: `GapUpScanner`, `VolumeScanner`, etc. that query pre-market data and dynamically populate the watchlist.

### 8. Strategy Evaluation Logic Duplication

**Decision**: Duplicate the strategy evaluation loop between `BacktestRunner` and `TradingEngine` rather than extracting a shared abstraction.

**Why**: The two loops have different execution contexts (sync simulated fills vs. async real broker), different error handling (backtest can crash-fast, live needs resilience), and different lifecycle management (backtest runs to completion, live runs indefinitely). A shared abstraction would be a forced fit.

**Sync requirement**: BacktestRunner and TradingEngine strategy evaluation loops MUST stay in sync. When modifying the evaluation logic in one, check and update the other. This is a documented maintenance obligation.

### 9. Route Table Design

**Decision**: A route maps a Scanner to a Strategy factory + config. Phase 1 has one route: `StaticScanner(["AAPL"]) -> VelezStrategy`.

**Structure**:
```
Route:
  scanner: Scanner          # Produces symbols
  strategy_factory: type    # Strategy class to instantiate
  strategy_config: object   # Config for that strategy
```

**Why**: This cleanly models the user's mental model of "this scanner feeds these kinds of stocks to this strategy." It's extensible to multiple scanners/strategies without changing the engine.

---

## Open Questions

- **Scanner refresh interval**: How often does a dynamic scanner re-scan? Every minute? Every 5 minutes? Only pre-market? (Phase 2 concern)
- **Multi-strategy-per-symbol**: Position partitioning approach when we add this in Phase 2
- **AI advisory integration**: Where does AI analysis plug into the engine? Before strategy evaluation? As a filter? (Phase 2+)

---

## What's Next

Proceed to `/workflows:plan` to create the Step 7 implementation plan for TradingEngine.
