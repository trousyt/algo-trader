---
status: complete
priority: p1
issue_id: "005"
tags: [bug, deadlock, plan-edit]
dependencies: ["002"]
---

# Supervised Task Still Calls await self.shutdown() Inside TaskGroup

## Problem Statement
The original `_supervised_task` snippet in Task 2.2 calls `await self.shutdown()` when max retries are exceeded. `shutdown()` calls `task_group.cancel()` which cancels the very task calling it — a deadlock inside structured concurrency. The DEEPENED version correctly uses `self._shutdown_event.set()` + `raise`, but the original snippet still exists.

## Findings
- Original Task 2.2 snippet: `await self.shutdown()` on max retries exceeded
- `shutdown()` cancels the TaskGroup, which cancels the calling task — deadlock
- DEEPENED correction uses `self._shutdown_event.set()` + `raise RuntimeError(...)` — correct pattern
- Both versions coexist in the plan, reader hits wrong one first
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md` Task 2.2
- Overlaps with Issue #002 (remove stale snippets) but this is the specific deadlock risk

## Proposed Solutions

### Option 1: Ensure Issue #002 removes the original Task 2.2 snippet
- **Pros**: Single fix covers both issues
- **Cons**: Must verify Task 2.2 is explicitly in Issue #002's scope
- **Effort**: None additional (covered by dependency)
- **Risk**: Low

## Recommended Action
Verify that when Issue #002 is resolved, the original Task 2.2 `_supervised_task` snippet with `await self.shutdown()` is removed. Only the DEEPENED version with `self._shutdown_event.set()` + `raise` should remain.

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Task 2.2 (_supervised_task), shutdown lifecycle
- **Database Changes**: No

## Resources
- Original finding: Kieran reviewer (P1-F5)
- Deadlock pattern: `await self.shutdown()` inside TaskGroup cancels calling task
- Correct pattern: `self._shutdown_event.set()` + `raise` to propagate up to TaskGroup

## Acceptance Criteria
- [ ] Only one version of `_supervised_task` exists in Task 2.2
- [ ] That version uses `self._shutdown_event.set()` + `raise`, NOT `await self.shutdown()`
- [ ] No deadlock risk from shutdown inside TaskGroup

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready
- Dependency on Issue #002 noted

**Learnings:**
- Never call a method that cancels a TaskGroup from within a task managed by that TaskGroup
- asyncio structured concurrency requires propagating errors UP, not calling shutdown DOWN

## Notes
Source: Triage session on 2026-02-16
