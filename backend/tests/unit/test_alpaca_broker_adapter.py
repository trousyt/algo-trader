"""Tests for AlpacaBrokerAdapter.

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

from app.broker.alpaca.broker import AlpacaBrokerAdapter
from app.broker.errors import (
    BrokerAPIError,
    BrokerAuthError,
    BrokerNotConnectedError,
)
from app.broker.types import (
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderType,
    Side,
    TradeEventType,
)


def _make_api_error(status_code: int, message: str = "error") -> object:
    """Create an APIError with proper status_code property behavior."""
    from alpaca.common.exceptions import APIError

    http_error = SimpleNamespace(
        response=SimpleNamespace(status_code=status_code),
    )
    return APIError(f'{{"code": {status_code}, "message": "{message}"}}', http_error)


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        api_key="test-key",
        secret_key="test-secret",
        paper=True,
    )


def _make_alpaca_order(
    order_id: str = "order-uuid-123",
    status: str = "new",
    filled_qty: str = "0",
    filled_avg_price: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        symbol="AAPL",
        side="buy",
        qty="10",
        type="market",
        status=status,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
        submitted_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
    )


class TestConnect:
    """Test AlpacaBrokerAdapter.connect() behavior."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_connect_creates_clients(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        mock_trading_cls.assert_called_once()
        mock_stream_cls.assert_called_once()
        await adapter.disconnect()

    async def test_connect_validates_empty_api_key(self) -> None:
        config = SimpleNamespace(
            api_key="",
            secret_key="test-secret",
            paper=True,
        )
        adapter = AlpacaBrokerAdapter(config)
        with pytest.raises(BrokerAuthError, match="API key"):
            await adapter.connect()

    async def test_connect_validates_empty_secret_key(self) -> None:
        config = SimpleNamespace(
            api_key="test-key",
            secret_key="",
            paper=True,
        )
        adapter = AlpacaBrokerAdapter(config)
        with pytest.raises(BrokerAuthError, match="secret key"):
            await adapter.connect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_connect_twice_is_noop(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        await adapter.connect()
        assert mock_trading_cls.call_count == 1
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_connect_validates_via_api_call(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_trading_cls.return_value = mock_client
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        mock_client.get_account.assert_called_once()
        await adapter.disconnect()


class TestDisconnect:
    """Test AlpacaBrokerAdapter.disconnect() behavior."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_disconnect_stops_stream(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        await adapter.disconnect()
        mock_stream.stop.assert_called()

    async def test_disconnect_when_not_connected(self) -> None:
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.disconnect()


class TestSubmitOrder:
    """Test order submission."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_submit_market_order(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.submit_order.return_value = _make_alpaca_order()
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()

        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        status = await adapter.submit_order(req)
        assert status.broker_order_id == "order-uuid-123"
        assert status.symbol == "AAPL"
        assert status.side == Side.BUY
        assert status.status == BrokerOrderStatus.NEW
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_submit_stop_order(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.submit_order.return_value = _make_alpaca_order()
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()

        req = OrderRequest(
            symbol="AAPL",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.STOP,
            stop_price=Decimal("145.50"),
        )
        status = await adapter.submit_order(req)
        assert status.broker_order_id == "order-uuid-123"
        mock_client.submit_order.assert_called_once()
        await adapter.disconnect()

    async def test_submit_order_not_connected(self) -> None:
        adapter = AlpacaBrokerAdapter(_make_config())
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        with pytest.raises(BrokerNotConnectedError):
            await adapter.submit_order(req)

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_submit_order_api_error_422(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.submit_order.side_effect = _make_api_error(422, "Unprocessable")
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()

        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        with pytest.raises(BrokerAPIError) as exc_info:
            await adapter.submit_order(req)
        assert exc_info.value.status_code == 422
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_submit_order_auth_error_401(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.submit_order.side_effect = _make_api_error(401, "Unauthorized")
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()

        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        with pytest.raises(BrokerAuthError):
            await adapter.submit_order(req)
        await adapter.disconnect()


class TestBracketOrder:
    """Test bracket order submission."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_submit_bracket_order(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.submit_order.return_value = _make_alpaca_order()
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()

        req = BracketOrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
            stop_loss_price=Decimal("145.00"),
            take_profit_price=Decimal("160.00"),
        )
        status = await adapter.submit_bracket_order(req)
        assert status.broker_order_id == "order-uuid-123"
        await adapter.disconnect()


class TestCancelOrder:
    """Test order cancellation."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_cancel_order(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        await adapter.cancel_order("order-uuid-123")
        mock_client.cancel_order_by_id.assert_called_once_with("order-uuid-123")
        await adapter.disconnect()


class TestReplaceOrder:
    """Test order replacement."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_replace_order(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.replace_order_by_id.return_value = _make_alpaca_order()
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        status = await adapter.replace_order(
            "order-uuid-123",
            qty=Decimal("20"),
            limit_price=Decimal("155.00"),
        )
        assert status.broker_order_id == "order-uuid-123"
        mock_client.replace_order_by_id.assert_called_once()
        await adapter.disconnect()


class TestGetters:
    """Test account/position/order getters."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_get_positions(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_all_positions.return_value = [
            SimpleNamespace(
                symbol="AAPL",
                qty="10",
                side="long",
                avg_entry_price="150.00",
                market_value="1500.00",
                unrealized_pl="0",
                unrealized_plpc="0",
            ),
        ]
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        positions = await adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert isinstance(positions[0].avg_entry_price, Decimal)
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_get_account(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_account.return_value = SimpleNamespace(
            equity="100000.00",
            cash="50000.00",
            buying_power="200000.00",
            portfolio_value="100000.00",
            daytrade_count=0,
            pattern_day_trader=False,
        )
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        acct = await adapter.get_account()
        assert isinstance(acct.equity, Decimal)
        assert acct.equity == Decimal("100000.00")
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_get_order_status(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_order_by_id.return_value = _make_alpaca_order(
            status="filled",
            filled_qty="10",
            filled_avg_price="150.50",
        )
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        status = await adapter.get_order_status("order-uuid-123")
        assert status.status == BrokerOrderStatus.FILLED
        assert status.filled_avg_price == Decimal("150.50")
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_get_open_orders(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_orders.return_value = [_make_alpaca_order()]
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        orders = await adapter.get_open_orders()
        assert len(orders) == 1
        assert orders[0].broker_order_id == "order-uuid-123"
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_get_recent_orders(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_orders.return_value = [_make_alpaca_order()]
        mock_trading_cls.return_value = mock_client

        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        orders = await adapter.get_recent_orders(since_hours=24)
        assert len(orders) == 1
        await adapter.disconnect()


class TestTradeUpdates:
    """Test trade update streaming."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_subscribe_trade_updates_yields_updates(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()

        update_iter = await adapter.subscribe_trade_updates()

        # Push an update into the internal queue directly
        from app.broker.alpaca.mappers import alpaca_trade_update_to_trade_update

        alpaca_update = SimpleNamespace(
            event="fill",
            order=SimpleNamespace(
                id="order-uuid-123",
                symbol="AAPL",
                side="buy",
                qty="10",
                filled_qty="10",
                filled_avg_price="150.50",
            ),
            price="150.50",
            qty="10",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        trade_update = alpaca_trade_update_to_trade_update(alpaca_update)
        assert trade_update is not None
        adapter._trade_queue.put_nowait(trade_update)

        update = await asyncio.wait_for(update_iter.__anext__(), timeout=1.0)
        assert update.event == TradeEventType.FILL
        assert update.order_id == "order-uuid-123"
        await adapter.disconnect()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_trade_update_queue_unbounded(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        """Trade update queue must be unbounded — fill events are critical."""
        adapter = AlpacaBrokerAdapter(_make_config())
        await adapter.connect()
        assert adapter._trade_queue.maxsize == 0  # 0 = unbounded
        await adapter.disconnect()


class TestContextManager:
    """Test async context manager support."""

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_context_manager(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream

        async with AlpacaBrokerAdapter(_make_config()) as adapter:
            assert adapter._connected_event.is_set()

        mock_stream.stop.assert_called()

    @patch("app.broker.alpaca.broker.TradingStream")
    @patch("app.broker.alpaca.broker.TradingClient")
    async def test_context_manager_disconnects_on_error(
        self,
        mock_trading_cls: MagicMock,
        mock_stream_cls: MagicMock,
    ) -> None:
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream

        with pytest.raises(ValueError, match="test error"):
            async with AlpacaBrokerAdapter(_make_config()):
                raise ValueError("test error")

        mock_stream.stop.assert_called()
