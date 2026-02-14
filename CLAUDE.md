# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Algo-trader is an algorithmic trading system for US equities. It performs technical analysis on real-time market data, detects trading signals, and executes trades automatically via brokerage APIs. This system handles real money - treat every change with production-grade rigor.

## Architecture

- **Backend**: Python 3.11+ with FastAPI
- **Frontend**: React web UI (dashboard, strategy config, backtesting)
- **Broker**: Alpaca (direct integration Phase 1; refactor to adapter pattern when adding a second provider)
- **Data**: Alpaca IEX (direct integration Phase 1; abstract when adding a second provider)
- **Database**: SQLite (WAL mode) for all data initially. SQLAlchemy for ORM (enables future PostgreSQL/TimescaleDB migration). Add Parquet + DuckDB for analytical data only when SQLite performance becomes an issue.
- **Strategy Engine**: Jesse-inspired class inheritance. Deterministic - same strategy code runs in backtest, paper, and live mode.
- **AI Role**: Advisory ONLY. AI provides analysis, commentary, and confidence scores as inputs to the deterministic strategy engine. AI does NOT make trade decisions autonomously.
- **Notifications**: Discord webhooks (one-way initially; bot commands added later)
- **Containerization**: Docker

## Engineering Standards

### Process (non-negotiable)
1. **Deep planning before implementation** - Use `/workflows:plan` before building any feature
2. **Architectural review** - Run all architectural decisions through the `architecture-strategist` reviewer
3. **Frontend UI/UX** - Use `frontend-design` skill for all design recommendations and decisions
4. **Frontend code review** - All React/TypeScript code through `kieran-typescript-reviewer`
5. **Frontend design review** - All frontend code through `/frontend-design` reviewer. UI must be A+++: user friendly, powerful, logical, consistent
6. **Tech stack decisions** - Always pass through user for approval. Never assume.
7. **Knowledge compounding** - Run `/workflows:compound` at end of each effort to capture learnings
8. **Comprehensive testing** - Unit tests, integration tests, e2e tests. All tests pass before merge

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
