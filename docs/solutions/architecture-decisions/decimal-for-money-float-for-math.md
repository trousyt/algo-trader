---
title: "Decimal for Money, Float for Indicator Math"
category: architecture-decisions
tags: [decimal, float, indicators, performance, precision]
module: Engine
symptom: "IndicatorCalculator uses Decimal for SMA computation — unnecessary precision for signal detection"
root_cause: "Conflation of monetary precision requirements with mathematical computation requirements"
date: 2026-02-15
context: "Architecture review comparing algo-trader vs freqtrade vs Jesse"
---

# Decimal for Money, Float for Indicator Math

## Problem

The IndicatorCalculator uses `Decimal` for all SMA computation (ring buffers, running sums). While this gives zero accumulated drift, it's ~10-100x slower than numpy/float — and neither freqtrade nor Jesse uses Decimal for indicators.

The question: is this precision necessary?

## Analysis

| Domain | Needs Decimal? | Reasoning |
|--------|---------------|-----------|
| Order prices (entry, stop) | **Yes** | Submitting real prices to broker. Pennies matter. |
| Position sizing (shares, dollar risk) | **Yes** | Wrong rounding = wrong position size |
| P&L accounting | **Yes** | Regulatory reporting, tax basis |
| Indicator computation (SMA, RSI, ATR) | **No** | Signal is "above or below" — nanodollar drift doesn't flip signals |
| Charting / UI display | **No** | Visual display doesn't need arbitrary precision |
| Backtesting metrics (Sharpe, drawdown) | **No** | Statistical measures, not money |

Freqtrade and Jesse use float for indicators because **indicator math isn't money math**. They're correct. The precision boundary is where computation crosses into money: order prices, position sizes, P&L.

## Decision

- **Indicators**: Use `float` (or numpy when vectorized). Performance matters for backtesting.
- **Money**: Use `Decimal` — order prices, position sizes, P&L, risk calculations.
- **Boundary**: The strategy returns `Decimal` for `entry_price()` and `stop_loss_price()`. Indicators feed into signal detection (bool), not directly into prices.

## Impact

- IndicatorCalculator should be refactored to use float when indicator extensibility is implemented
- Ring buffer pattern (deque + running sum) works identically with float
- Backtesting over years of 1-min data becomes feasible without Decimal overhead
- Bar.close etc. remain Decimal (they're prices), but indicator functions receive float conversions

## Prevention

When adding new indicators, use float for computation. Only convert to Decimal at the money boundary (position sizing, order submission).
