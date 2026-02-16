---
status: complete
priority: p2
issue_id: "015"
tags: [simplification, yagni, deferral, plan-edit]
dependencies: []
---

# Defer PERF-2/PERF-4 and planned_stop_price Column

## Problem Statement
Two plan features add complexity without immediate payoff for Step 7:

1. **PERF-2/PERF-4**: Bar processing latency, signal-to-order latency, queue depth monitoring — performance instrumentation for an engine that hasn't run yet. Correctness first, optimize later.

2. **planned_stop_price column**: New nullable Decimal column on `order_state` to persist strategy-calculated stop prices for crash recovery. Without it, crash recovery falls back to `emergency_stop_pct` (which already works via StartupReconciler Phase 2). The column is a nice-to-have safety improvement but adds migration complexity.

## Findings
- PERF-2: Bar processing latency measurement — no baseline exists yet
- PERF-4: Queue depth monitoring — premature without knowing if queues are a bottleneck
- DHH: "Focus on correctness. Add time.monotonic() around warm-up only. Defer the rest."
- planned_stop_price: New DB column + migration 003 + populate in submit_entry + query on startup
- Fallback already exists: emergency_stop_pct via reconciler
- Code Simplicity reviewer: S10 (defer PERF), S14 (defer column)
- DHH: "one nullable Decimal column, populated in submit_entry, queried in startup. No new tables."
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md` Task 6.1, Task 2.1

## Proposed Solutions

### Option 1: Defer both to Step 8+
- **Pros**: Simpler Step 7, no migration, focus on correctness
- **Cons**: Crash recovery uses emergency_stop_pct fallback (conservative but imprecise)
- **Effort**: Small (plan edit — remove PERF-2/4 tasks, remove column from Task 2.1)
- **Risk**: Low — emergency_stop_pct fallback is safe, just wider than optimal

## Recommended Action
1. Remove PERF-2/PERF-4 instrumentation from plan. Keep only warm-up duration timing (5 lines)
2. Remove planned_stop_price column from Task 2.1 and migration scope
3. Note in plan that crash recovery uses emergency_stop_pct fallback for Step 7
4. Add both as Step 8 considerations

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Task 6.1 (performance), Task 2.1 (startup/migration), P1-16
- **Database Changes**: No (that's the point — deferring the migration)

## Resources
- Original finding: Code Simplicity reviewer (S10, S14), DHH reviewer (#13)

## Acceptance Criteria
- [ ] PERF-2 and PERF-4 removed from plan (only warm-up timing remains)
- [ ] planned_stop_price column removed from Step 7 scope
- [ ] Plan notes emergency_stop_pct fallback for crash recovery
- [ ] Both deferred items documented as Step 8 considerations

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- Performance instrumentation before first run is guessing at what to measure
- Emergency fallbacks that already work are acceptable for v1 — refine in v2

## Notes
Source: Triage session on 2026-02-16
