---
status: complete
priority: p1
issue_id: "016"
tags: [security, build, docker, dockerignore]
dependencies: []
---

# .dockerignore in wrong location — build context is backend/, not root

## Problem Statement
Docker reads `.dockerignore` from the build context root. Since `context: backend` in docker-compose.yml, the root-level `.dockerignore` is completely ignored. This means `.venv/` (hundreds of MB), `.env` (brokerage API keys), `data/`, and all cache dirs get sent to the Docker daemon and potentially baked into image layers.

## Findings
- Consolidates: P1-1, P2-7, DE-1, DE-3 from docker plan review
- Location: `.dockerignore` (root — wrong), `backend/.dockerignore` (missing)
- ALL 4 reviewers flagged this independently
- `.venv/` alone can be 500MB+ of Windows-compiled packages useless in Linux container
- `.env` contains real Alpaca brokerage API keys

## Proposed Solutions

### Option 1: Create backend/.dockerignore (recommended)
- **Pros**: Correct location for build context, prevents API key leakage, fast builds
- **Cons**: None
- **Effort**: Small (< 30 minutes)
- **Risk**: Low

## Recommended Action
Create `backend/.dockerignore` with proper exclusions. Do NOT exclude `tests/` (let Dockerfile stages manage). Do NOT exclude `uv.lock` (needed for `--frozen`).

Exclusions needed:
- `.venv/`
- `.env`, `.env.*`
- `data/`
- `__pycache__/`
- `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`
- `*.pyc`, `*.pyo`
- `*.egg-info/`, `dist/`, `build/`

## Technical Details
- **Affected Files**: `backend/.dockerignore` (create new)
- **Related Components**: Docker build context, image security
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P1-1, P2-7
- Docker expert review: DE-1, DE-3

## Acceptance Criteria
- [ ] `backend/.dockerignore` exists with proper exclusions
- [ ] `.venv/` excluded from build context
- [ ] `.env` excluded from build context
- [ ] `uv.lock` NOT excluded (needed for frozen installs)
- [ ] `tests/` NOT excluded (managed by Dockerfile stages)
- [ ] `docker compose build` sends minimal context to daemon

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- Docker resolves .dockerignore relative to build context root, not project root
- When build context is a subdirectory, root .dockerignore is 100% ignored

## Notes
Source: Triage session on 2026-02-16
