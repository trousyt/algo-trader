---
title: "Step 5: Startup Reconciliation + Crash Recovery"
type: feat
date: 2026-02-15
phase: 1
step: 5
deepened: 2026-02-15
depends_on:
  - docs/plans/2026-02-15-feat-step4-order-risk-management-plan.md
  - docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md
---

# Step 5: Startup Reconciliation + Crash Recovery

## Enhancement Summary

**Deepened on:** 2026-02-15
**Agents used:** architecture-strategist, code-simplicity-reviewer, data-integrity-guardian, kieran-python-reviewer, performance-oracle, security-sentinel, pattern-recognition-specialist, best-practices-researcher

### Key Improvements

1. **Simplified from 5 phases to 3** — Ghost detection (Phase 4) deferred as YAGNI; Phases 3+5 merged into single position-reconciliation pass. ~35% LOC reduction.
2. **Renamed to `StartupReconciler`** — Module becomes `startup_reconciler.py`, class `StartupReconciler`. Clearer naming per Kieran + Architecture reviewers.
3. **Parallelized broker fetches** — `asyncio.gather` for 3 initial REST calls drops worst-case startup from ~9.6s to ~1.85s.
4. **Deterministic orphan IDs** — `orphan-{symbol}-{date}` instead of random UUIDs for idempotent re-runs.
5. **Security hardening** — `force_state()` gated behind reconciliation context flag, broker response bounds-checking, reconciliation lock prevents WebSocket race.
6. **Data integrity guards** — NULL `avg_fill_price` guard, `quantize()` on emergency stop price, atomic force-transition in single transaction.
7. **Removed OrderManager coupling** — Reconciler owns its own stop placement and trade creation; no public API exposure needed on OrderManager.

### Conflicts Flagged for Review

- **Ghost detection scope**: Simplicity reviewer recommends deferring entirely (YAGNI). Architecture strategist suggests handling orphan broker orders too. **Resolution**: Defer ghost detection; cancel orphan broker orders (low cost, high safety).
- **ReconciliationResult**: Simplicity recommends eliminating (use logging). Data integrity recommends keeping for monitoring. **Resolution**: Keep as lightweight frozen dataclass — useful for integration test assertions and structured logging.

## Overview

Build the startup reconciliation module that runs before any live trading on every process start. Compares local SQLite order state against the broker's actual state, corrects discrepancies, and protects any open position that lacks an active stop-loss. This is safety-critical code — an unprotected position has unlimited downside risk.

## Problem Statement

When the trading engine crashes (or is stopped ungracefully), local state can diverge from broker state:

- An entry order was filled at the broker, but the process died before recording the fill
- A stop-loss was triggered while the system was down, closing a position we think is still open
- An order was submitted but the broker response was never received (PENDING_SUBMIT with no broker_id)
- Positions exist at the broker from manual trades or a previous DB reset

Without reconciliation, the system would start trading with incorrect state — potentially opening duplicate positions, failing to protect existing ones, or miscounting P&L.

## Proposed Solution

A standalone `StartupReconciler` class in `app/orders/startup_reconciler.py` that:

1. Fetches broker truth (positions + orders) via parallel REST calls
2. Compares against local SQLite state
3. Force-corrects local state where it diverges
4. Cancels orphan broker orders (open orders at broker with no local record)
5. Places emergency stop-losses on any unprotected position
6. Reconstructs CircuitBreaker from today's trades
7. Returns a structured result for logging/monitoring

Runs **before** WebSocket subscriptions, indicator warm-up, or any strategy evaluation.

### Research Insights

**Best Practices (NautilusTrader, pysystemtrade, Alpaca docs):**
- Startup = crash recovery: same reconciliation code path always runs, not just after crashes
- Broker is source of truth: always trust broker state over local state
- Short-lived DB sessions: broker REST calls happen outside session scope, DB writes in focused sessions
- Deterministic identifiers for idempotency: orphan records use `orphan-{symbol}-{date}` not random UUIDs
- Periodic reconciliation (not just startup) is industry standard — defer to future step but design for it

**Architecture (from Architecture Strategist):**
- Reconciler should NOT depend on OrderManager for stop placement or trade creation — own those operations directly via `BrokerAdapter` + `async_sessionmaker`. This avoids coupling to OrderManager's internal state and event expectations.
- Orphan broker ORDERS (not just positions) need handling: open orders at broker with no local record should be canceled to prevent unexpected fills.

