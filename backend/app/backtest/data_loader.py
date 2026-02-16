"""Historical data loader for backtesting — fetches 1-min bars from Alpaca.

Uses the alpaca-py SDK with auto-pagination. Concurrent per-symbol fetching
via asyncio.gather + run_in_executor (SDK is synchronous).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from app.backtest.config import BacktestError
from app.broker.types import Bar
from app.config import BrokerConfig

log = structlog.get_logger()

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)


class BacktestDataLoader:
    """Fetches historical 1-min bars from Alpaca REST for backtesting."""

    def __init__(self, broker_config: BrokerConfig) -> None:
        """Accept BrokerConfig (not raw keys) to limit credential exposure."""
        self._config = broker_config
        self._client = StockHistoricalDataClient(
            broker_config.api_key,
            broker_config.secret_key,
        )

    async def load_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[Bar]:
        """Fetch 1-min bars for all symbols, merged and sorted by timestamp.

        Returns oldest-first. SDK auto-paginates (no manual loop needed).
        Raises BacktestError if zero bars returned for any symbol.
        """
        loop = asyncio.get_event_loop()

        with ThreadPoolExecutor(max_workers=min(len(symbols), 5)) as executor:
            tasks = [
                loop.run_in_executor(
                    executor,
                    self._fetch_symbol,
                    symbol,
                    start_date,
                    end_date,
                )
                for symbol in symbols
            ]
            results = await asyncio.gather(*tasks)

        # Merge all symbols into one list, sorted by (timestamp, symbol)
        all_bars: list[Bar] = []
        for symbol, bars in zip(symbols, results):
            if not bars:
                raise BacktestError(
                    f"No bars returned for {symbol} "
                    f"between {start_date} and {end_date}"
                )
            log.info(
                "backtest_data_loaded",
                symbol=symbol,
                bar_count=len(bars),
                start=str(start_date),
                end=str(end_date),
            )
            all_bars.extend(bars)

        all_bars.sort(key=lambda b: (b.timestamp, b.symbol))
        log.info(
            "backtest_data_merged",
            total_bars=len(all_bars),
            symbols=symbols,
        )
        return all_bars

    def _fetch_symbol(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[Bar]:
        """Fetch bars for one symbol (runs in thread pool — blocking call)."""
        # Convert to timezone-aware datetimes (naive assumed UTC by SDK)
        start_dt = datetime.combine(start_date, _MARKET_OPEN, tzinfo=_ET)
        end_dt = datetime.combine(end_date, _MARKET_CLOSE, tzinfo=_ET)

        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start_dt,
            end=end_dt,
            limit=None,  # Fetch all — SDK auto-paginates
            adjustment=Adjustment.ALL,
            feed=DataFeed(self._config.feed),
        )

        response = self._client.get_stock_bars(request)
        alpaca_bars = response.data.get(symbol, [])

        # Convert to domain Bar objects, filter market hours
        bars: list[Bar] = []
        for ab in alpaca_bars:
            bar = Bar(
                symbol=symbol,
                timestamp=ab.timestamp,
                open=Decimal(str(ab.open)),
                high=Decimal(str(ab.high)),
                low=Decimal(str(ab.low)),
                close=Decimal(str(ab.close)),
                volume=int(ab.volume),
            )
            # Market hours filter (safety net — CandleAggregator also filters)
            bar_et = bar.timestamp.astimezone(_ET).time()
            if _MARKET_OPEN <= bar_et < _MARKET_CLOSE:
                bars.append(bar)

        return bars
