"""Tests for fake broker adapters used in downstream testing.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.broker.broker_adapter import BrokerAdapter
from app.broker.data_provider import DataProvider
from app.broker.fake.broker import FakeBrokerAdapter
from app.broker.fake.data import FakeDataProvider
from app.broker.types import (
    AccountInfo,
    Bar,
    BrokerOrderStatus,
    OrderRequest,
    OrderType,
    Position,
    Quote,
    Side,
    TradeEventType,
    TradeUpdate,
)


def _make_bar(symbol: str = "AAPL") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        open=Decimal("150.00"),
        high=Decimal("151.00"),
        low=Decimal("149.50"),
        close=Decimal("150.75"),
        volume=1000,
    )


def _make_quote(symbol: str = "AAPL") -> Quote:
    return Quote(
        symbol=symbol,
        timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        bid=Decimal("150.00"),
        ask=Decimal("150.05"),
        last=Decimal("150.02"),
        bid_size=100,
        ask_size=200,
        volume=0,
    )


class TestFakeDataProvider:
    """Test FakeDataProvider for downstream unit testing."""

    def test_satisfies_protocol(self) -> None:
        provider = FakeDataProvider()
        assert isinstance(provider, DataProvider)

    async def test_get_historical_bars_returns_canned_data(self) -> None:
        bars = [_make_bar("AAPL"), _make_bar("MSFT")]
        provider = FakeDataProvider(bars=bars)
        await provider.connect()
        result = await provider.get_historical_bars("AAPL", count=10)
        assert len(result) == 1
        assert result[0].symbol == "AAPL"
        await provider.disconnect()

    async def test_subscribe_bars_yields_pushed_bars(self) -> None:
        provider = FakeDataProvider()
        await provider.connect()
        bar_iter = await provider.subscribe_bars(["AAPL"])

        test_bar = _make_bar("AAPL")
        provider.push_bar(test_bar)

        bar = await asyncio.wait_for(bar_iter.__anext__(), timeout=1.0)
        assert bar.symbol == "AAPL"
        assert isinstance(bar.close, Decimal)
        await provider.disconnect()

    async def test_get_latest_quote(self) -> None:
        quote = _make_quote("AAPL")
        provider = FakeDataProvider(quotes={"AAPL": quote})
        await provider.connect()
        result = await provider.get_latest_quote("AAPL")
        assert result.symbol == "AAPL"
        assert result.bid == Decimal("150.00")
        await provider.disconnect()


class TestFakeBrokerAdapter:
    """Test FakeBrokerAdapter for downstream unit testing."""

    def test_satisfies_protocol(self) -> None:
        adapter = FakeBrokerAdapter()
        assert isinstance(adapter, BrokerAdapter)

    async def test_submit_order_returns_status(self) -> None:
        adapter = FakeBrokerAdapter()
        await adapter.connect()
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        status = await adapter.submit_order(req)
        assert status.symbol == "AAPL"
        assert status.broker_order_id  # Non-empty
        assert status.status == BrokerOrderStatus.ACCEPTED
        await adapter.disconnect()

    async def test_submit_order_records_for_inspection(self) -> None:
        adapter = FakeBrokerAdapter()
        await adapter.connect()
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        await adapter.submit_order(req)
        assert len(adapter.submitted_orders) == 1
        assert adapter.submitted_orders[0] is req
        await adapter.disconnect()

    async def test_get_positions_returns_configured(self) -> None:
        positions = [
            Position(
                symbol="AAPL",
                qty=Decimal("10"),
                side=Side.BUY,
                avg_entry_price=Decimal("150.00"),
                market_value=Decimal("1500.00"),
                unrealized_pl=Decimal("0"),
                unrealized_pl_pct=Decimal("0"),
            ),
        ]
        adapter = FakeBrokerAdapter(positions=positions)
        await adapter.connect()
        result = await adapter.get_positions()
        assert len(result) == 1
        assert result[0].symbol == "AAPL"
        await adapter.disconnect()

    async def test_get_account_returns_configured(self) -> None:
        acct = AccountInfo(
            equity=Decimal("100000"),
            cash=Decimal("50000"),
            buying_power=Decimal("200000"),
            portfolio_value=Decimal("100000"),
            day_trade_count=0,
            pattern_day_trader=False,
        )
        adapter = FakeBrokerAdapter(account=acct)
        await adapter.connect()
        result = await adapter.get_account()
        assert result.equity == Decimal("100000")
        await adapter.disconnect()

    async def test_subscribe_trade_updates_yields_pushed(self) -> None:
        adapter = FakeBrokerAdapter()
        await adapter.connect()
        update_iter = await adapter.subscribe_trade_updates()

        update = TradeUpdate(
            event=TradeEventType.FILL,
            order_id="fake-123",
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            filled_qty=Decimal("10"),
            filled_avg_price=Decimal("150.50"),
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        adapter.push_trade_update(update)

        result = await asyncio.wait_for(update_iter.__anext__(), timeout=1.0)
        assert result.event == TradeEventType.FILL
        await adapter.disconnect()
