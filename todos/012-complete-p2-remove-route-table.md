---
status: complete
priority: p2
issue_id: "012"
tags: [simplification, yagni, plan-edit]
dependencies: []
---

# Remove Route Table From Plan

## Problem Statement
The plan includes a `RouteTable` concept for mapping symbols to strategies, inspired by Jesse's multi-strategy routing. Phase 1 has exactly one strategy (Velez) applied to all symbols in `config.watchlist`. A route table is speculative infrastructure for multi-strategy support not needed until Phase 2+.

## Findings
- RouteTable maps symbol → strategy for multi-strategy support
- Phase 1 has one strategy (Velez) for all symbols
- `config.watchlist` already provides the symbol list
- Easy to add route table later when multi-strategy requirements are concrete
- Location: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`

## Proposed Solutions

### Option 1: Remove route table, use config.watchlist directly
- **Pros**: Simpler, no speculative abstraction, easy to refactor later
- **Cons**: None for Phase 1
- **Effort**: Small (plan edit)
- **Risk**: Low

## Recommended Action
1. Remove RouteTable class/concept from the plan
2. Use `config.watchlist` directly for symbol list
3. Hardwire single strategy (Velez) — `_resolve_strategy()` returns it for all symbols
4. When multi-strategy arrives in Phase 2+, design route table with real requirements

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-step7-trading-engine-plan.md`
- **Related Components**: Symbol-to-strategy mapping, _evaluate_strategy
- **Database Changes**: No

## Resources
- Original finding: Code Simplicity reviewer (S9)

## Acceptance Criteria
- [ ] RouteTable concept removed from plan
- [ ] Symbols sourced from `config.watchlist` directly
- [ ] Single strategy hardwired for Phase 1
- [ ] No multi-strategy infrastructure in Step 7

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending to ready

**Learnings:**
- One strategy + one symbol list = no routing needed. Add routing when the second strategy arrives.

## Notes
Source: Triage session on 2026-02-16
