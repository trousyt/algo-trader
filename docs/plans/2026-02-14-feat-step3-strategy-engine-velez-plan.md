---
title: "feat: Step 3 Strategy Engine + Velez Strategy"
type: feat
date: 2026-02-14
deepened: 2026-02-14
---

# Step 3: Strategy Engine + Velez Strategy

## Deepening Summary

**Deepened on:** 2026-02-14
**Agents used:** architecture-strategist, kieran-python-reviewer, performance-oracle, code-simplicity-reviewer, best-practices-researcher (SMA, state machines), pattern-recognition-specialist

### Key Amendments (HIGH priority)
1. **Add `indicators` param to `entry_price()` / `stop_loss_price()`** — future-proofs for indicator-dependent entries
2. **Fix DST handling** — `market_open_time` should be computed from bar date via existing `market_open()` util, not stored as `time`
3. **Add `on_position_closed()` lifecycle hook** — strategy needs to reset trailing stop state when position closes
4. **Running sum SMA optimization** — two deques (fast + slow) with running sums, 32x faster for backtest
5. **Fix mypy None-narrowing** — replace `any(v is None for v in [...])` with individual `or`-chained `is None` checks
6. **Division-by-zero guard** — add `price == 0` guard in `should_long()` spread calculation

### Key Amendments (MEDIUM priority)
7. **Merge `engine/types.py` into `engine/indicators.py`** — IndicatorSet doesn't need its own file (1 dataclass)
8. **Remove `hyperparameters: ClassVar`** from Strategy ABC — YAGNI, no per-symbol config in Phase 1
9. **Remove `reset()` from CandleAggregator and IndicatorCalculator** — YAGNI, engine creates fresh instances
10. **Use `(str, Enum)` for `_TrailState`** — per project convention (ruff UP042 suppressed)
11. **Shared test factories** — `tests/factories.py` with `make_bar()`, `make_green_bar()`, `make_red_bar()`
12. **`required_history()` → `@property`** — consistency with `bar_count` / `is_warm`
13. **3-state trailing stop** — merge PULLBACK + COUNTING_GREENS into PULLING_BACK (majority recommendation)
14. **Method-per-state dispatch** — `_on_watching()`, `_on_pulling_back()`, `_on_trailing()` instead of if/elif

### Structural Change
- Phase 3A (IndicatorSet) folded into Phase 3C (IndicatorCalculator) — reduces to 5 phases

## Overview

Build the candle aggregation pipeline, indicator calculation system, strategy base class, and the Velez SMA convergence strategy. This is the "brain" of the trading engine — it converts raw 1-min bars into multi-minute candles, computes technical indicators, evaluates strategy rules, and produces trading signals (entry price, stop-loss price, trailing stop updates, exit signals).

**Scope**: Pure computation and signal logic. No order execution, no risk management, no database persistence, no TradingEngine orchestration (those are Steps 4-5). The components built here are designed to be consumed by the TradingEngine in Step 5.

**Prerequisites**: Step 2 complete (215 tests, `Bar`/`Position` types, `DataProvider`/`BrokerAdapter` protocols).

## Design Decisions (SpecFlow Resolution)

The SpecFlow analysis identified 16 questions. Here are the resolved decisions:

### D1: SMA Divergence Definition (Critical)
**Decision**: The gap between SMA-20 and SMA-200 widened in favor of the trade direction on the latest candle.
- **Long**: `(sma_fast - sma_slow) > (prev_sma_fast - prev_sma_slow)` AND `sma_fast > sma_slow`
- This checks both that SMA-20 is above SMA-200 AND that the spread is increasing
- Single-candle check (no multi-bar confirmation required)

### D2: Trailing Stop State Machine (Critical)
**Decision**: Formal state machine with 3 states and method-per-state dispatch:
1. `WATCHING` — position open, waiting for first pullback (red candle)
2. `PULLING_BACK` — red candle detected, counting green candles toward 2-green threshold
3. `TRAILING` — stop moved to pullback low, counting max run, waiting for next pullback or exit

State cycles: `WATCHING → PULLING_BACK → TRAILING → WATCHING → ...`

**Implementation**: `_TrailState(str, Enum)` with method-per-state dispatch:
- `_on_watching(bar)` — check for red candle to start pullback
- `_on_pulling_back(bar)` — count greens, update pullback low on reds, transition on 2 greens
- `_on_trailing(bar)` — count strong run, detect next pullback red candle

