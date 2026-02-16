---
title: "Order Lifecycle + Risk Management Architecture"
category: architecture-decisions
tags: [order-management, risk-management, circuit-breaker, position-sizing, state-machine, async, sqlite]
module: Orders, Risk
symptom: "Need to manage full order lifecycle (submit → fill → stop → trade) with risk enforcement, crash recovery, and correct P&L tracking"
root_cause: "Complex async coordination between broker events, risk limits, and persistent state requires careful architectural boundaries"
date: 2026-02-15
context: "Step 4 of Phase 1 trading engine — bridging Strategy Engine (Step 3) and BrokerAdapter (Step 2)"
---

# Order Lifecycle + Risk Management Architecture

## Problem

Building the layer between strategy signals and broker execution requires solving several interrelated problems:
- Order state tracking with crash recovery
- Risk enforcement (position sizing, daily loss limits, consecutive loss pause)
- Stop-loss management (auto-submit on fill, replace on partial, market exit fallback)
- Trade record creation with correct P&L
- Concurrency control for simultaneous signals

## Key Architectural Decisions

### 1. OrderManager Does NOT Wire to CircuitBreaker

**Decision**: OrderManager creates trade records but does NOT call `cb.record_trade()`. That's TradingEngine's job (Step 5).

**Why**: OrderManager is a lifecycle orchestrator — it processes broker events and manages state. The CircuitBreaker is a pre-order gate that belongs at the engine level. Coupling them creates a circular dependency: RiskManager checks CB → OrderManager creates trades → CB needs updating. Instead, TradingEngine sits above both and wires them together.

**Pattern**:
```
TradingEngine
  ├── RiskManager.approve(signal)    # checks CB + sizer
  ├── OrderManager.submit_entry()    # submits to broker
  ├── OrderManager.handle_trade_update()  # creates trade record
  └── CircuitBreaker.record_trade()  # TradingEngine calls after trade created
```

### 2. In-Place Replace Order (No REPLACED Terminal State)

**Decision**: When updating a stop-loss (e.g., partial fill changes qty), we update `broker_id` on the existing `OrderStateModel` and write an audit event. We do NOT create a REPLACED terminal state.

**Why**: A REPLACED state would require creating a new order row for each modification, complicating correlation tracking. The broker replaces the order atomically — we mirror that by updating the broker_id and logging the change. The order's `local_id` and `correlation_id` remain stable.

### 3. asyncio.Event for Cancel-Then-Sell Flow

**Decision**: `request_exit()` uses `asyncio.Event` to wait for broker cancel confirmation before selling.

```python
cancel_event = asyncio.Event()
self._cancel_events[stop_order.broker_id] = cancel_event
await self._broker.cancel_order(stop_order.broker_id)
try:
    await asyncio.wait_for(cancel_event.wait(), timeout=5.0)
except TimeoutError:
    log.warning("stop_cancel_timeout", broker_id=stop_order.broker_id)
finally:
    self._cancel_events.pop(stop_order.broker_id, None)
```

**Why**: We can't sell while a stop-loss is active (double-sell risk). We need to cancel the stop first, confirm it's canceled, then sell. The Event bridges the async gap between requesting cancellation and receiving the broker's CANCELED event via `handle_trade_update()`.

### 4. Atomic State + Event Writes

**Decision**: Every state transition writes both `OrderStateModel` update and `OrderEventModel` insert in a single transaction.

```python
async with self._session_factory() as session, session.begin():
    order.state = new_state.value
    order.updated_at = now
    session.add(OrderEventModel(
        event_type=event_type,
        local_id=local_id,
        ...
    ))
```

**Why**: If the process crashes between writing state and event, we'd have inconsistent state. A single transaction guarantees both succeed or neither does. On restart, the state machine and event log always agree.

### 5. CircuitBreaker: Realized-Only P&L, Break-Even as Loss

**Decision**: Daily P&L tracks only realized (closed) trades, not unrealized. Break-even (`pnl <= 0`) counts as a loss for consecutive tracking.

**Why**: Unrealized P&L fluctuates tick-by-tick — using it for circuit breaker would cause constant flapping. Break-even as loss is conservative: if you're not making money, the strategy may be struggling. Better to pause and reassess than to let a marginally profitable strategy continue bleeding via commissions.

### 6. Position Sizing: Decimal(int()) Truncation

**Decision**: Position sizer computes exact shares, then truncates with `Decimal(int(qty))` — never rounds up.

