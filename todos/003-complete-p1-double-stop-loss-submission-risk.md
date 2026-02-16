---
status: complete
priority: p1
issue_id: "003"
tags: [architecture, safety, plan-edit]
dependencies: []
---

# Double Stop-Loss Submission Risk

## Problem Statement
`OrderManager._handle_fill()` has a code path to call `_submit_stop_loss_with_retry()` after entry fills (currently a `pass` no-op). The Step 7 plan has TradingEngine ALSO calling `submit_stop_loss()` after entry fills in `_handle_entry_fill`. If the OrderManager path ever gets a real implementation, duplicate stop-loss orders would be submitted for the same position.

## Findings
- `OrderManager._handle_fill()` has a `pass` placeholder for stop-loss after entry fill
- TradingEngine Task 3.3 `_handle_entry_fill` also submits stop-loss
- Two code paths for the same responsibility = duplicate orders risk
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md` Task 3.3
- Location: `backend/app/orders/order_manager.py` `_handle_fill()`

## Proposed Solutions

### Option 1: Clarify ownership in plan + code comment
- **Pros**: Single source of truth, prevents future confusion
- **Cons**: None
- **Effort**: Small (plan edit + code comment)
- **Risk**: Low

## Recommended Action
1. Update plan Task 3.3 to explicitly state stop-loss submission is TradingEngine's responsibility only
2. Add comment in `OrderManager._handle_fill()` that stop-loss is intentionally NOT handled here (engine owns it)
3. Remove or clearly mark the `pass` placeholder

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`, `backend/app/orders/order_manager.py`
- **Related Components**: Task 3.3 (_handle_entry_fill), OrderManager._handle_fill
- **Database Changes**: No

## Resources
- Original finding: Kieran reviewer (P1-F3)

## Acceptance Criteria
- [ ] Plan explicitly states TradingEngine owns stop-loss submission after entry fills
- [ ] OrderManager._handle_fill has comment clarifying engine ownership
- [ ] No duplicate stop-loss submission paths exist

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- When two components can both react to the same event (fill), ownership must be explicit and singular

## Notes
Source: Triage session on 2026-02-16
