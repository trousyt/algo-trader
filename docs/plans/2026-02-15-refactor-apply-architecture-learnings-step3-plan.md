---
title: "Apply Architecture Learnings to Step 3"
type: refactor
date: 2026-02-15
reviewed: 2026-02-15
---

# Apply Architecture Learnings to Step 3

## Context

After Step 3 completion, we compared algo-trader against freqtrade and Jesse and made three key architecture decisions (documented in `docs/solutions/architecture-decisions/`):

1. **Decimal for money, float for math** — indicators use float, not Decimal
2. **Indicator extensibility** — strategies declare needed indicators, engine provisions them
3. **Ring buffer generalizes** — each indicator type should be its own class with `update()`/`value`

This refactor applies decisions 1 and 3 to existing Step 3 code. Decision 2 (`required_indicators` on Strategy ABC) is deferred to Step 4 when TradingEngine exists to consume it. We use plain `float` (not numpy) — ring buffer streaming is single-value ops where float is faster and simpler.

---

## Summary of Changes

| # | Change | Files |
|---|--------|-------|
| 1 | Extract `SMA` ring-buffer class | `indicators.py`, `__init__.py` |
| 2 | Convert `IndicatorSet` to float | `indicators.py` |
| 3 | Refactor `IndicatorCalculator` to use `SMA` | `indicators.py` |
| 4 | VelezStrategy: float signal detection | `velez.py` |
| 5 | VelezConfig: signal thresholds → float | `config.py` |
| 6 | Update all tests + new SMA tests | `test_indicators.py`, `test_sma.py` (new), `test_velez_strategy.py` |
| 7 | Commit architecture decision docs | `docs/solutions/architecture-decisions/` (4 files) |

---

## Detailed Changes

### 1. Extract `SMA` ring-buffer class

**File**: `backend/app/engine/indicators.py`

Extract SMA computation from `IndicatorCalculator` into a standalone reusable class. This is the building block Step 4 will use to provision indicators per strategy declaration.

```python
class SMA:
    """Simple Moving Average via ring buffer with running sum. O(1) per update.

    Note: Running-sum approach may accumulate negligible float drift over very
    long series (100K+ updates). Acceptable for signal detection; add periodic
    re-sum if needed for backtesting precision.
    """

    __slots__ = ("_period", "_buf", "_sum")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"SMA period must be >= 1, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._sum: float = 0.0

    def update(self, value: float) -> None:
        """Add a value. Evicts oldest if at capacity.

        Callers must pass float, not Decimal. The Decimal-to-float
        conversion happens at the IndicatorCalculator boundary.
        """
        if len(self._buf) == self._period:
            self._sum -= self._buf[0]
        self._buf.append(value)
        self._sum += value

    @property
    def value(self) -> float | None:
        """Current SMA, or None if not warm."""
        if len(self._buf) < self._period:
            return None
        return self._sum / self._period

    @property
    def is_warm(self) -> bool:
        return len(self._buf) >= self._period

    @property
    def count(self) -> int:
        return len(self._buf)
```

Review additions vs original plan: `__slots__`, period validation (`>= 1`), drift docstring note.

### 2. Convert `IndicatorSet` to float

**File**: `backend/app/engine/indicators.py`

```python
@dataclass(frozen=True)
class IndicatorSet:
    sma_fast: float | None = None
    sma_slow: float | None = None
    prev_sma_fast: float | None = None
    prev_sma_slow: float | None = None
    bar_count: int = 0
```

IndicatorSet will be replaced with a flexible dict/namespace in Step 4. For now keep typed fields — Velez is the only consumer.

### 3. Refactor `IndicatorCalculator` to use `SMA` instances

**File**: `backend/app/engine/indicators.py`

Replace manual deque/sum management with two `SMA` instances:

```python
class IndicatorCalculator:
    def __init__(self, fast_period: int = 20, slow_period: int = 200) -> None:
        self._fast = SMA(fast_period)
        self._slow = SMA(slow_period)

    def process_candle(self, candle: Bar) -> IndicatorSet:
        close = float(candle.close)  # Decimal → float at boundary
        # TODO(step4): Consider input validation (finite check) when data pipeline matures
        prev_fast = self._fast.value
        prev_slow = self._slow.value
        self._fast.update(close)
        self._slow.update(close)
        return IndicatorSet(
            sma_fast=self._fast.value,
            sma_slow=self._slow.value,
            prev_sma_fast=prev_fast,
            prev_sma_slow=prev_slow,
            bar_count=self._slow.count,
        )

    @property
    def bar_count(self) -> int:
        return self._slow.count

    @property
    def is_warm(self) -> bool:
        return self._slow.is_warm
```

### 4. Update VelezStrategy

**File**: `backend/app/strategy/velez.py`

**Signal detection (`should_long()`)** — convert to float for indicator comparisons:

```python
# Before (all Decimal):
price = bar.close
spread = abs(sma_f - sma_s)
if spread / price * _HUNDRED >= self._config.tightness_threshold_pct:

# After (float for signal math):
price = float(bar.close)
spread = abs(sma_f - sma_s)  # sma_f/sma_s are now float
if spread / price * 100.0 >= self._config.tightness_threshold_pct:  # config is now float
```

