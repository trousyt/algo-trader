---
status: complete
priority: p2
issue_id: "024"
tags: [docker, compose, developer-experience, volumes]
dependencies: []
---

# Read-only mounts (:ro) add friction with no current benefit

## Problem Statement
The plan mounts code volumes as read-only (`:ro`). For single-developer local dev, this adds friction with no meaningful security benefit. Tools like pytest (coverage output), ruff (cache), or any future dev tool that writes to the working directory will fail unexpectedly.

Note: Docker-first scope is runtime/production code only (tests, CLI, web app). Migration generation (`alembic revision --autogenerate`) runs on host, not in Docker.

## Findings
- Flagged by: code-simplicity-reviewer
- Location: `docker-compose.yml` (planned — volume mounts with `:ro`)
- Security benefit is negligible for local dev environment
- Can cause unexpected write failures from dev tooling inside container

## Proposed Solutions

### Option 1: Drop :ro from all dev volume mounts (recommended)
- **Pros**: Unblocks alembic, all dev tools work, consistent Docker-first workflow
- **Cons**: None meaningful for local dev
- **Effort**: Small (< 10 minutes)
- **Risk**: Low

## Recommended Action
Remove `:ro` from all volume mounts in docker-compose.yml. Add `:ro` back in Step 9 for production configuration if needed.

## Technical Details
- **Affected Files**: `docker-compose.yml` (new file)
- **Related Components**: Developer workflow, alembic migrations
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P2-6

## Acceptance Criteria
- [ ] No `:ro` on dev volume mounts
- [ ] Dev tools (pytest, ruff) can write to mounted directories without errors

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- :ro mounts are security theater for local dev — save for production config

## Notes
Source: Triage session on 2026-02-16
