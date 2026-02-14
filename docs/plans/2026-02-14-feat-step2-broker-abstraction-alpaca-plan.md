---
title: "Step 2: Broker Abstraction + Alpaca Integration"
type: feat
date: 2026-02-14
deepened: 2026-02-14
parent: docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md
review: architecture-strategist
---

## Enhancement Summary

**Deepened on:** 2026-02-14
**Research agents used:** architecture-strategist, security-sentinel, performance-oracle, kieran-python-reviewer, code-simplicity-reviewer, pattern-recognition-specialist, best-practices-researcher (x2), framework-docs-researcher, git-history-analyzer, Context7 (alpaca-py SDK docs)

### Key Improvements
1. **CRITICAL BUG FIX**: `call_soon_threadsafe(queue.put_nowait)` raises unhandled `QueueFull` on bounded queue — must use wrapper function (D1 amended)
2. **CRITICAL**: Trade update queue must NOT use drop-oldest — dropped fill events desync the order state machine (D8 amended)
3. **HIGH**: `disconnect()` must have timeout on `thread.join()` to prevent blocking the event loop indefinitely (D3 amended)
4. **OrderRequest/BracketOrderRequest should be frozen** — they are value objects per CLAUDE.md conventions (Phase 2A amended)
5. **Auth validation in connect()** — make a lightweight `get_account()` call to fail fast on invalid credentials (D14 amended)
6. **Lifecycle lock** — `asyncio.Lock` on connect/disconnect prevents race conditions (D3 amended)
7. Added 12 new tests across phases for newly identified edge cases
8. SDK callback signatures confirmed via Context7 alpaca-py documentation

### New Risks Discovered
- `call_soon_threadsafe` + bounded queue = silent item loss (was high risk, now mitigated)
- Concurrent connect() calls can create duplicate SDK clients and threads
- `disconnect()` during in-flight REST calls needs `shutdown(wait=True, cancel_futures=True)`
- `threading.Event` more idiomatic than bare `bool` for `_connected` state

---

# Step 2: Broker Abstraction + Alpaca Integration

## Overview

Build the broker abstraction layer (domain types, protocols) and Alpaca implementation (data streaming, order execution). This step creates the boundary between our trading engine and the brokerage — all Alpaca-specific code lives behind clean async Protocol interfaces, enabling future broker additions (IBKR, Tradier) without touching engine logic.

## Problem Statement

Step 1 built the foundation (config, models, logging, calendar, CLI). The trading engine cannot function without: (1) domain types that all subsystems share (Bar, Quote, Position, OrderRequest, etc.), (2) abstract protocols defining what a "data provider" and "broker" must do, and (3) a concrete Alpaca implementation bridging the alpaca-py SDK (which is sync REST + blocking WebSocket) to our async architecture.

## Design Decisions (Gap Resolution)

These decisions resolve gaps identified during SpecFlow analysis.