**Rules**:
- First red candle after entry (or after trail) = pullback. Record its low. → `PULLING_BACK`
- Multiple consecutive red candles in `PULLING_BACK`: update pullback low to the LOWEST low across the red sequence.
- Green candle count resets on any new red candle within `PULLING_BACK`.
- After 2 green candles: move stop to pullback low. → `TRAILING`
- In `TRAILING`: count consecutive strong candles. If count >= `max_run_candles` → exit signal.
- A non-strong candle (including doji) resets the max run counter.
- Next red candle in `TRAILING` → `WATCHING` (cycle repeats).

### D3: Buy-Stop Expiry Ownership (Critical)
**Decision**: Add `should_cancel_pending(bar: Bar, candles_since_order: int) -> bool` to the strategy base class. Default implementation returns `candles_since_order >= 1` (cancel after 1 candle). VelezStrategy overrides using `config.buy_stop_expiry_candles`. The TradingEngine (Step 5) tracks candle count and calls this.

### D4: Risk Rejection Behavior (Critical)
**Decision**: Strategy resets to `WATCHING` state. No cooldown — if setup is still valid on the next candle, that's a legitimate signal. The Risk Manager will keep rejecting until conditions change (daily loss limit resets, etc.). This is the engine's responsibility (Step 5), not the strategy's.

### D5: Position/Order Check Before should_long (Critical)
**Decision**: The TradingEngine (Step 5) skips `should_long()` if there's an existing position or pending buy-stop for that symbol. The strategy does not need to know about positions/orders for signal detection. It only receives positions for stop management.

### D6: IndicatorSet Location
**Decision**: `IndicatorSet` lives at the top of `engine/indicators.py`. One frozen dataclass doesn't warrant its own `types.py` file. Strategies import from `app.engine.indicators` (or via `app.engine` re-export). No circular import risk.

### D7: Candle Type
**Decision**: Reuse `Bar` from `broker/types.py` for aggregated candles. An aggregated 2-min candle is still OHLCV data with the same fields. The timestamp is set to the window start time. This avoids type conversion overhead and keeps things simple.

### D8: Timeout Mechanism
**Decision**: **Defer to Step 5.** The CandleAggregator in Step 3 is a simple synchronous push-based processor: `process_bar(bar) -> Bar | None`. It receives bars one at a time and returns a completed candle when the window fills. The 90-second timeout logic, REST fallback, and market-close flush are orchestration concerns owned by the TradingEngine in Step 5. The CandleAggregator provides `flush() -> Bar | None` for the engine to call on timeout or close.

### D9: Ring Buffer Implementation
**Decision**: Two `collections.deque` instances — `deque(maxlen=fast_period)` and `deque(maxlen=slow_period)` — each with a running `Decimal` sum. On `process_candle()`: subtract the evicted value (if at capacity), add the new close, update the running sum. SMA = `running_sum / len(deque)`.

**Why two deques**: A single `deque(maxlen=slow_period)` would require iterating the last `fast_period` elements for the fast SMA. Two deques give O(1) SMA for both periods. Decimal running sums have zero drift (unlike float). Performance: ~0.8μs per SMA vs ~24.8μs for naive sum() — 32x faster, critical for backtest throughput.

### D10: should_update_stop Return Value
**Decision**: Returns the target stop price as `Decimal | None`. `None` = no change. The TradingEngine (Step 5) compares with current stop and calls `replace_order()` if different.

### D11: Strategy Status Lifecycle
**Decision**: Deferred to TradingEngine (Step 5). The strategy itself doesn't track status. The engine infers status from context (bar_count, positions, pending orders).

### D12: Pre/Post Market Bars
**Decision**: CandleAggregator ignores bars outside market hours. Uses `market_open()` and `market_close()` from `app.utils.time`.

### D13: Zero-Range Candle
**Decision**: If `high == low`, body_pct = 0%. Not a strong candle. Division by zero prevented.

### D14: Doji Threshold Role
**Decision**: A candle with `body_pct < doji_threshold_pct` is a doji. In the trailing stop state machine, doji candles are treated as neutral — they don't advance the green candle count (don't count toward the 2-green requirement), but they also don't reset it (not treated as a pullback). In the max run counter, a doji resets the consecutive strong candle count.

### D15: Per-Symbol Hyperparameters
**Decision**: Not in Phase 1. All symbols use the same `VelezConfig`.

### D16: Historical Bar Count for Warm-Up
**Decision**: Fetch `(sma_slow + 1) * candle_interval` bars (e.g., `201 * 2 = 402` for 2-min candles). This ensures `prev_sma_fast` and `prev_sma_slow` are populated on the first real evaluation.

---

## Technical Approach

### Architecture