## Design Decisions

### D1. State Machine Bypass: `force_state()` (Security-Gated)

**Decision**: Add `force_state(new_state: OrderState)` to `OrderStateMachine`, gated behind a `_reconciliation_mode: bool` flag.

**Context**: The normal `transition()` method validates against the transition table. Reconciliation needs to skip intermediate states (e.g., PENDING_SUBMIT → FILLED) because the broker already completed those transitions while we were down.

**Why not write directly to DB**: `force_state()` keeps the bypass explicit, auditable, and co-located with the transition logic. Direct DB writes scatter state management across modules.

**Security gate (from Security Sentinel)**: `force_state()` bypasses all validation — unrestricted access is a risk. Gate it behind a `_reconciliation_mode` flag set via context manager on the reconciler. Calling `force_state()` when not in reconciliation mode raises `RuntimeError`.

**Explicitly deferred from Step 4**: The Step 4 plan states "No `force_state()` — reconciliation deferred to Step 5. When Step 5 needs it, it adds it."

### D2. Emergency Stop Price: Configurable Percentage (with Data Integrity Guards)

**Decision**: Add `emergency_stop_pct: Decimal` to `RiskConfig` (default `Decimal("0.02")`, bounds `0.005`–`0.10`).

**Context**: During reconciliation, no bar data or indicators are loaded (warm-up happens after). The strategy's `stop_loss_price()` requires a `Bar` and `IndicatorSet` which are unavailable.

**Approach**: Emergency stop = `avg_entry_price * (1 - emergency_stop_pct)`. Simple, fast, always computable. After warm-up completes, the TradingEngine (future step) can recalculate with the strategy's preferred stop and update if different.

