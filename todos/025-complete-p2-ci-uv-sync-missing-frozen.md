---
status: complete
priority: p2
issue_id: "025"
tags: [ci, build-consistency, uv, dependencies]
dependencies: []
---

# CI uses uv sync without --frozen — inconsistency with Docker

## Problem Statement
CI pipeline runs `uv sync` without `--frozen`, allowing the resolver to update dependencies. Docker pins to lockfile with `--frozen`. This creates a "works in CI, fails in Docker" (or vice versa) scenario where CI and Docker use different dependency versions.

## Findings
- Flagged by: kieran-python-reviewer
- Location: `.github/workflows/ci.yml` lines 32, 57, 80
- All three jobs (lint, typecheck, test) use bare `uv sync`
- Docker plan uses `uv sync --frozen` — correct, but inconsistent with CI
- Out of scope for Docker PR — separate CI fix

## Proposed Solutions

### Option 1: Add --frozen to CI uv sync commands (recommended)
- **Pros**: CI and Docker use identical dependency versions, reproducible
- **Cons**: CI will fail if lockfile is stale (good — forces lockfile maintenance)
- **Effort**: Small (< 15 minutes)
- **Risk**: Low

## Recommended Action
Update `.github/workflows/ci.yml` — change all three `uv sync` to `uv sync --frozen`. Separate PR from Docker scaffolding.

## Technical Details
- **Affected Files**: `.github/workflows/ci.yml`
- **Related Components**: CI pipeline, dependency resolution
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P2-8

## Acceptance Criteria
- [ ] All `uv sync` in CI use `--frozen` flag
- [ ] CI fails if `uv.lock` is out of date (forces maintenance)
- [ ] CI and Docker use identical dependency versions

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Noted as separate PR from Docker scaffolding

**Learnings:**
- uv sync without --frozen allows silent dependency drift between environments
- All environments (CI, Docker, local) should pin to the same lockfile

## Notes
Source: Triage session on 2026-02-16
Separate PR from Docker scaffolding work.
