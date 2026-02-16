"""Tests for BacktestDataLoader — mocked Alpaca client."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.backtest.config import BacktestError
from app.backtest.data_loader import BacktestDataLoader
from app.config import BrokerConfig

_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def _make_broker_config() -> BrokerConfig:
    return BrokerConfig(
        api_key="test-key",
        secret_key="test-secret",
        base_url="https://paper-api.alpaca.markets",
        feed="iex",
    )


def _make_alpaca_bar(
    *,
    timestamp: datetime,
    open_: float = 150.0,
    high: float = 151.0,
    low: float = 149.0,
    close: float = 150.5,
    volume: int = 1000,
) -> SimpleNamespace:
    """Create a mock alpaca bar (SimpleNamespace mimics SDK bar attributes)."""
    return SimpleNamespace(
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_response(data: dict[str, list[SimpleNamespace]]) -> SimpleNamespace:
    """Create a mock response with .data.get() interface."""
    mock_data = MagicMock()
    mock_data.get = MagicMock(side_effect=lambda sym, default=None: data.get(sym, default or []))
    return SimpleNamespace(data=mock_data)


class TestFetchSymbol:
    """Tests for the synchronous _fetch_symbol method."""

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_converts_alpaca_bars_to_domain_bars(
        self, mock_client_cls: MagicMock,
    ) -> None:
        ts = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)  # 10:00 ET
        alpaca_bar = _make_alpaca_bar(
            timestamp=ts,
            open_=150.25,
            high=151.50,
            low=149.75,
            close=150.80,
            volume=5000,
        )
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({"AAPL": [alpaca_bar]})
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert len(bars) == 1
        bar = bars[0]
        assert bar.symbol == "AAPL"
        assert bar.timestamp == ts
        assert bar.open == Decimal("150.25")
        assert bar.high == Decimal("151.5")
        assert bar.low == Decimal("149.75")
        assert bar.close == Decimal("150.8")
        assert bar.volume == 5000

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_filters_pre_market_bars(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Bars before 9:30 ET should be filtered out."""
        pre_market = datetime(2026, 2, 10, 14, 0, tzinfo=_UTC)  # 9:00 ET
        market_hours = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)  # 10:00 ET

        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({
            "AAPL": [
                _make_alpaca_bar(timestamp=pre_market),
                _make_alpaca_bar(timestamp=market_hours),
            ],
        })
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert len(bars) == 1
        assert bars[0].timestamp == market_hours

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_filters_after_hours_bars(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Bars at or after 16:00 ET should be filtered out."""
        at_close = datetime(2026, 2, 10, 21, 0, tzinfo=_UTC)  # 16:00 ET
        after_hours = datetime(2026, 2, 10, 22, 0, tzinfo=_UTC)  # 17:00 ET
        market_hours = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)  # 10:00 ET

        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({
            "AAPL": [
                _make_alpaca_bar(timestamp=market_hours),
                _make_alpaca_bar(timestamp=at_close),
                _make_alpaca_bar(timestamp=after_hours),
            ],
        })
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert len(bars) == 1
        assert bars[0].timestamp == market_hours

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_bar_at_930_included(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Bar exactly at 9:30 ET should be included."""
        at_open = datetime(2026, 2, 10, 14, 30, tzinfo=_UTC)  # 9:30 ET

        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({
            "AAPL": [_make_alpaca_bar(timestamp=at_open)],
        })
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert len(bars) == 1

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_bar_at_1559_included(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Bar at 15:59 ET should be included (last valid minute)."""
        last_minute = datetime(2026, 2, 10, 20, 59, tzinfo=_UTC)  # 15:59 ET

        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({
            "AAPL": [_make_alpaca_bar(timestamp=last_minute)],
        })
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert len(bars) == 1

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_empty_response_returns_empty_list(
        self, mock_client_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({"AAPL": []})
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert bars == []

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_missing_symbol_returns_empty_list(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Symbol not in response.data should return empty list."""
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({})
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        assert bars == []

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_decimal_conversion_precision(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Float to Decimal via str should preserve precision."""
        ts = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)
        alpaca_bar = _make_alpaca_bar(
            timestamp=ts,
            open_=123.456789,
            high=124.0,
            low=122.0,
            close=123.5,
        )
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({"AAPL": [alpaca_bar]})
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 10))

        # Decimal(str(123.456789)) preserves float repr
        assert bars[0].open == Decimal("123.456789")

    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    def test_request_uses_correct_params(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Verify StockBarsRequest is constructed with correct parameters."""
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({"AAPL": []})
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        loader._fetch_symbol("AAPL", date(2026, 2, 10), date(2026, 2, 14))

        mock_client.get_stock_bars.assert_called_once()
        request = mock_client.get_stock_bars.call_args[0][0]

        assert request.symbol_or_symbols == ["AAPL"]
        # SDK Pydantic model converts tz-aware to UTC-naive internally
        # 9:30 ET = 14:30 UTC, 16:00 ET = 21:00 UTC
        assert request.start == datetime(2026, 2, 10, 14, 30)
        assert request.end == datetime(2026, 2, 14, 21, 0)
        assert request.limit is None


class TestLoadBars:
    """Tests for the async load_bars method."""

    @pytest.mark.asyncio
    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    async def test_single_symbol_returns_bars(
        self, mock_client_cls: MagicMock,
    ) -> None:
        ts1 = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)
        ts2 = datetime(2026, 2, 10, 15, 1, tzinfo=_UTC)

        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({
            "AAPL": [
                _make_alpaca_bar(timestamp=ts1),
                _make_alpaca_bar(timestamp=ts2),
            ],
        })
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = await loader.load_bars(["AAPL"], date(2026, 2, 10), date(2026, 2, 10))

        assert len(bars) == 2
        assert bars[0].timestamp < bars[1].timestamp

    @pytest.mark.asyncio
    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    async def test_multi_symbol_merged_and_sorted(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Multiple symbols should be merged and sorted by (timestamp, symbol)."""
        ts1 = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)
        ts2 = datetime(2026, 2, 10, 15, 1, tzinfo=_UTC)

        def mock_get_bars(request: MagicMock) -> SimpleNamespace:
            symbol = request.symbol_or_symbols[0]
            return _make_response({
                symbol: [
                    _make_alpaca_bar(timestamp=ts1),
                    _make_alpaca_bar(timestamp=ts2),
                ],
            })

        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = mock_get_bars
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        bars = await loader.load_bars(
            ["MSFT", "AAPL"],
            date(2026, 2, 10),
            date(2026, 2, 10),
        )

        assert len(bars) == 4
        # Same timestamp: AAPL before MSFT (alpha order)
        assert bars[0].symbol == "AAPL"
        assert bars[0].timestamp == ts1
        assert bars[1].symbol == "MSFT"
        assert bars[1].timestamp == ts1
        assert bars[2].symbol == "AAPL"
        assert bars[2].timestamp == ts2
        assert bars[3].symbol == "MSFT"
        assert bars[3].timestamp == ts2

    @pytest.mark.asyncio
    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    async def test_zero_bars_raises_backtest_error(
        self, mock_client_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_response({"AAPL": []})
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())

        with pytest.raises(BacktestError, match="No bars returned for AAPL"):
            await loader.load_bars(["AAPL"], date(2026, 2, 10), date(2026, 2, 10))

    @pytest.mark.asyncio
    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    async def test_one_symbol_empty_in_multi_raises(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """If one of multiple symbols returns zero bars, raise BacktestError."""
        ts = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)

        def mock_get_bars(request: MagicMock) -> SimpleNamespace:
            symbol = request.symbol_or_symbols[0]
            if symbol == "AAPL":
                return _make_response({"AAPL": [_make_alpaca_bar(timestamp=ts)]})
            return _make_response({"MSFT": []})

        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = mock_get_bars
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())

        with pytest.raises(BacktestError, match="No bars returned for MSFT"):
            await loader.load_bars(
                ["AAPL", "MSFT"],
                date(2026, 2, 10),
                date(2026, 2, 10),
            )

    @pytest.mark.asyncio
    @patch("app.backtest.data_loader.StockHistoricalDataClient")
    async def test_concurrent_fetching(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Verify multiple symbols result in multiple SDK calls."""
        ts = datetime(2026, 2, 10, 15, 0, tzinfo=_UTC)

        def mock_get_bars(request: MagicMock) -> SimpleNamespace:
            symbol = request.symbol_or_symbols[0]
            return _make_response({
                symbol: [_make_alpaca_bar(timestamp=ts)],
            })

        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = mock_get_bars
        mock_client_cls.return_value = mock_client

        loader = BacktestDataLoader(_make_broker_config())
        await loader.load_bars(
            ["AAPL", "MSFT", "GOOG"],
            date(2026, 2, 10),
            date(2026, 2, 10),
        )

        assert mock_client.get_stock_bars.call_count == 3
