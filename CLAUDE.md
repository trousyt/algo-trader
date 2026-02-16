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
- **Platform**: Linux only. Development and production both run in Docker/Linux. Do not write Windows-specific code or platform-conditional branches. `SIGTERM`/`SIGINT` via `loop.add_signal_handler()` is the only signal handling pattern needed.

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
- **Frontend browser testing** - Use Claude in Chrome MCP tools or Playwright via `webapp-testing` skill for all front-end browser testing. Every UI change must be verified in a real browser, not just unit tests
- **Security/penetration testing** - Use `ffuf-web-fuzzing` skill for web fuzzing and security testing
- **Tech stack decisions** - Always pass through user for approval. Never assume.
- **Test-driven development** - Use `tdd` skill. Write failing test first, then minimal code to pass, then refactor. No production code without a failing test
- **CLI smoke testing** - When changing CLI commands, run the actual CLI end-to-end (not just unit tests) to verify real output and error handling. **Safety gate**: before any CLI smoke test that touches the broker, run `cli config` and confirm `Paper: True`. Never run CLI smoke tests against a live trading account
- **Comprehensive testing** - Unit tests, integration tests, e2e tests. All tests pass before merge

### Plan Review Agents (curated list — do not auto-discover)

When running `/deepen-plan`, `/plan_review`, or any plan/code review workflow, use ONLY this curated agent list. Do not dynamically discover agents.

**Backend (Python) projects:**
- `security-sentinel`
- `performance-oracle`
- `architecture-strategist`
- `pattern-recognition-specialist`
- `data-integrity-guardian`
- `data-migration-expert`
- `code-simplicity-reviewer`
- `kieran-python-reviewer`

**Frontend (Web/React/TS) projects:**
- `kieran-typescript-reviewer`
- `julik-frontend-races-reviewer`
- `frontend-design`

**Universal (all projects):**
- `agent-native-reviewer`

### Review Agent Result Persistence

When running review agents in the background, instruct each agent to write its findings to `memory/reviewer-findings/{agent-name}-findings.md`. This avoids the empty background output file problem. Clean up findings after they've been synthesized into the plan.

### Python Style
- **Formatter/Linter**: Ruff (replaces Black, Flake8, isort — single tool)
- **Pre-push gate**: Always run `ruff check app/ tests/` and `ruff format --check app/ tests/` on the full codebase before pushing — never just check individual files piecemeal
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
- **Database tables**: Singular `snake_case` names (e.g. `backtest_run`, `order_event`, `trade`). Model class is `PascalCase` + `Model` suffix (e.g. `BacktestRunModel`). Never pluralize table names.

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
- **Acceptance criteria are mandatory** — Every plan has acceptance items (checkboxes). ALL must be confirmed passing before committing to the feature branch and merging to main. It is never acceptable to leave unchecked items and merge. If an item turns out to be unnecessary, explicitly remove it from the plan with a rationale before merging.
- Unit tests: Strategy logic, risk management, order state machine
- Integration tests: Broker API, data pipeline, WebSocket connections
- E2E tests: Signal-to-execution flow, web UI workflows
- Strategy logic testable with mock market data (no live API calls in unit tests)
- **CLI smoke tests** - When changing CLI commands, always run the actual CLI to verify real output (not just unit tests). Confirm commands produce clean output on success and clean error messages on failure. Unit tests mock internals; smoke tests catch what mocks hide. **Safety gate**: before any smoke test that touches the broker, run `cli config` and confirm `Paper: True`. Never smoke-test against a live trading account.
- **Browser tests** - When implementing or changing web UI, run browser tests using Claude in Chrome MCP tools or Playwright to validate changes render and behave correctly in a real browser. Don't rely solely on unit/component tests for UI work.
- **Frontend design fidelity** - When implementing or changing web UI, use the `frontend-design` skill to visually verify the rendered result matches design intent. Check spacing, alignment, colors, and interactive states in the browser.

### Git
- **Conventional Commits** ([spec](https://www.conventionalcommits.org/en/v1.0.0/)): `<type>(<scope>): <description>`
  - Types: `feat` (new feature), `fix` (bug fix), `refactor`, `docs`, `test`, `perf`, `build`, `ci`, `chore`
  - Scope is optional but encouraged: `feat(engine):`, `fix(broker):`, `docs(solutions):`
  - Breaking changes: append `!` after type/scope — `feat(api)!: remove v1 endpoints`
  - Body (optional): one blank line after description, explains "why" not "what"
  - Keep description lowercase, imperative, no period: `feat: add candle aggregator`
- Never add Co-Authored-By or Claude attribution to commits

### Safety
- Paper-trading-only by default. Explicit env var required to enable live trading
- Risk management (position sizing, daily loss limits) from Phase 1
- Order state machine with crash recovery and broker reconciliation
- Never commit API keys or secrets (`.env` + `.env.example`)

### README.md Maintenance

Keep `README.md` up to date as features are planned and implemented. This file is for **human consumption** — developers, contributors, and anyone evaluating the project. Update it when completing a plan or merging a feature. Required sections in order:

1. **Title** — Project name + one-line description
2. **Build/deploy status** — CI badges, build status
3. **Overview** — High-level product vision and what the system does (2-3 paragraphs max)
4. **Planned features** — Roadmap of what's built vs. what's coming, organized by phase
5. **Usage instructions** — How to run the system (CLI commands, configuration, paper vs. live)
6. **Compiling/dev instructions** — Prerequisites, setup, how to run tests, Docker
7. **Troubleshooting** — Common issues and solutions

## Key Design Docs

- README: `README.md`
- Brainstorm: `docs/brainstorms/2026-02-13-algo-trader-brainstorm.md`
- Phase 1 Plan: `docs/plans/2026-02-13-feat-phase-1-trading-engine-plan.md`
