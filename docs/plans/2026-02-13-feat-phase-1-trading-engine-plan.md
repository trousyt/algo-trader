---
title: "Phase 1: Trading Engine - CLI + Minimal Web UI"
type: feat
date: 2026-02-13
version: 3
brainstorm: docs/brainstorms/2026-02-13-algo-trader-brainstorm.md
review: DHH, Kieran, Simplicity reviewers (2026-02-13)
---

# Phase 1: Trading Engine - CLI + Minimal Web UI (v3)

## Overview

Build the foundational algorithmic trading engine for US equities. Phase 1 delivers a working system that can: connect to Alpaca for paper trading, stream real-time market data, evaluate the Velez SMA convergence strategy on configurable candle intervals (1m, 2m, 5m, 10m), manage orders through a full state machine with crash recovery, enforce risk management rules, run backtests against historical data, and provide monitoring via both CLI and a minimal web dashboard.

## Changes from v1 (Post-Review)

- **Config**: Switched from Dynaconf to Pydantic Settings (stronger types, IDE support)
- **Event bus**: Simplified to asyncio.Queue (no separate module)
- **Correlation IDs**: Kept but inlined into logging setup (no separate module)
- **Financial types**: `Decimal` for all monetary values (prices, P&L, equity)
- **Missing types**: Added `OrderRequest`, `BracketOrderRequest`, `OrderStatus`, `TradeUpdate`
- **Database schemas**: Full column definitions with types, indexes, and constraints
- **Config validation**: Bounds on every risk parameter
- **REST error handling**: Explicit spec for each failure scenario
- **Task supervision**: asyncio task group with restart logic
- **Reconciliation gap**: Handle partial-fill-then-crash (position with no stop)
- **Indicators**: Typed `IndicatorSet` instead of `dict`; engine computes, passes to strategy
- **Strategy base**: Added `should_short()` stub, fixed `hyperparameters` mutable default
- **WebSocket messages**: Added `version`, `timestamp`, `heartbeat`, expanded `pnl_update`
- **Naming**: `OrderEvent` (immutable) + `OrderState` (mutable) + `Trade` (completed round-trips)
- **Broker protocols**: Kept from day one; CLAUDE.md updated to match
- **Docker**: Added `.dockerignore`, fixed Poetry flag
- **Type checking**: Added mypy to quality gates

## Changes from v2 (Gap Resolution)

- **Package manager**: uv (Astral). Added ruff to dev dependencies
- **Broker protocols**: Full method signatures for `DataProvider` and `BrokerAdapter`
- **Candle intervals**: Configurable 1m, 2m, 5m, 10m (not hardcoded to 2m)
- **Candle aggregation**: Edge case table — missing bars, crash recovery, half-days
- **Indicator warm-up**: Explicit sequence — REST fetch → aggregate → fill buffer → deduplicate live overlap
- **Strategy instances**: One per symbol. `symbol` is `self.symbol`, not passed to every method
- **Backtest slippage**: Fixed unfavorable model, configurable per-share amount
- **WebSocket types**: Defined `DashboardSnapshot`, `ActivityEvent`, `StrategyState`, `ConnectionStatus`
- **Settings page scope**: Table of which settings are UI-editable vs restart-required
- **Task supervisor**: Backoff params (1s initial, 2x, 30s max, 3 failures in 5 min → shutdown)
- **Graceful shutdown**: 7-step sequence with in-flight order handling (5s timeout)
- **Style**: `Optional[X]` → `X | None` throughout all code samples

---

## Technical Approach

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Single Python Process                  │
│                    (asyncio event loop)                   │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Alpaca WS    │  │ Alpaca WS    │  │ FastAPI +    │  │
│  │ (Bar Data)   │  │ (Trade Upd.) │  │ WebSocket    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                  │                  │          │
│         ▼                  ▼                  ▼          │
│  ┌──────────────────────────────────────────────────┐   │
│  │            Task Supervisor                        │   │
│  │  (monitors all tasks, restarts on failure,        │   │
│  │   escalates to shutdown if unrecoverable)         │   │
│  └──────────────────────────────────────────────────┘   │
│         │                  │                  │          │
│         ▼                  ▼                  │          │
│  ┌──────────────┐  ┌──────────────┐          │          │
│  │ Candle       │  │ Order        │◄─────────┘          │
│  │ Aggregator   │  │ Manager      │                     │
│  │ (1m → 2m)    │  │              │                     │
│  └──────┬───────┘  └──────┬───────┘                     │
│         │                  │                             │
│         ▼                  ▼                             │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ Indicator    │  │ Risk         │                     │
│  │ Calculator   │  │ Manager      │                     │
│  └──────┬───────┘  └──────────────┘                     │
│         │                                                │
│         ▼                                                │
│  ┌──────────────┐                                       │
│  │ Strategy     │──→ asyncio.Queue ──→ WebSocket clients │
│  │ Engine       │                                       │
│  └──────┬───────┘                                       │
│         │                                                │
│         ▼                                                │
│  ┌──────────────┐                                       │
│  │ SQLite (WAL) │                                       │
│  │ via          │                                       │
│  │ SQLAlchemy   │                                       │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