```
1-min Bar (from DataProvider)
    │
    ▼
CandleAggregator.process_bar(bar) -> Bar | None
    │ (emits completed multi-minute candle)
    ▼
IndicatorCalculator.process_candle(candle) -> IndicatorSet
    │
    ▼
Strategy.should_long(bar, indicators) -> bool
Strategy.entry_price(bar, indicators) -> Decimal
Strategy.stop_loss_price(bar, indicators) -> Decimal
    │ (for positions)
    ▼
Strategy.should_update_stop(bar, position, indicators) -> Decimal | None
Strategy.should_exit(bar, position, indicators) -> bool
    │ (on position close — engine calls)
    ▼
Strategy.on_position_closed()  # resets trailing stop state
```

### File Structure

```
backend/app/
├── engine/
│   ├── __init__.py              # Re-exports: CandleAggregator, IndicatorCalculator, IndicatorSet
│   ├── candle_aggregator.py     # CandleAggregator class
│   └── indicators.py            # IndicatorSet frozen dataclass + IndicatorCalculator class
├── strategy/
│   ├── __init__.py              # Re-exports: Strategy, VelezStrategy
│   ├── base.py                  # Strategy ABC
│   └── velez.py                 # VelezStrategy + _TrailState enum
```

```
backend/tests/
├── factories.py                 # Shared: make_bar(), make_green_bar(), make_red_bar()
└── unit/
    ├── test_candle_aggregator.py
    ├── test_indicators.py       # Tests for both IndicatorSet and IndicatorCalculator
    ├── test_strategy_base.py
    └── test_velez_strategy.py
```

### Key Types

```python
# engine/indicators.py (top of file, before IndicatorCalculator)
@dataclass(frozen=True)
class IndicatorSet:
    """Typed indicator values passed to strategy."""
    sma_fast: Decimal | None       # SMA-20 (or configured fast period)
    sma_slow: Decimal | None       # SMA-200 (or configured slow period)
    prev_sma_fast: Decimal | None  # Previous candle's fast SMA
    prev_sma_slow: Decimal | None  # Previous candle's slow SMA
    bar_count: int                 # Number of candles in buffer
```

### CandleAggregator Design

```python
# engine/candle_aggregator.py
class CandleAggregator:
    """Aggregates 1-min bars into multi-minute candles.

    Push-based: call process_bar() with each incoming bar.
    Returns a completed candle when the window fills.
    Call flush() to emit a partial candle (market close, timeout).
    """

    def __init__(
        self,
        symbol: str,
        interval_minutes: int,
    ) -> None: ...

    def process_bar(self, bar: Bar) -> Bar | None:
        """Process a 1-min bar. Returns completed candle or None."""
        ...

    def flush(self) -> Bar | None:
        """Flush any buffered bars as a partial candle."""
        ...
```

**DST handling**: No stored `market_open_time: time`. Instead, derive market open from the bar's date using the existing `market_open(date)` utility from `app.utils.time`. This correctly handles DST transitions where open time shifts in UTC.

**Window alignment**: `(minutes_since_open) // interval * interval + market_open_minutes`. This aligns to market open (9:30 ET), so for 5-min: 9:30, 9:35, 9:40, etc.

**Deduplication**: Track `_last_bar_timestamp`. Drop bars with duplicate timestamps.

**Market hours filter**: Ignore bars before `market_open(bar.date)` or after `market_close(bar.date)`.

**No `reset()`**: YAGNI — the TradingEngine creates fresh instances per session. If needed later, add it then.

### IndicatorCalculator Design

```python
# engine/indicators.py
class IndicatorCalculator:
    """Computes SMA indicators from a candle stream.

    Maintains two ring buffers (deques) with running Decimal sums
    for O(1) SMA computation per candle. One deque per period.
    """

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 200,
    ) -> None:
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._fast_buf: deque[Decimal] = deque(maxlen=fast_period)
        self._slow_buf: deque[Decimal] = deque(maxlen=slow_period)
        self._fast_sum = Decimal(0)
        self._slow_sum = Decimal(0)
        self._prev_fast: Decimal | None = None
        self._prev_slow: Decimal | None = None
        ...

    def process_candle(self, candle: Bar) -> IndicatorSet:
        """Add candle to buffer and compute indicators.

        Running sum update: subtract evicted value (if at capacity),
        add new close, divide by length.
        """
        ...

    @property
    def bar_count(self) -> int:
        """Number of candles in the slow buffer (max = slow_period)."""
        ...

    @property
    def is_warm(self) -> bool:
        """True if enough candles for full SMA-slow calculation."""
        ...
```

