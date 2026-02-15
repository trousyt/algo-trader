"""AlpacaDataProvider — market data via alpaca-py SDK.

Bridges the sync/blocking alpaca-py SDK to our async architecture:
- WebSocket bar streaming runs in a dedicated daemon thread
- REST calls run in a ThreadPoolExecutor via run_in_executor
- call_soon_threadsafe bridges the thread boundary safely
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Self

import structlog
from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient

from app.broker.alpaca.mappers import alpaca_bar_to_bar
from app.broker.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerNotConnectedError,
)
from app.broker.types import Bar, Quote
from app.broker.utils import to_decimal

logger = structlog.get_logger()

# Bar queue capacity — ~2.7 hours of bars for 5 symbols at 1-min
BAR_QUEUE_MAXSIZE = 10_000

# Timeframe string to alpaca-py TimeFrame mapping
_TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}


class AlpacaDataProvider:
    """DataProvider implementation backed by the Alpaca SDK.

    Uses StockDataStream for real-time bar streaming and
    StockHistoricalDataClient for REST data fetches.
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._hist_client: StockHistoricalDataClient | None = None
        self._stream: StockDataStream | None = None
        self._ws_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._bar_queue: asyncio.Queue[Bar] = asyncio.Queue(
            maxsize=BAR_QUEUE_MAXSIZE,
        )
        self._connected_event = threading.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._subscribed = False

    def _enqueue_bar(self, bar: Bar) -> None:
        """Enqueue a bar safely, dropping newest if queue is full.

        Called via call_soon_threadsafe from the WS callback thread.
        Uses drop-newest strategy to preserve time-series continuity.
        """
        if self._bar_queue.full():
            logger.critical(
                "Bar queue full, dropping newest item",
                symbol=bar.symbol,
                queue_size=self._bar_queue.qsize(),
            )
            return
        self._bar_queue.put_nowait(bar)

    async def connect(self) -> None:
        """Establish connections to Alpaca data services."""
        async with self._lifecycle_lock:
            if self._connected_event.is_set():
                logger.warning("AlpacaDataProvider already connected")
                return

            api_key = self._config.api_key
            secret_key = self._config.secret_key

            if not api_key:
                raise BrokerAuthError(
                    "API key is required. "
                    "Set ALGO_BROKER__API_KEY environment variable.",
                )
            if not secret_key:
                raise BrokerAuthError(
                    "API secret key is required. "
                    "Set ALGO_BROKER__SECRET_KEY environment variable.",
                )

            # Validate credentials via lightweight API call
            trading_client = TradingClient(
                api_key,
                secret_key,
                paper=self._config.paper,
            )
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    trading_client.get_account,
                )
            except APIError as e:
                if hasattr(e, "status_code") and e.status_code in (401, 403):
                    raise BrokerAuthError(
                        f"Invalid API credentials: {e}",
                    ) from e
                raise BrokerConnectionError(
                    f"Failed to validate credentials: {e}",
                ) from e

            self._hist_client = StockHistoricalDataClient(api_key, secret_key)
            self._stream = StockDataStream(
                api_key,
                secret_key,
                feed=self._config.data_feed,
            )
            self._executor = ThreadPoolExecutor(max_workers=4)
            self._main_loop = asyncio.get_event_loop()
            self._connected_event.set()

            logger.info("AlpacaDataProvider connected")

    async def disconnect(self) -> None:
        """Tear down connections and release resources."""
        async with self._lifecycle_lock:
            if not self._connected_event.is_set():
                return

            if self._stream is not None:
                self._stream.stop()

            if self._ws_thread is not None and self._ws_thread.is_alive():
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            self._ws_thread.join,
                            5.0,
                        ),
                        timeout=10.0,
                    )
                except TimeoutError:
                    logger.critical(
                        "WebSocket thread did not terminate",
                        thread=self._ws_thread.name,
                    )

            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None

            self._connected_event.clear()
            self._subscribed = False
            logger.info("AlpacaDataProvider disconnected")

    async def subscribe_bars(
        self,
        symbols: list[str],
    ) -> AsyncIterator[Bar]:
        """Start streaming bars for the given symbols.

        Can only be called once per connection. Use update_bar_subscription()
        to change symbols on an active subscription.
        """
        if not self._connected_event.is_set():
            raise BrokerNotConnectedError(
                "Not connected. Call connect() first.",
            )
        if self._subscribed:
            raise BrokerError(
                "subscribe_bars() already called. "
                "Use update_bar_subscription() to change symbols.",
            )

        self._subscribed = True

        # Register the bar callback
        assert self._stream is not None
        self._stream.subscribe_bars(self._bar_callback, *symbols)

        # Start the WebSocket thread
        self._ws_thread = threading.Thread(
            target=self._run_stream,
            name="alpaca-data-stream",
            daemon=True,
        )
        self._ws_thread.start()

        return self._bar_iterator()

    async def _bar_iterator(self) -> AsyncIterator[Bar]:
        """Yield bars from the internal queue."""
        while self._connected_event.is_set():
            try:
                bar = await asyncio.wait_for(
                    self._bar_queue.get(),
                    timeout=1.0,
                )
                yield bar
            except TimeoutError:
                continue

    async def update_bar_subscription(
        self,
        symbols: list[str],
    ) -> None:
        """Update the active bar subscription to a new set of symbols."""
        if not self._connected_event.is_set():
            raise BrokerNotConnectedError(
                "Not connected. Call connect() first.",
            )
        if self._stream is None:
            return
        # The SDK supports dynamic subscription changes
        self._stream.subscribe_bars(self._bar_callback, *symbols)

    async def get_historical_bars(
        self,
        symbol: str,
        count: int,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        """Fetch historical bars for a symbol via REST."""
        if not self._connected_event.is_set():
            raise BrokerNotConnectedError(
                "Not connected. Call connect() first.",
            )
        assert self._hist_client is not None
        assert self._executor is not None

        tf = _TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            msg = f"Unsupported timeframe: {timeframe}"
            raise ValueError(msg)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            limit=count,
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            self._executor,
            self._hist_client.get_stock_bars,
            request,
        )

        alpaca_bars = response.get(symbol, [])  # type: ignore[union-attr]
        return [alpaca_bar_to_bar(b) for b in alpaca_bars]

    async def get_latest_quote(self, symbol: str) -> Quote:
        """Fetch the latest quote (bid/ask from quote + last from trade)."""
        if not self._connected_event.is_set():
            raise BrokerNotConnectedError(
                "Not connected. Call connect() first.",
            )
        assert self._hist_client is not None
        assert self._executor is not None

        loop = asyncio.get_event_loop()

        # Fetch quote and trade in parallel via executor
        quote_req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        trade_req = StockLatestTradeRequest(symbol_or_symbols=symbol)

        quote_resp, trade_resp = await asyncio.gather(
            loop.run_in_executor(
                self._executor,
                self._hist_client.get_stock_latest_quote,
                quote_req,
            ),
            loop.run_in_executor(
                self._executor,
                self._hist_client.get_stock_latest_trade,
                trade_req,
            ),
        )

        alpaca_quote = quote_resp[symbol]
        alpaca_trade = trade_resp[symbol]

        return Quote(
            symbol=symbol,
            timestamp=alpaca_quote.timestamp,
            bid=to_decimal(alpaca_quote.bid_price),
            ask=to_decimal(alpaca_quote.ask_price),
            last=to_decimal(alpaca_trade.price),
            bid_size=int(alpaca_quote.bid_size),
            ask_size=int(alpaca_quote.ask_size),
            volume=0,  # Daily volume not available from quote endpoint
        )

    async def _bar_callback(self, alpaca_bar: Any) -> None:
        """WebSocket bar callback — runs in the SDK's internal event loop.

        Bridges to the main event loop via call_soon_threadsafe.
        """
        bar = alpaca_bar_to_bar(alpaca_bar)
        if self._main_loop is not None:
            self._main_loop.call_soon_threadsafe(self._enqueue_bar, bar)

    def _run_stream(self) -> None:
        """Target for the WebSocket thread. Blocking call."""
        try:
            assert self._stream is not None
            self._stream.run()
        except Exception:
            logger.exception("Data stream thread died unexpectedly")

    async def __aenter__(self) -> Self:
        """Connect on context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Disconnect on context manager exit.

        Wraps disconnect in try/except to avoid masking the original exception.
        """
        try:
            await self.disconnect()
        except Exception:
            logger.exception("Error during disconnect in __aexit__")
