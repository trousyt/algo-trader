---
status: complete
priority: p1
issue_id: "002"
tags: [plan-edit, clarity]
dependencies: []
---

# Remove Stale/Contradictory Code Snippets from Plan

## Problem Statement
The plan contains TWO versions of fill handling, trade update processing, and strategy evaluation code. The originals use wrong APIs (`set.add()` on a dict, `update.correlation_id` on TradeUpdate which doesn't have it, `await self.shutdown()` inside TaskGroup). The DEEPENED versions are correct but appear below the originals. An implementer reading top-to-bottom hits wrong code first.

## Findings
- Task 3.3: `_handle_entry_fill` uses `self._positions.add()` (set API) but `_positions` is `dict[str, Position]`
- Task 3.3: `_handle_fill` references `update.correlation_id`, `update.pnl`, `update.fill_price` — none exist on `TradeUpdate`
- Task 2.2: `_supervised_task` still calls `await self.shutdown()` inside TaskGroup (P1-4 deadlock)
- Task 3.2: Case 2 uses `corr_id` but should use `ref.local_id` via `_PendingEntryRef`
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md` Tasks 2.2, 3.2, 3.3

## Proposed Solutions

### Option 1: Remove original snippets, keep only DEEPENED versions
- **Pros**: Single source of truth, no ambiguity
- **Cons**: Loses the "before/after" context
- **Effort**: Small (plan edit only)
- **Risk**: Low

## Recommended Action
Remove all original (pre-DEEPENED) code snippets from Tasks 2.2, 3.2, and 3.3. The DEEPENED blocks become the only code in those sections.

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Tasks 2.2, 3.2, 3.3
- **Database Changes**: No

## Resources
- Original finding: Kieran reviewer (P1-F2, P1-F5), Code Simplicity reviewer (S11)

## Acceptance Criteria
- [ ] Only one version of each code snippet exists per task
- [ ] All code snippets use correct APIs (dict not set, OrderStateModel lookup not phantom fields)
- [ ] `_supervised_task` shows `self._shutdown_event.set()` + raise, not `await self.shutdown()`

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- Plan deepening layered corrections without removing originals, creating ambiguity

## Notes
Source: Triage session on 2026-02-16