**Running sum SMA**: On each `process_candle()`:
1. If `len(deque) == maxlen`, subtract `deque[0]` from running sum (about to be evicted)
2. Append new `close` to deque (auto-evicts oldest)
3. Add new `close` to running sum
4. SMA = `running_sum / len(deque)` if `len(deque) >= period`, else `None`

Decimal running sums have zero accumulated drift (unlike float). Performance: ~0.8μs per SMA vs ~24.8μs for naive `sum()` — 32x faster, critical for backtest throughput.

**Previous values**: Stored from the prior `process_candle()` call. `None` on the very first call.

**No `reset()`**: YAGNI — the TradingEngine creates fresh instances per session.

### Strategy Base Class Design

```python
# strategy/base.py
class Strategy(ABC):
    """Abstract base class for trading strategies.

    One instance per symbol. The TradingEngine creates instances
    and passes bar + indicators each candle.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @abstractmethod
    def should_long(self, bar: Bar, indicators: IndicatorSet) -> bool: ...

    def should_short(self, bar: Bar, indicators: IndicatorSet) -> bool:
        """Phase 2 stub. Returns False."""
        return False

    @abstractmethod
    def entry_price(self, bar: Bar, indicators: IndicatorSet) -> Decimal: ...

    @abstractmethod
    def stop_loss_price(self, bar: Bar, indicators: IndicatorSet) -> Decimal: ...

    @abstractmethod
    def should_update_stop(
        self, bar: Bar, position: Position, indicators: IndicatorSet,
    ) -> Decimal | None: ...

    @abstractmethod
    def should_exit(
        self, bar: Bar, position: Position, indicators: IndicatorSet,
    ) -> bool: ...

    def should_cancel_pending(
        self, bar: Bar, candles_since_order: int,
    ) -> bool:
        """Whether to cancel an unfilled pending order.
        Default: cancel after 1 candle.
        """
        return candles_since_order >= 1

    @property
    def required_history(self) -> int:
        """Number of candles needed before strategy is warm."""
        return 200

    def on_position_closed(self) -> None:
        """Called by TradingEngine when a position is fully closed.
        Override to reset internal state (e.g., trailing stop state).
        Default: no-op.
        """
```

**Changes from initial design (deepening amendments):**
- Removed `hyperparameters: ClassVar` — YAGNI, no per-symbol config in Phase 1
- Added `indicators` param to `entry_price()` and `stop_loss_price()` — future-proofs for indicator-dependent entry logic
- Added `on_position_closed()` lifecycle hook — strategies with internal state (trailing stop) need to reset on close
- Changed `required_history()` from method to `@property` — consistency with `bar_count` / `is_warm`

### VelezStrategy Trailing Stop State Machine

```
                    ┌───────────────────────────────────────────┐
                    │                                           │
  Entry fill        ▼         Red candle                        │
 ───────────► WATCHING ──────────────────► PULLING_BACK ───┐    │
                    ▲                      (record low,    │    │
                    │                       green_count=0) │    │
                    │   Another red candle                  │    │
                    │   (update to lowest low)  ◄──────────┘    │
                    │                      │                    │
                    │   Green candle       │                    │
                    │   (green_count++)    │                    │
                    │                      │                    │
                    │   green_count >= 2   ▼                    │
                    │                 TRAILING                   │
                    │                 (stop → pullback low)      │
                    │                      │                    │
                    │   Next red candle    │                    │
                    └──────────────────────┘                    │
                                                                │
                    max_run_candles consecutive strong ──► EXIT  │
                    Doji resets max run counter ─────────────────┘
```

**Method-per-state dispatch** (not if/elif chains):
- `_on_watching(bar)` → returns `None`, transitions to `PULLING_BACK` on red candle
- `_on_pulling_back(bar)` → counts greens, updates pullback low on reds, returns new stop on 2 greens
- `_on_trailing(bar)` → counts strong run for exit, transitions to `WATCHING` on next red

### VelezStrategy Signal Logic

