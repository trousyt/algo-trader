---
status: complete
priority: p3
issue_id: "028"
tags: [docker, dockerfile, cleanup]
dependencies: []
---

# Remove no-op RUN mkdir -p data from Dockerfile

## Problem Statement
The Dockerfile has `RUN mkdir -p data` to create the SQLite directory. The compose file mounts `./backend/data:/app/data` — the volume mount creates the directory automatically, making the `mkdir` a dead layer in the image.

## Findings
- Flagged by: kieran-python-reviewer
- Location: `backend/Dockerfile` (planned)
- Volume mount overrides any directory created at build time
- Dead layer adds unnecessary image history

## Proposed Solutions

### Option 1: Remove the mkdir line (recommended)
- **Pros**: Cleaner Dockerfile, no dead layers
- **Cons**: None
- **Effort**: Small (< 5 minutes)
- **Risk**: Low

## Recommended Action
Remove `RUN mkdir -p data` from Dockerfile.

## Technical Details
- **Affected Files**: `backend/Dockerfile` (new file)
- **Related Components**: None
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P3-7

## Acceptance Criteria
- [ ] No `mkdir -p data` in Dockerfile
- [ ] SQLite directory still works via volume mount

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready

**Learnings:**
- Volume mounts create directories automatically — no need for build-time mkdir

## Notes
Source: Triage session on 2026-02-16
