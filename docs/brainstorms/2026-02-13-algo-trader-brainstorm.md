# Algo Trader Brainstorm

**Date**: 2026-02-13
**Status**: Complete

---

## What We're Building

An algorithmic trading system for US equities that performs technical analysis on real-time market data, detects trading signals, and executes trades automatically via the Alpaca brokerage API.

### Target User Profile

- Expert developer, beginning trader
- Moderate risk tolerance ($5K-$25K account, 1-2% risk per trade)
- Trading regular market hours (9:30 AM - 4:00 PM ET) with pre-market scanning
- Existing Webull brokerage account and TradingView subscription

### Core Capabilities

1. **Pre-market Scanner** - Scan for volatile stocks meeting criteria (gap ups/downs, volume, etc.) before market open
2. **Real-time Technical Analysis** - Calculate indicators (SMA, EMA, volume, etc.) on live 2-minute candle data
3. **Signal Detection & Execution** - Evaluate strategy rules and automatically place trades
4. **Risk Management** - Stop-loss placement, position sizing (1-2% risk per trade), daily loss limits
5. **Trade Metrics & Statistics** - Track cost/share, total trade value, trade timespan, P&L, win rate, and pattern analysis
6. **Notifications** - Console/log initially, with Discord/Slack/email added later
7. **AI-Powered Analysis** - Leverage AI/ML for pattern recognition, sentiment analysis, and trade signal augmentation beyond traditional technical indicators

---

## Why This Approach

### Architecture: Pure Python with Alpaca

**Chosen over** Webull-native (immature API).