```python
def should_long(self, bar: Bar, indicators: IndicatorSet) -> bool:
    # 1. Warm-up check
    if indicators.bar_count < self._config.sma_slow:
        return False

    # 2. SMAs must be non-None (with previous values)
    #    Use individual is-None checks — mypy strict can't narrow
    #    `any(v is None for v in [...])` on Optional fields
    sma_f = indicators.sma_fast
    sma_s = indicators.sma_slow
    prev_f = indicators.prev_sma_fast
    prev_s = indicators.prev_sma_slow
    if sma_f is None or sma_s is None or prev_f is None or prev_s is None:
        return False

    # 3. Division-by-zero guard + SMAs tight check
    price = bar.close
    if price == 0:
        return False
    spread = abs(sma_f - sma_s)
    if spread / price * 100 >= self._config.tightness_threshold_pct:
        return False

    # 4. SMA-20 diverging upward from SMA-200
    #    Gap widened AND SMA-20 is above SMA-200
    current_gap = sma_f - sma_s
    prev_gap = prev_f - prev_s
    if current_gap <= prev_gap:
        return False
    if sma_f <= sma_s:
        return False

    # 5. Strong green candle
    if bar.close <= bar.open:  # Not green
        return False
    if not self._is_strong_candle(bar):
        return False

    return True
```

**Deepening amendments applied:**
- Local variables for None-narrowing (mypy strict compliance)
- `price == 0` guard before division
- Variables use narrowed types after None check — no `# type: ignore` needed

---

## Implementation Phases

### Phase 3A: Test Factories + CandleAggregator (~25 min)

**Shared factories**: `backend/tests/factories.py`
- [ ] `make_bar(symbol, timestamp, open, high, low, close, volume)` — all params have defaults
- [ ] `make_green_bar(symbol, timestamp, ...)` — close > open guaranteed
- [ ] `make_red_bar(symbol, timestamp, ...)` — close < open guaranteed
- [ ] All prices are `Decimal`, volume is `Decimal`

**Tests**: `backend/tests/unit/test_candle_aggregator.py`

_Construction & validation:_
- [ ] Rejects invalid interval (e.g., 3, 7)
- [ ] Accepts valid intervals: 1, 2, 5, 10
- [ ] Stores symbol and interval

_1-min pass-through (interval=1):_
- [ ] Returns bar immediately (no buffering)
- [ ] Preserves all bar fields

_2-min aggregation:_
- [ ] First bar returns None (buffered)
- [ ] Second bar returns completed candle
- [ ] Candle OHLCV: open=first.open, high=max(highs), low=min(lows), close=last.close, volume=sum(volumes)
- [ ] Candle timestamp = window start time
- [ ] Candle symbol preserved

_5-min and 10-min aggregation:_
- [ ] Buffers correct number of bars before emitting
- [ ] OHLCV math correct for 5 bars
- [ ] OHLCV math correct for 10 bars

_Window alignment (DST-safe via market_open()):_
- [ ] Candles aligned to market open (9:30 ET)
- [ ] 5-min: bars at 9:30-9:34 → candle at 9:30, bars at 9:35-9:39 → candle at 9:35
- [ ] 2-min: bars at 9:30-9:31 → candle at 9:30, bars at 9:32-9:33 → candle at 9:32
- [ ] Mid-day start: bar at 10:47 correctly placed in its window (10:46 for 2-min)

_Edge cases:_
- [ ] Duplicate bar timestamp → dropped (returns None)
- [ ] Bar outside market hours → ignored (returns None)
- [ ] `flush()` returns partial candle from buffered bars
- [ ] `flush()` returns None when buffer is empty

**Implementation**: `backend/app/engine/candle_aggregator.py`
- [ ] `CandleAggregator` class
- [ ] `process_bar(bar: Bar) -> Bar | None`
- [ ] `flush() -> Bar | None`
- [ ] `_calculate_window_start(timestamp: datetime) -> datetime` — uses `market_open(bar_date)`
- [ ] `_is_market_hours(timestamp: datetime) -> bool` — uses `market_open()` / `market_close()`

---

### Phase 3B: IndicatorCalculator + IndicatorSet (~20 min)

**Tests**: `backend/tests/unit/test_indicators.py`

_IndicatorSet dataclass:_
- [ ] `IndicatorSet` is frozen
- [ ] All fields have correct types
- [ ] Default values work (bar_count=0, rest=None)
- [ ] Can construct with all values populated

_Basic SMA calculation (running sum):_
- [ ] SMA-20 correct with exactly 20 candles (verify against manual calculation)
- [ ] SMA-200 correct with exactly 200 candles
- [ ] SMA values are Decimal (not float)
- [ ] SMA matches expected value for known price series
- [ ] Running sum matches naive `sum()` result (correctness check)

_Warm-up behavior:_
- [ ] First candle: sma_fast=None, sma_slow=None, bar_count=1
- [ ] After 20 candles: sma_fast has value, sma_slow=None, bar_count=20
- [ ] After 200 candles: both have values, bar_count=200
- [ ] `is_warm` is False until 200 candles, True after

_Previous values:_
- [ ] First candle: prev_sma_fast=None, prev_sma_slow=None
- [ ] Second candle: prev values = previous candle's current values
- [ ] Values correctly shift each candle

