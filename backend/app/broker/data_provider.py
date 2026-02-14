"""DataProvider protocol — abstract interface for market data sources.

All broker data implementations (Alpaca, IBKR, fake) must satisfy this protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.broker.types import Bar, Quote


@runtime_checkable
class DataProvider(Protocol):
    """Async interface for streaming and historical market data.

    Implementations must support ``async with`` for lifecycle management.
    ``subscribe_bars`` can only be called once per connection — the returned
    iterator is tied to the internal queue. Use ``update_bar_subscription``
    to add/remove symbols on an active subscription.
    """

    async def connect(self) -> None:
        """Establish connection to the data source."""
        ...

    async def disconnect(self) -> None:
        """Tear down connection and release resources."""
        ...

    async def subscribe_bars(
        self,
        symbols: list[str],
    ) -> AsyncIterator[Bar]:
        """Start streaming bars for the given symbols.

        Can only be called once per connection. Raises BrokerError
        if called a second time — use update_bar_subscription instead.

        Returns:
            AsyncIterator that yields Bar objects as they arrive.
        """
        ...

    async def update_bar_subscription(
        self,
        symbols: list[str],
    ) -> None:
        """Update the active bar subscription to a new set of symbols."""
        ...

    async def get_historical_bars(
        self,
        symbol: str,
        count: int,
        timeframe: str = "1Min",
    ) -> list[Bar]:
        """Fetch historical bars for a symbol.

        Args:
            symbol: Ticker symbol (e.g. "AAPL").
            count: Number of bars to retrieve.
            timeframe: Bar interval (e.g. "1Min", "5Min", "1Hour", "1Day").

        Returns:
            List of Bar objects ordered by timestamp ascending.
        """
        ...

    async def get_latest_quote(self, symbol: str) -> Quote:
        """Fetch the latest quote (bid/ask/last) for a symbol."""
        ...

    async def __aenter__(self) -> DataProvider:
        """Connect on context manager entry."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Disconnect on context manager exit."""
        ...
