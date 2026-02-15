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

### Process (non-negotiable)
1. **Deep planning before implementation** - Use `/workflows:plan` before building any feature
2. **Architectural review** - Run all architectural decisions through the `architecture-strategist` reviewer
3. **Frontend UI/UX** - Use `frontend-design` and `web-artifacts-builder` skills for all design recommendations and decisions. UI must be A+++: user friendly, powerful, logical, consistent
4. **Frontend code review** - All React/TypeScript code through `kieran-typescript-reviewer`
5. **Frontend browser testing** - Use `webapp-testing` skill for all front-end browser testing
6. **Security/penetration testing** - Use `ffuf-web-fuzzing` skill for web fuzzing and security testing
7. **Tech stack decisions** - Always pass through user for approval. Never assume.
8. **Knowledge compounding** - Run `/workflows:compound` at end of each effort to capture learnings
9. **Test-driven development** - Use `tdd` skill. Write failing test first, then minimal code to pass, then refactor. No production code without a failing test
10. **Comprehensive testing** - Unit tests, integration tests, e2e tests. All tests pass before merge

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
