---
title: "Alpaca SDK Integration Bugs: Latent Issues Found by Real API Tests"
category: integration-issues
tags: [alpaca-py, broker-integration, integration-testing, mock-drift, BarSet, DataFeed, stream-lifecycle]
module: broker_adapter
symptom: "All 8 integration tests fail against live Alpaca API; config field undefined; stream crashes; historical bars return empty; unit tests pass but integration tests expose runtime bugs"
root_cause: "Unit tests with mocks hide alpaca-py SDK contract violations; code assumed strings where enums required; query params assumed optional that are required; Pydantic model treated as dict; stream lifecycle not defensive"
date: 2026-02-15
pr: "https://github.com/trousyt/algo-trader/pull/4"
---

# Alpaca SDK Integration Bugs

## Problem

Five latent bugs in the Alpaca broker adapter were hidden by unit test mocks and only discovered when running integration tests against the real paper trading API. All 8 integration tests failed on first run.

## Root Cause

**Mock-vs-reality drift.** Unit test mocks returned convenient Python types (plain dicts, bare strings) that didn't match the actual alpaca-py SDK response shapes (Pydantic models, enum parameters). The mocks "worked" but hid real SDK contract requirements.

## Bug 1: Config Field Name Mismatch

**Symptom**: `AttributeError: object has no attribute 'data_feed'`

`BrokerConfig` defines `feed: str = "iex"` but data provider referenced `self._config.data_feed`.

```python
# Before (broken)
feed=self._config.data_feed

# After (fixed)
feed=DataFeed(self._config.feed)
```

## Bug 2: DataFeed Enum Required

**Symptom**: `StockDataStream` rejects or misinterprets plain string `"iex"`.

The SDK constructor expects `DataFeed` enum, not a string.

```python
from alpaca.data.enums import DataFeed

# Convert string config to enum
feed=DataFeed(self._config.feed)  # "iex" -> DataFeed.IEX
```

**Pattern**: When alpaca-py expects an enum, always construct explicitly from the string value.

## Bug 3: `StockBarsRequest` Requires `start` Date

**Symptom**: `get_stock_bars()` returns empty `BarSet` with no error.

alpaca-py requires a `start` datetime. `limit` alone silently returns nothing.

```python
# Before (empty result)
request = StockBarsRequest(
    symbol_or_symbols=symbol,     # Also wrong: should be list
    timeframe=tf,
    limit=count,
)

# After (works)
_LOOKBACK_DAYS = {"1Min": 1, "5Min": 1, "15Min": 1, "1Hour": 2, "1Day": 3}

lookback_days = _LOOKBACK_DAYS.get(timeframe, 30)
start = datetime.now(tz=UTC) - timedelta(days=max(lookback_days * count, 7))

request = StockBarsRequest(
    symbol_or_symbols=[symbol],   # Must be a list
    timeframe=tf,
    start=start,
    limit=count,
)
```

Also: `symbol_or_symbols` must be a list even for single symbols — bare strings get iterated character-by-character.

## Bug 4: `BarSet.data` Access Pattern

**Symptom**: `AttributeError: 'BarSet' object has no attribute 'get'`

The response is a `BarSet` Pydantic model, not a plain dict. Access via `.data`:

```python
# Before (broken)
alpaca_bars = response.get(symbol, [])

# After (correct)
alpaca_bars = response.data.get(symbol, [])
```

**Pattern**: alpaca-py wraps REST responses in typed Pydantic objects. Always use `.data` to access the underlying dict.

## Bug 5: Stream `stop()` Guard

**Symptom**: `AttributeError: 'NoneType' object has no attribute 'is_running'` during `disconnect()`.

Both `StockDataStream` and `TradingStream` set `_loop` only when `.run()` is called. Calling `.stop()` on a never-started stream crashes.

```python
# Before (crashes)
if self._stream is not None:
    self._stream.stop()

# After (safe)
if self._stream is not None and getattr(self._stream, "_loop", None):
    self._stream.stop()
```

Applied in both `data.py` and `broker.py`.

## Unit Test Fix

Mock return value must match real SDK shape:

```python
# Before (plain dict — hides Bug 4)
mock_client.get_stock_bars.return_value = {"AAPL": [mock_bar]}

# After (matches BarSet shape)
mock_client.get_stock_bars.return_value = SimpleNamespace(
    data={"AAPL": [mock_bar]},
)
```

## Prevention Strategies

1. **Match mock shapes to real SDK responses** — use `SimpleNamespace(data=...)` not plain dicts
2. **Run integration tests against real API regularly** — unit mocks catch logic bugs, integration tests catch SDK contract bugs
3. **Type-check SDK parameters** — wrap string config values in SDK enums at the adapter boundary
4. **Guard all stream lifecycle methods** — check internal state before calling `stop()`, `close()`, etc.
5. **Always provide required parameters** — alpaca-py silently returns empty on missing `start` date; read SDK docs for each endpoint
6. **Use list for `symbol_or_symbols`** — even for single symbols, always wrap in `[symbol]`

## Key Takeaway

Unit tests with mocks test YOUR logic. Integration tests test the SDK CONTRACT. Both are needed. A green unit test suite with no integration tests is a false sense of security.

## Cross-References

- Alpaca Threading Bridge: `docs/solutions/integration-issues/alpaca-py-async-threading-bridge.md`
- Alpaca API Error Mocking: `docs/solutions/integration-issues/alpaca-py-api-error-mocking.md`
- Alpaca Replace Order Qty: `docs/solutions/test-failures/alpaca-py-replace-order-qty-type.md`
- Step 2 Plan: `docs/plans/2026-02-14-feat-step2-broker-abstraction-alpaca-plan.md`
- PR #4: https://github.com/trousyt/algo-trader/pull/4