**Data flow**: Alpaca WebSocket (1-min bars) → Candle Aggregator (1m → configurable interval: 1m/2m/5m/10m) → Indicator Calculator (SMA-20, SMA-200) → Strategy Engine (Velez) → Risk Manager (approve/reject) → Order Manager (state machine) → Alpaca REST → Trade updates back via WebSocket. UI events pushed via asyncio.Queue to WebSocket clients.

**Task supervisor**: All long-running asyncio tasks (bar stream, trade update stream, FastAPI, APScheduler) are monitored. If a critical task dies (unhandled exception), it is restarted with exponential backoff: initial delay 1s, 2x multiplier, max delay 30s. If a task fails 3 times within a 5-minute window, the supervisor triggers graceful shutdown — it is considered unrecoverable. This prevents the scenario where the trade update stream dies silently and orders go unmonitored.

### Project Structure

```
algo-trader/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # Entry point, task supervisor, asyncio runner
│   │   ├── config.py                # Pydantic Settings models
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # DeclarativeBase, engine setup, WAL pragmas
│   │   │   ├── order.py             # OrderState, OrderEvent, Trade
│   │   │   └── backtest.py          # BacktestRun, BacktestTrade
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   ├── trading_engine.py    # Main orchestrator
│   │   │   ├── candle_aggregator.py # 1-min → 2-min aggregation
│   │   │   └── indicators.py        # IndicatorCalculator (computes SMA, passes to strategy)
│   │   ├── strategy/
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # Base Strategy class
│   │   │   └── velez.py             # Velez SMA convergence strategy
│   │   ├── broker/
│   │   │   ├── __init__.py
│   │   │   ├── types.py             # Bar, Quote, Position, OrderRequest, OrderStatus, etc.
│   │   │   ├── data_provider.py     # DataProvider protocol
│   │   │   ├── broker_adapter.py    # BrokerAdapter protocol
│   │   │   └── alpaca/
│   │   │       ├── __init__.py
│   │   │       ├── data.py          # AlpacaDataProvider
│   │   │       └── broker.py        # AlpacaBrokerAdapter
│   │   ├── risk/
│   │   │   ├── __init__.py
│   │   │   ├── position_sizer.py
│   │   │   ├── circuit_breaker.py
│   │   │   └── risk_manager.py      # Facade: pre-order approval
│   │   ├── orders/
│   │   │   ├── __init__.py
│   │   │   ├── state_machine.py     # OrderStateMachine with transitions
│   │   │   ├── order_manager.py     # Lifecycle: submit, monitor, reconcile
│   │   │   └── reconciliation.py    # Startup broker state reconciliation
│   │   ├── backtest/
│   │   │   ├── __init__.py
│   │   │   ├── executor.py          # BacktestExecution (BrokerAdapter impl)
│   │   │   ├── runner.py            # Backtest harness
│   │   │   └── metrics.py           # Performance calculation
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── app.py               # FastAPI app with lifespan
│   │   │   ├── ws.py                # WebSocket endpoint + ConnectionManager
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       ├── dashboard.py     # GET /api/dashboard
│   │   │       └── settings.py      # GET/PUT /api/settings
│   │   ├── cli/
│   │   │   ├── __init__.py
│   │   │   └── commands.py          # CLI commands (start, backtest, status, stop)
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── logging.py           # Structured JSON logging + correlation ID context
│   │       └── time.py              # UTC helpers, market calendar wrapper
│   ├── alembic/
│   │   ├── env.py                   # render_as_batch=True for SQLite
│   │   └── versions/
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── test_velez_strategy.py
│   │   │   ├── test_order_state_machine.py
│   │   │   ├── test_risk_manager.py
│   │   │   ├── test_candle_aggregator.py
│   │   │   ├── test_position_sizer.py
│   │   │   ├── test_indicators.py
│   │   │   └── test_config.py
│   │   ├── integration/
│   │   │   ├── test_alpaca_data.py
│   │   │   ├── test_alpaca_broker.py
│   │   │   ├── test_backtest_runner.py
│   │   │   └── test_reconciliation.py
│   │   └── e2e/
│   │       ├── test_signal_to_execution.py
│   │       ├── test_trading_engine.py
│   │       └── test_graceful_shutdown.py
│   ├── pyproject.toml
│   ├── .env.example
│   └── mypy.ini
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── hooks/
│   │   │   └── useWebSocket.ts
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   │   ├── SummaryRibbon.tsx
│   │   │   ├── PositionsTable.tsx
│   │   │   ├── ActivityFeed.tsx
│   │   │   └── StrategyCard.tsx
│   │   └── types/
│   │       └── ws.ts
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── package.json
├── Dockerfile
├── .dockerignore
├── .gitattributes
├── .gitignore
├── .env.example
├── CLAUDE.md
└── README.md
```

### Dependencies

**Package manager**: uv (Astral — same team as Ruff). Manages virtualenv, dependencies, and lockfile in one tool. `uv init`, `uv add`, `uv run`.

