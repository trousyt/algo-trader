---
status: complete
priority: p2
issue_id: "027"
tags: [docker, compose, developer-experience, config]
dependencies: []
---

# Mount mypy.ini and pyproject.toml for test/lint commands

## Problem Statement
`mypy.ini` and `pyproject.toml` contain critical config (strict mode, per-package ignores, pytest markers, ruff rules) but neither is volume-mounted in compose. Dev volume mounts override `app/` but config files at the container root are baked in at build time. Any config change requires a full image rebuild.

## Findings
- Flagged by: architecture-strategist (P3-5, P3-6)
- Elevated to P2 by Docker expert review — these are functional blockers
- Location: `docker-compose.yml` (planned — missing volume mounts)
- `backend/mypy.ini` — strict mode, per-package ignore_missing_imports
- `backend/pyproject.toml` — pytest asyncio_mode, testpaths, markers, ruff config

## Proposed Solutions

### Option 1: Add volume mounts for config files (recommended)
- **Pros**: Config changes reflected immediately, no rebuild needed
- **Cons**: None
- **Effort**: Small (< 15 minutes)
- **Risk**: Low

## Recommended Action
Add volume mounts to docker-compose.yml app service:
```yaml
volumes:
  - ./backend/mypy.ini:/app/mypy.ini
  - ./backend/pyproject.toml:/app/pyproject.toml
```

## Technical Details
- **Affected Files**: `docker-compose.yml` (new file)
- **Related Components**: mypy, pytest, ruff configuration
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P3-5, P3-6
- Docker expert review elevated to P2

## Acceptance Criteria
- [ ] `mypy.ini` mounted from host into container
- [ ] `pyproject.toml` mounted from host into container
- [ ] `docker compose run --rm app mypy app/` uses strict mode from host config
- [ ] Config changes on host reflected immediately without rebuild

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Elevated from P3 to P2 — functional blocker for dev workflow

**Learnings:**
- Volume mounts for app code aren't enough — config files need mounting too
- Build-time COPY is for the image, volume mounts are for dev iteration

## Notes
Source: Triage session on 2026-02-16
