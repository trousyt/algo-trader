"""Tests for AlpacaDataProvider.

TDD: These tests are written BEFORE the implementation.
All tests use mocked SDK clients — no real API calls.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.broker.alpaca.data import AlpacaDataProvider
from app.broker.errors import BrokerAuthError, BrokerNotConnectedError


def _make_config() -> SimpleNamespace:
    """Create a minimal config object for testing."""
    return SimpleNamespace(
        api_key="test-key",
        secret_key="test-secret",
        paper=True,
        feed="iex",
    )


def _make_alpaca_bar(
    symbol: str = "AAPL",
    price: float = 150.0,
) -> SimpleNamespace:
    """Create a mock Alpaca SDK bar."""
    return SimpleNamespace(
        symbol=symbol,
        timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        open=price,
        high=price + 1.0,
        low=price - 0.5,
        close=price + 0.5,
        volume=1000.0,
    )


class TestConnect:
    """Test AlpacaDataProvider.connect() behavior."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    async def test_connect_creates_clients(
        self,
        mock_hist_client_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        provider = AlpacaDataProvider(_make_config())
        # Mock the credential validation call
        mock_trading_client = MagicMock()
        tc_path = "app.broker.alpaca.data.TradingClient"
        with patch(tc_path, return_value=mock_trading_client):
            await provider.connect()

        mock_hist_client_cls.assert_called_once()
        mock_stream_cls.assert_called_once()
        await provider.disconnect()

    async def test_connect_validates_empty_api_key(self) -> None:
        config = SimpleNamespace(
            api_key="",
            secret_key="test-secret",
            paper=True,
            feed="iex",
        )
        provider = AlpacaDataProvider(config)
        with pytest.raises(BrokerAuthError, match="API key"):
            await provider.connect()

    async def test_connect_validates_empty_secret_key(self) -> None:
        config = SimpleNamespace(
            api_key="test-key",
            secret_key="",
            paper=True,
            feed="iex",
        )
        provider = AlpacaDataProvider(config)
        with pytest.raises(BrokerAuthError, match="secret key"):
            await provider.connect()

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_connect_twice_is_noop(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        provider = AlpacaDataProvider(_make_config())
        await provider.connect()
        await provider.connect()  # Should not raise
        # Only one client created
        assert mock_hist_cls.call_count == 1
        await provider.disconnect()

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_connect_validates_via_api_call(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        """connect() calls get_account() to validate credentials."""
        mock_trading_client = MagicMock()
        mock_trading_cls.return_value = mock_trading_client
        provider = AlpacaDataProvider(_make_config())
        await provider.connect()
        mock_trading_client.get_account.assert_called_once()
        await provider.disconnect()


class TestDisconnect:
    """Test AlpacaDataProvider.disconnect() behavior."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_disconnect_stops_stream(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream
        provider = AlpacaDataProvider(_make_config())
        await provider.connect()
        await provider.disconnect()
        mock_stream.stop.assert_called()

    async def test_disconnect_when_not_connected(self) -> None:
        provider = AlpacaDataProvider(_make_config())
        await provider.disconnect()  # Should not raise


class TestGetHistoricalBars:
    """Test AlpacaDataProvider.get_historical_bars()."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_returns_bars_with_decimal_prices(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_hist_cls.return_value = mock_client

        # Mock response: BarSet-like object with .data dict
        mock_bar = _make_alpaca_bar("AAPL", 150.0)
        mock_client.get_stock_bars.return_value = SimpleNamespace(
            data={"AAPL": [mock_bar]},
        )

        provider = AlpacaDataProvider(_make_config())
        await provider.connect()
        bars = await provider.get_historical_bars("AAPL", count=10)
        assert len(bars) == 1
        assert isinstance(bars[0].open, Decimal)
        assert bars[0].symbol == "AAPL"
        await provider.disconnect()

    async def test_not_connected_raises(self) -> None:
        provider = AlpacaDataProvider(_make_config())
        with pytest.raises(BrokerNotConnectedError):
            await provider.get_historical_bars("AAPL", count=10)


class TestGetLatestQuote:
    """Test AlpacaDataProvider.get_latest_quote()."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_returns_quote_with_decimal_prices(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_hist_cls.return_value = mock_client

        # Mock latest quote response
        mock_quote = SimpleNamespace(
            bid_price=150.0,
            ask_price=150.05,
            bid_size=100,
            ask_size=200,
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        mock_client.get_stock_latest_quote.return_value = {"AAPL": mock_quote}

        # Mock latest trade response
        mock_trade = SimpleNamespace(
            price=150.02,
        )
        mock_client.get_stock_latest_trade.return_value = {"AAPL": mock_trade}

        provider = AlpacaDataProvider(_make_config())
        await provider.connect()
        quote = await provider.get_latest_quote("AAPL")
        assert isinstance(quote.bid, Decimal)
        assert isinstance(quote.ask, Decimal)
        assert isinstance(quote.last, Decimal)
        assert quote.bid == Decimal("150.0")
        assert quote.last == Decimal("150.02")
        await provider.disconnect()


class TestSubscribeBars:
    """Test AlpacaDataProvider.subscribe_bars()."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_yields_converted_bars(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        provider = AlpacaDataProvider(_make_config())
        await provider.connect()

        # Simulate bar arriving through the queue
        bar_iter = await provider.subscribe_bars(["AAPL"])

        # Push a bar into the internal queue directly
        from app.broker.alpaca.mappers import alpaca_bar_to_bar

        test_bar = alpaca_bar_to_bar(_make_alpaca_bar("AAPL", 150.0))
        provider._bar_queue.put_nowait(test_bar)

        bar = await asyncio.wait_for(bar_iter.__anext__(), timeout=1.0)
        assert bar.symbol == "AAPL"
        assert isinstance(bar.close, Decimal)
        await provider.disconnect()

    async def test_subscribe_not_connected_raises(self) -> None:
        provider = AlpacaDataProvider(_make_config())
        with pytest.raises(BrokerNotConnectedError):
            await provider.subscribe_bars(["AAPL"])


class TestContextManager:
    """Test async context manager support."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_context_manager_connects_and_disconnects(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream

        async with AlpacaDataProvider(_make_config()) as provider:
            assert provider._connected_event.is_set()

        mock_stream.stop.assert_called()

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_context_manager_disconnects_on_error(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        """__aexit__ should not propagate disconnect failures."""
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream

        with pytest.raises(ValueError, match="test error"):
            async with AlpacaDataProvider(_make_config()):
                raise ValueError("test error")

        # disconnect was still called even though body raised
        mock_stream.stop.assert_called()


class TestBarQueueBackpressure:
    """Test bar queue backpressure handling."""

    @patch("app.broker.alpaca.data.StockDataStream")
    @patch("app.broker.alpaca.data.StockHistoricalDataClient")
    @patch("app.broker.alpaca.data.TradingClient")
    async def test_full_queue_drops_newest_with_log(
        self,
        mock_trading_cls: MagicMock,
        mock_hist_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        provider = AlpacaDataProvider(_make_config())
        await provider.connect()

        # Fill the queue to capacity
        from app.broker.alpaca.mappers import alpaca_bar_to_bar

        test_bar = alpaca_bar_to_bar(_make_alpaca_bar("AAPL", 150.0))
        for _ in range(provider._bar_queue.maxsize):
            provider._bar_queue.put_nowait(test_bar)

        assert provider._bar_queue.full()

        # Try to enqueue one more — should not raise, should drop newest
        new_bar = alpaca_bar_to_bar(_make_alpaca_bar("AAPL", 999.0))
        provider._enqueue_bar(new_bar)

        # Queue should still be full at max capacity
        assert provider._bar_queue.full()

        await provider.disconnect()
