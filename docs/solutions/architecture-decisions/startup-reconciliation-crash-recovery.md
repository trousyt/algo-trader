---
title: "Startup Reconciliation Architecture: Order and Position State Recovery"
category: architecture-decisions
tags: [startup, reconciliation, crash-recovery, order-state, broker-sync, emergency-stop, idempotent]
module: startup_reconciler
symptom: "Process restart requires broker state comparison; diverged local state after crash; unprotected positions without stop-loss"
root_cause: "No automated reconciliation on startup; broker and local SQLite can diverge after crash; OrderStateMachine lacks escape hatch for recovery"
date: 2026-02-15
pr: "https://github.com/trousyt/algo-trader/pull/4"
---

# Startup Reconciliation Architecture

## Problem

When a trading system crashes or restarts, local SQLite order state can diverge from broker truth. Unprotected positions (no stop-loss) have unlimited downside risk. The system must reconcile before any trading resumes.

## Key Design Decision: No OrderManager Dependency

Architecture-strategist confirmed: the reconciler calls the broker directly. It does NOT route through OrderManager.

**Why**: OrderManager enforces business rules (risk checks, state transitions) that don't apply during recovery. The reconciler needs raw broker access to force-correct local state. ~15 lines of duplicated retry logic is justified by clean separation and independent testability.

## The 3-Phase Reconciliation Algorithm

Runs once on every process start, before WebSocket subscriptions or strategy evaluation.

### Phase 1: Order Reconciliation

For each local non-terminal order with a `broker_id`:
- Look up in broker state. If different state, `force_state()` local to match broker.
- For PENDING_SUBMIT orders (no `broker_id`): mark SUBMIT_FAILED (stale from pre-submission crash).
- Orphan broker orders (open on broker, no local match): cancel immediately.

### Phase 2: Position Reconciliation

For each broker position:
- Check if a local FILLED entry order exists for that symbol.
- If not: create synthetic OrderStateModel with deterministic ID.
- For every position: check if an active stop-loss exists. If not: place emergency stop.

### Phase 3: CircuitBreaker Reconstruction

Happens externally — reads FILLED trade records from DB after reconciliation completes.

## Key Patterns

### Security-Gated `force_state()`

The OrderStateMachine normally enforces strict transitions. During reconciliation, local state may have diverged arbitrarily. A keyword-only boolean acts as a safety gate:

```python
def force_state(
    self,
    new_state: OrderState,
    *,
    _reconciliation: bool = False,
) -> None:
    if not _reconciliation:
        raise RuntimeError("force_state() can only be called during reconciliation")
    self._state = new_state
```

The underscore prefix signals "internal use only". Default `False` means you must explicitly opt in. Catches programming errors at runtime.

### Parallel Broker Fetches with Fatal Error

Three REST calls run in parallel via `asyncio.gather`. If all retries fail, `ReconciliationFatalError` aborts startup — trading with stale state is worse than not trading.

```python
positions, open_orders, recent_orders = await asyncio.gather(
    asyncio.wait_for(self._broker.get_positions(), timeout=_BROKER_CALL_TIMEOUT),
    asyncio.wait_for(self._broker.get_open_orders(), timeout=_BROKER_CALL_TIMEOUT),
    asyncio.wait_for(self._broker.get_recent_orders(24), timeout=_BROKER_CALL_TIMEOUT),
)
```

Constants: `_STOP_RETRY_MAX = 3`, `_BROKER_CALL_TIMEOUT = 10.0`, exponential backoff (1s, 2s, 4s).

### Emergency Stop: 3x Retry + Market Sell Fallback

An unprotected position is the worst state. Emergency stop uses `emergency_stop_pct` (default 2%, configurable 0.5%-10%) below entry price. After 3 failed stop attempts, falls back to market sell. Leaving a position unprotected is never acceptable.

### Deterministic Orphan IDs

Orphan positions get `correlation_id = f"orphan-{symbol}-{YYYYMMDD}"`. Dedup-checked before creation. Restarting multiple times on the same day does not create duplicates.

### Broker Status Mapping

Static `STATUS_MAP` converts broker statuses to local `OrderState`. Transient states (PENDING_CANCEL, REPLACED) map to `None` and are skipped. Unknown statuses raise `ReconciliationFatalError` — fail-safe, never silently ignore.

### NULL Fill Price Guard

When broker reports FILLED but `avg_fill_price` is None (should never happen): log CRITICAL, record in errors, but still force the state — broker is truth.

### ReconciliationResult Structured Output

Frozen dataclass for logging and test assertions:

```python
@dataclass(frozen=True)
class ReconciliationResult:
    orders_reconciled: int
    orphans_detected: int
    orphan_orders_canceled: int
    emergency_stops_placed: int
    errors: list[str]
```

Errors are accumulated (not raised) so all positions get processed even if some fail.

## Testing Strategy

- **FakeBrokerAdapter** with configurable `open_orders`, `recent_orders`, `order_statuses` for unit tests
- **`make_position()` and `make_order_status()` factories** for readable test setup
- **In-memory aiosqlite** (`"sqlite+aiosqlite://"`) for test isolation
- **19 unit tests** covering all phases, edge cases, idempotency, and broker API failure
- **4 integration tests** covering full crash recovery flow, CircuitBreaker reconstruction, multi-strategy, and parallel fetches

## Prevention Strategies

- Safety-critical escape hatches need explicit security gates (not just comments)
- Crash recovery must be idempotent by design (deterministic IDs, dedup checks)
- External data (broker responses) must be bounds-validated before use
- Monitor invariants: every position must have an active stop

## Cross-References

- Phase 1 Plan: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md`
- Step 5 Plan: `docs/plans/2026-02-15-feat-step5-startup-reconciliation-crash-recovery-plan.md`
- Order Lifecycle: `docs/solutions/architecture-decisions/order-lifecycle-and-risk-architecture.md`
- Alpaca Threading Bridge: `docs/solutions/integration-issues/alpaca-py-async-threading-bridge.md`
- PR #4: https://github.com/trousyt/algo-trader/pull/4