**Rationale**:
- Alpaca is the best-in-class API for retail algo trading (BrokerChooser #1 in 2026)
- $0 to start - free paper trading, free IEX real-time data, $0 commissions
- Pure Python gives full control over strategy logic and lowest latency for 2-min candle strategies
- Expert developer can handle building the indicator/signal engine
- Same codebase works for backtesting, paper trading, and live execution

### Design Inspiration: Jesse Framework

Borrow architectural patterns from [Jesse](https://github.com/jesse-ai/jesse) (a crypto trading framework) for the strategy engine - NOT the crypto domain:

- **Strategy-as-a-class**: Base `Strategy` class with overridable methods (`should_long()`, `go_long()`, `should_exit()`)
- **Unified execution**: Identical strategy code runs across backtesting, paper trading, and live trading
- **Declarative indicators**: Clean syntax for accessing technical indicators
- **Declarative hyperparameters**: Strategies declare tunable parameters for optimization
- **Built-in risk management**: Utilities for position sizing and stop-loss calculation

### Tech Stack

- **Language**: Python 3.11+
- **Broker/Execution**: Alpaca (`alpaca-py`)
- **Data**: Alpaca real-time WebSocket (IEX free tier) + historical bars API
- **Technical Analysis**: `pandas-ta` (pure Python, easy install on Windows) or `ta-lib`
- **Data Manipulation**: `pandas`, `numpy`
- **Data Storage**: SQLite (WAL mode) for transactional data + Parquet files for bulk analytical data
- **Analytical Queries**: DuckDB (in-process, no server) against Parquet files
- **ORM/Abstraction**: SQLAlchemy (enables future PostgreSQL migration)
- **Scheduling**: `APScheduler` for in-process job scheduling
- **Async I/O**: `asyncio` + `websockets` for real-time data streams
- **Web UI**: React frontend + FastAPI backend (WebSocket for real-time)
- **Bot Control**: Discord bot (notifications + commands in one platform)
- **Notifications**: Console/logging initially; Discord webhooks later
- **Containerization**: Docker (portable across local/cloud)
- **Platform**: Windows 11 for development (Docker for deployment)

---

## Key Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Broker | Alpaca | Best API, $0 cost, free paper trading, largest community |
| Data source | Alpaca built-in (IEX) | Free, real-time, integrated with broker. Upgrade to SIP ($9/mo) later |
| Language | Python | Best ecosystem for finance (pandas, ta-lib), best broker SDK support |
| Strategy pattern | Jesse-inspired class inheritance | Clean separation, same code for backtest/paper/live |
| Database | SQLite + Parquet hybrid | SQLite (WAL mode) for transactional data, Parquet files for bulk analytical data (market history, backtests). DuckDB as in-process analytical query engine. Abstract via SQLAlchemy for future PostgreSQL/TimescaleDB migration if needed |
| Safety | Paper-only with kill switch | Explicit env var/config flag required to enable live trading |
| TA library | pandas-ta | Pure Python, clean install on Windows (ta-lib is notoriously hard on Windows) |
| Notifications | Layered approach | Console first, add Discord/email later |
| Web UI | React + FastAPI | Dashboard, strategy config, backtesting. Jesse-inspired. React experience + Python backend |
| Bot control | Discord bot | Dual-purpose: notifications AND command interface (/status, /stop, /positions) |
| TradingView | Removed | Not needed - pure Python engine handles all analysis |
| PDT Rule | Fund above $25K | Plan to fund account above $25K threshold, no PDT constraint in design |
| Backtesting | Custom-built | Jesse-inspired: same strategy code runs in backtest and live mode |
| Short selling | Both long and short | Margin account on Alpaca; strategy supports both directions |
| Options | Not now, architect for later | Abstract broker interface so IBKR/Tradier can be added for options |
| Deployment | Docker container | Containerized for portability - run locally during dev, push to cloud later |
| AI analysis | Yes, integrated | Use AI/ML for pattern recognition, sentiment analysis, signal augmentation |
| AI role | Advisory, NOT decision-maker | Deterministic strategy engine decides. AI provides confidence scores, analysis, commentary as inputs. Per architecture review. |
| AI agents | Persona-based analysis | Agent personas provide commentary and analysis. One active agent at a time, switchable. Inspired by Alpha Arena |
| Agent commentary | Dashboard + dedicated chat | Short updates in activity feed, full reasoning in agent chat view |
| Short selling | Long-only Phase 1, add shorts Phase 2 | Low-float stocks often hard-to-borrow; need SSR/uptick handling. Get core engine solid first. |
| Broker abstraction | Defer to when needed | Build Alpaca directly in Phase 1. Refactor to adapter pattern when adding a second provider. |
| Risk management | Phase 1 (non-negotiable) | Position sizing, daily loss limits from day one. Even paper trading builds habits. |
| Backtesting engine | Phase 1 | Needed to validate Velez strategy before any trading. Minimal backtest UI in Phase 1. |

---

## Trading Strategies

### Strategy 1: Velez Strategy (primary, Phase 1)

**Timeframe**: 2-minute candles

**Setup Condition**:
- 20 SMA and 200 SMA are "tight": `abs(20SMA - 200SMA) / price < threshold%` (configurable, start ~2%)
- 20 SMA begins diverging from 200 SMA (upward for long, downward for short)

**Long Entry**:
1. SMAs are tight, 20 SMA starts diverging upward from 200 SMA
2. A strong green candle forms (the "first bar") - wait for it to fully close
3. Place a **buy-stop** at the first bar's high
4. When price breaks that high on subsequent bars → confirmation, order fills
5. **Stop loss**: below the first bar's low + small buffer

**Short Entry**:
1. SMAs are tight, 20 SMA starts diverging downward from 200 SMA
2. A strong red candle forms (the "first bar") - wait for it to fully close
3. Place a **sell-stop** at the first bar's low
4. When price breaks that low on subsequent bars → confirmation, order fills
5. **Stop loss**: above the first bar's high + small buffer

**Exit / Trailing Stop** (candle-structure based):
- **Short**: On a minor pullback (green candle), if followed by two red candles, move stop to the top of that green candle
- **Long**: On a minor pullback (red candle), if followed by two green candles, move stop to the bottom of that red candle
- **Max run rule**: After a pullback candle and subsequent overtake of high/low, allow max 3 consecutive strong candles before exiting
- Additional rules for specific candle types to be defined during implementation

**Order types used**: Buy-stop (long entry), sell-stop (short entry), bracket orders for stop-loss

---

## Pre-Market Scanner

### Filter Criteria (all configurable via web UI)

| Filter | Default | Notes |
|--------|---------|-------|
| Price range | $1 - $20 | Min $1 excludes penny stocks |
| Relative volume (1-day) | >= 5x | Unusual volume vs. average |
| Pre-market gap | > 2% | Gap up or down from previous close |
| Exchange | US only, no OTC | NYSE, NASDAQ, AMEX |
| Float | 100K - 10M shares | Low-float momentum plays |
| Price change (1-day) | >= 10% | Already showing strong movement |
| Market cap | Configurable | Default TBD, adjustable per strategy |
| Sector exclusions | Biotech, SPACs | Avoid binary event stocks |

### Output: Tiered Watchlist

- **Tier 1**: Strongest candidates - auto-monitored by strategy engine at open
- **Tier 2**: Decent - monitored if Tier 1 is thin
- **Tier 3**: Marginal - logged only, available for manual review in web UI

Scoring: weighted combination of relative volume, gap %, float tightness, price change strength, and **lower price preference** (cheaper stocks score higher, all else equal). All weights configurable via web UI.

### Catalyst Tagging

Basic news API lookup annotates each candidate with recent headlines/events. Phase 3 AI upgrades this to sentiment scoring.

### Scan Schedule (ramps up approaching open)

- 4:00 AM - First scan (overnight news movers)
- 6:00 AM - Second scan
- 7:30 AM - Third scan (European influence)
- 8:30 AM - Fourth scan (economic data releases)
- 9:00 AM - Fifth scan (final pre-market picture)
- 9:15 AM - Sixth scan (last-minute refinement)
- 9:25 AM - Final scan (lock watchlist for open)

Watchlist evolves between scans - stocks can move between tiers as conditions change.

---

### Future Strategies

Additional strategies (momentum/breakout, mean reversion, etc.) will be defined later. The Jesse-inspired strategy class architecture supports adding new strategies as plug-in modules without changing core code.

---

## AI-Powered Trading Agents

### Architecture Decision (per Architecture Review)

**The deterministic strategy engine is the decision-maker.** AI provides advisory analysis, commentary, and confidence scoring as inputs to the strategy engine. AI does NOT autonomously execute trades.

This resolves the fundamental tension: the strategy engine is predictable, backtestable, and auditable. AI adds value without adding non-deterministic risk to the execution path. The strategy engine can always trade independently if the LLM API is down.

**Future/experimental**: AI-recommended trades requiring human confirmation. Full autonomous AI execution only after extensive validation and with hard guardrails.

### Core Concept: Agent Personas

Inspired by [Alpha Arena (nof1.ai)](https://nof1.ai/) - AI agents with distinct personas provide analysis and commentary on market conditions and strategy signals. Each persona has a unique "voice" and analytical style.

### Agent Definition

An agent persona consists of:
- **Name**: Human-readable identifier (e.g., "Cautious Carl", "Momentum Mike")
- **LLM Model**: Which AI model powers it (Claude, GPT, DeepSeek, Gemini, etc.)
- **System Prompt / Personality**: Instructions that shape analytical perspective and commentary style
- **Commentary Style**: How the agent "speaks" about its analysis - technical, casual, terse, detailed

### How It Works (Advisory Mode)

1. Strategy engine generates a signal (e.g., Velez setup detected on AAPL)
2. Agent receives: market data, the signal, account state, scanner context
3. Agent analyzes the situation through its persona's lens
4. Agent outputs: **confidence score** (0-1) + **reasoning commentary**
5. Strategy engine uses confidence score as one input to its decision (configurable weight)
6. Strategy engine decides and executes (or not)
7. Commentary is logged and displayed in the UI

### Agent Commentary

- **Dashboard activity feed**: Short status updates ("AAPL Velez setup detected - confidence 0.82. Strong volume confirmation, SMA gap tightening nicely.")
- **Dedicated agent chat view**: Full reasoning chain with market context, pattern observations, and sentiment analysis

### Agent Management

- Define multiple agent personas (different models, different prompts, or both)
- Switch active analysis agent as desired
- All agent analysis and commentary logged for review
- Compare different agents' commentary on the same signals

### AI Analysis Capabilities

- **News/Sentiment Analysis**: Analyze headlines, earnings, SEC filings for sentiment signals
- **Pattern Recognition**: Identify chart patterns that traditional indicators miss
- **Signal Confidence Scoring**: Rate signal strength as input to strategy engine
- **Trade Review**: Post-trade analysis of what worked and what didn't
- **Anomaly Detection**: Flag unusual volume, price action, or market conditions

---

## Web UI Design

### Design Principles
- Clean, approachable, easy to use, powerful (inspired by Jesse's feel, NOT a clone)
- Dark theme by default (light mode optional)
- Desktop-first (1440px+), responsive down to mobile for monitoring only
- Progressive disclosure: essentials first, expand for depth
- Consistent color language: green=profit/healthy, red=loss/error, amber=warning, blue=informational
- Meaningful empty states that guide users to action
- Workspace persistence: save/restore layout state across sessions

### Navigation: Collapsible Left Sidebar

```
App Shell
├── Top Bar (persistent): Market Status Pill | Page Title | P&L Chip | Notifications Bell | Account
├── Left Sidebar (persistent, collapsible 56px↔220px)
│   ├── Dashboard        /
│   ├── Scanner          /scanner
│   ├── Strategies       /strategies
│   ├── Agents           /agents
│   ├── Backtesting      /backtesting
│   ├── Trade History    /history
│   ├── Charts           /charts
│   ├── Settings         /settings
│   └── [footer] System Status indicator (green/yellow/red) → slide-out panel
└── Main Content Area
```

Keyboard shortcuts: `D` dashboard, `S` scanner, `C` charts, `/` global symbol search, `?` shortcut help

### Screen 1: Dashboard (`/`)

Command center. Live-updating. Trader's default view during market hours.

**Zone A - Summary Ribbon** (full width, top): 6 metric cards
- Account Balance (+ delta from yesterday)
- Today's P&L ($ and %, green/red, live)
- Open Positions (count, badge if alert state)
- Win Rate Today (% with fraction e.g. "75% - 3/4")
- Buying Power
- Strategy Status (name + running/paused)

**Zone B - Open Positions Table** (left 2/3, middle)
- Columns: Symbol (clickable→chart), Side (pill), Qty, Avg Entry, Current Price (flash on change), P&L $, P&L %, Stop Loss, Status, Actions (close, adjust stop)
- Sortable. Losing positions: warm-tinted background. Near-stop: warning indicator.
- Empty state: "No open positions" + strategy context

**Zone C - Activity Feed** (right 1/3, middle)
- Scrolling event feed, newest at top
- Color-coded left borders: blue=trades, amber=signals, red=alerts, gray=system
- Agent commentary summaries appear here
- Auto-scroll unless manually scrolled; "New events" badge

**Zone D - Mini Chart** (left 2/3, bottom)
- Compact real-time chart of most active symbol
- 1-day intraday + 20 SMA + volume
- Dropdown to switch symbols. Click → full Charts view

**Zone E - Strategy Summary Card** (right 1/3, bottom)
- Active strategy + state (Running/Paused/Stopped)
- Key params at glance. Run/Pause toggle. Last signal time.

### Screen 2: Scanner (`/scanner`)

Pre-market workflow. Used heavily 30-60 min before open.

**Top - Controls**: "Run Scan" button, last scan timestamp, quick filter toggles, "Configure Filters" → side drawer with full criteria form

**Main - Tiered Results** (3-column desktop layout)
- Tier 1 (green header): High Conviction - auto-monitored at open
- Tier 2 (neutral): Moderate - monitored if Tier 1 thin
- Tier 3 (subdued): Watch - logged only

Each stock card: Ticker, price + gap%, volume ratio, catalyst pills, sparkline, "Add to Watchlist" / "View Chart" buttons. Click to expand: sector, float, avg volume, news, SMA levels.

Mobile: single list with segmented tier control.

**Bottom - Saved Watchlist**: Persistent across sessions.

### Screen 3: Strategies (`/strategies`)

List/detail layout.

**Left - Strategy List**: Cards with name, status toggle (Enabled/Disabled), description, performance summary, "Configure" button.

**Right - Strategy Detail** (3 tabs):
- **Parameters**: Grouped form (MA settings, timeframe/execution, risk management). Tooltips on each param. Inline validation. Save / Reset to Defaults.
- **Performance**: Equity curve, key stats (trades, win rate, avg win/loss, profit factor, Sharpe, max drawdown), recent trades table.
- **Signals Log**: Chronological signals (acted on + filtered), with timestamp, symbol, type, reason.

### Screen 4: Agents (`/agents`)

AI agent persona management and commentary.

**Left Panel - Agent Selector**: List of defined personas with avatar/icon. Active agent highlighted.

**Main Panel - Agent Chat**: Chat-style feed of active agent's reasoning commentary. Timestamped messages showing observations, analysis, and decisions as they happen.

**Right Panel (collapsible) - Agent Profile**: Name, model, personality summary, current state, performance stats (win rate, P&L, trades made).

**Agent Management** (accessible here or via Settings): Create/edit personas, configure model + system prompt + personality, switch active agent.

### Screen 5: Backtesting (`/backtesting`)

**Top - Config Card**: Strategy selector, agent persona selector, symbol(s), date range (with presets), initial capital, "Run Backtest" button, progress bar with ETA.

**Results Summary Ribbon**: Total Return, Win Rate, Total Trades, Profit Factor, Max Drawdown, Sharpe Ratio.

**Results Tabs**:
- **Equity Curve**: Portfolio value over time + drawdown shading + trade markers
- **Trade List**: Sortable table (entry/exit date, symbol, side, prices, P&L, duration, reason)
- **Statistics**: Monthly returns heatmap, win/loss histogram, avg hold period, best/worst trade, streaks, return by day of week, drawdown analysis
- **Agent Commentary**: Agent's reasoning log for each decision during backtest

**Saved Backtests**: Sidebar list of previous runs, click to reload.

### Screen 6: Trade History (`/history`)

**Filters Bar**: Date range (presets), symbol, side, outcome (winners/losers), strategy, agent.

**Summary Stats Row**: Total Trades, Win Rate, Total P&L, Avg P&L/trade, Avg Hold Time, Largest Win/Loss.

**Trade Table**: Date, Symbol, Side, Qty, Entry/Exit Price, Cost Basis, Proceeds, P&L $, P&L %, Duration, Strategy, Agent, Notes (editable).

**Expandable Row**: Precise timestamps, triggering signal, agent reasoning, chart snippet with entry/exit markers.

**Export CSV** button.

### Screen 7: Charts (`/charts`)

Dedicated technical analysis view.

**Top Bar**: Symbol search (type-ahead), timeframe selector (1m/2m/5m/15m/30m/1H/1D), indicator toggles (20 SMA, 200 SMA, Volume), date range.

**Main Chart** (~80%): Candlestick chart, price/time axes, crosshair cursor, SMA overlays with legend, volume sub-chart, trade entry/exit markers with tooltips. Real-time candle formation, auto-scroll at live edge.

**Right Sidebar** (collapsible, ~20%): Current price/bid/ask/volume/day range, key levels (open, prev close, pre-market high/low), SMA values + gap %, open position details if applicable, watchlist.

### Screen 8: Settings (`/settings`)

Vertical tab list (left) + content panel (right).

**Tabs**:
- **Broker**: Provider selector, API keys (masked), paper/live toggle (prominent warning on live), connection test
- **Data Provider**: Provider selector, API key, refresh interval, connection test
- **Risk Management (Global)**: Max allocation/position %, max positions, max daily loss ($/%), circuit breaker auto-pause
- **Agents**: Persona list, create/edit/delete, model selector, API key per model, system prompt, personality, commentary style, set active
- **Notifications**: Discord webhook URL, notification matrix (events × channels: Discord/Browser/None)
- **Appearance**: Dark/light theme toggle, dashboard density (comfortable/compact)

### System Status Panel (slide-out from sidebar footer)

~400px right-edge slide-out panel.

**Connection Cards**: Broker (status dot, last heartbeat, latency), Data Feed (status, last data, streaming count), Discord Bot (status, last message). Each has "Reconnect" button.

**System Logs**: Reverse-chronological, severity filter (All/Error/Warning/Info), text search, auto-scroll toggle.

### UX Patterns

- **Price flash**: 300ms green/red background pulse on price change
- **Animated P&L numbers**: Digits roll smoothly to new values
- **Activity feed slide-in**: New entries animate from top
- **Stale data indicators**: "Last updated: X ago" + dimmed prices when data stops
- **Non-blocking connection banners**: "Data feed disconnected - reconnecting..." with pulse animation (no modal dialogs)
- **Confirmation only for destructive actions**: Close position, disable live strategy, paper→live switch, clear history
- **Contextual help tooltips**: `?` icon on every strategy parameter

---

## Phased Rollout (Revised per Architecture Review)

### Phase 1: Trading Engine (CLI + Minimal UI)
- Alpaca paper trading account setup (direct integration, no abstraction layer yet)
- Strategy base class (Jesse-inspired) + Velez strategy implementation (long-only to start)
- Real-time data via Alpaca WebSocket
- **Order state machine** with explicit states (pending, submitted, partial, filled, canceled, failed), transitions, and recovery
- **Position sizing and risk management from day one** (max position size, 1-2% risk per trade, daily loss limits)
- Backtesting engine (reuses strategy classes)
- Trade logging to SQLite with immutable trade ledger + mutable trade journal (notes)
- Broker state reconciliation on startup
- **Logging architecture**: structured JSON logging, log levels, correlation IDs tying signals to orders
- **Configuration management**: defaults in code, overrides in config file (YAML/TOML), secrets in `.env`
- **Time handling**: all timestamps UTC, NTP sync, market calendar (`exchange-calendars`), stale/missing candle handling
- Secret management (`.env` + `.env.example` in repo, `.env` in `.gitignore`)
- Paper-trading-only mode with kill switch
- Console/CLI interface for monitoring and control
- Docker smoke test (basic `Dockerfile` to validate Linux build, catch path/line-ending issues)
- `.gitattributes` for LF line endings
- **Minimal Web UI (React + FastAPI)**: Dashboard (positions, P&L, activity feed) + Settings page only. Real-time via WebSocket.

### Phase 2: Full Web UI + Monitoring
- Full 8-screen web UI (Dashboard, Scanner, Strategies, Agents, Backtesting, Trade History, Charts, Settings)
- System status slide-out panel
- Pre-market scanner
- Advanced trade metrics (cost/share, P&L, win rate, trade timespan, pattern analysis)
- **Short selling support** (margin account, hard-to-borrow handling, SSR/uptick rule checks, short-specific position sizing)
- Discord notifications (one-way webhooks only initially)

### Phase 3: Production Hardening + Docker
- Production Docker Compose setup
- Health monitoring and automated alerts (WebSocket alive, candle arrival, memory, API success rates)
- Backup and disaster recovery procedures
- Circuit breaker: max orders/minute, auto-pause on anomalies
- Discord bot commands (add control interface on top of existing notifications)

### Phase 4: AI Analysis System (Advisory, NOT Decision-Making)
- AI-powered signal analysis: news/sentiment scoring, pattern recognition, confidence scoring
- AI confidence score as **one input to the deterministic strategy engine** (not the decision-maker)
- Agent commentary system (analysis notes in activity feed + dedicated chat view)
- Agent persona framework (model + system prompt + personality for commentary style)
- Agent management UI
- Post-trade AI review and insights
- **Future/experimental**: AI-recommended trades requiring human confirmation via UI

### Phase 5: Go Live
- Fund Alpaca account (above $25K for no PDT restriction)
- Production hardening verification
- Start with minimal position sizes
- Monitor and tune strategies
- Scale gradually

### Future
- Broker/data abstraction layer (refactor Alpaca into adapter pattern when adding a second provider)
- IBKR or Tradier adapters for options trading
- Parquet + DuckDB for analytical data (when SQLite performance becomes a real issue)
- AI autonomous execution with hard guardrails (only after extensive paper trading with AI recommendations)

---

## Resolved Questions

1. **PDT Rule**: Plan to fund above $25K to avoid the constraint entirely
2. **Backtesting**: Custom-built, Jesse-inspired - same strategy classes run in both backtest and live mode
3. **Short Selling**: Both long and short supported. Margin account on Alpaca required
4. **Options**: Not a priority now. Abstract the broker interface so IBKR or Tradier can be added later for options
5. **Deployment**: Docker containers - develop locally, deploy anywhere when ready
6. **AI Integration**: Use AI/ML for analysis (pattern recognition, sentiment, signal augmentation)

## Broker & Data Abstraction Design

Two separate plugin/adapter abstractions, configured independently:

**DataProvider** (market data) - adapters: Alpaca, Polygon.io, Finnhub, etc.
- `get_bars(symbol, timeframe, start, end)` → historical OHLCV
- `get_latest_quote(symbol)` → bid/ask/last
- `stream_bars(symbols, timeframe)` → async real-time bars
- `stream_quotes(symbols)` → async real-time quotes
- `get_snapshot(symbol)` → current price + volume + daily stats
- `is_market_open()` → market hours check

**BrokerAdapter** (execution only) - adapters: Alpaca, IBKR, Tradier, etc.
- `get_account()` → balance, buying power, margin
- `get_positions()` → open positions with P&L
- `place_order()` → market, limit, stop, stop-limit
- `place_bracket_order()` → entry + stop-loss + take-profit
- `place_trailing_stop()` → trailing stop order
- `cancel_order(order_id)` / `cancel_all_orders()` → kill switch
- `get_order_status(order_id)` → fills, partial fills
- `stream_trade_updates()` → async order fill/cancel events

Both adapters normalize responses into common dataclasses (`Order`, `Position`, `Bar`, `Quote`). Strategy code never imports broker/data libraries directly. Adapters registered via config:

```yaml
data:
  provider: alpaca     # or "polygon", "finnhub"
broker:
  adapter: alpaca      # or "ibkr", "tradier"
  paper_trading: true
```

Day one: Alpaca for both. Can independently swap data or execution later without touching strategy code.

---

## Engineering Standards

### Quality Bar
This system handles real money. Every component must be production-grade.

### Process Requirements
1. **Deep planning before implementation** - Use `/workflows:plan` before building any feature. No cowboy coding.
2. **Architectural review** - All architectural decisions run through the `architecture-strategist` reviewer agent
3. **Frontend design review** - All frontend code reviewed via `/frontend-design` skill. The web UI must be A+++ quality: user friendly, powerful, logical, and **consistent**
4. **Frontend code review** - All React/TypeScript code reviewed via `kieran-typescript-reviewer`. Always use TypeScript reviewer for any frontend changes.
5. **Frontend UI/UX decisions** - Use the `frontend-design` skill for all UI/UX recommendations and design work
6. **Tech stack decisions** - Always pass through the user for approval. Never assume.
7. **Knowledge compounding** - Run `/workflows:compound` at the end of each effort to capture learnings in `docs/solutions/`
8. **Comprehensive testing**:
   - **Unit tests** - All strategy logic, broker adapters, data providers, risk management
   - **Integration tests** - Broker API integration, data pipeline, WebSocket connections
   - **E2E tests** - Full signal-to-execution flow, web UI workflows, Discord bot commands
9. **Code review** - Use specialized review agents (code-simplicity, security-sentinel, performance-oracle) for critical components

### Testing Strategy
- Strategy logic must be testable with mock market data (no live API calls in unit tests)
- Broker adapters tested against both mock and sandbox/paper trading APIs
- Web UI tested with Playwright or similar for e2e browser tests
- All tests must pass before any merge to main

---

## Architecture Review Findings (Need Deeper Planning)

The following items were identified by architecture review and need dedicated design work during `/workflows:plan`:

1. **Order state machine**: Explicit states (pending, submitted, partial, filled, canceled, failed), transitions, recovery actions, crash resilience
2. **Time handling**: NTP sync, UTC everywhere, market calendar, stale/missing candle handling, half-day holidays, trading halts
3. **Audit trail**: Immutable trade ledger (order submissions, fills, prices) separate from mutable trade journal (notes, tags). Broker state reconciliation on startup.
4. **Logging architecture**: Structured JSON logging, log levels, correlation IDs (signal → order), log rotation, separate streams for trading vs system ops
5. **Configuration management**: Hierarchy (code defaults → config file → env vars → runtime API). Hot-reload of strategy params without restart.
6. **Secret management**: `.env` files for dev, Docker secrets for deployment, `.env.example` in repo
7. **Velez strategy math spec**: Precise definitions for "tight", "strong candle", "buffer". Edge cases: market open noise, trading halts, candles with no body, minimum 200 bars for 200 SMA
8. **Performance requirements**: Max latency from candle close to order submission (~5s budget), max concurrent symbols, memory budget, WebSocket reconnection requirements
9. **Health monitoring**: Automated checks for WebSocket alive, candle arrival cadence, memory usage, LLM API success rate
10. **Disaster recovery**: DB backup schedule, crash-mid-trade recovery, position reconciliation, max orders/minute circuit breaker

## Remaining Open Questions

1. **Pre-market Data**: Does Alpaca's free tier include pre-market data for scanning, or is that SIP-only? (Blocking dependency for scanner - resolve before implementation)
2. **AI Approach**: Which AI capabilities to prioritize, which models/APIs to use, cost budget per day
3. **Charting library**: Tech stack decision for the Charts screen (TradingView Lightweight Charts, Recharts, D3, etc.)
4. **React framework**: Next.js, Vite + React, Create React App, etc. (tech stack decision for user)

---

## Cost Summary

| Item | Phase 1 | Phase 2+ |
|------|---------|----------|
| Alpaca (paper + IEX data) | $0 | $0 |
| Python + all libraries | $0 | $0 |
| Alpaca SIP data | - | ~$9/month |
| Cloud VM (optional) | - | ~$5-6/month |
| AI API (Claude/OpenAI) | - | ~$5-20/month (usage-based) |
| **Total** | **$0** | **~$20-35/month** |