**Python:**
```
alpaca-py >= 0.43
fastapi >= 0.115
uvicorn[standard]
sqlalchemy[asyncio] >= 2.0.38
aiosqlite
alembic
pandas >= 2.0
pandas-ta >= 0.3
numpy
pydantic-settings >= 2.0
exchange-calendars >= 4.12
apscheduler >= 3.11, < 4.0
structlog
click
```

**Frontend:** React 18.x, TypeScript 5.x, Vite 6.x

**Dev/Test:** pytest, pytest-asyncio, hypothesis (property-based testing), mypy, ruff

---

## Shared Types (`broker/types.py`)

All monetary values use `Decimal`. Enums enforce valid values.

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"

class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"

@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime          # UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume: int
    timestamp: datetime

@dataclass
class Position:
    symbol: str
    qty: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    side: Side

@dataclass
class AccountInfo:
    equity: Decimal
    buying_power: Decimal
    cash: Decimal
    margin_used: Decimal

@dataclass
class OrderRequest:
    symbol: str
    side: Side
    order_type: OrderType
    qty: Decimal
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    client_order_id: str | None = None    # For idempotent submission

@dataclass
class BracketOrderRequest:
    entry: OrderRequest
    stop_loss_price: Decimal
    take_profit_price: Decimal | None = None

class BrokerOrderStatus(str, Enum):
    ACCEPTED = "accepted"
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"

@dataclass
class OrderStatus:
    broker_order_id: str
    status: BrokerOrderStatus
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    submitted_at: datetime
    updated_at: datetime

@dataclass
class TradeUpdate:
    broker_order_id: str
    event: str                   # "fill", "partial_fill", "canceled", "rejected"
    symbol: str
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    timestamp: datetime
```

---

## Broker Protocols

### `DataProvider` (`broker/data_provider.py`)

```python
from typing import AsyncIterator, Protocol

