"""Integration tests with Alpaca paper trading API.

These tests require real API keys and make real API calls.
They are marked with @pytest.mark.integration and skip automatically
when ALGO_BROKER__API_KEY / ALGO_BROKER__SECRET_KEY are not set.

Run with: uv run pytest -m integration -v
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.broker.types import OrderRequest, OrderType, Side

pytestmark = pytest.mark.integration


class TestDataProviderIntegration:
    """Integration tests for AlpacaDataProvider against real API."""

    async def test_get_historical_bars_real(
        self,
        data_provider: Any,
    ) -> None:
        """Fetch real AAPL 1-min bars and verify types."""
        bars = await data_provider.get_historical_bars(
            "AAPL",
            count=5,
            timeframe="1Min",
        )
        assert len(bars) > 0
        bar = bars[0]
        assert bar.symbol == "AAPL"
        assert isinstance(bar.open, Decimal)
        assert isinstance(bar.high, Decimal)
        assert isinstance(bar.low, Decimal)
        assert isinstance(bar.close, Decimal)
        assert isinstance(bar.volume, int)

    async def test_get_latest_quote_real(
        self,
        data_provider: Any,
    ) -> None:
        """Fetch real AAPL quote and verify all fields populated."""
        quote = await data_provider.get_latest_quote("AAPL")
        assert quote.symbol == "AAPL"
        assert isinstance(quote.bid, Decimal)
        assert isinstance(quote.ask, Decimal)
        assert isinstance(quote.last, Decimal)
        assert quote.bid > Decimal("0")
        assert quote.ask > Decimal("0")
        assert quote.last > Decimal("0")

    async def test_get_historical_bars_daily(
        self,
        data_provider: Any,
    ) -> None:
        """Fetch daily bars to verify timeframe mapping."""
        bars = await data_provider.get_historical_bars(
            "AAPL",
            count=3,
            timeframe="1Day",
        )
        assert len(bars) > 0


class TestBrokerAdapterIntegration:
    """Integration tests for AlpacaBrokerAdapter against real API."""

    async def test_get_account_real(
        self,
        broker_adapter: Any,
    ) -> None:
        """Fetch paper account and verify Decimal equity."""
        acct = await broker_adapter.get_account()
        assert isinstance(acct.equity, Decimal)
        assert isinstance(acct.cash, Decimal)
        assert isinstance(acct.buying_power, Decimal)
        assert acct.equity > Decimal("0")

    async def test_get_positions_real(
        self,
        broker_adapter: Any,
    ) -> None:
        """Fetch positions (may be empty)."""
        positions = await broker_adapter.get_positions()
        assert isinstance(positions, list)

    async def test_submit_and_cancel_order(
        self,
        broker_adapter: Any,
    ) -> None:
        """Submit a limit order far from market, then cancel it."""
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("1.00"),  # Far from market
        )
        status = await broker_adapter.submit_order(req)
        assert status.broker_order_id
        assert status.symbol == "AAPL"

        # Cancel it
        await broker_adapter.cancel_order(status.broker_order_id)

    async def test_get_open_orders_real(
        self,
        broker_adapter: Any,
    ) -> None:
        """Submit an order, verify it appears in open orders, then cancel."""
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("1"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("1.00"),
        )
        status = await broker_adapter.submit_order(req)

        orders = await broker_adapter.get_open_orders()
        order_ids = [o.broker_order_id for o in orders]
        assert status.broker_order_id in order_ids

        await broker_adapter.cancel_order(status.broker_order_id)

    async def test_get_recent_orders_real(
        self,
        broker_adapter: Any,
    ) -> None:
        """Fetch recent orders (may be empty)."""
        orders = await broker_adapter.get_recent_orders(since_hours=1)
        assert isinstance(orders, list)
