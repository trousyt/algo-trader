---
title: "feat: Add minimal Docker scaffolding for backend development"
type: feat
date: 2026-02-16
---

# feat: Add Minimal Docker Scaffolding for Backend Development

## Overview

Add a Dockerfile and docker-compose.yml so the backend can be built, tested, and run entirely in Linux/Docker — matching the production target environment. Update CLAUDE.md and all documentation to enforce Docker-first development: all commands (tests, lint, mypy, CLI) run through the container. This must be completed **before** Step 7 (TradingEngine) to avoid platform issues with `loop.add_signal_handler()` and other Linux-only APIs.

No frontend container (Phase 2), no production deployment concerns (Step 9).

## Motivation

CLAUDE.md declares Linux-only platform — dev and prod both run in Docker/Linux. Currently development happens on Windows with a Python venv, but the codebase uses `loop.add_signal_handler()` (Linux-only) and will fail on Windows once Step 7 lands. Docker scaffolding now means Step 7 can be developed and tested in the target environment from day one.

**This is a prerequisite for Step 7.** The TradingEngine plan must execute inside Docker to validate signal handling, async lifecycle, and WebSocket stream behavior on the target platform.

## Proposed Solution

Three new files + updates to existing files:

### 1. `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution (matches CI)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# Install the project itself (editable not needed in container)
RUN uv sync --frozen --no-dev

# Create data directory for SQLite
RUN mkdir -p data

# Default: run the CLI
ENTRYPOINT ["uv", "run", "algo-trader"]
```

**Key decisions:**
- `python:3.12-slim` — matches CI (`ubuntu-latest` + Python 3.12), small image
- `uv` for package management — matches CI pipeline (`.github/workflows/ci.yml` uses `setup-uv@v4`)
- Layer caching: `pyproject.toml` + `uv.lock` copied before app code so dependency layer is cached on code changes
- No `.env` baked in — passed at runtime via `docker-compose.yml` or `--env-file`
- `ENTRYPOINT` uses CLI so all commands work: `docker compose run app backtest ...`

### 2. `docker-compose.yml` (project root)

```yaml
services:
  app:
    build:
      context: backend
      dockerfile: Dockerfile
    env_file:
      - backend/.env
    volumes:
      # Mount code for live reload during development
      - ./backend/app:/app/app:ro
      # Mount alembic for migration development
      - ./backend/alembic:/app/alembic:ro
      # Persist SQLite database on host
      - ./backend/data:/app/data
    # Default command: start the trading engine (Step 7+)
    # Override with: docker compose run app backtest --strategy velez ...
    command: ["start"]

  test:
    build:
      context: backend
      dockerfile: Dockerfile
    env_file:
      - backend/.env
    volumes:
      - ./backend/app:/app/app:ro
      - ./backend/tests:/app/tests:ro
      - ./backend/alembic:/app/alembic:ro
    # Override entrypoint for test runner
    entrypoint: ["uv", "run", "pytest"]
    command: ["tests/", "-v", "--tb=short"]
    profiles:
      - test
```

**Key decisions:**
- `app` service for running the trading engine / CLI commands
- `test` service in `test` profile — only runs when explicitly requested (`docker compose --profile test run test`)
- Code mounted read-only (`:ro`) for development iteration without rebuilds
- `backend/data/` volume-mounted so SQLite persists across container restarts
- `.env` file passed via `env_file` — not baked into image
- No `ports:` exposed yet — web server is Step 8

### 3. Create `backend/.dockerignore`

The `.dockerignore` goes in `backend/` because the build context is `backend/` (set in `docker-compose.yml`). Do NOT exclude `tests/` (needed in the image for the single-stage approach) or `uv.lock` (needed for `uv sync --frozen`).

```
# Virtual environment
.venv/

# Environment files (secrets — passed at runtime via env_file)
.env
.env.*

# SQLite data (mounted as volume, not baked into image)
data/

# Python bytecode / caches
__pycache__/
*.pyc
*.pyo
.mypy_cache/
.ruff_cache/
.pytest_cache/

# Build artifacts
*.egg-info/
dist/
build/
```

### 4. Update `backend/Dockerfile` for dev dependencies (test service)

The test service needs dev dependencies (pytest, mypy, ruff). Two options:

**Option A (chosen): Multi-stage build**
```dockerfile
# Production stage
FROM python:3.12-slim AS production
# ... (as above)

