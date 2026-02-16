---
status: complete
priority: p1
issue_id: "018"
tags: [security, docker, supply-chain, reproducibility]
dependencies: []
---

# uv:latest tag is unpinned — supply chain risk + non-reproducible builds

## Problem Statement
`COPY --from=ghcr.io/astral-sh/uv:latest` means builds are non-reproducible and vulnerable to supply chain attacks. The `latest` tag is a moving target — a compromised uv release could inject malicious code into the build. For a financial system with brokerage API access, this is unacceptable.

## Findings
- Flagged by: security-sentinel, kieran-python-reviewer, code-simplicity-reviewer
- Location: `backend/Dockerfile` (planned — COPY --from line)
- CI also uses `version: "latest"` in `setup-uv@v4` (related but separate fix)
- Docker image pinning is higher risk since COPY --from pulls an entirely separate image

## Proposed Solutions

### Option 1: Pin to specific version tag (recommended)
- **Pros**: Reproducible builds, known-good version, easy to update intentionally
- **Cons**: Must manually update when new uv versions release
- **Effort**: Small (< 15 minutes)
- **Risk**: Low

### Option 2: Pin with digest
- **Pros**: Maximum reproducibility, tamper-proof
- **Cons**: Harder to read, must look up digest on each update
- **Effort**: Small (< 15 minutes)
- **Risk**: Low

## Recommended Action
Pin to specific version tag: `COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /usr/local/bin/uv`. Check current uv version used in project and match it.

## Technical Details
- **Affected Files**: `backend/Dockerfile` (new file)
- **Related Components**: Build pipeline, dependency resolution
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P1-3

## Acceptance Criteria
- [ ] uv image pinned to specific version (not `latest`)
- [ ] Version matches what CI and local dev use
- [ ] `docker compose build` produces reproducible image

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- Ready to be picked up and worked on

**Learnings:**
- Never use :latest in COPY --from for financial systems
- Supply chain attacks via container images are a real threat vector

## Notes
Source: Triage session on 2026-02-16