**Data integrity guards (from Data Integrity Guardian):**
- Guard against NULL or zero `avg_entry_price` — skip stop placement and log CRITICAL (requires manual intervention)
- Apply `quantize(Decimal("0.01"))` to emergency stop price — ensure tick-size compliance
- Bounds-check: if computed stop price <= 0, log CRITICAL and skip (don't place a zero-price stop)

**Alternatives rejected**:
- Fetch historical bars during reconciliation — adds latency and complexity to a safety-critical path
- Store stop price on entry order — would require schema change and doesn't help orphan positions
- Use strategy default — requires indicators that aren't available yet

### D3. Broker API Failure: Abort on Read Failure

**Decision**: Retry reads (positions/orders) 3× with exponential backoff. If reads fail after retries, **abort startup entirely** by raising `ReconciliationFatalError`.

**Context**: If we can't see broker state, we can't know if positions are unprotected. Trading blind is unacceptable for a real-money system.

**For writes (emergency stop placement)**: Use the existing `submit_stop_loss()` pattern — 3× retry with market sell fallback. An unprotected position is the worst state; always attempt fallback.

**Implementation (from Kieran Python Reviewer):**
- Define `ReconciliationFatalError(Exception)` — specific exception for abort-startup scenarios
- Hand-rolled retry (not tenacity) matching existing OrderManager patterns
- Use `asyncio.wait_for(coro, timeout=10.0)` wrapper on each broker call (from Performance Oracle)
- Caller (TradingEngine/main) catches `ReconciliationFatalError` and refuses to proceed

### D4. Order Matching: By `broker_id` with Individual Fallback

**Decision**: Primary match on `broker_id` ↔ `broker_order_id`. For non-terminal orders with a `broker_id` not found in the 24h batch, fall back to individual `get_order_status(broker_id)`.

**Context**: `get_recent_orders(since_hours=24)` misses orders from extended downtime (weekends). Individual lookups handle this at the cost of N extra API calls (typically 0–2).

### D5. Orphan Positions: Synthetic Records + Emergency Stop (Deterministic IDs)

**Decision**: Create synthetic `OrderStateModel` records for broker positions with no local match. Assign `correlation_id = "orphan-{symbol}-{YYYYMMDD}"`, `strategy = "unknown"`, `order_role = ENTRY`, `state = FILLED`. Place emergency stop using `emergency_stop_pct`. Log WARNING.

**Context**: Orphans can come from manual trades, DB resets, or very old fills. They need tracking and protection, but cannot participate in normal strategy lifecycle.

**Deterministic IDs (from Best Practices Researcher):** Use `orphan-{symbol}-{YYYYMMDD}` instead of random UUIDs. This makes re-runs idempotent — the same orphan produces the same correlation_id, and the deduplication check (`WHERE correlation_id LIKE 'orphan-{symbol}%'`) prevents duplicates.

**Orphan deduplication query (from Data Integrity Guardian):** Be explicit — check for existing non-terminal orders with `correlation_id LIKE 'orphan-{symbol}%'` AND `state = FILLED`. Don't match against canceled/expired orphans from previous days.

### D6. Ghost Positions: DEFERRED

**Decision**: Defer ghost position detection to a future step.

**Rationale (from Code Simplicity Reviewer):** Ghost detection (local FILLED entry with no broker position) adds ~30% of the implementation complexity but covers an edge case that only happens when positions are closed externally while the system is down. The system can safely operate without it — the worst case is stale local state that doesn't affect real broker positions. When TradingEngine is built, strategy evaluation will naturally discover the mismatch.

**If needed later**: Check local FILLED entries against `broker_positions`. If symbol not present, search `broker_recent_orders` for a filled exit. Create Trade record or mark `externally_closed`.

### D7. Stop Quantity: Use Broker Position

**Decision**: Emergency stop quantity = `broker_position.qty`, not `local_order.qty_filled`.

**Context**: The broker is the source of truth for current position size. Multiple entries, partial fills, or manual trades could make the local qty_filled inaccurate. The stop must protect the **entire** position.

### D8. Idempotency: Required

**Decision**: Reconciliation must be safe to run multiple times (crash during reconciliation → re-run on next startup).

**Guards**:
- Skip orders already in terminal states
- Check for existing active stop before placing a new one
- Check for existing orphan records (by symbol + "orphan" correlation prefix) before creating duplicates

### D9. Startup Sequence Order

```
1. Connect to broker (REST only, no WebSocket yet)
2. Acquire reconciliation lock (prevents WebSocket events during reconciliation)
3. Run StartupReconciler.reconcile()
   a. Fetch broker positions + orders (parallel via asyncio.gather)
   b. Reconcile local order states
   c. Cancel orphan broker orders
   d. Protect unprotected positions (orphans + existing)
4. Reconstruct CircuitBreaker from today's trades
5. Release reconciliation lock
6. (Future: warm-up indicators via REST historical bars)
7. (Future: subscribe to WebSocket streams)
8. (Future: begin strategy evaluation)
```

Steps 6–8 are TradingEngine work (Step 7). This plan covers steps 2–5.

**Reconciliation lock (from Security Sentinel):** An `asyncio.Lock` that is held during reconciliation and checked before processing any WebSocket trade updates. Prevents race conditions where a fill event arrives while we're still reconciling (WebSocket subscription shouldn't be active yet, but defense in depth).

### D10. Orphan Broker Orders: Cancel on Startup

**Decision**: Open orders at broker with no matching local record → cancel via `broker.cancel_order()`. Log WARNING with order details.

**Context (from Architecture Strategist):** The original plan only handled orphan positions, not orphan orders. An open limit/stop order at the broker with no local record could fill unexpectedly during the trading day, creating an untracked position. Canceling is safer than leaving unknown orders live.

**Guard**: Only cancel orders that have no local `OrderStateModel` match by `broker_order_id`. Orders that DO have local records are handled in Phase 1 (order reconciliation).

### D11. Broker Response Validation

**Decision**: Sanity-check all broker-reported values before using them.

**Context (from Security Sentinel):** Broker REST responses are untrusted external input. Manipulated or corrupted data could lead to incorrect state corrections.

