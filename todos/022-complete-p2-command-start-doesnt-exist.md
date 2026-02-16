---
status: complete
priority: p2
issue_id: "022"
tags: [docker, bug, compose, cli]
dependencies: []
---

# command: ["start"] doesn't exist yet — docker compose up will crash

## Problem Statement
The plan sets `command: ["start"]` as the default for the app service. The `start` CLI subcommand is Step 7 (TradingEngine) which doesn't exist yet. Running `docker compose up` will fail immediately with `Error: No such command 'start'`.

## Findings
- Flagged by: code-simplicity-reviewer
- Location: `docker-compose.yml` (planned — command line)
- `start` subcommand planned for Step 7 TradingEngine
- Container will exit with code 2 on any `docker compose up`

## Proposed Solutions

### Option 1: Use command: ["--help"] with Step 7 comment (recommended)
- **Pros**: Safe default, shows available commands, documents intent
- **Cons**: None
- **Effort**: Small (< 10 minutes)
- **Risk**: Low

## Recommended Action
Set `command: ["--help"]` with a comment noting Step 7 will replace this with `["start"]`.

## Technical Details
- **Affected Files**: `docker-compose.yml` (new file)
- **Related Components**: CLI, docker compose workflow
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P2-3

## Acceptance Criteria
- [ ] Default command is `["--help"]` (not `["start"]`)
- [ ] Comment notes Step 7 will replace with `["start"]`
- [ ] `docker compose up` runs without error (shows help and exits cleanly)

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- User preference: use ["--help"] as safe default, note Step 7 will replace

**Learnings:**
- Don't reference future CLI commands in compose defaults — use safe fallback

## Notes
Source: Triage session on 2026-02-16