# Development stage (extends production, adds dev deps)
FROM production AS development
RUN uv sync --frozen
COPY tests/ ./tests/
```

The `test` service targets `development` stage. The `app` service targets `production` stage (default).

### 5. Update CLAUDE.md — Docker-First Development Workflow

All development commands must route through Docker. Update these CLAUDE.md sections:

**Python Style → Pre-push gate** (line ~89):
```
Before: ruff check app/ tests/
After:  docker compose run --rm test ruff check app/ tests/
```

**Python Style → Type checker** (line ~90):
```
Before: mypy with strict = true
After:  docker compose run --rm test mypy app/
```

**Testing section** — add Docker as the primary way to run tests:
```
Before: Run tests directly (pytest, etc.)
After:  docker compose --profile test run --rm test
```

**CLI smoke testing** — update to use Docker:
```
Before: run the actual CLI end-to-end
After:  docker compose run --rm app config  (safety gate)
        docker compose run --rm app backtest --strategy velez ...
```

**Add new section: "Docker Development" after Architecture:**
```markdown
### Docker Development (non-negotiable)

All backend commands run inside Docker. Never run Python, pytest, ruff, mypy, or the CLI directly on the host. This ensures Linux-only code (signal handlers, async patterns) is always tested on the target platform.

**Build:**
docker compose build

**Run tests:**
docker compose --profile test run --rm test

**Run lint + format check:**
docker compose --profile test run --rm test ruff check app/ tests/
docker compose --profile test run --rm test ruff format --check app/ tests/

**Run type checker:**
docker compose --profile test run --rm test mypy app/

**Run CLI commands:**
docker compose run --rm app config
docker compose run --rm app backtest --strategy velez --symbols AAPL --start-date 2025-01-01 --end-date 2025-12-31

**Run migrations:**
docker compose run --rm app alembic upgrade head

**Start trading engine (Step 7+):**
docker compose up app
```

### 6. Update README.md

Replace the current Development section with Docker-first commands. Update:
- **Usage** → all CLI examples use `docker compose run --rm app ...`
- **Development** → setup becomes `docker compose build`, tests become `docker compose --profile test run --rm test`
- **Troubleshooting** → add Docker-specific issues (build failures, volume permissions)

### 7. Update CI pipeline consideration

The CI pipeline (`.github/workflows/ci.yml`) currently runs directly on `ubuntu-latest`. No change needed now — CI already runs on Linux. Consider switching CI to use Docker build in a future step for full parity, but this is not blocking.

## Acceptance Criteria

- [ ] `docker compose build` succeeds (both app and test targets)
- [ ] `docker compose run --rm app config` shows configuration from `.env`
- [ ] `docker compose run --rm app backtest --strategy velez --symbols AAPL --start-date 2025-06-01 --end-date 2025-06-30` completes
- [ ] `docker compose --profile test run --rm test` runs full test suite and passes
- [ ] `docker compose run --rm test ruff check app/ tests/` passes
- [ ] `docker compose run --rm test mypy app/` passes
- [ ] SQLite database persists in `backend/data/` after container stops
- [ ] Signal handling infrastructure in place (`init: true`, `stop_signal: SIGTERM`, `stop_grace_period: 30s`). Functional validation deferred to Step 7
- [ ] CLAUDE.md updated: all command examples use Docker, new "Docker Development" section added
- [ ] README.md updated: Usage and Development sections use Docker commands
- [ ] No Windows-specific code or platform conditionals introduced

## Files to Create/Modify

| File | Action |
|------|--------|
| `backend/Dockerfile` | Create (multi-stage: production + development) |
| `docker-compose.yml` | Create (project root) |
| `backend/.dockerignore` | Create (exclude `.venv/`, `.env`, caches, `data/`; keep `tests/` and `uv.lock`) |
| `CLAUDE.md` | Add Docker Development section, update all command examples |
| `README.md` | Update Usage + Development sections with Docker commands |

## References

- CI pipeline: `.github/workflows/ci.yml` (uses `uv`, Python 3.12, ubuntu-latest)
- Config loading: `backend/app/config.py` (pydantic-settings, `ALGO_` prefix, `__` delimiter)
- Env template: `backend/.env.example`
- Existing `.dockerignore`: project root
- Alembic config: `backend/alembic.ini` (SQLite path: `data/trading.db`)
