---
status: complete
priority: p2
issue_id: "023"
tags: [docker, compose, signal-handling, architecture]
dependencies: []
---

# Missing init: true, stop_signal, stop_grace_period in docker-compose

## Problem Statement
The compose file has no `init: true`, `stop_signal`, or `stop_grace_period`. Without `init: true`, the Python process is PID 1 and won't properly handle SIGTERM — it also can't reap zombie processes from alpaca-py's threading bridge. This is the entire reason Docker scaffolding exists as a prerequisite for Step 7's `loop.add_signal_handler()` design.

## Findings
- Flagged by: architecture-strategist, Docker expert review
- Location: `docker-compose.yml` (planned — app service)
- `init: true` provides tini as PID 1 — reaps zombies, forwards signals correctly
- alpaca-py WebSocket uses threading bridge — zombie processes without init
- Default `stop_grace_period` (10s) may be insufficient for graceful position management
- This is foundational for Step 7's signal handling architecture

## Proposed Solutions

### Option 1: Add init, stop_signal, stop_grace_period to app service (recommended)
- **Pros**: Correct signal handling from day one, Step 7 just works, prevents zombie processes
- **Cons**: None
- **Effort**: Small (< 15 minutes)
- **Risk**: Low

## Recommended Action
Add to app service in docker-compose.yml:
```yaml
init: true              # tini reaps zombies, forwards signals
stop_signal: SIGTERM    # explicit (matches loop.add_signal_handler)
stop_grace_period: 30s  # allow time for graceful position management
```

## Technical Details
- **Affected Files**: `docker-compose.yml` (new file)
- **Related Components**: Signal handling, graceful shutdown, alpaca-py threading
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P2-4
- Docker expert review strongly endorsed this

## Acceptance Criteria
- [ ] `init: true` set on app service
- [ ] `stop_signal: SIGTERM` explicitly set
- [ ] `stop_grace_period: 30s` set (sufficient for graceful shutdown)
- [ ] `docker compose up` + Ctrl+C delivers SIGTERM via tini to Python process

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- init: true is critical when Python is the main process — PID 1 signal handling is unreliable
- tini reaps zombie processes from threading bridges (alpaca-py WebSocket)
- This is prerequisite infrastructure for Step 7's loop.add_signal_handler() design

## Notes
Source: Triage session on 2026-02-16