class DataProvider(Protocol):
    async def connect(self) -> None:
        """Establish connection. Called once on startup."""
        ...

    async def disconnect(self) -> None:
        """Clean shutdown of connections."""
        ...

    async def subscribe_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        """Stream real-time 1-min bars. Yields Bar objects as they arrive."""
        ...

    async def get_historical_bars(
        self,
        symbol: str,
        count: int,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        """Fetch historical bars for indicator warm-up. Returns oldest-first."""
        ...

    async def get_latest_quote(self, symbol: str) -> Quote:
        """Get current bid/ask/last for a symbol."""
        ...
```

### `BrokerAdapter` (`broker/broker_adapter.py`)

```python
from typing import AsyncIterator, Protocol

class BrokerAdapter(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        """Submit order to broker. Returns initial status with broker_order_id."""
        ...

    async def submit_bracket_order(self, bracket: BracketOrderRequest) -> OrderStatus:
        """Submit entry + stop-loss as atomic bracket. Returns entry order status."""
        ...

    async def cancel_order(self, broker_order_id: str) -> None:
        """Request cancellation. Actual cancel confirmed via trade updates."""
        ...

    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """Poll current order status from broker."""
        ...

    async def get_positions(self) -> list[Position]: ...
    async def get_account(self) -> AccountInfo: ...

    async def get_open_orders(self) -> list[OrderStatus]:
        """All orders with non-terminal status."""
        ...

    async def get_recent_orders(self, since_hours: int = 24) -> list[OrderStatus]:
        """Recent orders (including terminal) for reconciliation."""
        ...

    async def subscribe_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        """Stream real-time order fill/cancel/reject events."""
        ...
```

---

## Indicator System

**Who computes indicators**: The `IndicatorCalculator` in `engine/indicators.py` owns indicator computation. It maintains a ring buffer per symbol, receives completed candles (at the strategy's configured interval), recalculates all indicators, and passes a typed `IndicatorSet` to the strategy.

```python
@dataclass(frozen=True)
class IndicatorSet:
    """Typed indicator values passed to strategy. No dict lookups."""
    sma_fast: Decimal | None       # SMA-20
    sma_slow: Decimal | None       # SMA-200
    prev_sma_fast: Decimal | None  # Previous bar's SMA-20
    prev_sma_slow: Decimal | None  # Previous bar's SMA-200
    bar_count: int                 # Number of bars in buffer (for warm-up check)
```

The strategy never computes indicators itself. It receives `IndicatorSet` and makes decisions. This keeps indicator math in one place and the strategy focused on signal logic.

### Indicator Warm-Up Sequence

Runs after reconciliation, before subscribing to live bar stream:

1. For each symbol in watchlist, fetch enough 1-min bars to produce 200 candles at the strategy's interval. E.g., 2-min interval needs `200 * 2 = 400` 1-min bars: `DataProvider.get_historical_bars(symbol, count=400, timeframe="1Min")`
2. Feed historical 1-min bars through the CandleAggregator to produce candles at the configured interval
3. Feed candles through IndicatorCalculator to fill the ring buffer
4. After warm-up, `IndicatorSet.bar_count >= 200` — strategy is ready to evaluate
5. Subscribe to live bar stream. Deduplicate overlap: if a live bar's timestamp matches the last historical bar, skip it
6. If REST fetch fails for a symbol (see error handling table), that symbol starts with an empty buffer. Strategy sees `bar_count < 200` and skips evaluation until warm. Log WARNING.

---

## Candle Aggregation

The CandleAggregator converts 1-min bars from the data provider into multi-minute candles. **Supported intervals**: 1m, 2m, 5m, 10m. The interval is configurable per strategy via `VelezConfig.candle_interval_minutes` (default 2).

**Architecture**: One CandleAggregator instance per `(symbol, interval)` pair. The TradingEngine creates aggregators based on which strategies are active and what intervals they require. A single 1-min bar stream feeds all aggregators for a given symbol — the aggregator fans out.

**Aggregation rule**: N consecutive 1-min bars are combined into one N-minute candle, aligned to market open (9:30). For a 5-min interval: 9:30-9:34 → candle timestamped 9:30, 9:35-9:39 → timestamped 9:35, etc. OHLCV: open of first bar, high of all bars, low of all bars, close of last bar, sum of volumes.

**1-min "aggregation"**: When interval is 1, the aggregator is a pass-through — it emits each incoming bar directly with no buffering.

**Edge cases:**

| Scenario | Behavior |
|----------|----------|
| First 1-min bar arrives late (>60s after expected) | Buffer the bar, wait for remaining bars in the window. The multi-min candle emits late but correct. |
| Missing 1-min bar within a window | After 90s past the window's expected close with fewer than N bars received, emit candle from available bars. Log WARNING. |
| No bars received for an entire window | After 90s past expected close, trigger REST fallback: `DataProvider.get_historical_bars(symbol, count=N, timeframe="1Min")` for the missing window. If REST also returns nothing, skip the window. Log WARNING. |
| System crashes mid-candle | Partial candle state is lost. On restart, warm-up fetches historical bars via REST, so the candle is reconstructed from historical data. No data loss. |
| Duplicate bar timestamp from live stream | Deduplicate by `(symbol, timestamp)`. Second bar with same timestamp is dropped. |
| Market half-day / early close | exchange-calendars provides the close time. CandleAggregator stops expecting bars after market close. Flush any buffered partial candle at close. |

---

## Database Schemas

### `order_state` (mutable — tracks order lifecycle)

```sql
CREATE TABLE order_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id        TEXT NOT NULL UNIQUE,           -- UUID, generated locally
    broker_id       TEXT,                            -- Alpaca order ID (null until submitted)
    correlation_id  TEXT NOT NULL,                   -- UUID tying signal → orders → fills
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('long', 'short')),
    order_type      TEXT NOT NULL,
    qty_requested   TEXT NOT NULL,                   -- Decimal stored as text
    qty_filled      TEXT NOT NULL DEFAULT '0',
    avg_fill_price  TEXT,
    state           TEXT NOT NULL DEFAULT 'pending_submit',
    version         INTEGER NOT NULL DEFAULT 0,      -- Optimistic concurrency
    parent_id       TEXT,                            -- For bracket child orders
    submit_attempts INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TEXT NOT NULL,                   -- ISO 8601 UTC
    updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX ix_order_state_local_id ON order_state(local_id);
CREATE INDEX ix_order_state_broker_id ON order_state(broker_id);
CREATE INDEX ix_order_state_correlation_id ON order_state(correlation_id);
CREATE INDEX ix_order_state_state ON order_state(state);
CREATE INDEX ix_order_state_symbol_created ON order_state(symbol, created_at);
```

### `order_event` (immutable — append-only audit log)

```sql
CREATE TABLE order_event (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_local_id  TEXT NOT NULL,
    event_type      TEXT NOT NULL,                   -- 'submitted', 'accepted', 'fill', 'partial_fill', 'canceled', 'rejected', 'failed'
    old_state       TEXT,
    new_state       TEXT NOT NULL,
    qty_filled      TEXT,
    fill_price      TEXT,
    broker_id       TEXT,
    detail          TEXT,                            -- Error message, rejection reason, etc.
    recorded_at     TEXT NOT NULL                    -- ISO 8601 UTC
);

CREATE INDEX ix_order_event_local_id ON order_event(order_local_id);
CREATE INDEX ix_order_event_recorded ON order_event(recorded_at);

-- Immutability trigger
CREATE TRIGGER no_update_order_event BEFORE UPDATE ON order_event
BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;

CREATE TRIGGER no_delete_order_event BEFORE DELETE ON order_event
BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;
```

### `trade` (immutable — completed round-trip trades)

```sql
CREATE TABLE trade (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT NOT NULL UNIQUE,            -- UUID
    correlation_id  TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK(side IN ('long', 'short')),
    qty             TEXT NOT NULL,
    entry_price     TEXT NOT NULL,
    exit_price      TEXT NOT NULL,
    entry_at        TEXT NOT NULL,
    exit_at         TEXT NOT NULL,
    pnl             TEXT NOT NULL,                   -- Decimal as text
    pnl_pct         TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    commission      TEXT NOT NULL DEFAULT '0'
);

CREATE INDEX ix_trade_symbol_exit ON trade(symbol, exit_at);
CREATE INDEX ix_trade_correlation ON trade(correlation_id);
CREATE INDEX ix_trade_strategy_exit ON trade(strategy, exit_at);

CREATE TRIGGER no_update_trade BEFORE UPDATE ON trade
BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;
```

### `trade_note` (mutable — user annotations)

```sql
CREATE TABLE trade_note (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id  TEXT NOT NULL REFERENCES trade(trade_id),
    note      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### `backtest_run` and `backtest_trade`

```sql
CREATE TABLE backtest_run (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy        TEXT NOT NULL,
    symbols         TEXT NOT NULL,                   -- JSON array
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    initial_capital TEXT NOT NULL,
    params          TEXT NOT NULL,                   -- JSON of strategy params
    total_return    TEXT,
    win_rate        TEXT,
    profit_factor   TEXT,
    sharpe_ratio    TEXT,
    max_drawdown    TEXT,
    total_trades    INTEGER,
    equity_curve    TEXT,                            -- JSON array of {timestamp, equity}
    created_at      TEXT NOT NULL
);

CREATE TABLE backtest_trade (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES backtest_run(id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             TEXT NOT NULL,
    entry_price     TEXT NOT NULL,
    exit_price      TEXT NOT NULL,
    entry_at        TEXT NOT NULL,
    exit_at         TEXT NOT NULL,
    pnl             TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL
);

CREATE INDEX ix_backtest_trade_run ON backtest_trade(run_id);
```

### `settings_override` (runtime config from web UI)

```sql
CREATE TABLE settings_override (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    previous_value TEXT                              -- Audit: what was it before
);
```

---

## Configuration (Pydantic Settings)

```python
from decimal import Decimal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

class BrokerConfig(BaseSettings):
    provider: str = "alpaca"
    paper: bool = True
    feed: str = "iex"
    api_key: str = Field(default="", alias="ALGO_BROKER_API_KEY")
    secret_key: str = Field(default="", alias="ALGO_BROKER_SECRET_KEY")

class RiskConfig(BaseSettings):
    max_risk_per_trade_pct: Decimal = Field(default=Decimal("0.01"), ge=Decimal("0.001"), le=Decimal("0.05"))
    max_risk_per_trade_abs: Decimal = Field(default=Decimal("500"), ge=Decimal("10"), le=Decimal("5000"))
    max_position_pct: Decimal = Field(default=Decimal("0.05"), ge=Decimal("0.01"), le=Decimal("0.25"))
    max_daily_loss_pct: Decimal = Field(default=Decimal("0.03"), ge=Decimal("0.01"), le=Decimal("0.10"))
    max_open_positions: int = Field(default=5, ge=1, le=20)
    consecutive_loss_pause: int = Field(default=3, ge=2, le=10)

class VelezConfig(BaseSettings):
    enabled: bool = True
    sma_fast: int = Field(default=20, ge=5, le=50)
    sma_slow: int = Field(default=200, ge=100, le=500)
    candle_interval_minutes: int = Field(default=2)  # Validated: must be in {1, 2, 5, 10}
    tightness_threshold_pct: Decimal = Field(default=Decimal("2.0"), ge=Decimal("0.5"), le=Decimal("5.0"))
    strong_candle_body_pct: Decimal = Field(default=Decimal("50.0"), ge=Decimal("30.0"), le=Decimal("80.0"))
    stop_buffer_pct: Decimal = Field(default=Decimal("0.1"), ge=Decimal("0.05"), le=Decimal("1.0"))
    stop_buffer_min: Decimal = Field(default=Decimal("0.02"), ge=Decimal("0.01"), le=Decimal("0.10"))
    buy_stop_expiry_candles: int = Field(default=1, ge=1, le=5)
    max_run_candles: int = Field(default=3, ge=2, le=10)
    doji_threshold_pct: Decimal = Field(default=Decimal("10.0"))

class WebConfig(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000

class AppConfig(BaseSettings):
    log_level: str = "INFO"
    broker: BrokerConfig = BrokerConfig()
    risk: RiskConfig = RiskConfig()
    velez: VelezConfig = VelezConfig()
    web: WebConfig = WebConfig()
    watchlist: list[str] = ["AAPL", "TSLA", "AMD", "NVDA", "META"]
    db_path: str = "data/trading.db"

    model_config = {"env_prefix": "ALGO_", "env_nested_delimiter": "__"}

    @field_validator("watchlist")
    @classmethod
    def validate_watchlist(cls, v):
        import re
        for symbol in v:
            if not re.match(r"^[A-Z]{1,5}$", symbol):
                raise ValueError(f"Invalid symbol: {symbol}")
        if len(v) == 0:
            raise ValueError("Watchlist must not be empty")
        return v
```

**Config hierarchy** (lowest to highest priority):
1. Pydantic defaults (in code above)
2. `.env` file (loaded by Pydantic Settings)
3. Environment variables (`ALGO_RISK__MAX_DAILY_LOSS_PCT=0.05`)
4. SQLite `settings_override` table (from web UI)

**Validation**: Every risk parameter has explicit bounds. A typo like `max_risk_per_trade_pct = 0.1` (10%) is rejected because the max is 0.05 (5%).

**Settings page scope** (what's editable from the web UI via `settings_override` table):

| Setting | Editable from UI | Requires restart |
|---------|:---:|:---:|
| Risk params (`max_risk_per_trade_pct`, `max_daily_loss_pct`, etc.) | Yes | No (applied on next signal evaluation) |
| Watchlist | Yes | No (triggers re-subscribe to bar stream) |
| Strategy enabled/disabled | Yes | No |
| Broker config (API keys, provider, paper mode) | No | Yes |
| Strategy hyperparameters (`sma_fast`, `sma_slow`, etc.) | No | Yes |
| Web config (host, port) | No | Yes |
| Log level | Yes | No (applied immediately) |

The `settings_override` table only accepts keys that match the editable settings above. Writes are validated against the same Pydantic bounds before persisting. Invalid keys are rejected with 400.

---

## REST API Error Handling

| Alpaca REST Call | Transient Error (5xx, timeout) | Rate Limited (429) | Client Error (4xx) | Action on Failure |
|---|---|---|---|---|
| `submit_order` | Retry 2x with 1s backoff. If still fails → order state = SUBMIT_FAILED | Wait `Retry-After` header, retry once | → order state = REJECTED, log error detail | Stop-loss already in place if this was a stop update; if entry order, no position opened |
| `cancel_order` | Retry 3x with 1s backoff | Wait and retry | Log warning (order may already be filled/canceled) | Check order status to confirm |
| `get_account` | Retry 2x. If fails → use last known equity (cached) | Wait and retry | Fatal: invalid credentials → shutdown | Risk check uses potentially stale data — log warning |
| `get_positions` | Retry 2x. If fails → use cached positions | Wait and retry | Fatal → shutdown | Reconciliation may be incomplete — log warning |
| `get_bars` (historical) | Retry 3x with 2s backoff | Respect rate limit, retry with backoff | Skip symbol, log error | Indicator warm-up incomplete for that symbol |

**General principle**: Transient errors → retry with backoff. Persistent errors → fail to safe state (no order submitted = no risk). Never block the main loop waiting for retries — use asyncio tasks.

---

## Strategy Base Class

**Instance model**: The TradingEngine creates **one strategy instance per symbol**. Each instance owns its per-symbol state (e.g., Velez tracks candle pattern state, trailing stop level, active signal). The engine passes `bar` and `indicators` — the strategy never fetches its own data.

```python
from abc import ABC, abstractmethod
from typing import Any, ClassVar

class Strategy(ABC):
    # Override in subclass — ClassVar prevents mutable-default footgun
    hyperparameters: ClassVar[dict[str, Any]] = {}

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @abstractmethod
    def should_long(self, bar: Bar, indicators: IndicatorSet) -> bool: ...

    def should_short(self, bar: Bar, indicators: IndicatorSet) -> bool:
        """Stub for Phase 2. Returns False by default."""
        return False

    @abstractmethod
    def entry_price(self, bar: Bar) -> Decimal: ...

    @abstractmethod
    def stop_loss_price(self, bar: Bar) -> Decimal: ...

    @abstractmethod
    def should_update_stop(self, bar: Bar,
                           position: Position, indicators: IndicatorSet) -> Decimal | None: ...

    @abstractmethod
    def should_exit(self, bar: Bar,
                    position: Position, indicators: IndicatorSet) -> bool: ...

    def required_history(self) -> int:
        return 200
```

Since each instance is bound to one symbol, `symbol` is no longer passed to every method — it's `self.symbol`. The Velez strategy stores per-symbol state (current signal, trailing stop level, candle pattern tracking) as instance attributes.

---

## Order State Machine

```
States:
  PENDING_SUBMIT   → Created locally, not yet sent
  SUBMITTED        → REST call sent, awaiting ack
  ACCEPTED         → Broker acknowledged, on book
  PARTIALLY_FILLED → Some shares filled
  FILLED           → Terminal
  CANCELED         → Terminal
  EXPIRED          → Terminal
  REJECTED         → Terminal
  SUBMIT_FAILED    → REST call failed, terminal

Valid transitions:
  PENDING_SUBMIT   → {SUBMITTED, SUBMIT_FAILED}
  SUBMITTED        → {ACCEPTED, REJECTED, FILLED, CANCELED}
  ACCEPTED         → {PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED}
  PARTIALLY_FILLED → {PARTIALLY_FILLED, FILLED, CANCELED}

Crash recovery: force-set state during reconciliation (bypasses validation).
Every transition persisted to order_state table + appended to order_event table
BEFORE the next action (write-ahead logging).
```

**Partial fill handling:**
1. Partial fill arrives → update `order_state`, append `order_event`
2. Place stop-loss for filled quantity immediately
3. If remaining order cancels AND filled qty < 5 shares → close partial position at market
4. **Crash scenario**: If system crashes after partial fill but before stop-loss placed → reconciliation on restart detects position with no stop → places stop-loss immediately

---

## Reconciliation (Crash Recovery)

Runs BEFORE subscribing to any WebSocket streams on every startup:

1. Fetch all open positions from Alpaca
2. Fetch all open + recent (24h) orders from Alpaca
3. Compare against local SQLite:
   - Orders locally SUBMITTED but broker says FILLED → update state, record fill
   - Orders locally SUBMITTED but broker says CANCELED → update state
   - Orders locally PENDING_SUBMIT with no broker_id → mark SUBMIT_FAILED
   - Positions in Alpaca not in local DB → create local records (orphan, log WARNING)
   - Positions in local DB not in Alpaca → mark as closed
4. **NEW (v2)**: For any position without an active stop-loss order → place stop-loss immediately using the strategy's default stop distance. Log CRITICAL alert.
5. Log all reconciliation actions
6. Only after reconciliation: subscribe to WebSocket streams

---

## WebSocket Message Schema

```typescript
// Every message includes version and timestamp
type BaseMessage = {
  version: 1;
  timestamp: string;  // ISO 8601 UTC
};

type WSMessage = BaseMessage & (
  | { type: "snapshot"; data: DashboardSnapshot }        // Sent on connect
  | { type: "position_update"; data: Position[] }
  | { type: "pnl_update"; data: PnlData }
  | { type: "activity"; data: ActivityEvent }
  | { type: "strategy_state"; data: StrategyState }
  | { type: "connection_status"; data: ConnectionStatus }
  | { type: "error"; data: { code: string; message: string; correlation_id?: string } }
  | { type: "heartbeat"; data: { server_time: string } }
);

type PnlData = {
  today_pnl: number;
  today_pnl_pct: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_equity: number;
  buying_power: number;
};
```

**Remaining WebSocket types:**

```typescript
type DashboardSnapshot = {
  account: { equity: number; buying_power: number; cash: number };
  positions: Position[];
  pnl: PnlData;
  strategies: StrategyState[];
  recent_activity: ActivityEvent[];
  connection: ConnectionStatus;
};

type Position = {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  side: "long" | "short";
};

type ActivityEvent = {
  id: string;
  timestamp: string;
  type: "signal" | "order_submitted" | "order_filled" | "order_canceled" | "order_rejected" | "stop_moved" | "circuit_breaker" | "error";
  symbol: string;
  message: string;
  correlation_id: string;
};

type StrategyState = {
  name: string;
  symbol: string;
  enabled: boolean;
  status: "warming_up" | "watching" | "signal_active" | "in_position" | "paused";
  indicators: { sma_fast: number | null; sma_slow: number | null };
  bar_count: number;
};

type ConnectionStatus = {
  status: "connected" | "reconnecting" | "disconnected" | "shutting_down";
  bar_stream: boolean;
  trade_stream: boolean;
  last_bar_at: string | null;
};
```

On WebSocket connect → server sends `snapshot` with full dashboard state. After that, only incremental updates. Heartbeat sent every 15 seconds.

---

## CLI Interface

| Command | Description | Mechanism |
|---------|-------------|-----------|
| `algo-trader start` | Start engine + web server | Long-running asyncio process |
| `algo-trader stop` | Graceful shutdown | HTTP POST to `localhost:8000/api/shutdown` (FastAPI endpoint) |
| `algo-trader status` | Show positions, P&L, engine state | HTTP GET from `localhost:8000/api/dashboard` |
| `algo-trader backtest ...` | Run backtest | Separate short-lived process |
| `algo-trader config` | Dump resolved config with source of each value | Print to stdout |

`algo-trader stop` communicates via HTTP to the running process (works on Windows, no POSIX signals needed). The `/api/shutdown` endpoint triggers graceful shutdown:

1. **Stop new signals** — Disable strategy evaluation. No new orders will be generated.
2. **Wait for in-flight orders** — Orders in SUBMITTED or PENDING_SUBMIT state: wait up to 5 seconds for broker acknowledgment. After timeout, log WARNING with order IDs and proceed.
3. **Cancel pending orders** — Cancel any ACCEPTED (unfilled) orders (e.g., buy-stop entries waiting for trigger). Retry cancel up to 3x.
4. **Leave filled positions** — Positions with broker-side stop-loss orders remain open. The broker enforces stops even while our system is offline.
5. **Broadcast shutdown to WebSocket clients** — Send `{ type: "connection_status", data: { status: "shutting_down" } }`.
6. **Flush logs and close DB** — Ensure all pending writes complete.
7. **Exit** — Process terminates. Target: < 10 seconds on idle system.

---

## Implementation Steps

### Step 1: Foundation
Project scaffolding, config, database, logging, market calendar, CLI skeleton.

### Step 2: Broker Abstraction + Alpaca Integration
Protocols, shared types, Alpaca data streaming, candle aggregation, Alpaca order execution.

### Step 3: Strategy Engine + Velez Strategy
Base class, indicator calculator, Velez implementation with all resolved parameters.

### Step 4: Order Management + Risk Management
State machine, order lifecycle, position sizing, circuit breaker, risk manager facade.

### Step 5: Startup Reconciliation + Crash Recovery
Broker state reconciliation, orphan detection, partial-fill-without-stop recovery.

### Step 6: Backtesting Engine
BacktestExecution adapter, runner, fill simulation with slippage, metrics.

**Slippage model (Phase 1)**: Fixed unfavorable slippage applied to every fill.
- **Entry (buy-stop)**: Fill at `stop_price + slippage`. Default slippage = `$0.01`.
- **Exit (stop-loss)**: Fill at `stop_price - slippage`. Default slippage = `$0.01`.
- **Market orders**: Fill at `close + slippage` (buy) or `close - slippage` (sell).
- Configurable via `BacktestConfig.slippage_per_share: Decimal = Decimal("0.01")`.
- No volume-based or volatility-based slippage in Phase 1. Can be refined later with empirical data from paper trading fills.

### Step 7: CLI + Web UI
Full CLI commands, FastAPI + WebSocket, React dashboard + settings.

### Step 8: Docker Smoke Test
Dockerfile, .dockerignore, .gitattributes, smoke test.

---

## Acceptance Criteria

### Functional
- [ ] Engine connects to Alpaca paper trading and streams 1-min bars for 5 configured symbols
- [ ] Candle aggregator produces correct OHLCV for 1m, 2m, 5m, and 10m intervals with market-open-aligned windows
- [ ] Indicator calculator produces correct SMA-20 and SMA-200 values (verified against pandas-ta)
- [ ] Velez strategy detects SMA convergence + strong candle + divergence on test dataset of 500 candles
- [ ] Buy-stop placed at first bar high. Stop-loss at first bar low - max(price*0.1%, $0.02)
- [ ] Buy-stop canceled if not filled within 1 candle (2 minutes)
- [ ] Trailing stop moves correctly: pullback(red) → 2 continuations(green) → stop to pullback low
- [ ] Order state machine: all 9 valid transitions work, all invalid transitions raise error
- [ ] Every state transition persisted to `order_state` + appended to `order_event` before next action
- [ ] Risk manager rejects order when daily loss limit exceeded (existing positions untouched)
- [ ] Circuit breaker trips after 3 consecutive losses, resets next trading day
- [ ] Position sizing: 1% risk with $0.50 stop distance on $25K equity = 500 shares
- [ ] Reconciliation detects stale SUBMITTED order that broker shows as FILLED → updates local state
- [ ] Reconciliation detects position with no stop-loss → places stop immediately
- [ ] Backtest on 1 month AAPL data produces equity curve and metrics matching manual verification
- [ ] Dashboard shows real-time positions and P&L via WebSocket within 1 second of fill
- [ ] Settings page validates risk params (rejects max_risk_per_trade_pct = 0.1)
- [ ] `algo-trader stop` triggers graceful shutdown within 10 seconds on idle system

### Non-Functional
- [ ] Latency: < 3 seconds from candle close to order submission (measured in logs)
- [ ] WebSocket reconnects automatically within 60 seconds after simulated disconnect
- [ ] SQLite write transactions complete within 50ms (measured via logging)
- [ ] Memory: < 500MB after 6 hours with 5 symbols (measured via process monitor)
- [ ] All monetary calculations use Decimal (no float for prices, P&L, equity, position sizing)
- [ ] mypy passes with zero errors on all application code

### Quality Gates
- [ ] All unit tests pass (strategy, orders, risk, candles, indicators, config)
- [ ] All integration tests pass (Alpaca paper connection, backtest runner, reconciliation)
- [ ] E2E tests pass (signal→risk→order→fill→ledger, graceful shutdown)
- [ ] Property-based tests pass (order state machine via Hypothesis — random event sequences never produce invalid state)
- [ ] No hardcoded secrets in codebase
- [ ] `.env.example` documents every required environment variable
- [ ] All code reviewed per CLAUDE.md process (architecture, frontend, TypeScript)

---

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Alpaca IEX data loss (documented) | High | Medium | REST fallback gap-fill; stale candle detection; alert in UI |
| IEX covers ~3% of volume (low-float stocks missed) | High | High | Monitor signal generation; upgrade to Polygon ($7/mo) if insufficient |
| pandas-ta archived July 2026 | Medium | Low | pandas-ta-classic drop-in replacement; SMA is trivial to implement |
| SQLite write contention (engine + UI settings) | Low | Medium | WAL mode + busy_timeout; settings writes are rare |
| Unhandled exception kills asyncio task silently | Medium | Critical | Task supervisor monitors + restarts; escalates to shutdown |
| Partial fill + crash = unprotected position | Low | Critical | Reconciliation detects and places stop immediately on startup |
| Config typo weakens risk controls | Medium | High | Pydantic validation bounds on every risk parameter |
| Stale account data during risk check | Medium | Medium | Cache with 30s TTL; log warning if stale; Alpaca rejects if buying power insufficient |

---

## References

### Internal
- Brainstorm: `docs/brainstorms/2026-02-13-algo-trader-brainstorm.md`
- CLAUDE.md engineering standards

### External
- [alpaca-py SDK](https://github.com/alpacahq/alpaca-py)
- [Alpaca WebSocket issues](https://forum.alpaca.markets/t/websocket-bars-missing-inconsistent-data-stream/13747)
- [exchange-calendars](https://github.com/gerrymanoim/exchange_calendars)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [ib_async](https://github.com/ib-api-reloaded/ib_async) — Future IBKR integration
- [gnzsnz/ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker) — IBKR Gateway Docker