```python
qty_raw = risk_amount / stop_distance
qty = Decimal(int(qty_raw))  # Always rounds DOWN
```

**Why**: Rounding up could exceed risk budget. With real money, conservative is always correct. If the calculation says 499.7 shares, we buy 499.

### 7. RiskManager: asyncio.Lock for Concurrent Signals

**Decision**: `RiskManager.approve()` acquires an `asyncio.Lock` before checking open positions.

**Why**: Two signals arriving simultaneously could both see "4 open positions" (limit 5), both approve, and result in 6 positions. The lock serializes approval decisions so position count is always current.

### 8. Stop-Loss Retry with Market Sell Fallback

**Decision**: `submit_stop_loss()` retries 3 times with 1-second backoff. If all retries fail, submits a market sell as fallback.

**Why**: A failed stop-loss means an unprotected position — the worst possible state. The fallback to market sell ensures the position is always protected, even if the stop order type is temporarily unavailable.

### 9. _submit_stop_loss_with_retry Is a Pass-Through

**Decision**: `_submit_stop_loss_with_retry()` is intentionally a no-op `pass`. The actual `submit_stop_loss()` is a separate public method called by TradingEngine.

**Why**: OrderManager doesn't know the stop price — that comes from the strategy signal. Rather than storing stop prices on the order model or threading them through fill events, the TradingEngine (which has the signal context) calls `submit_stop_loss()` directly after receiving the fill notification.

## Migration Gotcha: SQLite batch_alter_table Destroys Triggers

**Problem**: Alembic's `batch_alter_table` for SQLite recreates the entire table (copy → drop → rename). This destroys any triggers on the original table.

**Solution**: After any `batch_alter_table` operation, re-create all triggers defensively with `IF NOT EXISTS`:

```python
def _recreate_immutability_triggers() -> None:
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_update_order_event "
        "BEFORE UPDATE ON order_event "
        "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
    )
    # ... same for no_delete_order_event, no_update_trade, no_delete_trade
```

**Prevention**: Any future migration using `batch_alter_table` on tables with triggers must include trigger re-creation at the end. Add a comment referencing this gotcha.

## Testing Patterns

### FakeBrokerAdapter for Unit Tests

OrderManager unit tests use `FakeBrokerAdapter` which returns `ACCEPTED` status and tracks `submitted_orders`. No real broker calls. Integration tests wire RiskManager + OrderManager + FakeBrokerAdapter together with an in-memory `aiosqlite` database.

### In-Memory Async SQLite for Test Isolation

```python
@pytest.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
```

Each test gets a fresh database. No cleanup needed. `expire_on_commit=False` prevents detached instance errors after commit.

### Test Factory Pattern

`tests/factories.py` provides `make_signal()`, `make_account_info()` with sensible defaults. Tests override only what matters, keeping test code focused on the behavior being tested.

### 10. Candle Counter: In-Memory Transient State

**Decision**: OrderManager tracks candle counts for pending entries in an in-memory `dict[str, int]`, not in the database.

**Why**: This state is transient — it only matters while the order is pending. On restart, `cancel_all_pending()` closes unfilled entries anyway, so the counter doesn't need persistence. Storing it in the DB would bloat the schema with data that's only relevant for seconds-to-minutes.

**Cleanup**: Entries are removed from the dict when the order reaches a terminal state (filled, canceled, etc.), preventing memory leaks.

## Cross-References

- [Decimal for Money, Float for Math](decimal-for-money-float-for-math.md) — boundary between risk (Decimal) and indicators (float)
- [Applying Decimal/Float Boundary Refactor](applying-decimal-float-boundary-refactor.md) — how the boundary was applied in Step 3
- [alpaca-py Async Threading Bridge](../integration-issues/alpaca-py-async-threading-bridge.md) — broker adapter async patterns
- [alpaca-py API Error Mocking](../integration-issues/alpaca-py-api-error-mocking.md) — how to mock broker errors in tests
- [alpaca-py Replace Order Qty Type](../test-failures/alpaca-py-replace-order-qty-type.md) — qty must be `int` not `float`

## Future Considerations

- **TradingEngine (Step 5)** will wire OrderManager + RiskManager + CircuitBreaker together
- **DecimalText TypeDecorator** in `app/models/order.py` stores Decimal as TEXT in SQLite — works but may need adjustment for PostgreSQL migration
- **Commission tracking** is stubbed as `Decimal("0")` — real commission data comes from Alpaca trade events in a future step
