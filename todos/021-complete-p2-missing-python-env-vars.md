---
status: complete
priority: p2
issue_id: "021"
tags: [docker, python, observability, logging]
dependencies: []
---

# Missing PYTHONDONTWRITEBYTECODE=1 and PYTHONUNBUFFERED=1

## Problem Statement
Two essential Python container environment variables are missing from the Dockerfile. `PYTHONUNBUFFERED=1` is critical for a trading system — without it, stdout is buffered and log output is delayed. `PYTHONDONTWRITEBYTECODE=1` prevents `__pycache__` write failures on read-only mounts and keeps the image clean.

## Findings
- Flagged by: kieran-python-reviewer
- Location: `backend/Dockerfile` (planned — no ENV directives)
- `PYTHONUNBUFFERED=1` is table stakes for any containerized Python app
- Especially critical for trading systems where real-time log visibility matters
- `PYTHONDONTWRITEBYTECODE=1` prevents noisy .pyc write failures

## Proposed Solutions

### Option 1: Add ENV directives near top of Dockerfile (recommended)
- **Pros**: Standard practice, zero downside, immediate benefit
- **Cons**: None
- **Effort**: Small (< 10 minutes)
- **Risk**: Low

## Recommended Action
Add near top of Dockerfile after FROM:
```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
```

## Technical Details
- **Affected Files**: `backend/Dockerfile` (new file)
- **Related Components**: Logging, container runtime behavior
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P2-1

## Acceptance Criteria
- [ ] `PYTHONDONTWRITEBYTECODE=1` set in Dockerfile
- [ ] `PYTHONUNBUFFERED=1` set in Dockerfile
- [ ] `docker compose logs` shows real-time output without buffering delays

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- PYTHONUNBUFFERED=1 is non-negotiable for containerized Python apps
- Especially critical for financial systems needing real-time log visibility

## Notes
Source: Triage session on 2026-02-16
