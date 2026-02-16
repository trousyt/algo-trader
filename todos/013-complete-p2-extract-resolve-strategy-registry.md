---
status: complete
priority: p2
issue_id: "013"
tags: [architecture, dry, plan-edit]
dependencies: []
---

# Extract _resolve_strategy to Shared Registry

## Problem Statement
`_resolve_strategy()` maps a strategy name string to a Strategy class. It exists in `BacktestRunner` and will be duplicated in `TradingEngine`. This is the sole concrete boundary between the engine and strategy implementations — it should live in one place.

## Findings
- `BacktestRunner._resolve_strategy()` currently maps `{"velez": VelezStrategy}`
- TradingEngine will need the identical mapping
- Both are the same simple dict lookup
- Kieran flagged as DRY violation
- Location: `backend/app/backtest/runner.py` (_resolve_strategy), plan Task 2.1

## Proposed Solutions

### Option 1: Extract to shared strategy_registry.py
- **Pros**: Single source of truth, both runners import from same place
- **Cons**: New file, but trivially small
- **Effort**: Small (plan edit + refactor BacktestRunner during implementation)
- **Risk**: Low

## Recommended Action
1. Create `backend/app/strategy/registry.py` with a `resolve_strategy(name: str) -> type[Strategy]` function
2. Simple dict: `{"velez": VelezStrategy}`
3. Update plan to use registry in TradingEngine
4. During implementation, refactor BacktestRunner to use the same registry

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`, `backend/app/backtest/runner.py` (refactor during impl)
- **Related Components**: BacktestRunner._resolve_strategy, TradingEngine strategy loading
- **Database Changes**: No

## Resources
- Original finding: Kieran reviewer (P2-F4)
- Existing implementation: `backend/app/backtest/runner.py`

## Acceptance Criteria
- [ ] Plan references shared strategy registry instead of inline _resolve_strategy
- [ ] Registry module location specified in plan
- [ ] BacktestRunner refactor noted as part of implementation

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- When two components need the same mapping, extract it before the second copy exists

## Notes
Source: Triage session on 2026-02-16