_Ring buffer with running sum:_
- [ ] After 201 candles, bar_count capped at slow_period (oldest evicted)
- [ ] SMA recalculated correctly after eviction (running sum stays accurate)

_Edge cases:_
- [ ] All candles same price → SMA = that price
- [ ] Monotonically increasing prices → SMA lags
- [ ] Large price differences → no precision loss (Decimal)

**Implementation**: `backend/app/engine/indicators.py`
- [ ] `IndicatorSet` frozen dataclass (top of file)
- [ ] `IndicatorCalculator` class
- [ ] Two deques: `_fast_buf`, `_slow_buf` with running sums `_fast_sum`, `_slow_sum`
- [ ] `process_candle(candle: Bar) -> IndicatorSet`
- [ ] `bar_count` property (uses `len(_slow_buf)`)
- [ ] `is_warm` property

---

### Phase 3C: Strategy Base Class (~10 min)

**Tests**: `backend/tests/unit/test_strategy_base.py`

_Abstract class behavior:_
- [ ] Cannot instantiate Strategy directly (ABC)
- [ ] Concrete subclass that implements all abstract methods can be instantiated
- [ ] `symbol` set on `__init__`
- [ ] `should_short()` returns False by default
- [ ] `should_cancel_pending()` returns True when candles_since_order >= 1
- [ ] `required_history` property returns 200 by default
- [ ] `on_position_closed()` is a no-op by default
- [ ] `entry_price()` and `stop_loss_price()` accept `(bar, indicators)` signature

**Implementation**: `backend/app/strategy/base.py`
- [ ] `Strategy` ABC with all methods per design above
- [ ] Google-style docstrings

---

### Phase 3D: VelezStrategy (~40 min)

**Tests**: `backend/tests/unit/test_velez_strategy.py`

_Signal detection (should_long):_
- [ ] Returns False when not warm (bar_count < 200)
- [ ] Returns False when indicators are None
- [ ] Returns False when SMAs not tight (spread > threshold%)
- [ ] Returns False when SMAs tight but not diverging (gap not widening)
- [ ] Returns False when diverging but SMA-20 below SMA-200
- [ ] Returns False when setup valid but candle is red (close <= open)
- [ ] Returns False when setup valid but candle not strong (body_pct < threshold)
- [ ] Returns True when ALL conditions met: warm + tight + diverging + green + strong
- [ ] Boundary test: spread exactly at threshold → False (exclusive)
- [ ] Zero-range candle (high == low) → not strong → False
- [ ] Zero-price bar (close == 0) → False (division-by-zero guard)

_Entry and stop prices:_
- [ ] `entry_price(bar, indicators)` returns `bar.high` (buy-stop level)
- [ ] `stop_loss_price(bar, indicators)` returns `bar.low - max(bar.low * stop_buffer_pct/100, stop_buffer_min)`
- [ ] Stop buffer percentage vs minimum: larger of the two is used
- [ ] Decimal precision maintained

_Buy-stop expiry:_
- [ ] `should_cancel_pending(bar, 0)` → False (just placed)
- [ ] `should_cancel_pending(bar, 1)` → True (default expiry is 1 candle)
- [ ] Configurable: with `buy_stop_expiry_candles=3`, returns False for 0,1,2 and True for 3

_Trailing stop state machine (3 states, method-per-state):_
- [ ] Initial state is `WATCHING`
- [ ] `WATCHING` + red candle → `PULLING_BACK` (record low, green_count=0)
- [ ] `PULLING_BACK` + another red → update pullback low to lowest, green_count=0
- [ ] `PULLING_BACK` + 1 green candle → returns None (need 2)
- [ ] `PULLING_BACK` + 2 green candles → returns pullback low, → `TRAILING`
- [ ] `PULLING_BACK` + green then red → resets green count, need 2 fresh greens
- [ ] `TRAILING` + red candle → `WATCHING` (cycle repeats)
- [ ] Doji candle → neutral: does not advance green count, does not start pullback
- [ ] `on_position_closed()` resets to `WATCHING` with all counters cleared

_Max run rule (should_exit):_
- [ ] Returns False when no position (defensive)
- [ ] Returns False during normal trailing
- [ ] Returns True after `max_run_candles` consecutive strong candles post-trail
- [ ] Non-strong candle resets the max run counter
- [ ] Doji resets the max run counter

_Helper method tests:_
- [ ] `_is_strong_candle(bar)` — body percentage >= threshold
- [ ] `_is_strong_candle(bar)` — zero range → False
- [ ] `_is_doji(bar)` — body percentage < doji threshold
- [ ] `_body_pct(bar)` — correct calculation

