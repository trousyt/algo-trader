# Algo Trader

An algorithmic trading system for US equities that performs technical analysis on real-time market data, detects trading signals, and executes trades automatically.

## Vision

Build a production-grade automated trading platform that combines deterministic technical analysis strategies with AI-powered advisory analysis. The system scans for opportunities pre-market, monitors positions in real-time, manages risk automatically, and provides a polished web dashboard for monitoring and control.

## Goals

- **Automate proven strategies** - Encode technical analysis rules (starting with the Velez SMA convergence strategy) and let the system execute them consistently without emotional interference
- **Manage risk first** - Position sizing, stop-losses, daily loss limits, and a kill switch are built in from day one
- **Learn and iterate** - Comprehensive trade logging, backtesting, and performance metrics to refine strategies over time
- **Stay in control** - Paper trading by default, explicit opt-in for live trading, real-time monitoring dashboard, and Discord notifications
- **AI as advisor, not autopilot** - AI agents provide analysis, confidence scores, and commentary as inputs to the deterministic strategy engine. The strategy engine always makes the final call.

## Key Features

### Trading Engine
- Jesse-inspired strategy framework: define strategies as classes, run the same code in backtest, paper, and live modes
- Real-time 2-minute candle data via Alpaca WebSocket
- Order state machine with crash recovery and broker reconciliation
- Structured logging with correlation IDs from signal detection through order execution

### Pre-Market Scanner
- Configurable filters: price range, relative volume, gap %, float, sector exclusions
- Tiered watchlist output (Tier 1/2/3) with weighted scoring
- Ramping scan schedule from 4:00 AM through 9:25 AM ET

### Risk Management
- 1-2% max risk per trade with automatic position sizing
- Stop-loss placement per strategy rules
- Daily loss limits and circuit breaker auto-pause
- Paper-trading-only by default with explicit env var required for live trading

### Backtesting
- Same strategy classes used in live trading run against historical data
- Performance metrics: equity curve, win rate, profit factor, Sharpe ratio, max drawdown
- Monthly returns heatmap, trade-by-trade analysis, drawdown visualization

### AI Advisory System
- Agent personas with configurable LLM models and system prompts
- Confidence scoring on detected signals as input to strategy decisions
- News/sentiment analysis, pattern recognition, anomaly detection
- Full commentary log for post-trade review

### Web Dashboard
- Real-time positions, P&L, and activity feed
- 8 screens: Dashboard, Scanner, Strategies, Agents, Backtesting, Trade History, Charts, Settings
- Dark theme, desktop-first, keyboard shortcuts
- WebSocket-powered live updates

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Broker / Execution | Alpaca (`alpaca-py`) |
| Market Data | Alpaca WebSocket (IEX free tier) |
| Technical Analysis | `pandas-ta` |
| Database | SQLite (WAL mode) via SQLAlchemy |
| Web Backend | FastAPI + WebSocket |
| Web Frontend | React + TypeScript |
| Notifications | Discord webhooks |
| Containerization | Docker |

## Project Status

**Phase**: Pre-development (design and planning)

The brainstorm and architecture review are complete. The project is ready for implementation planning via phased rollout:

1. **Phase 1** - Trading engine (CLI + minimal dashboard), Velez strategy, risk management, backtesting, paper trading
2. **Phase 2** - Full web UI, pre-market scanner, short selling, advanced trade metrics
3. **Phase 3** - Production Docker Compose, health monitoring, circuit breakers, Discord bot commands
4. **Phase 4** - AI advisory system, agent personas, confidence scoring, post-trade review
5. **Phase 5** - Go live with real capital (above $25K for no PDT restriction)

## Cost

| Item | Phase 1 | Phase 2+ |
|------|---------|----------|
| Alpaca (paper + IEX data) | $0 | $0 |
| Python + all libraries | $0 | $0 |
| Alpaca SIP data upgrade | - | ~$9/month |
| Cloud VM (optional) | - | ~$5-6/month |
| AI API (Claude/GPT/etc.) | - | ~$5-20/month |
| **Total** | **$0** | **~$20-35/month** |

## Getting Started

> **Note**: The project is in the design phase. Setup instructions will be added as implementation begins.

## Documentation

- [Brainstorm & Design Decisions](docs/brainstorms/2026-02-13-algo-trader-brainstorm.md) - Complete architecture decisions, strategy specifications, UI design, and phased rollout plan

## License

TBD
