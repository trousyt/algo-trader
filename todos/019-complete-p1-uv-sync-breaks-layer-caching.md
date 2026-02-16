---
status: complete
priority: p1
issue_id: "019"
tags: [docker, build-performance, layer-caching, uv]
dependencies: []
---

# uv sync runs twice — breaks Docker layer caching

## Problem Statement
The plan's Dockerfile runs `uv sync --frozen --no-dev` twice — once after copying `pyproject.toml`/`uv.lock`, and again after copying app code. The second `uv sync` re-resolves the full dependency tree, completely undermining Docker's layer caching. Every code change triggers a full dependency reinstall.

## Findings
- Flagged by: kieran-python-reviewer
- Location: `backend/Dockerfile` (planned — two `RUN uv sync` lines)
- The `--no-install-project` flag is the key to correct two-step pattern
- Without it, both steps install all deps + project, wasting the cache

## Proposed Solutions

### Option 1: --no-install-project + --no-editable pattern (recommended)
- **Pros**: Correct layer caching — deps cached until pyproject.toml/uv.lock change, project install is fast
- **Cons**: None
- **Effort**: Small (< 15 minutes)
- **Risk**: Low

## Recommended Action
Use the correct uv Docker pattern:
```dockerfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project   # deps only (cached layer)
COPY app/ ./app/
COPY alembic.ini alembic/ ./
RUN uv sync --frozen --no-dev --no-editable           # install project only (fast)
```

## Technical Details
- **Affected Files**: `backend/Dockerfile` (new file)
- **Related Components**: Build pipeline, developer iteration speed
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P1-4

## Acceptance Criteria
- [ ] First `uv sync` uses `--no-install-project` (deps only)
- [ ] Second `uv sync` uses `--no-editable` (project install only)
- [ ] Code-only changes rebuild in seconds, not minutes
- [ ] `docker compose build` uses cached dep layer when only app code changes

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- uv's --no-install-project flag is essential for Docker layer caching
- Two-step pattern: deps first (cached), project second (fast)

## Notes
Source: Triage session on 2026-02-16
