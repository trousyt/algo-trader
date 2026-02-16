---
status: complete
priority: p1
issue_id: "001"
tags: [architecture, yagni, plan-edit]
dependencies: []
---

# Apply S1-S4 Simplifications (Plan Contradicts Itself)

## Problem Statement
The plan identifies 4 correct simplifications (S1-S4) but the implementation phases ignore all of them. Task 1.2 builds the event bus (S1 says delete). Task 1.1 builds the scanner protocol (S2 says inline). Task 1.3 builds safety.py (S3 says inline). Task 1.1 adds `force_close_eod` (S4 says remove). All 3 reviewers flagged this as the #1 issue.

## Findings
- S1: Remove EngineEventBus + LogListener (~220 LOC saved) — use structlog directly
- S2: Inline StaticScanner — `symbols = list(config.watchlist)` (~45 LOC saved)
- S3: Inline safety check into `TradingEngine.start()` (~40 LOC saved)
- S4: Remove `force_close_eod` Strategy ABC property (~10 LOC saved)
- Total: ~255 LOC saved + associated tests
- Location: Tasks 1.1, 1.2, 1.3 in `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`

## Proposed Solutions

### Option 1: Edit plan to apply all S1-S4 inline
- **Pros**: Clean plan, no contradictions, implementer has clear instructions
- **Cons**: None
- **Effort**: Small (plan edit only)
- **Risk**: Low

## Recommended Action
Delete Task 1.2 entirely. Remove scanner/force_close_eod from Task 1.1. Inline safety check into `start()`. Replace all `_event_bus.emit()` with `log.info()` calls. Strike through or remove contradictory code snippets.

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Tasks 1.1, 1.2, 1.3, acceptance criteria
- **Database Changes**: No

## Resources
- Original finding: DHH reviewer (#1-5), Kieran reviewer (P1-F1), Code Simplicity reviewer (S1-S4 validation)

## Acceptance Criteria
- [ ] Task 1.2 (EngineEventBus) deleted from plan
- [ ] All `_event_bus.emit()` replaced with structlog calls in code snippets
- [ ] Scanner protocol removed from Task 1.1
- [ ] `force_close_eod` removed from Task 1.1
- [ ] safety.py inlined into `TradingEngine.start()` or `_verify_paper_mode()`
- [ ] No contradictions between simplification table and implementation tasks

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- All 3 reviewers independently flagged this as the top issue
- Plan deepening process added contradictions by layering corrections without removing originals

## Notes
Source: Triage session on 2026-02-16
