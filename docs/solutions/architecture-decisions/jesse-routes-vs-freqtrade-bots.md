---
title: "Jesse Routes vs Freqtrade Bots — Engine vs Bot Architecture"
category: architecture-decisions
tags: [architecture, jesse, freqtrade, multi-strategy, routing]
module: Engine
symptom: "Need to understand multi-strategy execution models"
root_cause: "Fundamental architectural identity difference between frameworks"
date: 2026-02-15
context: "Architecture review comparing algo-trader vs freqtrade vs Jesse"
---

# Jesse Routes vs Freqtrade Bots

## The Two Models

**Freqtrade = Bot-centric.** The bot IS the process. One strategy class across N pairs. Config, database, Telegram, web UI — all scoped to one bot. Want two strategies? Deploy two bots (two processes, two configs, two databases).

**Jesse = Engine-centric.** No "bot" concept. You define routes (symbol + timeframe + strategy class), and the engine orchestrates all of them in one process with shared infrastructure.

```python
# Jesse routes example
routes = [
    ('Binance', 'BTC-USDT', '4h', 'TrendFollowing'),
    ('Binance', 'ETH-USDT', '1h', 'MeanReversion'),
]
```

## algo-trader Alignment

Our architecture maps to Jesse's model:
- TradingEngine = orchestrator managing multiple strategy instances
- One strategy instance per symbol (already in Strategy ABC)
- Shared broker connection, database, risk management
- Adding a new strategy = write subclass + add to routing config

## Tradeoff: Shared Process

**Upside of Jesse/algo-trader model:**
- Shared infrastructure (one DB connection, one broker connection, one risk manager)
- Cross-strategy risk management (global daily loss limit across all strategies)
- Simpler deployment (one process, one config)

**Upside of Freqtrade's model:**
- Blast radius isolation — strategy A crashing doesn't affect strategy B
- Independent scaling and resource allocation
- Simpler per-instance debugging

**Our mitigation:** Task Supervisor with restart/escalation handles strategy-level failures within the shared process. Individual strategy crashes should be caught and isolated without bringing down the engine.

## Decision

Engine-centric (Jesse model). The Task Supervisor provides crash isolation within a single process. If we ever need true process-level isolation, we can run multiple engine instances — but that's a scaling concern, not an architecture concern.

## Related

- [Indicator Extensibility Requirement](./indicator-extensibility-requirement.md)
