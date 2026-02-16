"""Integration tests for BacktestDataLoader against real Alpaca API.

Requires real API keys. Skips when ALGO_BROKER__API_KEY not set.
Run with: uv run pytest -m integration -v
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.backtest.data_loader import BacktestDataLoader
from app.broker.types import Bar
from app.config import BrokerConfig

pytestmark = pytest.mark.integration


def _make_broker_config(alpaca_config: Any) -> BrokerConfig:
    """Convert test fixture to BrokerConfig."""
    return BrokerConfig(
        api_key=alpaca_config.api_key,
        secret_key=alpaca_config.secret_key,
        feed=alpaca_config.feed,
    )


class TestBacktestDataLoader:
    """Integration tests for BacktestDataLoader — fetches real market data."""

    @pytest.mark.asyncio
    async def test_load_bars_returns_data(
        self,
        alpaca_config: Any,
    ) -> None:
        """Fetch real AAPL bars for a known trading day."""
        config = _make_broker_config(alpaca_config)
        loader = BacktestDataLoader(config)

        bars = await loader.load_bars(
            symbols=["AAPL"],
            start_date=date(2025, 1, 6),  # Monday
            end_date=date(2025, 1, 6),
        )

        assert len(bars) > 0
        assert all(isinstance(b, Bar) for b in bars)
        assert all(b.symbol == "AAPL" for b in bars)

    @pytest.mark.asyncio
    async def test_bars_have_correct_types(
        self,
        alpaca_config: Any,
    ) -> None:
        """Verify Bar fields are correct Decimal/int types."""
        config = _make_broker_config(alpaca_config)
        loader = BacktestDataLoader(config)

        bars = await loader.load_bars(
            symbols=["AAPL"],
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 6),
        )

        bar = bars[0]
        assert isinstance(bar.open, Decimal)
        assert isinstance(bar.high, Decimal)
        assert isinstance(bar.low, Decimal)
        assert isinstance(bar.close, Decimal)
        assert isinstance(bar.volume, int)
        assert bar.open > Decimal("0")
        assert bar.volume > 0

    @pytest.mark.asyncio
    async def test_bars_sorted_by_timestamp(
        self,
        alpaca_config: Any,
    ) -> None:
        """Bars must be sorted oldest-first by timestamp."""
        config = _make_broker_config(alpaca_config)
        loader = BacktestDataLoader(config)

        bars = await loader.load_bars(
            symbols=["AAPL"],
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 7),
        )

        timestamps = [b.timestamp for b in bars]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_multi_symbol_bars_interleaved(
        self,
        alpaca_config: Any,
    ) -> None:
        """Multi-symbol fetch returns bars for all symbols, sorted."""
        config = _make_broker_config(alpaca_config)
        loader = BacktestDataLoader(config)

        bars = await loader.load_bars(
            symbols=["AAPL", "MSFT"],
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 6),
        )

        symbols_seen = {b.symbol for b in bars}
        assert "AAPL" in symbols_seen
        assert "MSFT" in symbols_seen

        # Sorted by (timestamp, symbol)
        keys = [(b.timestamp, b.symbol) for b in bars]
        assert keys == sorted(keys)

    @pytest.mark.asyncio
    async def test_bars_within_market_hours(
        self,
        alpaca_config: Any,
    ) -> None:
        """All bars should be within market hours (9:30-16:00 ET)."""
        from zoneinfo import ZoneInfo

        config = _make_broker_config(alpaca_config)
        loader = BacktestDataLoader(config)

        bars = await loader.load_bars(
            symbols=["AAPL"],
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 6),
        )

        et = ZoneInfo("America/New_York")
        for bar in bars:
            bar_time = bar.timestamp.astimezone(et).time()
            assert bar_time.hour >= 9
            assert bar_time.hour < 16 or (
                bar_time.hour == 9 and bar_time.minute >= 30
            )
