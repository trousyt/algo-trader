---
status: complete
priority: p1
issue_id: "004"
tags: [bug, api-mismatch, plan-edit]
dependencies: []
---

# CircuitBreaker.reconstruct_from_trades Signature Mismatch

## Problem Statement
The plan's startup sequence calls `await self._circuit_breaker.reconstruct_from_trades(self._session_factory, self._broker)` but the actual implementation takes `(today_trades: list[TradeModel], start_of_day_equity: Decimal)`. Three bugs: wrong arguments, `await` on a sync method, and missing pre-work to fetch trades/equity.

## Findings
- Actual signature: `reconstruct_from_trades(self, today_trades: list[TradeModel], start_of_day_equity: Decimal) -> None`
- Plan passes `session_factory` and `broker` — completely wrong types
- Plan uses `await` but method is synchronous
- Plan's D6 section correctly describes the equity estimation logic but the code snippet doesn't implement it
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md` Task 2.1 startup sequence (~line 540)
- Real implementation: `backend/app/risk/circuit_breaker.py:74`

## Proposed Solutions

### Option 1: Fix startup snippet to use correct API
- **Pros**: Matches real implementation, includes trade fetch + equity computation
- **Cons**: None
- **Effort**: Small (plan edit only)
- **Risk**: Low

## Recommended Action
Update the plan's startup code to:
1. Query today's trades from DB via session_factory
2. Compute start-of-day equity: `current_equity - sum(today's realized P&L)`
3. Call `self._circuit_breaker.reconstruct_from_trades(today_trades, start_of_day_equity)` (no await)

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Task 2.1 startup sequence, CircuitBreaker, D6 design decision
- **Database Changes**: No

## Resources
- Original finding: Kieran reviewer (P1-F4)
- Real API: `backend/app/risk/circuit_breaker.py:74`
- Existing tests: `backend/tests/unit/test_circuit_breaker.py:115`

## Acceptance Criteria
- [ ] Plan startup snippet calls `reconstruct_from_trades(today_trades, start_of_day_equity)` with correct types
- [ ] No `await` on the sync method
- [ ] Trade fetch and equity computation shown before the call
- [ ] Consistent with D6 design decision

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- Plan snippets can drift from real implementations — always cross-reference actual signatures

## Notes
Source: Triage session on 2026-02-16
