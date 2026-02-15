"""FakeDataProvider — in-memory market data for testing.

Lightweight implementation of DataProvider for unit testing
downstream components (strategy engine, candle aggregator, etc.).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Self

from app.broker.types import Bar, Quote


class FakeDataProvider:
    """In-memory DataProvider for testing.

    Supply canned bars/quotes at construction, or push them dynamically
    during tests via push_bar().
    """

    def __init__(
        self,
        bars: list[Bar] | None = None,
        quotes: dict[str, Quote] | None = None,
    ) -> None:
        self._bars: list[Bar] = bars if bars is not None else []
        self._quotes: dict[str, Quote] = quotes if quotes is not None else {}
        self._bar_queue: asyncio.Queue[Bar] = asyncio.Queue()
        self._connected = False

    def push_bar(self, bar: Bar) -> None:
        """Push a bar into the streaming queue (for testing live streaming)."""
        self._bar_queue.put_nowait(bar)

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def subscribe_bars(
        self,
        symbols: list[str],
    ) -> AsyncIterator[Bar]:
        return self._bar_iterator()

    async def _bar_iterator(self) -> AsyncIterator[Bar]:
        while self._connected:
            try:
                bar = await asyncio.wait_for(
                    self._bar_queue.get(),
                    timeout=0.1,
                )
                yield bar
            except TimeoutError:
                continue

    async def update_bar_subscription(
        self,
        symbols: list[str],
    ) -> None:
        pass

    async def get_historical_bars(
        self,
        symbol: str,
        count: int,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        return [b for b in self._bars if b.symbol == symbol][:count]

    async def get_latest_quote(self, symbol: str) -> Quote:
        return self._quotes[symbol]

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        await self.disconnect()
