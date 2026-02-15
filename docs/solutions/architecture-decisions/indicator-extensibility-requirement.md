---
title: "Indicator System Must Be Extensible From the Start"
category: architecture-decisions
tags: [indicators, strategy, extensibility, architecture]
module: Engine
symptom: "IndicatorCalculator hardcoded for SMA-20/200 only — adding ATR/RSI requires modifying engine"
root_cause: "Centralized indicator computation with fixed IndicatorSet dataclass"
date: 2026-02-15
context: "Architecture review comparing algo-trader vs freqtrade vs Jesse"
---

# Indicator System Must Be Extensible From the Start

## Problem

Current `IndicatorCalculator` is hardcoded:
- Only computes SMA-20 and SMA-200
- Returns fixed `IndicatorSet(sma_fast, sma_slow, prev_sma_fast, prev_sma_slow, bar_count)`
- Adding any new indicator requires modifying both IndicatorCalculator AND IndicatorSet
- Strategy has no control over what indicators it receives

Both reviewers flagged this. User mandated: **MUST be extensible from the start, not a retrofit.**

## How Other Frameworks Solve This

**Jesse** — Strategy owns its indicators via `@property`:
```python
@property
def slow_sma(self):
    return ta.sma(self.candles, 200)
```
- Pro: Maximum flexibility, zero engine changes per strategy
- Con: No caching unless strategy manages it; recomputes on each access

**Freqtrade** — Strategy populates a DataFrame:
```python
def populate_indicators(self, dataframe):
    dataframe['sma_200'] = ta.SMA(dataframe, timeperiod=200)
    return dataframe
```
- Pro: Vectorized, flexible
- Con: DataFrame-centric, batch-oriented (not streaming-friendly)

## Chosen Approach: Declaration Pattern (B/C Hybrid)

Strategy declares what indicators it needs. Engine provisions the right calculators.

```
Strategy declares: indicators = [SMA(20), SMA(200), ATR(14), RSI(14)]
Engine creates: one ring-buffer calculator per declared indicator
Engine computes: only what the strategy requested
Engine passes: results as a dict/namespace to strategy methods
```

### Why This Approach

1. **Ring buffer pattern generalizes** — deque + running value works for any sliding-window indicator (SMA, EMA, ATR, Bollinger Bands, RSI). Each type just needs its own update formula.
2. **O(1) per candle** — streaming-friendly for live trading
3. **Strategy controls what it needs** — no engine changes to add indicators
4. **Engine manages lifecycle** — warmup, caching, computation timing
5. **Float for math** — indicators use float (see decimal-for-money-float-for-math.md)

### What Must Change

- `IndicatorSet` frozen dataclass → flexible dict/namespace keyed by indicator name
- `IndicatorCalculator` single class → registry of indicator implementations
- Strategy ABC gets a declaration mechanism (class attribute or method)
- Engine reads declarations, provisions calculators per route

## Timeline

Must be designed into the TradingEngine (Step 4/5). Cannot be retrofitted without rewriting the engine's candle processing loop.

## Related

- [Decimal for Money, Float for Math](./decimal-for-money-float-for-math.md)
- [Jesse Routes vs Freqtrade Bots](./jesse-routes-vs-freqtrade-bots.md)
