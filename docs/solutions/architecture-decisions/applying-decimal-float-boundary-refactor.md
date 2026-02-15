---
title: "Applying the Decimal/Float Boundary: Refactoring Patterns and Gotchas"
category: architecture-decisions
tags: [decimal, float, refactoring, indicators, boundary-pattern, testing, pytest-approx, yagni]
module: engine.indicators, strategy.velez, config
symptom: "IndicatorCalculator performed all SMA computation using Decimal, incurring 10-100x performance penalty for signal detection math"
root_cause: "Initial implementation applied Decimal uniformly without distinguishing money concerns from math concerns"
date: 2026-02-15
context: "Step 3 strategy engine refactor — applying architecture decision to existing code. 327 tests passing after refactor."
related:
  - docs/solutions/architecture-decisions/decimal-for-money-float-for-math.md
  - docs/solutions/architecture-decisions/ring-buffer-generalizes-to-all-indicators.md
  - docs/plans/2026-02-15-refactor-apply-architecture-learnings-step3-plan.md
---

# Applying the Decimal/Float Boundary: Refactoring Patterns and Gotchas

## Problem

After deciding on "Decimal for money, float for math" (see `decimal-for-money-float-for-math.md`), the existing Step 3 code needed refactoring. The challenge wasn't the decision itself — it was applying it cleanly across indicators, strategy, config, and tests without introducing bugs.

## Solution

Seven changes applied in TDD order (tests first, then implementation):

1. **Extract SMA as standalone class** — `__slots__`, period validation, drift docstring
2. **Convert IndicatorSet fields** — `Decimal | None` to `float | None`
3. **Refactor IndicatorCalculator** — compose SMA instances, `float(candle.close)` at boundary
4. **VelezStrategy signal math** — float for comparisons, Decimal for entry/stop prices
5. **VelezConfig thresholds** — signal fields to float, money fields stay Decimal
6. **Migrate all tests** — pytest.approx for float, exact equality for money
7. **Commit architecture decision docs**

## Gotchas and Pitfalls

### 1. Decimal Subtraction First, Then Convert

```python
# WRONG — converts each operand separately, loses Decimal precision benefit
total_range = float(bar.high) - float(bar.low)

# RIGHT — Decimal subtraction (exact), then convert result
total_range = float(bar.high - bar.low)
```

This matters when prices are close together. Decimal subtraction is exact; converting the result preserves that precision.

### 2. pytest.approx for Float, Exact for Money

```python
# Float indicator — use approx (default rel=1e-6)
assert result.sma_fast == pytest.approx(10.5)

# Decimal money — exact equality
assert strategy.entry_price(bar, indicators) == Decimal("155.50")
```

### 3. Type Assertion Tests Need Splitting

A single test asserting Decimal on all config fields breaks when some become float:

```python
# Before (fails after refactor):
def test_velez_fields_are_decimal():
    assert isinstance(config.tightness_threshold_pct, Decimal)  # NOW FLOAT

# After (split by concern):
def test_velez_signal_fields_are_float():
    assert isinstance(config.tightness_threshold_pct, float)

def test_velez_money_fields_are_decimal():
    assert isinstance(config.stop_buffer_pct, Decimal)
```

### 4. Float Literal vs Decimal Constant

Use `100.0` in float signal math, keep `_HUNDRED = Decimal("100")` for Decimal money math:

```python
# Signal detection (float)
spread / price * 100.0

# Stop loss calculation (Decimal)
low * self._config.stop_buffer_pct / _HUNDRED
```

### 5. Ruff Requires Sorted __slots__

```python
# Triggers RUF023
__slots__ = ("_period", "_buf", "_sum")

# Fixed (alphabetical)
__slots__ = ("_buf", "_period", "_sum")
```

## Decision Framework: "Is This Money or Math?"

| If the value... | Use | Example |
|-----------------|-----|---------|
| Represents price, qty, P&L, cash | Decimal | `bar.close`, `order.qty` |
| Feeds indicator/signal calculation | float | `sma_fast`, `body_pct` |
| Gets sent to broker API | Decimal | `entry_price()` return |
| Is a config threshold for signals | float | `tightness_threshold_pct` |
| Is a config value for money math | Decimal | `stop_buffer_pct` |

**Boundary placement**: Convert Decimal to float at `IndicatorCalculator.process_candle()` — the earliest point where monetary precision is no longer needed.

## YAGNI Decision Process

Three review agents disagreed on refactor scope:

- **architecture-strategist**: SMA extraction generalizes to EMA/ATR/RSI — keep it
- **kieran-python-reviewer**: Add `__slots__`, validation, drift tests — enhance it
- **code-simplicity-reviewer**: Defer both SMA extraction AND `required_indicators` — YAGNI

**Resolution**: Middle ground. Keep SMA extraction (useful building block, validated by architecture reviewer). Defer `required_indicators` (nothing consumes it yet, clear YAGNI). Incorporate Python reviewer's `__slots__`/validation/drift suggestions.

**Takeaway**: When review agents conflict, present the tension to the decision-maker with each agent's reasoning. Don't default to the most conservative or most ambitious position.

## Prevention

When adding new code to this project:

1. **New indicators**: Use float internally. Accept float in `update()`. Return float from `value`.
2. **New strategy methods**: Signal detection uses float indicators. Money methods (`entry_price`, `stop_loss_price`) return Decimal.
3. **New config fields**: Signal thresholds = float. Money buffers/limits = Decimal.
4. **New tests**: `pytest.approx()` for computed float values. Exact equality for Decimal money.
5. **Bar field access in helpers**: Subtract in Decimal first, convert result: `float(bar.high - bar.low)`.

## Cross-References

- **Decision rationale**: `docs/solutions/architecture-decisions/decimal-for-money-float-for-math.md`
- **Ring buffer pattern**: `docs/solutions/architecture-decisions/ring-buffer-generalizes-to-all-indicators.md`
- **Indicator extensibility**: `docs/solutions/architecture-decisions/indicator-extensibility-requirement.md`
- **Implementation plan**: `docs/plans/2026-02-15-refactor-apply-architecture-learnings-step3-plan.md`
- **PR**: #2 on `feat/step3-strategy-engine` branch
