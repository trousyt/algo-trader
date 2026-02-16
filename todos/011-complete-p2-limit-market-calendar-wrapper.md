---
status: complete
priority: p2
issue_id: "011"
tags: [simplification, yagni, plan-edit]
dependencies: []
---

# Limit MarketCalendar Wrapper to 2 Methods Max

## Problem Statement
The plan creates a `MarketCalendar` wrapper around `exchange_calendars`. While a thin wrapper aids testability, it risks scope creep into a full calendar abstraction. The engine only needs to know two things: when does the market close today, and is it open now.

## Findings
- Plan proposes MarketCalendar wrapper class for testability
- DHH: "You need exactly one method: when does the market close today? Maybe a second."
- Code Simplicity reviewer flagged as potential YAGNI
- A thin wrapper (~30 lines) is justified for test injection without monkeypatching
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`

## Proposed Solutions

### Option 1: Keep wrapper, limit to 2 methods
- **Pros**: Testable without monkeypatching, scope-bounded, ~30 lines
- **Cons**: Still a wrapper (but justified)
- **Effort**: Small (plan edit — constrain interface)
- **Risk**: Low

## Recommended Action
Update the plan to explicitly constrain MarketCalendar to exactly 2 methods:
1. `next_close(now: datetime) -> datetime` — when does the market close today/next
2. `is_open(now: datetime) -> bool` — is the market open right now

No other methods. Add a plan comment: "Do not expand this interface. If you need more calendar logic, use `exchange_calendars` directly."

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: MarketCalendar wrapper, EOD scheduling
- **Database Changes**: No

## Resources
- Original finding: DHH reviewer (#12), Code Simplicity reviewer (S8)

## Acceptance Criteria
- [ ] MarketCalendar wrapper defined with exactly 2 methods: `next_close()` and `is_open()`
- [ ] Plan includes explicit "do not expand" constraint comment
- [ ] No additional calendar methods in any task

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready
- User chose Solution A: keep wrapper, limit to 2 methods

**Learnings:**
- Thin wrappers for testability are justified when bounded; the risk is scope creep, not the wrapper itself

## Notes
Source: Triage session on 2026-02-16