### D1: Event Loop Bridge — `call_soon_threadsafe` ⚠️ AMENDED
**Decision**: Use Option B from SpecFlow Q1. Store a reference to the main asyncio event loop in `connect()`. In the alpaca-py WebSocket callback (which runs in the SDK's own event loop in a background thread), use `main_loop.call_soon_threadsafe(self._enqueue_bar, converted_bar)` to push items into an `asyncio.Queue` on the main loop. No extra dependencies needed.

**Research Insight — CRITICAL BUG FIX**: The original plan called `call_soon_threadsafe(queue.put_nowait, item)`. This is unsafe with a bounded queue because `put_nowait` raises `asyncio.QueueFull` when the queue is at capacity. Since `call_soon_threadsafe` schedules the callable on the main event loop, the exception surfaces as an **unhandled exception in the event loop's exception handler** — the item is silently lost with no logging, and the `_enqueue_or_drop()` helper from D8 never runs.

**Fix**: Schedule a wrapper method instead of raw `put_nowait`:
```python
def _enqueue_bar(self, bar: Bar) -> None:
    """Called via call_soon_threadsafe from the WS callback thread."""
    if self._bar_queue.full():
        try:
            self._bar_queue.get_nowait()  # Drop oldest
        except asyncio.QueueEmpty:
            pass
        logger.warning("Bar queue full, dropped oldest item", symbol=bar.symbol)
    self._bar_queue.put_nowait(bar)

# In the WS callback:
main_loop.call_soon_threadsafe(self._enqueue_bar, converted_bar)
```

**SDK confirmation** (Context7): alpaca-py `StockDataStream` callbacks are `async def` handlers that run inside the SDK's own event loop in a background thread. The `run()` method is indeed blocking. The callback signature is `async def handle_bar(bar)` where `bar` has `.symbol`, `.open`, `.high`, `.low`, `.close`, `.volume`, `.timestamp` attributes.

### D2: Thread Death Detection
**Decision**: Each WebSocket thread sets a `threading.Event` (`_stream_error`) when it exits unexpectedly. The `AsyncIterator` checks this event when the queue is empty. If set, it raises `BrokerConnectionError`. The Task Supervisor (Step 5+) catches this and restarts. The SDK's built-in WebSocket reconnect handles transient disconnects — thread death means something truly unrecoverable happened.

### D3: Connection State Validation ⚠️ AMENDED
**Decision**: Adapters track state via `threading.Event` (not bare `bool`). Methods that require a connection raise `BrokerNotConnectedError("Not connected. Call connect() first.")` if `_connected_event` is not set. `connect()` when already connected is a no-op with a warning log. `disconnect()` when already disconnected is a no-op.

**Research Insight — Lifecycle Lock**: Add `asyncio.Lock` to `connect()` and `disconnect()` to prevent concurrent lifecycle mutations. Without this, two concurrent `connect()` calls could both see `_connected == False` and both create SDK clients and start WebSocket threads.

```python
self._lifecycle_lock = asyncio.Lock()
self._connected_event = threading.Event()

async def connect(self) -> None:
    async with self._lifecycle_lock:
        if self._connected_event.is_set():
            logger.warning("Already connected")
            return
        # ... create clients, start threads ...
        self._connected_event.set()
```

**Research Insight — Disconnect Timeout**: `disconnect()` must use a timeout on `thread.join()` to prevent blocking the event loop indefinitely. If `stop()` fails to break the SDK's internal loop, `join()` blocks forever. Use `run_in_executor` with a timeout:

```python
async def disconnect(self) -> None:
    async with self._lifecycle_lock:
        if not self._connected_event.is_set():
            return
        self._stream.stop()
        # Join with timeout in executor to avoid blocking event loop
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._ws_thread.join, 5.0
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.critical("WebSocket thread did not terminate", thread=self._ws_thread.name)
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._connected_event.clear()
```

**Research Insight — `threading.Event` consistency**: Using `threading.Event` for `_connected` creates a consistent pattern with `_stream_error` (D2). While bare `bool` is safe on CPython due to GIL, `threading.Event` is more idiomatic and provides explicit memory barrier semantics.

### D4: Add `replace_order` to BrokerAdapter
**Decision**: Yes. Cancel-and-resubmit creates an unacceptable window with no stop-loss protection. Add `replace_order(broker_order_id: str, qty: Decimal | None, limit_price: Decimal | None, stop_price: Decimal | None) -> OrderStatus` to the protocol. Maps to Alpaca's `PATCH /orders/{id}`.

### D5: Float-to-Decimal Conversion
**Decision**: `Decimal(str(float_value))` for all float→Decimal conversions (avoids IEEE 754 precision issues). `Decimal(str_value)` directly for string values from Alpaca. `int(float_value)` for volume. A helper `_to_decimal(value: float | str) -> Decimal` centralizes this.

### D6: Quote Type — Merge Quote + Latest Trade
**Decision**: `get_latest_quote()` calls both Alpaca's latest quote and latest trade endpoints, populating `bid`/`ask` from the quote and `last` from the trade. Both are cheap REST calls that run in the executor. Volume is set to `0` (not available from quote endpoint — daily volume comes from bars).

### D7: No Proactive Rate Limiting in Step 2
**Decision**: Rely on the SDK's built-in 429 retry (3 attempts with backoff). Log a WARNING when a 429 is encountered. Revisit if rate limits become an issue during integration testing.

### D8: Bounded Queue with Backpressure Logging ⚠️ AMENDED
**Decision**: Use **separate queue strategies** for bar data vs trade updates:

- **Bar queue**: `asyncio.Queue(maxsize=10_000)`. When full, drop the **newest** item (refuse to enqueue) and log CRITICAL. 10K items is ~2.7 hours of bars for 5 symbols at 1-min intervals.
- **Trade update queue**: `asyncio.Queue(maxsize=0)` (unbounded). Trade updates are critical state transitions — a dropped fill event means the order state machine is out of sync with the broker. The queue should never grow large (trade updates are infrequent), but if it does, that indicates a consumer bug, not a normal backpressure scenario.

**Research Insight — Drop-Oldest is Dangerous for Bars**: The original plan dropped the oldest item. For bars, this breaks time-series continuity — the candle aggregator (Step 3) needs consecutive bars to build multi-minute candles. Dropping the **newest** item preserves the existing time-series in the queue and logs CRITICAL to signal a systemic problem.

**Research Insight — Trade Updates MUST NOT Be Dropped**: A dropped fill event means our Position model doesn't know a fill happened. This creates a position mismatch with the broker — potentially leading to unhedged risk. The trade update queue should be unbounded. If it grows suspiciously large (>100 items), log CRITICAL and trigger a reconciliation cycle.

```python
# Bar queue — bounded, drop newest on full
self._bar_queue: asyncio.Queue[Bar] = asyncio.Queue(maxsize=10_000)

# Trade update queue — unbounded, never drop
self._trade_queue: asyncio.Queue[TradeUpdate] = asyncio.Queue()
```

### D9: Include Fake Adapters for Testing
**Decision**: Create `FakeDataProvider` and `FakeBrokerAdapter` in `broker/fake/`. These replay canned data for unit testing in Steps 3-6. Not full simulation — just enough to test the interfaces.

### D10: Subscription Updates via Separate Method
**Decision**: Add `update_bar_subscription(symbols: list[str]) -> None` to `DataProvider`. This calls `subscribe_bars()` / `unsubscribe_bars()` on the live SDK connection without reconnecting. Calling `subscribe_bars()` a second time raises `RuntimeError` — use `update_bar_subscription()` instead.

### D11: Async Context Manager Support
**Decision**: Both protocols support `async with`. `__aenter__` calls `connect()`, `__aexit__` calls `disconnect()`.

### D12: TradeUpdate Event Mapping
**Decision**: Create a `TradeEventType(str, Enum)` that covers all Alpaca events we care about: `NEW`, `ACCEPTED`, `FILL`, `PARTIAL_FILL`, `CANCELED`, `EXPIRED`, `REJECTED`, `REPLACED`, `PENDING_CANCEL`. Other events (`PENDING_NEW`, `PENDING_REPLACE`, `RESTATED`) are logged but filtered from the iterator — they add noise without actionable value for the order state machine.

### D13: Error Exception Hierarchy
**Decision**: Define custom exceptions in `broker/errors.py`:
```
BrokerError (base)
├── BrokerConnectionError   (connect failures, thread death, WebSocket down)
├── BrokerAuthError         (invalid/missing credentials — HTTP 401/403)
├── BrokerAPIError          (REST errors after SDK retries — 4xx/5xx)
├── BrokerTimeoutError      (request timeout)
└── BrokerNotConnectedError (method called before connect())
```
The adapter catches `APIError` from the SDK and translates to these types. `BrokerAuthError` is raised immediately on 401/403 (no retry). `BrokerAPIError` wraps the status code, message, and original exception.

### D14: Credential Validation ⚠️ AMENDED
**Decision**: `connect()` validates that `api_key` and `secret_key` are non-empty before creating SDK clients. Raises `BrokerAuthError("API key and secret key are required. Set ALGO_BROKER__API_KEY and ALGO_BROKER__SECRET_KEY.")` if empty.

**Research Insight — Validate Credentials Against API**: After creating SDK clients, `connect()` should perform a lightweight validation call (e.g., `get_account()`) to fail fast on invalid/revoked credentials. Without this, invalid credentials are only discovered when the WebSocket thread dies — which surfaces as a confusing `BrokerConnectionError` instead of a clear `BrokerAuthError`. Add to both `AlpacaDataProvider.connect()` and `AlpacaBrokerAdapter.connect()`:

```python
# After creating SDK clients, validate credentials
try:
    await self._loop.run_in_executor(self._executor, self._trading_client.get_account)
except APIError as e:
    if e.status_code in (401, 403):
        raise BrokerAuthError(f"Invalid API credentials: {e}") from e
    raise BrokerAPIError(e.status_code, str(e)) from e
```

### D15: OrderRequest Trailing Stop Fields
**Decision**: Add `trail_price: Decimal | None = None` and `trail_percent: Decimal | None = None` to `OrderRequest`. These are only used when `order_type == OrderType.TRAILING_STOP`. Validation: exactly one of `trail_price` or `trail_percent` must be set for trailing stop orders.

### D16: ThreadPoolExecutor — Per-Adapter, 4 Workers
**Decision**: Each adapter instance creates its own `ThreadPoolExecutor(max_workers=4)` in `connect()` and shuts it down in `disconnect()`. 4 workers allows concurrent REST calls (e.g., reconciliation fetches positions + orders + account in parallel) without overwhelming rate limits.

**Research Insight — Per-Adapter Is Correct**: Architecture review confirmed per-adapter executors are the right choice for 3 reasons: (1) failure isolation — slow data fetches don't starve order submission, (2) independent lifecycle management avoids coordination complexity, (3) Data API and Trading API have separate rate limits. 8 total threads is negligible overhead.

**Research Insight — Shutdown Behavior**: Use `shutdown(wait=True, cancel_futures=True)` (Python 3.9+) in `disconnect()`. This lets in-flight REST calls (e.g., order submissions) complete while canceling queued-but-not-started calls. `shutdown(wait=False)` could orphan a running order submission.

### D17: Alternative Architecture — `_run_forever()` (Rejected)

**Decision**: The alpaca-py `StockDataStream` has a private `_run_forever()` async method that could theoretically be run as an `asyncio.create_task()` on the main event loop, eliminating the thread boundary entirely. **Rejected** because `_run_forever()` is a private API (underscore prefix). Relying on it risks silent breakage on SDK upgrades. The public `run()` API with threading bridge is safer for a production trading system. Revisit if alpaca-py exposes a public async interface in the future.

---

## Technical Approach

### Architecture

```
backend/app/broker/
├── __init__.py                 # Re-exports protocols and types
├── types.py                    # Domain types: Bar, Quote, Position, OrderRequest, etc.
├── errors.py                   # BrokerError hierarchy
├── data_provider.py            # DataProvider Protocol
├── broker_adapter.py           # BrokerAdapter Protocol
├── alpaca/
│   ├── __init__.py
│   ├── data.py                 # AlpacaDataProvider (implements DataProvider)
│   ├── broker.py               # AlpacaBrokerAdapter (implements BrokerAdapter)
│   └── mappers.py              # Alpaca SDK type ↔ domain type converters
└── fake/
    ├── __init__.py
    ├── data.py                 # FakeDataProvider (for testing)
    └── broker.py               # FakeBrokerAdapter (for testing)
```

### Threading Model

```
Main Thread (asyncio event loop — FastAPI, TradingEngine, OrderManager)
│
├── Thread: StockDataStream.run()
│   └── SDK event loop → async callback → call_soon_threadsafe → asyncio.Queue (main loop)
│
├── Thread: TradingStream.run()
│   └── SDK event loop → async callback → call_soon_threadsafe → asyncio.Queue (main loop)
│
└── ThreadPoolExecutor (4 workers): REST calls
    ├── TradingClient.submit_order()
    ├── TradingClient.get_account()
    ├── StockHistoricalDataClient.get_stock_bars()
    └── ... (all sync REST calls)
```

---

## Implementation Phases

All phases follow TDD: write failing test first, then minimal code to pass, then refactor. Each phase ends with `uv run pytest` and `uv run mypy app/` passing.

### Phase 2A: Domain Types (~30 min)

**Goal**: All shared domain types used across the system — frozen dataclasses for value objects, mutable dataclasses for state objects, `(str, Enum)` for all enums.

**Test first** (`backend/tests/unit/test_broker_types.py`):
```
# Tests to write FIRST:
# 1. test_bar_is_frozen - Bar(symbol, timestamp, open, high, low, close, volume) is immutable
# 2. test_bar_decimal_fields - open, high, low, close are Decimal type
# 3. test_quote_is_frozen - Quote is immutable
# 4. test_position_is_mutable - Position fields can be updated
# 5. test_account_info_is_mutable - AccountInfo fields can be updated
# 6. test_side_enum_values - Side.LONG == "long", Side.SHORT == "short"
# 7. test_order_type_enum_values - all 5 order types present
# 8. test_time_in_force_enum_values - DAY, GTC, IOC present
# 9. test_broker_order_status_enum_values - all statuses present
# 10. test_order_request_defaults - time_in_force defaults to DAY, optional fields are None
# 11. test_bracket_order_request - entry + stop_loss_price, optional take_profit
# 12. test_trade_event_type_enum - all event types present
# 13. test_trailing_stop_fields - trail_price and trail_percent on OrderRequest
```

**Then implement** (`backend/app/broker/types.py`):
```python
# Enums: Side, OrderType, TimeInForce, BrokerOrderStatus, TradeEventType
# Frozen dataclasses: Bar, Quote, IndicatorSet, OrderRequest, BracketOrderRequest
# Mutable dataclasses: Position, AccountInfo, OrderStatus, TradeUpdate
```

#### Research Insights (Phase 2A)

**OrderRequest/BracketOrderRequest Should Be Frozen**: Per CLAUDE.md: "frozen=True for value objects." An `OrderRequest` describes a specific order intent — once created, it should not be modified. If something downstream accidentally mutates qty or price, the audit trail (order_event table) would not reflect what was actually submitted. Make both `@dataclass(frozen=True)`.

**Add test for OrderRequest immutability**:
```
# 14. test_order_request_is_frozen - OrderRequest fields cannot be mutated after creation
# 15. test_bracket_order_request_is_frozen - BracketOrderRequest is immutable
```

**Side Enum — Use BUY/SELL not LONG/SHORT**: The Alpaca SDK uses `OrderSide.BUY` and `OrderSide.SELL`, not LONG/SHORT. Our `Side` enum for orders should match: `Side.BUY = "buy"`, `Side.SELL = "sell"`. The `Position` dataclass can have a separate `side` field using the same enum. Confirm by checking alpaca-py's `OrderSide` values during implementation.

### Phase 2B: Error Hierarchy (~15 min)

**Goal**: Custom exception classes for clean error handling across the adapter boundary.

**Test first** (`backend/tests/unit/test_broker_errors.py`):
```
# Tests to write FIRST:
# 1. test_broker_error_is_base - all errors inherit from BrokerError
# 2. test_broker_api_error_status_code - BrokerAPIError stores status_code and message
# 3. test_broker_auth_error_message - includes helpful instructions about env vars
# 4. test_broker_connection_error_message - includes endpoint context
```

**Then implement** (`backend/app/broker/errors.py`):
```python
# BrokerError, BrokerConnectionError, BrokerAuthError, BrokerAPIError,
# BrokerTimeoutError, BrokerNotConnectedError
```

### Phase 2C: Protocols (~20 min)

**Goal**: `DataProvider` and `BrokerAdapter` protocols defining the async interface all broker implementations must satisfy.

**Test first** (`backend/tests/unit/test_broker_protocols.py`):
```
# Tests to write FIRST:
# 1. test_data_provider_is_protocol - DataProvider is a runtime-checkable Protocol
# 2. test_broker_adapter_is_protocol - BrokerAdapter is a runtime-checkable Protocol
# 3. test_fake_data_provider_satisfies_protocol - isinstance check passes
# 4. test_fake_broker_adapter_satisfies_protocol - isinstance check passes
# 5. test_data_provider_has_context_manager - __aenter__ and __aexit__ defined
# 6. test_broker_adapter_has_context_manager - __aenter__ and __aexit__ defined
```

**Then implement:**

`backend/app/broker/data_provider.py`:
```python
# @runtime_checkable Protocol:
# async def connect() -> None
# async def disconnect() -> None
# async def subscribe_bars(symbols: list[str]) -> AsyncIterator[Bar]
# async def update_bar_subscription(symbols: list[str]) -> None
# async def get_historical_bars(symbol: str, count: int, timeframe: str = "1Min") -> list[Bar]
# async def get_latest_quote(symbol: str) -> Quote
# async def __aenter__ / __aexit__
```

`backend/app/broker/broker_adapter.py`:
```python
# @runtime_checkable Protocol:
# async def connect() -> None
# async def disconnect() -> None
# async def submit_order(order: OrderRequest) -> OrderStatus
# async def submit_bracket_order(bracket: BracketOrderRequest) -> OrderStatus
# async def cancel_order(broker_order_id: str) -> None
# async def replace_order(broker_order_id: str, qty: Decimal | None, ...) -> OrderStatus
# async def get_order_status(broker_order_id: str) -> OrderStatus
# async def get_positions() -> list[Position]
# async def get_account() -> AccountInfo
# async def get_open_orders() -> list[OrderStatus]
# async def get_recent_orders(since_hours: int = 24) -> list[OrderStatus]
# async def subscribe_trade_updates() -> AsyncIterator[TradeUpdate]
# async def __aenter__ / __aexit__
```

#### Research Insights (Phase 2C)

**`@runtime_checkable` Protocol Limitation**: `isinstance` checks only verify method names exist — they do NOT verify return types or async signatures at runtime. The protocol tests (tests 3-4) are structural checks, not full type verification. Document this in the test file. Real type safety comes from `mypy --strict`, which the project already requires.

**`AsyncIterator` Return Type in Protocol**: `subscribe_bars` and `subscribe_trade_updates` return `AsyncIterator[T]`. This works in Protocol definitions, but the implementations will use `async def ... -> AsyncIterator[T]` with `yield`. This is correct and type-checks with mypy. The key constraint: these methods can only be called once per connection (the iterator is tied to the internal queue). Document this in the Protocol docstring.

**Add test for subscribe_bars called twice**:
```
# 7. test_subscribe_bars_called_twice_raises - second call raises RuntimeError
```

### Phase 2D: Alpaca Mappers (~25 min)

**Goal**: Pure functions that convert between Alpaca SDK types and our domain types. These are the Decimal conversion boundary.

**Test first** (`backend/tests/unit/test_alpaca_mappers.py`):
```
# Tests to write FIRST:
# 1. test_alpaca_bar_to_bar - float prices converted to Decimal via str()
# 2. test_alpaca_bar_volume_is_int - float volume converted to int
# 3. test_alpaca_bar_timestamp_preserved - UTC timestamp unchanged
# 4. test_alpaca_position_to_position - str prices converted to Decimal
# 5. test_alpaca_account_to_account_info - str equity/cash to Decimal
# 6. test_alpaca_order_to_order_status - maps all relevant fields
# 7. test_alpaca_trade_update_to_trade_update - event mapped to TradeEventType
# 8. test_alpaca_trade_update_fill_event - price and qty populated on fill
# 9. test_order_request_to_alpaca_market - maps to MarketOrderRequest
# 10. test_order_request_to_alpaca_stop - maps to StopOrderRequest with Decimal→float
# 11. test_order_request_to_alpaca_limit - maps to LimitOrderRequest
# 12. test_order_request_to_alpaca_trailing_stop - maps trail_percent/trail_price
# 13. test_bracket_request_to_alpaca - maps to OrderRequest with order_class=BRACKET
# 14. test_decimal_to_float_precision - Decimal("123.45") → 123.45 (no precision loss)
# 15. test_filtered_trade_events - PENDING_NEW, RESTATED filtered out
```

**Then implement** (`backend/app/broker/alpaca/mappers.py`):
```python
# _to_decimal(value: float | str) -> Decimal
# alpaca_bar_to_bar(alpaca_bar: alpaca.data.models.Bar) -> Bar
# alpaca_position_to_position(alpaca_pos: alpaca.trading.models.Position) -> Position
# alpaca_account_to_account_info(alpaca_acct: alpaca.trading.models.TradeAccount) -> AccountInfo
# alpaca_order_to_order_status(alpaca_order: alpaca.trading.models.Order) -> OrderStatus
# alpaca_trade_update_to_trade_update(update: alpaca.trading.models.TradeUpdate) -> TradeUpdate | None
# order_request_to_alpaca(req: OrderRequest) -> alpaca.trading.requests.*OrderRequest
# bracket_request_to_alpaca(req: BracketOrderRequest) -> alpaca.trading.requests.OrderRequest
```

#### Research Insights (Phase 2D)

**Alpaca SDK Return Types** (Context7 confirmed):
- REST responses return string values for monetary fields (position.avg_entry_price, account.equity, etc.) — use `Decimal(str_value)` directly
- WebSocket bar data returns float values for OHLC — use `Decimal(str(float_value))`
- Volume is returned as int in some contexts, float in others — always `int(value)`
- TradeUpdate has `.event` (string like "fill", "canceled"), `.order` (full Order object), `.price` (fill price, may be None), `.qty` (fill qty, may be None)

**Decimal Precision Edge Case**: `str(0.1 + 0.2)` produces `"0.30000000000000004"`, and `Decimal("0.30000000000000004")` preserves this imprecision. For prices from REST (which come as strings), this is a non-issue. For WebSocket floats, consider adding a quantization step:

```python
def _to_decimal(value: float | str) -> Decimal:
    if isinstance(value, str):
        return Decimal(value)
    return Decimal(str(value))
    # Note: quantization not needed for prices (max 2 decimal places)
    # but keep the option open if precision issues arise
```

**Add test for Alpaca SDK string vs float types**:
```
# 16. test_to_decimal_from_string - Decimal("123.45") exact
# 17. test_to_decimal_from_float - Decimal(str(123.45)) preserves value
# 18. test_to_decimal_float_edge_case - 0.1 + 0.2 handled correctly
```

**SDK Order Request Types** (Context7 confirmed): `MarketOrderRequest`, `LimitOrderRequest`, `StopOrderRequest`, `StopLimitOrderRequest`, `TrailingStopOrderRequest` all take `symbol`, `qty`, `side` (OrderSide.BUY/SELL), `time_in_force`. Price fields: `limit_price` (float), `stop_price` (float), `trail_percent` (float), `trail_price` (float). Our Decimal→float conversion uses `float(decimal_value)`.

### Phase 2E: AlpacaDataProvider (~45 min)

**Goal**: Full implementation of `DataProvider` backed by alpaca-py. WebSocket bar streaming in a background thread, REST historical bars and quotes via executor.

**Test first** (`backend/tests/unit/test_alpaca_data_provider.py`):
```
# Tests to write FIRST (all use mocked SDK clients):
# 1. test_connect_creates_clients - connect() instantiates StockHistoricalDataClient and StockDataStream
# 2. test_connect_validates_credentials - empty api_key raises BrokerAuthError
# 3. test_connect_twice_is_noop - second connect() logs warning, no error
# 4. test_disconnect_stops_stream - disconnect() calls stop() on the stream
# 5. test_disconnect_joins_thread - disconnect() joins the WebSocket thread
# 6. test_disconnect_when_not_connected - no error
# 7. test_get_historical_bars_converts_types - returns list[Bar] with Decimal prices
# 8. test_get_historical_bars_count_param - requests correct time range for count
# 9. test_get_historical_bars_not_connected - raises RuntimeError
# 10. test_get_latest_quote_converts_types - returns Quote with Decimal prices
# 11. test_subscribe_bars_yields_converted_bars - AsyncIterator yields Bar objects
# 12. test_subscribe_bars_not_connected - raises RuntimeError
# 13. test_context_manager - async with connects and disconnects
```

**Then implement** (`backend/app/broker/alpaca/data.py`):
```python
# class AlpacaDataProvider:
#   __init__(config: BrokerConfig)
#   connect(): create clients, start WS thread, store main loop ref
#   disconnect(): stop WS, join thread, shutdown executor
#   subscribe_bars(): register callback, return async iterator over queue
#   update_bar_subscription(): add/remove symbols on live connection
#   get_historical_bars(): REST via executor, convert with mappers
#   get_latest_quote(): REST via executor for both quote + trade
#   _bar_callback(): converts and enqueues via call_soon_threadsafe
#   _run_stream(): target for WS thread (calls stock_stream.run())
```

#### Research Insights (Phase 2E)

**SDK Initialization** (Context7 confirmed):
```python
from alpaca.data.live import StockDataStream
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.enums import DataFeed

# StockDataStream takes api_key, secret_key, feed keyword
stock_stream = StockDataStream(api_key, secret_key, feed=DataFeed.IEX)

# subscribe_bars takes handler and *symbols (unpacked)
stock_stream.subscribe_bars(handle_bar, "AAPL", "MSFT")

# run() is blocking — must be in a thread
stock_stream.run()

# stop() from another thread to stop
stock_stream.stop()
```

**Critical Implementation Detail**: The `_bar_callback` is an `async def` that runs in the SDK's internal event loop. To bridge to the main loop's queue, we need:
```python
async def _bar_callback(self, alpaca_bar: AlpacaBar) -> None:
    bar = alpaca_bar_to_bar(alpaca_bar)
    self._main_loop.call_soon_threadsafe(self._enqueue_bar, bar)
```
The `_enqueue_bar` method (see D1 amendment) handles the bounded queue safely.

**Add tests for thread lifecycle**:
```
# 14. test_disconnect_with_timeout - disconnect completes within 10s even if thread hangs
# 15. test_connect_validates_via_api_call - connect() calls get_account to verify credentials
# 16. test_bar_queue_backpressure - full queue drops newest item with CRITICAL log
```

**pytest-asyncio Required**: All adapter tests need `@pytest.mark.asyncio` and the project should add `pytest-asyncio` to dev dependencies if not already present. The `async with` context manager tests require async test support.

### Phase 2F: AlpacaBrokerAdapter (~45 min)

**Goal**: Full implementation of `BrokerAdapter` backed by alpaca-py. Trade update streaming in a background thread, REST order/position/account operations via executor.

**Test first** (`backend/tests/unit/test_alpaca_broker_adapter.py`):
```
# Tests to write FIRST (all use mocked SDK clients):
# 1. test_connect_creates_clients - connect() instantiates TradingClient and TradingStream
# 2. test_connect_validates_credentials - empty api_key raises BrokerAuthError
# 3. test_disconnect_stops_stream - disconnect() stops TradingStream
# 4. test_submit_order_market - submits MarketOrderRequest, returns OrderStatus
# 5. test_submit_order_stop - submits StopOrderRequest with correct stop_price
# 6. test_submit_bracket_order - submits bracket with stop_loss and take_profit
# 7. test_cancel_order - calls cancel_order_by_id
# 8. test_replace_order - calls replace_order_by_id with updated fields
# 9. test_get_order_status - fetches and converts single order
# 10. test_get_positions - fetches and converts position list
# 11. test_get_account - fetches and converts account info
# 12. test_get_open_orders - fetches orders with open status filter
# 13. test_get_recent_orders - fetches orders from last N hours
# 14. test_subscribe_trade_updates_yields_updates - AsyncIterator yields TradeUpdate
# 15. test_submit_order_api_error - APIError 422 raises BrokerAPIError
# 16. test_submit_order_auth_error - APIError 401 raises BrokerAuthError
# 17. test_submit_order_not_connected - raises RuntimeError
# 18. test_context_manager - async with connects and disconnects
```

**Then implement** (`backend/app/broker/alpaca/broker.py`):
```python
# class AlpacaBrokerAdapter:
#   __init__(config: BrokerConfig)
#   connect(): create clients, start trade stream thread
#   disconnect(): stop stream, join thread, shutdown executor
#   submit_order(): convert OrderRequest → Alpaca request, REST via executor
#   submit_bracket_order(): convert BracketOrderRequest, REST via executor
#   cancel_order(): REST via executor
#   replace_order(): REST via executor (PATCH /orders/{id})
#   get_order_status(): REST via executor, convert with mappers
#   get_positions(): REST via executor, convert list
#   get_account(): REST via executor, convert
#   get_open_orders(): REST via executor with status filter
#   get_recent_orders(): REST via executor with time filter
#   subscribe_trade_updates(): register callback, return async iterator
#   _trade_update_callback(): converts and enqueues via call_soon_threadsafe
#   _run_trade_stream(): target for WS thread
```

#### Research Insights (Phase 2F)

**SDK TradingClient Initialization** (Context7 confirmed):
```python
from alpaca.trading.client import TradingClient
from alpaca.trading.stream import TradingStream

trading_client = TradingClient(api_key, secret_key, paper=True)
trading_stream = TradingStream(api_key, secret_key, paper=True)

# Trade update handler — async def with TradeUpdate object
async def handle_trade_update(update):
    # update.event = "fill", "canceled", etc.
    # update.order = full Order object
    # update.order.id, .symbol, .side, .qty, .status, .filled_qty, .filled_avg_price
    pass

trading_stream.subscribe_trade_updates(handle_trade_update)
trading_stream.run()  # blocking
```

**Trade Update Queue — UNBOUNDED** (per D8 amendment): The trade update queue must be unbounded. Fill events are critical state transitions for real money. A dropped fill means position mismatch with broker. Log CRITICAL if queue size exceeds 100 items (indicates consumer is stuck).

**Add tests for trade update safety**:
```
# 19. test_trade_update_queue_unbounded - queue accepts arbitrary number of items
# 20. test_disconnect_waits_for_inflight_rest - executor shutdown uses wait=True
# 21. test_connect_lifecycle_lock - concurrent connect() calls don't create duplicate clients
```

**APIError Handling** (SDK pattern): alpaca-py raises `alpaca.common.exceptions.APIError` with `status_code` attribute for REST errors. Map: 401/403 → `BrokerAuthError`, 422 → `BrokerAPIError`, 429 → log WARNING (SDK retries), 5xx → `BrokerAPIError`.

### Phase 2G: Fake Adapters for Testing (~20 min)

**Goal**: Lightweight in-memory implementations of both protocols for use in unit tests of downstream components (Steps 3-6).

**Test first** (`backend/tests/unit/test_fake_adapters.py`):
```
# Tests to write FIRST:
# 1. test_fake_data_provider_satisfies_protocol - isinstance(FakeDataProvider, DataProvider)
# 2. test_fake_data_provider_returns_bars - get_historical_bars returns canned data
# 3. test_fake_data_provider_subscribe - subscribe_bars yields pushed bars
# 4. test_fake_broker_satisfies_protocol - isinstance(FakeBrokerAdapter, BrokerAdapter)
# 5. test_fake_broker_submit_order - returns OrderStatus with generated broker_id
# 6. test_fake_broker_get_positions - returns configured positions
# 7. test_fake_broker_get_account - returns configured account info
```

**Then implement:**

`backend/app/broker/fake/data.py`:
```python
# class FakeDataProvider:
#   __init__(bars: list[Bar] = [], quotes: dict[str, Quote] = {})
#   push_bar(bar: Bar): put into internal queue (for testing live streaming)
#   subscribe_bars(): yields from internal queue
#   get_historical_bars(): returns self.bars filtered by symbol
#   get_latest_quote(): returns self.quotes[symbol]
```

`backend/app/broker/fake/broker.py`:
```python
# class FakeBrokerAdapter:
#   __init__(positions: list[Position] = [], account: AccountInfo = ...)
#   submitted_orders: list[OrderRequest]  (inspectable by tests)
#   submit_order(): appends to submitted_orders, returns fake OrderStatus
#   get_positions(): returns self.positions
#   get_account(): returns self.account
#   subscribe_trade_updates(): yields from internal queue
#   push_trade_update(update): for testing
```

### Phase 2H: Integration Tests with Alpaca Paper API (~30 min)

**Goal**: Verify the adapters work against the real Alpaca paper trading API. These tests are slow, require API keys, and are marked to skip in CI without credentials.

**Test file** (`backend/tests/integration/test_alpaca_integration.py`):
```
# Marked with @pytest.mark.integration and @pytest.mark.skipif(no API keys)
#
# Data Provider tests:
# 1. test_get_historical_bars_real - fetches AAPL 1-min bars, verifies Decimal types
# 2. test_get_latest_quote_real - fetches AAPL quote, verifies all fields populated
# 3. test_get_historical_bars_empty_symbol - handles unknown symbol gracefully
#
# Broker Adapter tests:
# 4. test_get_account_real - fetches paper account, verifies Decimal equity
# 5. test_get_positions_real - fetches positions (may be empty list)
# 6. test_submit_and_cancel_order - submits limit order far from market, cancels it
# 7. test_get_open_orders_real - after submit, order appears in open orders
```

**Fixtures** (`backend/tests/conftest.py` additions):
```python
# @pytest.fixture
# def alpaca_config() -> BrokerConfig: loads from env vars, skips if missing
#
# @pytest.fixture
# async def data_provider(alpaca_config) -> AsyncIterator[AlpacaDataProvider]
#
# @pytest.fixture
# async def broker_adapter(alpaca_config) -> AsyncIterator[AlpacaBrokerAdapter]
```

#### Research Insights (Phase 2H)

**Integration Test Best Practices**:
- Use `pytest.ini` or `pyproject.toml` to register the `integration` marker: `markers = ["integration: requires Alpaca API keys"]`
- Integration tests should clean up after themselves: cancel any orders submitted, close any positions opened
- Use `try/finally` in fixtures to ensure cleanup even on test failure
- Limit orders should be placed far from market (e.g., AAPL limit buy at $1.00) to avoid accidental fills
- Add a `test_websocket_bar_streaming` integration test: subscribe, wait 60s for a bar, verify it arrives with correct types. Mark with `@pytest.mark.slow`

**Add integration tests**:
```
# 8. test_websocket_bar_streaming - subscribe to AAPL bars, wait for 1 bar, verify types
# 9. test_replace_order_real - submit limit order, replace price, verify new price
# 10. test_get_recent_orders_real - submit order, fetch recent orders, verify it appears
```

**conftest.py Fixture Pattern**:
```python
@pytest.fixture
async def broker_adapter(alpaca_config: BrokerConfig) -> AsyncIterator[AlpacaBrokerAdapter]:
    adapter = AlpacaBrokerAdapter(alpaca_config)
    await adapter.connect()
    try:
        yield adapter
    finally:
        # Clean up: cancel all open orders
        open_orders = await adapter.get_open_orders()
        for order in open_orders:
            await adapter.cancel_order(order.broker_order_id)
        await adapter.disconnect()
```

### Phase 2I: Integration Verification (~15 min)

**Goal**: All tests pass, mypy passes, ruff passes.

**Tasks:**
- [x] `uv run pytest` — all unit + integration tests pass (skip integration if no keys)
- [x] `uv run mypy app/` — zero errors
- [x] `uv run ruff check app/ tests/` — zero errors
- [x] `uv run ruff format --check app/ tests/` — no formatting issues
- [x] Update `broker/__init__.py` to re-export all public types and protocols
- [x] Commit

---

## Acceptance Criteria

### Functional
- [x] `Bar`, `Quote`, `Position`, `AccountInfo`, `OrderRequest`, `BracketOrderRequest`, `OrderStatus`, `TradeUpdate` are correctly defined with proper types
- [x] All monetary fields are `Decimal` (never `float`)
- [x] All enums are `(str, Enum)` for serialization
- [x] `DataProvider` protocol has all required methods with correct signatures
- [x] `BrokerAdapter` protocol has all required methods including `replace_order()`
- [x] Both protocols support `async with` context manager
- [x] `AlpacaDataProvider.get_historical_bars()` returns correctly typed `list[Bar]`
- [x] `AlpacaDataProvider.get_latest_quote()` returns `Quote` with `last` price from latest trade
- [x] `AlpacaDataProvider.subscribe_bars()` yields `Bar` objects from WebSocket stream
- [x] `AlpacaBrokerAdapter.submit_order()` submits market/limit/stop/trailing_stop orders
- [x] `AlpacaBrokerAdapter.submit_bracket_order()` submits entry + stop-loss atomically
- [x] `AlpacaBrokerAdapter.cancel_order()` cancels by broker order ID
- [x] `AlpacaBrokerAdapter.replace_order()` modifies existing order
- [x] `AlpacaBrokerAdapter.get_positions()` returns `list[Position]` with Decimal values
- [x] `AlpacaBrokerAdapter.get_account()` returns `AccountInfo` with Decimal values
- [x] `AlpacaBrokerAdapter.subscribe_trade_updates()` yields `TradeUpdate` objects
- [x] `FakeDataProvider` and `FakeBrokerAdapter` satisfy their respective protocols
- [x] Integration tests pass against Alpaca paper trading API
- [x] Empty API keys raise `BrokerAuthError` with helpful message
- [x] Alpaca `APIError` 401/403 raises `BrokerAuthError`
- [x] Alpaca `APIError` 422/5xx raises `BrokerAPIError` with status code

### Non-Functional
- [x] All monetary values are `Decimal` type (never `float`)
- [x] Float→Decimal conversion uses `Decimal(str(value))` pattern
- [x] WebSocket streams run in dedicated daemon threads
- [x] REST calls run in `ThreadPoolExecutor` via `run_in_executor`
- [x] No API keys or secrets in codebase
- [x] Integration tests skip gracefully when API keys are not set
- [x] `connect()` and `disconnect()` protected by `asyncio.Lock` (no concurrent lifecycle mutations)
- [x] `disconnect()` has timeout on `thread.join()` (never blocks event loop indefinitely)
- [x] Trade update queue is unbounded (fill events must never be dropped)
- [x] Bar queue uses drop-newest backpressure (preserves time-series continuity)
- [x] `connect()` validates credentials via lightweight API call (fail-fast on bad keys)
- [x] `OrderRequest` and `BracketOrderRequest` are frozen dataclasses

### Quality Gates
- [x] All tests written BEFORE implementation (TDD)
- [x] Zero mypy errors in strict mode
- [x] Zero ruff lint/format errors
- [x] No `Optional[X]` — use `X | None` throughout
- [x] No bare `except:` — specific exceptions only
- [x] Google-style docstrings on all public classes and non-obvious functions
- [x] `pytest-asyncio` added to dev dependencies for async test support

---

## File List

### New Files
| File | Purpose |
|------|---------|
| `backend/app/broker/types.py` | Domain types: Bar, Quote, Position, etc. |
| `backend/app/broker/errors.py` | BrokerError exception hierarchy |
| `backend/app/broker/data_provider.py` | DataProvider Protocol |
| `backend/app/broker/broker_adapter.py` | BrokerAdapter Protocol |
| `backend/app/broker/alpaca/mappers.py` | Alpaca SDK ↔ domain type converters |
| `backend/app/broker/alpaca/data.py` | AlpacaDataProvider implementation |
| `backend/app/broker/alpaca/broker.py` | AlpacaBrokerAdapter implementation |
| `backend/app/broker/fake/__init__.py` | Fake adapter package |
| `backend/app/broker/fake/data.py` | FakeDataProvider for testing |
| `backend/app/broker/fake/broker.py` | FakeBrokerAdapter for testing |
| `backend/tests/unit/test_broker_types.py` | Tests for domain types |
| `backend/tests/unit/test_broker_errors.py` | Tests for error hierarchy |
| `backend/tests/unit/test_broker_protocols.py` | Tests for protocols |
| `backend/tests/unit/test_alpaca_mappers.py` | Tests for type mappers |
| `backend/tests/unit/test_alpaca_data_provider.py` | Tests for AlpacaDataProvider |
| `backend/tests/unit/test_alpaca_broker_adapter.py` | Tests for AlpacaBrokerAdapter |
| `backend/tests/unit/test_fake_adapters.py` | Tests for fake adapters |
| `backend/tests/integration/test_alpaca_integration.py` | Integration tests with real API |

### Modified Files
| File | Change |
|------|--------|
| `backend/app/broker/__init__.py` | Re-export all public types and protocols |
| `backend/app/broker/alpaca/__init__.py` | Re-export AlpacaDataProvider, AlpacaBrokerAdapter |
| `backend/tests/conftest.py` | Add fixtures for Alpaca integration tests |

---

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| alpaca-py `run()` blocking pattern doesn't work in thread as expected | Low | Critical | Build proof-of-concept spike in Phase 2E before full implementation |
| `call_soon_threadsafe` fails if main loop is closed during shutdown | Medium | Medium | Check loop state before calling; catch RuntimeError |
| Float→Decimal conversion introduces subtle precision errors | Low | High | Centralized `_to_decimal()` helper; test with known precision edge cases |
| Integration tests flaky due to market hours / API availability | High | Low | Use limit orders far from market price; mark tests for skip in CI |
| alpaca-py SDK breaks backward compat in future versions | Low | Medium | Pin version in pyproject.toml; test against specific version |
| Rate limiting during integration tests consumes allocation | Medium | Low | Use minimal API calls; clean up orders after tests |

#### Risks Discovered During Deep Review

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ~~`call_soon_threadsafe(put_nowait)` on full bounded queue~~ | ~~High~~ | ~~Critical~~ | **MITIGATED** — Use wrapper `_enqueue_bar()` method (D1 amendment) |
| ~~Trade update queue drop-oldest loses fill events~~ | ~~Medium~~ | ~~Critical~~ | **MITIGATED** — Trade update queue is unbounded (D8 amendment) |
| ~~`disconnect()` blocks event loop indefinitely~~ | ~~Medium~~ | ~~High~~ | **MITIGATED** — Timeout on `thread.join()` (D3 amendment) |
| Concurrent `connect()` creates duplicate SDK clients | Low | Medium | asyncio.Lock on lifecycle (D3 amendment) |
| `disconnect()` during in-flight order submission | Medium | Medium | `shutdown(wait=True, cancel_futures=True)` (D16 note) |
| Invalid credentials discovered late via thread death | Medium | Low | Auth validation call in `connect()` (D14 amendment) |

---

## References

### Internal
- Phase 1 Plan: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md`
- Step 1 Plan: `docs/plans/2026-02-14-feat-step1-foundation-scaffolding-plan.md`
- Engineering Standards: `CLAUDE.md`

### External
- [alpaca-py SDK](https://github.com/alpacahq/alpaca-py) (v0.43.x)
- [alpaca-py Docs](https://alpaca.markets/sdks/python/)
- [Alpaca Trading API](https://docs.alpaca.markets/docs/trading-api)
- [Alpaca Data API](https://docs.alpaca.markets/docs/market-data-api)
- [asyncio `call_soon_threadsafe`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.call_soon_threadsafe)

### SDK Quick Reference (from Context7 Research)

**Key Imports**:
```python
# Data streaming
from alpaca.data.live import StockDataStream
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.enums import DataFeed

# Trading
from alpaca.trading.client import TradingClient
from alpaca.trading.stream import TradingStream
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, StopOrderRequest,
    StopLimitOrderRequest, TrailingStopOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

# Errors
from alpaca.common.exceptions import APIError
```

**Key Patterns**:
- `StockDataStream(api_key, secret_key, feed=DataFeed.IEX)` — IEX is free, SIP requires subscription
- `TradingClient(api_key, secret_key, paper=True)` — paper=True for sandbox
- `TradingStream(api_key, secret_key, paper=True)` — paper trading WebSocket
- All `subscribe_*` methods take `async def handler(data)` callback + `*symbols`
- All `run()` methods are blocking — must run in a dedicated thread
- All `stop()` methods can be called from another thread
- `APIError` has `.status_code` attribute for HTTP status