**Implementation**: `backend/app/strategy/velez.py`
- [ ] `_TrailState(str, Enum)` — `WATCHING`, `PULLING_BACK`, `TRAILING`
- [ ] `VelezStrategy(Strategy)` class
- [ ] `__init__(symbol, config: VelezConfig)`
- [ ] `should_long()` — full signal detection (with mypy-safe None narrowing)
- [ ] `entry_price(bar, indicators)` — bar.high
- [ ] `stop_loss_price(bar, indicators)` — bar.low minus buffer
- [ ] `should_update_stop()` — trailing stop state machine via dispatch
- [ ] `_on_watching(bar)` — detect red candle for pullback entry
- [ ] `_on_pulling_back(bar)` — count greens, update pullback low
- [ ] `_on_trailing(bar)` — count strong run, detect next pullback
- [ ] `should_exit()` — max run rule
- [ ] `should_cancel_pending()` — configurable expiry
- [ ] `on_position_closed()` — reset `_trail_state` to `WATCHING`, clear counters
- [ ] `_is_strong_candle(bar: Bar) -> bool`
- [ ] `_is_doji(bar: Bar) -> bool`
- [ ] `_body_pct(bar: Bar) -> Decimal`
- [ ] Internal state: `_trail_state`, `_pullback_low`, `_green_count`, `_strong_run_count`

---

### Phase 3E: Package Re-exports + Verification (~10 min)

**Tasks:**
- [ ] `engine/__init__.py` re-exports: `CandleAggregator`, `IndicatorCalculator`, `IndicatorSet`
- [ ] `strategy/__init__.py` re-exports: `Strategy`, `VelezStrategy`
- [ ] `uv run pytest` — all tests pass
- [ ] `uv run mypy app/` — zero errors
- [ ] `uv run ruff check app/ tests/` — zero errors
- [ ] `uv run ruff format --check app/ tests/` — no formatting issues
- [ ] Commit

---

## Acceptance Criteria

### Functional
- [ ] `IndicatorSet` is correctly defined as frozen dataclass with 5 typed fields (lives in `indicators.py`)
- [ ] `CandleAggregator` correctly aggregates 1-min bars into 1/2/5/10-min candles
- [ ] Candles aligned to market open (9:30 ET) using `market_open()` util (DST-safe)
- [ ] 1-min pass-through works (no buffering)
- [ ] Duplicate bar timestamps are dropped
- [ ] Bars outside market hours are ignored
- [ ] `flush()` emits partial candle from buffer
- [ ] `IndicatorCalculator` correctly computes SMA-20 and SMA-200 using running sums
- [ ] Running sum SMA matches naive `sum()` calculation (correctness verified)
- [ ] SMA values match manual calculation for known price series
- [ ] Warm-up: `sma_fast=None` until 20 candles, `sma_slow=None` until 200 candles
- [ ] Previous SMA values correctly track prior candle's values
- [ ] Ring buffer auto-evicts oldest when at capacity
- [ ] `Strategy` base class is abstract (cannot instantiate directly)
- [ ] `should_short()` returns False by default
- [ ] `should_cancel_pending()` has default implementation (cancel after 1 candle)
- [ ] `on_position_closed()` is a no-op by default
- [ ] `required_history` is a `@property` returning 200
- [ ] `entry_price()` and `stop_loss_price()` accept `(bar, indicators)` signature
- [ ] VelezStrategy detects SMA convergence setup (tight + diverging + strong green candle)
- [ ] VelezStrategy handles zero-price bar (division-by-zero guard)
- [ ] VelezStrategy returns correct entry price (bar.high)
- [ ] VelezStrategy returns correct stop-loss price (bar.low minus buffer)
- [ ] Trailing stop uses 3-state machine: WATCHING → PULLING_BACK → TRAILING
- [ ] Method-per-state dispatch: `_on_watching()`, `_on_pulling_back()`, `_on_trailing()`
- [ ] Multiple consecutive red candles use lowest low for pullback
- [ ] Doji candles treated as neutral in trailing stop
- [ ] Max run rule exits after N consecutive strong candles post-trail
- [ ] Buy-stop expiry works with configurable candle count
- [ ] `on_position_closed()` resets trailing stop state to WATCHING

