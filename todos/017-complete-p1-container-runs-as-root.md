---
status: complete
priority: p1
issue_id: "017"
tags: [security, docker, container-hardening]
dependencies: []
---

# Container runs as root — no USER directive

## Problem Statement
No `USER` directive in the Dockerfile. The container runs as root by default. Root access + writable volume mounts = full access to SQLite database, trade records, and environment variables if the container is compromised. For a financial system handling real money, this is unacceptable.

## Findings
- Flagged by: security-sentinel, kieran-python-reviewer
- Location: `backend/Dockerfile` (planned, not yet created)
- Root + writable volumes = full DB access if compromised
- Standard container security best practice violated

## Proposed Solutions

### Option 1: Add non-root user (appuser) after dependency installation
- **Pros**: Standard practice, minimal effort, significant security improvement
- **Cons**: None meaningful
- **Effort**: Small (< 30 minutes)
- **Risk**: Low

## Recommended Action
Add non-root user creation and USER directive to Dockerfile:
```dockerfile
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser
# Copy files with --chown=appuser:appuser
USER appuser
```

## Technical Details
- **Affected Files**: `backend/Dockerfile` (new file)
- **Related Components**: Docker image, volume mount permissions
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P1-2

## Acceptance Criteria
- [ ] Dockerfile includes `USER` directive with non-root user
- [ ] User created with specific UID/GID (not default)
- [ ] Application files owned by appuser
- [ ] Container processes run as non-root (verify with `docker exec ... whoami`)
- [ ] SQLite data directory writable by appuser

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- Root in containers is a security anti-pattern, especially with writable volume mounts
- Financial systems require defense-in-depth — non-root is baseline

## Notes
Source: Triage session on 2026-02-16