**Helper methods** — `_body_pct()` returns `float`. Subtract in Decimal (exact), then convert result:

```python
def _body_pct(self, bar: Bar) -> float:
    total_range = float(bar.high - bar.low)  # Decimal subtraction first, then float
    if total_range == 0:
        return 0.0
    body = abs(float(bar.close - bar.open))  # Decimal subtraction first, then float
    return body / total_range * 100.0
```

`_is_strong_candle()` and `_is_doji()` compare float against float config thresholds.

**Money methods stay Decimal** — `entry_price()`, `stop_loss_price()` return `Decimal`. `_pullback_low` stays `Decimal`. `_HUNDRED` constant retained for `stop_loss_price` Decimal path; `100.0` literal used in float signal math.

**No `required_indicators` override** — deferred to Step 4.

### 5. VelezConfig signal fields → float

**File**: `backend/app/config.py`

Change signal-detection thresholds from `Decimal` to `float`:

```python
tightness_threshold_pct: float = Field(default=2.0, ge=0.5, le=5.0)
strong_candle_body_pct: float = Field(default=50.0, ge=30.0, le=80.0)
doji_threshold_pct: float = Field(default=10.0)
```

Keep as `Decimal` (money boundary):
- `stop_buffer_pct: Decimal` — used in `stop_loss_price()` which returns Decimal
- `stop_buffer_min: Decimal` — used in `stop_loss_price()` which returns Decimal

### 6. Update tests

**`backend/tests/unit/test_sma.py`** (NEW):
- Warmup (None until period reached)
- Correct SMA value after exact period
- Eviction (correct after buffer wraps)
- Running sum matches naive sum
- All-same-price edge case
- is_warm / count properties
- **Period = 1 degenerate case** (always returns latest value)
- **Period validation** (period < 1 raises ValueError)
- **Long-run drift test** (1000+ values, verify against naive `sum(last_n)/n` within `pytest.approx`)
- Uses `pytest.approx()` for float assertions (default rel=1e-6 tolerance)

**`backend/tests/unit/test_indicators.py`**:
- `IndicatorSet` construction: `float` values instead of `Decimal`
- `test_sma_values_are_decimal` → `test_sma_values_are_float` (isinstance check)
- SMA assertions: `pytest.approx()` for computed values
- `test_large_price_differences_no_precision_loss` → rename to `test_large_price_differences` and use `pytest.approx`
- Helper `_candle_at()` keeps `Decimal` for Bar construction (Bar prices stay Decimal)

**`backend/tests/unit/test_velez_strategy.py`**:
- `_warm_indicators()` helper: `float` values instead of `Decimal`
- Config overrides for signal thresholds: `float` instead of `Decimal`
- `_body_pct` test: now returns `float`, use `pytest.approx(50.0)`
- Stop price tests stay `Decimal` (money)

### 7. Commit architecture decision docs

The 4 files in `docs/solutions/architecture-decisions/` are currently untracked. Commit them as part of this work.

---

## Files Modified

| File | Action | Nature of Change |
|------|--------|-----------------|
| `backend/app/engine/indicators.py` | Edit | Extract SMA class, convert to float |
| `backend/app/strategy/velez.py` | Edit | Float signal detection, float helpers |
| `backend/app/config.py` | Edit | Signal threshold fields → float |
| `backend/app/engine/__init__.py` | Edit | Export `SMA` |
| `backend/tests/unit/test_sma.py` | **New** | SMA class unit tests |
| `backend/tests/unit/test_indicators.py` | Edit | Float assertions, pytest.approx |
| `backend/tests/unit/test_velez_strategy.py` | Edit | Float indicator values, float config thresholds |
| `docs/solutions/architecture-decisions/*.md` | Commit | 4 existing untracked files |

## Deferred to Step 4 (TradingEngine)

- **`required_indicators` on Strategy ABC** — Add when TradingEngine exists to consume it. Use `NamedTuple` (`IndicatorSpec(type_name, period)`) instead of bare tuple. VelezStrategy override at that time.
- **`Indicator` ABC/Protocol** — Formalize `update`/`value`/`is_warm` interface when adding second indicator type
- Full indicator registry/provisioning system
- Dict/namespace-based indicator results replacing IndicatorSet
- Multi-strategy indicator sharing
- Additional indicator types (EMA, ATR, RSI, etc.)
- numpy vectorized computation (backtesting optimization)

## Verification

1. `cd backend && python -m pytest tests/ -v` — all tests pass (311+ existing + new SMA tests)
2. `cd backend && python -m mypy app/ --strict` — clean
3. `cd backend && python -m ruff check app/ tests/` — clean
4. `cd backend && python -m ruff format --check app/ tests/` — clean
5. New SMA tests cover: warmup, eviction, precision, edge cases, period=1, validation, long-run drift
6. Existing IndicatorCalculator tests pass with float precision
7. VelezStrategy signal tests pass with float indicator math
8. Stop price / entry price tests still use exact Decimal equality (money)