### Non-Functional
- [ ] All monetary values are `Decimal` (never `float`)
- [ ] SMA computation uses `Decimal` running sums (no float intermediaries, zero drift)
- [ ] No circular imports between `engine` and `strategy` modules
- [ ] No magic numbers — all thresholds come from `VelezConfig` or named constants
- [ ] Strategy state is instance-scoped (one instance per symbol)
- [ ] `_TrailState` uses `(str, Enum)` per project convention
- [ ] Shared test factories in `tests/factories.py` (not duplicated per test file)

### Quality Gates
- [ ] All tests written BEFORE implementation (TDD)
- [ ] Zero mypy errors in strict mode (None-narrowing uses individual `is None` checks)
- [ ] Zero ruff lint/format errors
- [ ] No `Optional[X]` — use `X | None` throughout
- [ ] No bare `except:` — specific exceptions only
- [ ] Google-style docstrings on all public classes and non-obvious functions

---

## Dependencies & Prerequisites

| Dependency | Status | Notes |
|-----------|--------|-------|
| `Bar` dataclass | Done (Step 2) | `app.broker.types.Bar` |
| `Position` dataclass | Done (Step 2) | `app.broker.types.Position` |
| `VelezConfig` | Done (Step 1) | `app.config.VelezConfig` |
| `VALID_CANDLE_INTERVALS` | Done (Step 1) | `app.config.VALID_CANDLE_INTERVALS` |
| `market_open()` / `market_close()` | Done (Step 1) | `app.utils.time` |
| `exchange-calendars` | Done (Step 1) | Already in dependencies |
| `collections.deque` | stdlib | No new dependencies |

**No new pip dependencies required.**

---

## Research Insights (from deepening)

### Performance (Performance Oracle)
- Naive Decimal SMA-200 summation: ~24.8μs per call. Running sum: ~0.8μs (32x speedup)
- At 5 symbols / 2-min intervals, total live computation is <0.15ms of 3-second budget — not a bottleneck
- Running sums become critical for backtest: 5-symbol 1-year backtest drops from ~6s to ~250ms
- Memory: ~144KB for 5 symbols with 2 deques each — negligible
- Decimal running sums have zero accumulated drift (unlike float)

### State Machine Patterns (Best Practices Researcher)
- Method-per-state dispatch (`_on_watching`, `_on_pulling_back`, `_on_trailing`) is cleaner than if/elif chains for 3 states
- Transition table pattern is over-engineering for 3 states (better for 5+)
- Test every edge of the state graph explicitly — there are 11 transitions total
- Hypothesis `RuleBasedStateMachine` can supplement as fuzzer (nice-to-have, not required)
- Embed state machine directly in VelezStrategy — don't extract a separate StateMachine class

### Codebase Patterns (Pattern Recognition Specialist)
- Every file starts with `from __future__ import annotations`
- Module-level `logger = structlog.get_logger()`
- Test helper functions use underscore prefix: `_make_bar()`, `_make_api_error()`
- Test classes grouped by concept, not by method
- Import ordering: stdlib → third-party → local (one per line for multi-imports)
- `frozen=True` for value objects, mutable for state objects

### Code Simplicity (Code Simplicity Reviewer)
- Merging `engine/types.py` into `engine/indicators.py` saves 1 file + 1 test file
- Removing `reset()` from both classes saves ~6 lines + 2 test cases. Fresh instances are the correct pattern.
- Removing `hyperparameters: ClassVar` saves ~3 lines. YAGNI — no per-symbol config in Phase 1.
- 3-state machine (merging PULLBACK + COUNTING_GREENS) reduces state space while preserving all behavior

---

## References

### Internal
- Phase 1 Plan — Candle Aggregation: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md:462-483`
- Phase 1 Plan — Indicator System: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md:433-459`
- Phase 1 Plan — Strategy Base Class: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md:737-777`
- Brainstorm — Velez Strategy: `docs/brainstorms/2026-02-13-algo-trader-brainstorm.md:107-136`
- Bar dataclass: `backend/app/broker/types.py:76-86`
- VelezConfig: `backend/app/config.py:61-100`
- Market time utils: `backend/app/utils/time.py`

### Institutional Learnings
- Threading bridge pattern: `docs/solutions/integration-issues/alpaca-py-async-threading-bridge.md`
- Decimal conversion: `docs/solutions/test-failures/alpaca-py-replace-order-qty-type.md`
- Ruff UP042 suppression: `docs/solutions/build-errors/ruff-up042-str-enum-convention.md`

### Test Patterns (from Step 2)
- `_make_bar()` helper: `backend/tests/unit/test_fake_adapters.py`
- Protocol satisfaction tests: `backend/tests/unit/test_broker_protocols.py`
- TDD docstring convention: `backend/tests/unit/test_broker_types.py`
