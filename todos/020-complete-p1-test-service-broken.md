---
status: complete
priority: p1
issue_id: "020"
tags: [docker, bug, testing, dockerfile, compose]
dependencies: []
---

# Test service will fail — dev deps missing, entrypoint wrong, Dockerfile not merged

## Problem Statement
Two compounding bugs make the test service non-functional:
1. Section 1 of the plan shows a single-stage Dockerfile with `--no-dev` (no pytest/mypy/ruff). Section 4 sketches multi-stage but is never merged — it's a disconnected fragment.
2. Test entrypoint is `["uv", "run", "pytest"]` — running `docker compose run test ruff check` becomes `uv run pytest ruff check` (broken).

## Findings
- Consolidates: P1-5, P2-2 (missing target directives), P2-9 (unnecessary test service)
- Flagged by: kieran-python-reviewer, architecture-strategist, code-simplicity-reviewer
- Plan sections 1 and 4 are disconnected — no single coherent Dockerfile
- Without `target:` directives, both services build the last stage regardless
- Entrypoint bakes `pytest` in, breaking `ruff` and `mypy` commands

## Proposed Solutions

### Option 1: Single-stage Dockerfile with dev deps, single service (recommended)
- **Pros**: Simple, no multi-stage/target complexity, everything works via command override
- **Cons**: Dev deps in image (acceptable for dev — split in Step 9 for production)
- **Effort**: Small (< 1 hour)
- **Risk**: Low

### Option 2: Fix multi-stage + add target directives
- **Pros**: Separate prod/dev images now
- **Cons**: Premature complexity, more things to break, not needed until Step 9
- **Effort**: Medium (2-4 hours)
- **Risk**: Medium — more moving parts

## Recommended Action
Single-stage Dockerfile with dev deps included. Single `app` service in compose. Run tests via command override: `docker compose run --rm app pytest tests/ -v`. Split to multi-stage in Step 9 when production image is actually needed.

If keeping test service at all, use `profiles: [test]` and set entrypoint to `["uv", "run"]` with `command: ["pytest", "tests/", "-v", "--tb=short"]`.

## Technical Details
- **Affected Files**: `backend/Dockerfile` (new), `docker-compose.yml` (new)
- **Related Components**: Test pipeline, lint pipeline, developer workflow
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P1-5, P2-2, P2-9

## Acceptance Criteria
- [ ] One coherent Dockerfile (not disconnected sections)
- [ ] `docker compose run --rm app pytest tests/ -v` works
- [ ] `docker compose run --rm app ruff check app/ tests/` works
- [ ] `docker compose run --rm app mypy app/` works
- [ ] All dev dependencies available in container (pytest, mypy, ruff, hypothesis)

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- Single-stage with dev deps is the right level of complexity for local dev
- Multi-stage split belongs in Step 9 when production images are actually needed
- Entrypoint should be the base command, command should be the arguments

## Notes
Source: Triage session on 2026-02-16
