---
status: complete
priority: p3
issue_id: "030"
tags: [plan, cleanup, documentation]
dependencies: []
---

# Merge duplicate plan sections 3+5 (.dockerignore)

## Problem Statement
Plan sections 3 and 5 both cover `.dockerignore` with overlapping and contradictory guidance. Section 3 says to add `tests/` to `.dockerignore`, while review found that excluding `tests/` breaks the development stage COPY. Confusing for implementation.

## Findings
- Flagged by: code-simplicity-reviewer
- Location: `docs/plans/2026-02-16-feat-docker-scaffolding-plan.md` (sections 3 and 5)
- Contradictory: section 3 excludes `tests/`, but P2-7 says don't exclude `tests/`
- Duplicate coverage of same topic

## Proposed Solutions

### Option 1: Merge into one section, remove tests/ exclusion (recommended)
- **Pros**: Clear, non-contradictory, single source of truth
- **Cons**: None
- **Effort**: Small (< 10 minutes)
- **Risk**: Low

## Recommended Action
Merge sections 3 and 5 into one coherent `.dockerignore` section. Remove `tests/` exclusion per P1-1/P2-7 findings. Clarify that `.dockerignore` goes in `backend/` not root.

## Technical Details
- **Affected Files**: `docs/plans/2026-02-16-feat-docker-scaffolding-plan.md`
- **Related Components**: Plan structure
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P3-11

## Acceptance Criteria
- [ ] Sections 3 and 5 merged into single coherent section
- [ ] No contradictory guidance about `tests/` exclusion
- [ ] References `backend/.dockerignore` (not root)

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready

**Learnings:**
- Duplicate plan sections create contradictions — merge early

## Notes
Source: Triage session on 2026-02-16
