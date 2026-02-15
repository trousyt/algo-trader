# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Algo-trader is an algorithmic trading system for US equities. It performs technical analysis on real-time market data, detects trading signals, and executes trades automatically via brokerage APIs. This system handles real money - treat every change with production-grade rigor.

## Architecture

- **Backend**: Python 3.11+ with FastAPI
- **Frontend**: React web UI (dashboard, strategy config, backtesting)
- **Broker**: Alpaca via `DataProvider`/`BrokerAdapter` protocols from day one (IBKR upgrade planned for live trading)
- **Data**: Alpaca IEX via `DataProvider` protocol from day one (Polygon.io upgrade planned if IEX coverage insufficient)
- **Database**: SQLite (WAL mode) for all data initially. SQLAlchemy for ORM (enables future PostgreSQL/TimescaleDB migration). Add Parquet + DuckDB for analytical data only when SQLite performance becomes an issue.
- **Strategy Engine**: Jesse-inspired class inheritance. Deterministic - same strategy code runs in backtest, paper, and live mode.
- **AI Role**: Advisory ONLY. AI provides analysis, commentary, and confidence scores as inputs to the deterministic strategy engine. AI does NOT make trade decisions autonomously.
- **Notifications**: Discord webhooks (one-way initially; bot commands added later)
- **Containerization**: Docker

## Engineering Standards

### Development Workflow (non-negotiable)

This workflow MUST be followed for all work. Never skip phases or use ad-hoc planning.

1. **`/workflows:brainstorm`** — Ideation and exploration. Use before planning when requirements are unclear, multiple approaches exist, or the problem space needs exploration. Outputs go to `docs/brainstorms/`.
2. **`/workflows:plan`** — Work planning. ALWAYS use before any feature, refactor, or bug fix. Plans are stored in `docs/plans/` with date-prefixed filenames (e.g., `2026-02-15-feat-feature-name-plan.md`). Never store plans in `.claude/plans/` or other locations.
3. **`/workflows:work`** — Implementation and iteration. Execute the plan. Follow TDD (failing test first, minimal code to pass, refactor).
4. **`/workflows:review`** *(optional)* — Exhaustive code review using multi-agent analysis. **Mandatory when reading in changes from a PR.** Optional but recommended before merging any significant work.
5. **`/workflows:compound`** — Knowledge compounding. Run at end of each effort to capture learnings in `docs/solutions/`.

#### Phase Mechanics
- **Plan**: Spawns 3 parallel research agents (repo, framework, best-practices). Outputs blueprint with specific file changes
- **Work**: Creates git worktree for isolation. Executes step-by-step, runs tests/lint/typecheck after each change
- **Review**: Deploys 14+ specialized agents in parallel. Findings prioritized as P1 (critical/must-fix), P2 (important/should-fix), P3 (minor/nice-to-fix)
- **Compound**: Spawns 6 subagents to analyze, extract, classify, document. Output to `docs/solutions/[category]/` with YAML frontmatter (tags, category, module, symptoms)

#### Additional Commands
- **`/lfg [description]`** — Full autonomous pipeline: plan → work → review → compound
- **`/triage`** — Manual approval workflow for review findings
- **`/resolve_pr_parallel`** — Auto-fix all PR review findings
- **`/resolve_todo_parallel`** — Work through approved findings in `todos/` directory (`NNN-status-priority-description.md`)

#### Principles
- **80/20 time split**: 80% planning + review, 20% work + compounding
- **Three critical questions for AI output**: (1) What was the hardest decision? (2) What alternatives were rejected, and why? (3) What are you least confident about?

### Additional Process Requirements
- **Architectural review** - Run all architectural decisions through the `architecture-strategist` reviewer
- **Frontend UI/UX** - Use `frontend-design` and `web-artifacts-builder` skills for all design recommendations and decisions. UI must be A+++: user friendly, powerful, logical, consistent
- **Frontend code review** - All React/TypeScript code through `kieran-typescript-reviewer`
- **Frontend browser testing** - Use `webapp-testing` skill for all front-end browser testing
- **Security/penetration testing** - Use `ffuf-web-fuzzing` skill for web fuzzing and security testing
- **Tech stack decisions** - Always pass through user for approval. Never assume.
- **Test-driven development** - Use `tdd` skill. Write failing test first, then minimal code to pass, then refactor. No production code without a failing test
- **Comprehensive testing** - Unit tests, integration tests, e2e tests. All tests pass before merge

### Python Style
- **Formatter/Linter**: Ruff (replaces Black, Flake8, isort — single tool)
- **Type checker**: mypy with `strict = true`
- **Line length**: 88 (Ruff default)
- **Quotes**: Double quotes
- **Imports**: Ruff isort — stdlib → third-party → local, one import per line for multi-imports
- **Naming**: PEP 8 — `snake_case` functions/variables/modules, `PascalCase` classes, `UPPER_SNAKE` constants
- **Type hints**: Required on all function signatures and return types. Use `X | None` (not `Optional[X]`)
- **Docstrings**: Google style. Required on public classes and non-obvious public functions. Not required on trivial methods or when types make intent clear
- **Trailing commas**: Always on multi-line collections, arguments, and function parameters
- **f-strings**: Preferred over `.format()` and `%`
- **Exceptions**: Always catch specific exceptions — never bare `except:`
- **Decimal**: All monetary values (prices, P&L, equity, position sizing) — never `float`
- **Dataclasses**: `frozen=True` for value objects (Bar, Quote, IndicatorSet). Mutable dataclasses for state objects (Position, AccountInfo)
- **Enums**: `(str, Enum)` for string-based enumerations (serialization-friendly)
- **Constants**: Module-level `UPPER_SNAKE` — no magic numbers in logic

### TypeScript/React Style
- **Formatter**: Prettier
- **Linter**: ESLint v10 with flat config (`eslint.config.ts`) + `@typescript-eslint`
- **Strict mode**: `"strict": true` + `"noUncheckedIndexedAccess": true` in tsconfig.json
- **Naming**: `camelCase` variables/functions, `PascalCase` types/components, `UPPER_SNAKE` constants
- **Semicolons**: Yes (Prettier default)
- **Quotes**: Double quotes (consistent with Python)
- **Types**: `type` by default. `interface` only when extending or for class contracts
- **Components**: Function components only. Named exports (no default exports)
- **Return types**: Explicit on exported functions. Inferred OK for internal helpers

### Shared Standards
- No commented-out code — delete it, git has history
- No TODO without context — use `TODO(step3):` or `TODO(#issue):` format
- Error messages include context (symbol, order ID, state, correlation ID)
- No magic numbers — named constants for all thresholds and limits
- Prefer early returns over deeply nested conditionals

### Testing
- Unit tests: Strategy logic, risk management, order state machine
- Integration tests: Broker API, data pipeline, WebSocket connections
- E2E tests: Signal-to-execution flow, web UI workflows
- Strategy logic testable with mock market data (no live API calls in unit tests)

### Git
- Never add Co-Authored-By or Claude attribution to commits

### Safety
- Paper-trading-only by default. Explicit env var required to enable live trading
- Risk management (position sizing, daily loss limits) from Phase 1
- Order state machine with crash recovery and broker reconciliation
- Never commit API keys or secrets (`.env` + `.env.example`)

## Key Design Docs

- README: `README.md` (keep up to date as development progresses)
- Brainstorm: `docs/brainstorms/2026-02-13-algo-trader-brainstorm.md`
- Phase 1 Plan: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md`
