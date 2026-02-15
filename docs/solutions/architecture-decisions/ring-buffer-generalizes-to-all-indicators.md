---
title: "Ring Buffer Pattern Generalizes to All Sliding-Window Indicators"
category: architecture-decisions
tags: [indicators, ring-buffer, deque, performance, streaming]
module: Engine
symptom: "Ring buffer only used for SMA — unclear if pattern extends"
root_cause: "Pattern is general but only one implementation exists"
date: 2026-02-15
context: "Architecture review — indicator extensibility discussion"
---

# Ring Buffer Pattern Generalizes to All Sliding-Window Indicators

## Current Implementation

`IndicatorCalculator` uses `deque(maxlen=period)` with running sums for O(1) SMA:
- Append new value → deque auto-evicts oldest
- Running sum: subtract evicted, add new, divide by period
- Zero accumulated drift (when using Decimal; negligible with float)

## Generalization

The deque + running computation pattern works for ANY sliding-window indicator:

| Indicator | Window Operation | Ring Buffer Approach |
|-----------|-----------------|---------------------|
| **SMA** | sum / period | Running sum, subtract evicted, add new |
| **EMA** | weighted average | No buffer needed (single prev value), but deque useful for initialization |
| **ATR** | average of True Range | Deque of TR values + running sum |
| **RSI** | avg gain / avg loss | Two running sums (gains, losses) over period |
| **Bollinger Bands** | SMA + k * stddev | Running sum + running sum-of-squares |
| **VWAP** | cumulative(price*vol) / cumulative(vol) | Two running sums (session-reset daily) |
| **Stochastic** | (close - low_n) / (high_n - low_n) | Deque tracking min/max over window |

## Implementation Pattern

Each indicator type implements a common interface:
1. `update(value)` — feed new candle data
2. `value` — current indicator result (or None if not warm)
3. Internal state: deque + running computation variables

The engine creates one instance per (indicator_type, period) declared by a strategy. Multiple strategies sharing the same indicator spec can share the instance.

## Key Insight

The ring buffer is NOT the candle aggregator. It's the indicator computation layer. When refactoring for extensibility, each indicator type becomes a class with:
- Its own deque(s) and running state
- An `update()` method with O(1) computation
- A `value` property returning the current result

## Performance Note

With float (not Decimal), each indicator update is a few arithmetic operations. Even with 20 indicators across 10 symbols, the per-candle cost is microseconds. This is not a bottleneck.