**Checks:**
- Position `qty` must be > 0 and <= `max_position_shares` (from RiskConfig, or a reasonable cap like 100,000)
- Position `avg_entry_price` must be > 0 and < 1,000,000 (reasonable equity price bound)
- Order `filled_qty` must be >= 0 and <= `qty`
- Fail CRITICAL + skip (don't abort) if any single record fails validation

## Technical Approach

### Reconciliation Algorithm (Simplified: 3 Phases)

```
SETUP:
  # Parallel fetch via asyncio.gather (saves ~400ms)
  broker_positions, broker_open_orders, broker_recent_orders = await asyncio.gather(
      asyncio.wait_for(broker.get_positions(), timeout=10.0),
      asyncio.wait_for(broker.get_open_orders(), timeout=10.0),
      asyncio.wait_for(broker.get_recent_orders(24), timeout=10.0),
  )
  # Validate all broker responses (D11)
  # Build lookup: broker_order_map = {order.broker_order_id: order for order in ...}
  local_nonterminal_orders: list[OrderStateModel]  # WHERE state NOT IN terminal

PHASE 1: Reconcile local orders against broker
  # 1a. Orders with broker_id → match against broker state
  For each local order WHERE broker_id IS NOT NULL AND state NOT terminal:
    broker_order = broker_order_map.get(broker_id)
    If not found:
      broker_order = await get_order_status(broker_id)  # individual fallback
    If still not found:
      Log WARNING "broker_order_not_found", skip
      Continue
    Map broker status → local OrderState (module-level STATUS_MAP dict)
    If mapped_state != local_state:
      force_transition(order, mapped_state, fill_data_from_broker)

  # 1b. PENDING_SUBMIT with no broker_id → stale
  For each local order WHERE broker_id IS NULL AND state = PENDING_SUBMIT:
    force_transition(order, SUBMIT_FAILED, detail="no_broker_id_on_startup")

  # 1c. Orphan broker orders → cancel (D10)
  local_broker_ids = {o.broker_id for o in local_nonterminal_orders if o.broker_id}
  For each broker_open_order:
    If broker_open_order.broker_order_id NOT in local_broker_ids:
      await broker.cancel_order(broker_open_order.broker_order_id)
      Log WARNING "orphan_broker_order_canceled"

PHASE 2: Reconcile positions (orphan detection + stop protection, merged)
  For each broker_position:
    # Validate broker response (D11: qty > 0, avg_entry_price > 0)
    If validation fails: log CRITICAL, skip this position

    # Check for local match
    Find local FILLED entry order matching position symbol
    If no match found:
      # Orphan: create synthetic record with deterministic ID
      correlation_id = f"orphan-{symbol}-{today_YYYYMMDD}"
      If NOT already exists (dedup check):
        Create synthetic OrderStateModel (FILLED, role=ENTRY, strategy="unknown")
        Log WARNING "orphan_position_detected"

    # Check for active stop protection
    Find active (non-terminal) stop-loss order for this symbol
    If no active stop found:
      # Guard: avg_entry_price must be > 0 and not NULL
      emergency_price = (avg_entry_price * (1 - emergency_stop_pct)).quantize(Decimal("0.01"))
      If emergency_price <= 0: log CRITICAL, skip
      await submit_stop_loss(symbol, position.qty, emergency_price)
      Log CRITICAL "emergency_stop_placed"

PHASE 3: Reconstruct CircuitBreaker
  today_trades = query TradeModel WHERE closed_at >= today's market open
  circuit_breaker.reconstruct_from_trades(today_trades, start_of_day_equity)
```

### Research Insights: Performance

**Parallelization opportunities (from Performance Oracle):**

| Optimization | Savings | How |
|---|---|---|
| Parallel broker fetches (3 calls) | ~400ms | `asyncio.gather` in SETUP |
| Parallel emergency stop placement | ~800ms | `asyncio.gather` across positions needing stops |
| Parallel Phase 1 fallback lookups | ~800ms | `asyncio.gather` for individual get_order_status() calls |
| Timeout wrapper | prevents hang | `asyncio.wait_for(coro, timeout=10.0)` on each broker call |

**Estimated worst case**: Drops from ~9.6s (sequential) to ~1.85s (parallel) for 5 positions with fallback lookups.

### Research Insights: Data Integrity

**Atomic force-transition (from Data Integrity Guardian):**

Each `force_transition()` must be a single DB transaction containing:
1. `UPDATE order_state SET state = :new_state, qty_filled = :qty, avg_fill_price = :price`
2. `INSERT INTO order_event (order_id, event_type, from_state, to_state, detail, ...)`

Never write the state update without the audit event. Use the same `async with session.begin():` pattern from `OrderManager._transition_order()`.

**NULL avg_fill_price guard:** If broker reports a FILLED order with `filled_avg_price = None`, log CRITICAL and skip the trade record creation (don't create a Trade with `Decimal("0")` P&L — that's corrupted data).

### Broker Status → Local State Mapping

**Implementation (from Kieran Python Reviewer):** Module-level `STATUS_MAP` dict + wrapper function that raises `ReconciliationFatalError` on unknown status. No inline if/elif chains.

```python
STATUS_MAP: dict[BrokerOrderStatus, OrderState | None] = {
    BrokerOrderStatus.NEW: OrderState.SUBMITTED,
    BrokerOrderStatus.ACCEPTED: OrderState.ACCEPTED,
    BrokerOrderStatus.FILLED: OrderState.FILLED,
    BrokerOrderStatus.PARTIALLY_FILLED: OrderState.PARTIALLY_FILLED,
    BrokerOrderStatus.CANCELED: OrderState.CANCELED,
    BrokerOrderStatus.EXPIRED: OrderState.EXPIRED,
    BrokerOrderStatus.REJECTED: OrderState.REJECTED,
    BrokerOrderStatus.PENDING_CANCEL: None,  # transient, no change
    BrokerOrderStatus.REPLACED: None,         # handled via broker_id update
}

def map_broker_status(status: BrokerOrderStatus) -> OrderState | None:
    """Map broker status to local OrderState. Returns None for transient states."""
    if status not in STATUS_MAP:
        raise ReconciliationFatalError(f"Unknown broker status: {status}")
    return STATUS_MAP[status]
```

### Reconciliation Event Types

New `event_type` values for `OrderEventModel` (reduced from 5 to 3 per Simplicity Reviewer — `externally_closed` deferred with ghost detection):

| Event Type | When Used |
|---|---|
| `reconciled` | State forced to match broker (detail: `"old={old}, broker={broker}"`) |
| `orphan_created` | Synthetic record for broker position with no local match |
| `emergency_stop` | Stop-loss placed during reconciliation |

**Note**: `stale_cleared` merged into `reconciled` (it's just a state correction). `externally_closed` deferred with ghost detection (D6).

## Files to Create

### `backend/app/orders/startup_reconciler.py`

Main reconciliation module. Renamed from `reconciliation.py` / `ReconciliationService` per Kieran + Architecture reviewers.

```python
class ReconciliationFatalError(Exception):
    """Raised when reconciliation cannot proceed safely. Aborts startup."""

@dataclass(frozen=True)
class ReconciliationResult:
    """Structured result of reconciliation for logging and test assertions."""
    orders_reconciled: int       # state corrections (includes stale cleared)
    orphans_detected: int        # broker positions with no local match
    orphan_orders_canceled: int  # broker orders with no local match
    emergency_stops_placed: int  # positions that needed protection
    errors: list[str]            # non-fatal errors encountered

# Module-level status mapping
STATUS_MAP: dict[BrokerOrderStatus, OrderState | None] = { ... }

def map_broker_status(status: BrokerOrderStatus) -> OrderState | None: ...

class StartupReconciler:
    def __init__(
        self,
        broker: BrokerAdapter,
        session_factory: async_sessionmaker[AsyncSession],
        emergency_stop_pct: Decimal,
    ) -> None: ...

    async def reconcile(self) -> ReconciliationResult:
        """Run full reconciliation. Raises ReconciliationFatalError on fatal broker API failure."""
        ...

    async def _fetch_broker_state(self) -> tuple[list[Position], list[OrderStatus], list[OrderStatus]]:
        """Parallel fetch of positions + open orders + recent orders."""
        ...

    async def _reconcile_orders(self, ...) -> int:
        """Phase 1: Reconcile local orders against broker state."""
        ...

    async def _reconcile_positions(self, ...) -> tuple[int, int]:
        """Phase 2: Orphan detection + emergency stop protection."""
        ...

    async def _force_transition(self, order_id: int, new_state: OrderState, ...) -> None:
        """Atomic state + event write in single transaction."""
        ...

    async def _place_emergency_stop(self, symbol: str, qty: Decimal, price: Decimal) -> None:
        """Place stop via broker adapter. 3x retry + market sell fallback."""
        ...
```

**Dependencies**: `BrokerAdapter` (for broker state + stop placement), `async_sessionmaker` (for DB queries + writes). **No OrderManager dependency** — reconciler owns its own DB writes and broker calls.

**Size estimate**: ~250–350 lines (reduced from 300–400 due to phase elimination).

### `backend/tests/unit/test_startup_reconciler.py`

Unit tests using `FakeBrokerAdapter` + in-memory SQLite. Reduced from 20 to 14 tests (ghost detection deferred, related tests removed):

| Test | Scenario |
|---|---|
| `test_clean_startup_no_actions` | Empty DB, empty broker → zero actions |
| `test_clean_restart_no_actions` | DB matches broker → zero actions |
| `test_submitted_but_broker_filled` | Local SUBMITTED, broker FILLED → force FILLED, record fill |
| `test_submitted_but_broker_canceled` | Local SUBMITTED, broker CANCELED → force CANCELED |
| `test_accepted_but_broker_filled` | Local ACCEPTED, broker FILLED → force FILLED |
| `test_pending_submit_no_broker_id` | PENDING_SUBMIT, broker_id=NULL → SUBMIT_FAILED |
| `test_orphan_position_detected` | Broker has position, no local match → create orphan with deterministic ID |
| `test_orphan_broker_order_canceled` | Open broker order with no local match → canceled |
| `test_unprotected_position_gets_stop` | Position with no active stop → emergency stop placed |
| `test_protected_position_no_duplicate_stop` | Position with active stop → no action (idempotent) |
| `test_order_older_than_24h_individual_lookup` | Order not in recent batch → individual get_order_status() |
| `test_idempotent_double_run` | Run reconciliation twice → second run is no-op |
| `test_broker_api_read_failure_aborts` | get_positions() fails 3× → raises ReconciliationFatalError |
| `test_null_avg_fill_price_skips_trade` | Broker FILLED with NULL price → CRITICAL log, no trade record |

**Size estimate**: ~400–500 lines (14 tests × ~30 lines each).

### Research Insights: Testing

**From Pattern Recognition Specialist:**
- Each test should assert both the state change AND the audit event (OrderEventModel)
- Use `make_position()` and `make_order_status()` factories extensively
- The `test_idempotent_double_run` test is the most important — it validates the entire deduplication logic

**From Data Integrity Guardian:**
- `test_null_avg_fill_price_skips_trade` is critical — NULL prices in Trade records corrupt P&L calculations
- Add assertion that `ReconciliationResult.errors` contains the skip reason

### `backend/tests/integration/test_startup_reconciler.py`

Integration tests with full DB setup (in-memory aiosqlite):

| Test | Scenario |
|---|---|
| `test_full_crash_recovery_flow` | Entry filled while down, no stop → reconcile + place stop |
| `test_reconciliation_then_circuit_breaker` | Reconcile + CB reconstruction → CB state reflects today's trades |
| `test_reconciliation_with_multiple_strategies` | Orders from different strategies → all reconciled correctly |
| `test_parallel_broker_fetches` | Verify asyncio.gather is used (mock latency, check total time) |

**Size estimate**: ~250 lines.

## Files to Modify

### `backend/app/orders/state_machine.py`

Add security-gated `force_state()` method:

```python
def force_state(self, new_state: OrderState, *, _reconciliation: bool = False) -> None:
    """Force-set state without transition validation.

    Used ONLY during startup reconciliation to correct local state
    that diverged from broker while the system was down.

    Args:
        new_state: The target state to force.
        _reconciliation: Must be True. Guards against accidental misuse.

    Raises:
        RuntimeError: If _reconciliation is not True.
    """
    if not _reconciliation:
        raise RuntimeError("force_state() can only be called during reconciliation")
    self._state = new_state
```

~10 lines added.

### `backend/app/config.py`

Add `emergency_stop_pct` to `RiskConfig`:

```python
emergency_stop_pct: Decimal = Field(
    default=Decimal("0.02"),
    ge=Decimal("0.005"),
    le=Decimal("0.10"),
)
```

~5 lines added.

### `backend/app/broker/fake/broker.py`

Enhance `FakeBrokerAdapter` for reconciliation testing:

```python
def __init__(
    self,
    positions: list[Position] | None = None,
    account: AccountInfo | None = None,
    open_orders: list[OrderStatus] | None = None,        # NEW
    recent_orders: list[OrderStatus] | None = None,       # NEW
    order_statuses: dict[str, OrderStatus] | None = None, # NEW: broker_id → status
) -> None:
    ...
    self._open_orders = open_orders or []
    self._recent_orders = recent_orders or []
    self._order_statuses = order_statuses or {}

async def get_open_orders(self) -> list[OrderStatus]:
    return list(self._open_orders)

async def get_recent_orders(self, since_hours: int = 24) -> list[OrderStatus]:
    return list(self._recent_orders)

async def get_order_status(self, broker_order_id: str) -> OrderStatus:
    if broker_order_id in self._order_statuses:
        return self._order_statuses[broker_order_id]
    # Fall back to existing behavior
    ...
```

~25 lines modified.

### `backend/app/orders/order_manager.py`

**No changes.** Per Architecture Strategist + Simplicity Reviewer: the reconciler owns its own trade creation and stop placement via `BrokerAdapter` + `async_sessionmaker`. `_create_trade_record()` stays private. This avoids coupling to OrderManager's internal state expectations and keeps OrderManager's API surface unchanged.

### `backend/tests/factories.py`

Add new factories:

```python
def make_position(
    *,
    symbol: str = "AAPL",
    qty: Decimal = Decimal("100"),
    side: Side = Side.BUY,
    avg_entry_price: Decimal = Decimal("150.00"),
    market_value: Decimal = Decimal("15000.00"),
    unrealized_pl: Decimal = Decimal("0"),
    unrealized_pl_pct: Decimal = Decimal("0"),
) -> Position: ...

def make_order_status(
    *,
    broker_order_id: str = "broker-001",
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    qty: Decimal = Decimal("100"),
    order_type: OrderType = OrderType.STOP,
    status: BrokerOrderStatus = BrokerOrderStatus.ACCEPTED,
    filled_qty: Decimal = Decimal("0"),
    filled_avg_price: Decimal | None = None,
    submitted_at: datetime = _DEFAULT_TIMESTAMP,
) -> OrderStatus: ...
```

~40 lines added.

## Acceptance Criteria

### Functional

- [x] Reconciliation detects stale SUBMITTED order that broker shows as FILLED → updates local state and records fill details
- [x] Reconciliation detects stale SUBMITTED order that broker shows as CANCELED → updates local state
- [x] PENDING_SUBMIT orders with no `broker_id` are marked SUBMIT_FAILED on startup
- [x] Orphan positions (broker has position, no local record) create synthetic local records with deterministic IDs
- [x] Orphan broker orders (open orders at broker with no local record) are canceled
- [x] Every position without an active stop-loss gets an emergency stop placed (CRITICAL log)
- [x] Protected positions (with active stops) are NOT double-protected (idempotent)
- [x] Emergency stop uses `broker_position.qty` (not local qty_filled)
- [x] Emergency stop price = `(avg_entry_price * (1 - emergency_stop_pct)).quantize(Decimal("0.01"))` using Decimal math
- [x] NULL or zero `avg_entry_price` → CRITICAL log, skip stop placement (don't place zero-price stop)
- [x] Orders older than 24h are resolved via individual `get_order_status()` fallback
- [x] CircuitBreaker state is reconstructed from today's trades AFTER reconciliation
- [x] Reconciliation completes before any WebSocket subscription
- [x] Every reconciliation action is logged as an `OrderEventModel` with appropriate event type
- [x] `ReconciliationResult` contains accurate counts of all actions taken
- [x] Broker fetches are parallelized via `asyncio.gather`
- [x] `force_state()` is gated — raises RuntimeError if `_reconciliation=True` not passed

### Non-Functional

- [x] Reconciliation completes within 3 seconds for typical case (5 symbols, 5 positions) — parallel fetches
- [x] Broker API read failure (3× retry exhausted) raises `ReconciliationFatalError`
- [x] Emergency stop write failure uses 3× retry + market sell fallback
- [x] Running reconciliation twice produces identical end state (idempotent)
- [x] All monetary calculations use Decimal (no float)
- [x] Broker response values validated (qty > 0, price > 0, reasonable bounds)
- [x] mypy strict clean, ruff clean

### Quality Gates

- [x] All 19 unit tests pass (14 reconciler + 5 force_state)
- [x] All 4 integration tests pass
- [x] `force_state()` unit tests pass (including security gate test)
- [x] FakeBrokerAdapter enhancement tests pass
- [x] No existing tests broken by changes (485 total, 8 skipped)

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Crash during reconciliation itself | Low | High | Idempotency + deterministic IDs — re-run is safe |
| Emergency stop at wrong price | Low | Medium | Conservative 2% default + configurable + quantize() |
| Orphan position from manual trade | Medium | Low | Synthetic records + emergency stop |
| Broker API down during startup | Low | High | ReconciliationFatalError — refuse to trade blind |
| Double stop-loss for same position | Medium | Medium | Check for existing active stop before placing |
| 24h order window misses old orders | Medium | Medium | Individual `get_order_status()` fallback |
| NULL avg_fill_price from broker | Low | High | Guard: skip trade record, log CRITICAL |
| Race condition: WebSocket during reconciliation | Low | High | Reconciliation lock + WS not subscribed yet |
| Corrupted broker response (bad qty/price) | Very Low | High | Bounds-check validation on all broker data |
| Orphan broker order fills unexpectedly | Medium | Medium | Cancel orphan orders in Phase 1c |

## Implementation Phases

### Phase A: Foundation (~30% of effort)

1. Add security-gated `force_state()` to `OrderStateMachine` + tests (including RuntimeError gate test)
2. Add `ReconciliationFatalError` exception class
3. Add `emergency_stop_pct` to `RiskConfig` + test
4. Enhance `FakeBrokerAdapter` (open_orders, recent_orders, order_statuses, cancel tracking)
5. Add `make_position()` and `make_order_status()` to factories
6. Add `STATUS_MAP` + `map_broker_status()` function

### Phase B: Core Reconciliation (~50% of effort)

1. Create `ReconciliationResult` frozen dataclass
2. Create `StartupReconciler` class with constructor (broker, session_factory, emergency_stop_pct)
3. Implement `_fetch_broker_state()` with parallel `asyncio.gather` + timeout
4. Implement Phase 1: Order reconciliation (broker_id matching + force_transition + stale cleanup + orphan order cancel)
5. Implement Phase 2: Position reconciliation (orphan detection + emergency stop protection, merged)
6. Implement `_force_transition()` with atomic state + event write
7. Implement `_place_emergency_stop()` with 3× retry + market sell fallback
8. Implement broker response validation (D11)
9. Unit tests for each scenario (TDD — failing test first)

### Phase C: Integration + CircuitBreaker (~20% of effort)

1. Wire `CircuitBreaker.reconstruct_from_trades()` after reconciliation (Phase 3 of algorithm)
2. Integration test: full crash recovery flow
3. Integration test: reconciliation → CircuitBreaker reconstruction
4. Integration test: parallel broker fetches (mock latency)
5. Final lint/type check sweep

## References

### Internal

- Phase 1 plan reconciliation spec: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md:814-828`
- Step 4 deferred items: `docs/plans/2026-02-15-feat-step4-order-risk-management-plan.md:893`
- Order lifecycle architecture: `docs/solutions/architecture-decisions/order-lifecycle-and-risk-architecture.md`
- Alpaca threading bridge: `docs/solutions/integration-issues/alpaca-py-async-threading-bridge.md`
- OrderStateMachine: `backend/app/orders/state_machine.py`
- OrderManager: `backend/app/orders/order_manager.py`
- BrokerAdapter protocol: `backend/app/broker/broker_adapter.py`
- CircuitBreaker: `backend/app/risk/circuit_breaker.py`
- FakeBrokerAdapter: `backend/app/broker/fake/broker.py`
- DB models: `backend/app/models/order.py`
- Config: `backend/app/config.py`
- Test factories: `backend/tests/factories.py`

### Institutional Learnings Applied

- Atomic state + event writes in single transaction (from Step 4 compound)
- `force_state()` was explicitly deferred from Step 4 to Step 5
- Trade queue unbounded — fills never dropped (from Alpaca threading bridge)
- SQLite `batch_alter_table` destroys triggers (no migration needed for Step 5)
- Position sizing truncates DOWN (conservative, real money)
- CircuitBreaker: realized-only P&L, break-even counts as loss
- `FakeBrokerAdapter` for tests — no real API calls in unit tests
- In-memory aiosqlite for test isolation

### External Research (from Best Practices Researcher)

- NautilusTrader reconciliation pattern: deterministic identifiers, broker as source of truth
- pysystemtrade: startup = crash recovery (same code path), short-lived DB sessions
- Alpaca docs: REST-first reconciliation before WebSocket subscriptions
