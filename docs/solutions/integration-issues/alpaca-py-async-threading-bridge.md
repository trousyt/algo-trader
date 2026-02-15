---
title: "Bridging Sync alpaca-py SDK to Async Architecture"
category: integration-issues
tags: [alpaca-py, asyncio, threading, websocket, run_in_executor, call_soon_threadsafe]
module: broker.alpaca
symptom: "Blocking SDK calls freeze the asyncio event loop"
root_cause: "alpaca-py REST is synchronous, WebSocket run() blocks indefinitely"
date_solved: 2026-02-14
---

# Bridging Sync alpaca-py SDK to Async Architecture

## Problem

The alpaca-py SDK is fundamentally synchronous and blocking, which conflicts
directly with our asyncio-based application architecture:

- **REST calls** (`get_account()`, `submit_order()`, `get_all_positions()`, etc.)
  are synchronous. Calling them directly from an async coroutine blocks the
  entire event loop, freezing all concurrent tasks (WebSocket processing, order
  management, heartbeats).

- **WebSocket streaming** (`StockDataStream.run()`, `TradingStream.run()`) blocks
  the calling thread indefinitely. These methods enter an infinite receive loop
  and never return until the connection is closed.

- **No native async API**. The SDK does not expose `async`/`await` equivalents
  for any of its operations.

Running any of these operations directly on the event loop thread causes the
entire application to hang.

## Solution

A three-part threading bridge that isolates all blocking SDK operations from
the asyncio event loop.

### 1. REST Calls via ThreadPoolExecutor + run_in_executor

All synchronous REST calls are dispatched to a dedicated thread pool, allowing
the event loop to continue processing other coroutines while the blocking call
executes on a worker thread.

```python
self._executor = ThreadPoolExecutor(max_workers=4)

async def get_account(self) -> AccountInfo:
    raw = await asyncio.get_event_loop().run_in_executor(
        self._executor,
        self._trading_client.get_account,
    )
    return self._map_account(raw)
```

**Why a dedicated executor**: The default executor is shared across the entire
application. A slow or stalled Alpaca API response would consume a shared
worker, potentially starving unrelated `run_in_executor` calls. A dedicated
pool with `max_workers=4` bounds the concurrency to what the Alpaca rate
limiter allows while isolating failures.

### 2. WebSocket Streaming in Dedicated Daemon Threads

Each WebSocket stream (`StockDataStream` for market data, `TradingStream` for
order/fill updates) runs in its own dedicated daemon thread. The thread calls
the SDK's blocking `run()` method, which loops forever receiving messages.

```python
self._ws_thread = threading.Thread(
    target=self._run_stream,
    name="alpaca-data-stream",
    daemon=True,
)
self._ws_thread.start()

def _run_stream(self) -> None:
    """Target for the stream thread. Runs until cancelled."""
    try:
        self._stream.run()
    except Exception:
        logger.exception("Stream thread crashed")
    finally:
        self._connected.clear()
```

**Why daemon threads**: If the main process exits (crash, shutdown signal), the
daemon threads are terminated automatically. Without `daemon=True`, the process
would hang waiting for the WebSocket thread to finish its infinite loop.

### 3. Thread-Safe Bridge via call_soon_threadsafe + Bounded Queue

WebSocket callbacks execute on the SDK's internal thread, not the asyncio event
loop thread. To safely pass data from the SDK thread to the async world, we use
`call_soon_threadsafe` to schedule an enqueue operation on the event loop
thread, which then puts the item into an `asyncio.Queue` that async consumers
can `await`.

```python
# In WS callback (runs in SDK's thread):
self._main_loop.call_soon_threadsafe(self._enqueue_bar, bar)

# Enqueue wrapper (runs on event loop thread via call_soon_threadsafe):
def _enqueue_bar(self, bar: Bar) -> None:
    if self._bar_queue.full():
        logger.critical("Bar queue full, dropping newest bar: %s", bar.symbol)
        return
    self._bar_queue.put_nowait(bar)
```

**Why not `put_nowait` directly from the SDK thread**: `asyncio.Queue` is NOT
thread-safe. Calling `put_nowait` from a non-event-loop thread corrupts
internal state. `call_soon_threadsafe` schedules the call to run on the event
loop thread, where `put_nowait` is safe.

## Key Design Decisions

### Bar Queue: BOUNDED (10,000) with Drop-Newest Backpressure

```python
self._bar_queue: asyncio.Queue[Bar] = asyncio.Queue(maxsize=10_000)
```

- **Bounded**: Prevents unbounded memory growth if the consumer falls behind
  (e.g., during a strategy computation spike or GC pause).
