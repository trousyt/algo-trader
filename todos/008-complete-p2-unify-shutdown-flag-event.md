---
status: complete
priority: p2
issue_id: "008"
tags: [simplification, plan-edit]
dependencies: []
---

# Remove _shutdown_requested Bool, Use _shutdown_event.is_set() Only

## Problem Statement
The plan has both `self._shutdown_requested: bool` and `self._shutdown_event: asyncio.Event()` serving the same purpose — signaling shutdown. This duality means two fields must be kept in sync. `asyncio.Event` already provides `.is_set()` for boolean checks AND `.wait()` for interruptible sleep.

## Findings
- `_shutdown_requested` is a plain bool, checked in loops and handlers
- `_shutdown_event` is an asyncio.Event, used for `await event.wait()` interruptible sleeps
- Both are set during shutdown — redundant
- `_shutdown_event.is_set()` is a direct drop-in replacement for `_shutdown_requested`
- Flagged by: Code Simplicity reviewer (S13), Kieran reviewer (P2-F8)
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md` Task 2.1 (__init__), throughout handlers

## Proposed Solutions

### Option 1: Remove _shutdown_requested, use _shutdown_event.is_set()
- **Pros**: Single source of truth, one fewer field, no sync risk
- **Cons**: None — `.is_set()` is identical semantics
- **Effort**: Small (plan edit — remove field, find/replace checks)
- **Risk**: Low

## Recommended Action
1. Remove `self._shutdown_requested = False` from `__init__`
2. Replace all `self._shutdown_requested = True` with `self._shutdown_event.set()`
3. Replace all `if self._shutdown_requested:` with `if self._shutdown_event.is_set():`

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Task 2.1 (__init__), shutdown handler, bar loop, trade update loop
- **Database Changes**: No

## Resources
- Original finding: Code Simplicity reviewer (S13), Kieran reviewer (P2-F8)

## Acceptance Criteria
- [ ] `_shutdown_requested` field removed from plan
- [ ] All shutdown checks use `_shutdown_event.is_set()`
- [ ] `_shutdown_event.set()` is the sole shutdown signal mechanism

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- asyncio.Event serves dual purpose: awaitable signal AND boolean flag via .is_set()

## Notes
Source: Triage session on 2026-02-16
