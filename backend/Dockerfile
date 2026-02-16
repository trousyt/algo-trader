# ---------------------------------------------------------------------------
# algo-trader development Dockerfile
# Single-stage build with dev dependencies (pytest, mypy, ruff, hypothesis).
# Production multi-stage image deferred to Step 9.
# ---------------------------------------------------------------------------

# --- Base image ------------------------------------------------------------
FROM python:3.12-slim

# --- Python environment vars (TODO 021) -----------------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- Install uv (pinned, TODO 018) ----------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /uvx /bin/

# --- Non-root user (TODO 017) ---------------------------------------------
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

# --- Working directory -----------------------------------------------------
WORKDIR /app

# --- Dependency layer (cached, TODO 019) -----------------------------------
# Copy only dependency manifests first so the dep-install layer is cached
# as long as pyproject.toml / uv.lock don't change.
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# --- Application code ------------------------------------------------------
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser alembic/ ./alembic/
COPY --chown=appuser:appuser tests/ ./tests/

# --- Project install (fast, TODO 019) --------------------------------------
RUN uv sync --frozen --no-editable

# --- Switch to non-root user (TODO 017) ------------------------------------
USER appuser

# --- Entrypoint ------------------------------------------------------------
# CLI-based: all commands work via docker-compose command override.
#   docker compose run app backtest --strategy velez ...
#   docker compose run app config
ENTRYPOINT ["uv", "run", "algo-trader"]
