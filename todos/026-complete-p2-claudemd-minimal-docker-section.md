---
status: complete
priority: p2
issue_id: "026"
tags: [documentation, claude-md, docker, developer-experience]
dependencies: []
---

# CLAUDE.md — add focused Docker Development section, clarify when to use Docker

## Problem Statement
The plan proposes rewriting multiple existing CLAUDE.md sections, bundling a documentation rewrite into an infrastructure PR. Instead: add one new "Docker Development" section with a command table and clear guidance on when Docker is required vs. when host tools are fine.

## Findings
- Flagged by: code-simplicity-reviewer
- Location: `CLAUDE.md` (plan section 6 proposes 5+ section rewrites)
- Risk of breaking established workflow patterns with excessive edits
- Larger diff = more merge conflicts, harder review

## Proposed Solutions

### Option 1: Single additive section with clear scope (recommended)
- **Pros**: Minimal diff, clear guidance, no risk of breaking existing patterns
- **Cons**: None
- **Effort**: Small (< 30 minutes)
- **Risk**: Low

## Recommended Action
Add a single "Docker Development" section to CLAUDE.md that:

1. **Clarifies Docker scope**: Docker is for running anything that runs in production — tests, CLI commands, web app. Not for dev-only generation tools (alembic autogenerate, etc.)
2. **Command table**: Build, test, lint, typecheck, CLI commands — all via Docker
3. **When to use Docker vs. host**:
   - **Docker**: `pytest`, `ruff check`, `ruff format --check`, `mypy`, CLI (`algo-trader backtest`, `config`), web server
   - **Host**: `alembic revision --autogenerate`, `ruff format` (auto-fix), other dev-generation tools
4. Do NOT rewrite existing sections — just add the new section

## Technical Details
- **Affected Files**: `CLAUDE.md`
- **Related Components**: Developer workflow documentation
- **Database Changes**: No

## Resources
- Original finding: `memory/reviewer-findings/docker-plan-synthesis.md` P2-10
- User clarification: Docker-first scope is runtime/production code only

## Acceptance Criteria
- [ ] New "Docker Development" section added to CLAUDE.md
- [ ] Clear guidance on what runs in Docker vs. on host
- [ ] Command table with all Docker-wrapped commands
- [ ] Existing CLAUDE.md sections NOT modified (additive only)
- [ ] README.md updated with Docker commands in Usage/Development sections

## Work Log

### 2026-02-16 - Approved for Work
**By:** Claude Triage System
**Actions:**
- Issue approved during triage session
- Status changed from pending -> ready
- User specified: clarify Docker scope (production-like commands only, not migration generation)

**Learnings:**
- Docker-first doesn't mean Docker-everything — scope to production-like operations
- Additive doc changes are safer than rewrites

## Notes
Source: Triage session on 2026-02-16