- **Drop-newest**: When the queue is full, the newest arriving bar is dropped
  rather than the oldest. This preserves time-series continuity -- the consumer
  sees a contiguous sequence from the oldest buffered bar forward, with a gap at
  the end rather than holes in the middle.
- **10,000 capacity**: At ~4 bars/second across a 50-symbol watchlist, this
  provides roughly 50 seconds of buffer. Sufficient for transient slowdowns
  without being so large that memory becomes a concern.

### Trade Update Queue: UNBOUNDED

```python
self._trade_queue: asyncio.Queue[TradeUpdate] = asyncio.Queue()  # unbounded
```

- **Fill events must NEVER be dropped**. A dropped fill means the system's
  internal position state diverges from the broker's actual state. This leads to
  incorrect position sizing, duplicate orders, or failure to apply stop losses.
- The volume of trade updates is orders of magnitude lower than market data
  (tens per day vs. thousands per second), so unbounded growth is not a
  practical risk.

### threading.Event for Connected State

```python
self._connected = threading.Event()
```

- Provides an explicit memory barrier between the SDK thread (which sets the
  flag) and the event loop thread (which reads it).
- Without a synchronization primitive, the event loop thread could read stale
  cached values of a plain `bool` flag due to CPU memory ordering.

### asyncio.Lock on Connect/Disconnect Lifecycle

```python
self._lifecycle_lock = asyncio.Lock()

async def connect(self) -> None:
    async with self._lifecycle_lock:
        if self._connected.is_set():
            return
        # ... start threads, wait for connection ...

async def disconnect(self) -> None:
    async with self._lifecycle_lock:
        if not self._connected.is_set():
            return
        # ... stop threads, cleanup ...
```

- Prevents race conditions if `connect()` and `disconnect()` are called
  concurrently (e.g., a reconnect loop firing while a graceful shutdown is in
  progress).

### Disconnect Timeout on thread.join()

```python
self._ws_thread.join(timeout=5.0)
if self._ws_thread.is_alive():
    logger.warning("Stream thread did not exit within timeout")
```

- `thread.join()` without a timeout blocks the calling coroutine indefinitely
  if the SDK thread is stuck (network hang, unresponsive server).
- A 5-second timeout ensures disconnect completes in bounded time. The daemon
  flag ensures the thread is cleaned up on process exit regardless.

### __aexit__ Wraps Disconnect in try/except

```python
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    try:
        await self.disconnect()
    except Exception:
        logger.exception("Error during disconnect in __aexit__")
```

- If the `async with` block exits due to an exception, and `disconnect()` also
  raises, the original exception would be masked. The try/except ensures the
  original exception propagates while logging the disconnect failure.

## Data Flow Diagram

```
asyncio event loop thread          SDK threads
========================          ===========

[Strategy Engine]                  [StockDataStream.run()]
      |                                   |
      |  await bar_queue.get()             |  on_bar callback
      |<-----------------------------------+
      |   (via call_soon_threadsafe        |
      |    + asyncio.Queue)                |
      |                                    |
      |                            [TradingStream.run()]
      |                                   |
      |  await trade_queue.get()           |  on_trade_update callback
      |<-----------------------------------+
      |                                    |
      |  await run_in_executor(            |
      |    submit_order)                   |
      +---------------------------------->|
      |                   [ThreadPoolExecutor worker]
      |<----------------------------------+
      |   (future resolved)               |
```

## Pitfalls to Avoid

1. **Never call `asyncio.Queue.put_nowait()` from a non-event-loop thread.**
   Always use `call_soon_threadsafe` to schedule the put on the correct thread.

2. **Never use `queue.put_nowait()` directly in the `call_soon_threadsafe`
   callback without checking `full()` first.** A full bounded queue raises
   `QueueFull`, which would surface as an unhandled exception on the event loop.

3. **Never use an unbounded queue for high-frequency market data.** A consumer
   hiccup would cause memory to grow until OOM.

4. **Never omit the timeout on `thread.join()`.** A stuck SDK thread will block
   the event loop thread indefinitely, freezing the entire application during
   shutdown.

5. **Never use a plain `bool` for cross-thread state.** Without a memory barrier
   (provided by `threading.Event`, `Lock`, or similar), one thread may never see
   writes from another thread due to CPU caching and memory ordering.

## Related

- `broker.alpaca` module (implementation)
- `broker.protocols` module (`DataProvider`, `BrokerAdapter` protocol definitions)
- Step 2 plan: `docs/plans/2026-02-14-feat-step2-broker-abstraction-alpaca-plan.md`
