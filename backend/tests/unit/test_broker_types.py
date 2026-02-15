"""Tests for broker domain types.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.broker.types import (
    AccountInfo,
    Bar,
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    TimeInForce,
    TradeEventType,
    TradeUpdate,
)


class TestBar:
    """Test Bar frozen dataclass."""

    def test_bar_is_frozen(self) -> None:
        bar = Bar(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            open=Decimal("150.00"),
            high=Decimal("151.00"),
            low=Decimal("149.50"),
            close=Decimal("150.75"),
            volume=1000,
        )
        with pytest.raises(FrozenInstanceError):
            bar.symbol = "MSFT"  # type: ignore[misc]

    def test_bar_decimal_fields(self) -> None:
        bar = Bar(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            open=Decimal("150.00"),
            high=Decimal("151.00"),
            low=Decimal("149.50"),
            close=Decimal("150.75"),
            volume=1000,
        )
        assert isinstance(bar.open, Decimal)
        assert isinstance(bar.high, Decimal)
        assert isinstance(bar.low, Decimal)
        assert isinstance(bar.close, Decimal)

    def test_bar_volume_is_int(self) -> None:
        bar = Bar(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            open=Decimal("150.00"),
            high=Decimal("151.00"),
            low=Decimal("149.50"),
            close=Decimal("150.75"),
            volume=1000,
        )
        assert isinstance(bar.volume, int)


class TestQuote:
    """Test Quote frozen dataclass."""

    def test_quote_is_frozen(self) -> None:
        quote = Quote(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            bid=Decimal("150.00"),
            ask=Decimal("150.05"),
            last=Decimal("150.02"),
            bid_size=100,
            ask_size=200,
            volume=0,
        )
        with pytest.raises(FrozenInstanceError):
            quote.bid = Decimal("999.99")  # type: ignore[misc]

    def test_quote_decimal_fields(self) -> None:
        quote = Quote(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            bid=Decimal("150.00"),
            ask=Decimal("150.05"),
            last=Decimal("150.02"),
            bid_size=100,
            ask_size=200,
            volume=0,
        )
        assert isinstance(quote.bid, Decimal)
        assert isinstance(quote.ask, Decimal)
        assert isinstance(quote.last, Decimal)


class TestPosition:
    """Test Position mutable dataclass."""

    def test_position_is_mutable(self) -> None:
        pos = Position(
            symbol="AAPL",
            qty=Decimal("10"),
            side=Side.BUY,
            avg_entry_price=Decimal("150.00"),
            market_value=Decimal("1500.00"),
            unrealized_pl=Decimal("0.00"),
            unrealized_pl_pct=Decimal("0.00"),
        )
        pos.qty = Decimal("20")
        assert pos.qty == Decimal("20")


class TestAccountInfo:
    """Test AccountInfo mutable dataclass."""

    def test_account_info_is_mutable(self) -> None:
        acct = AccountInfo(
            equity=Decimal("100000.00"),
            cash=Decimal("50000.00"),
            buying_power=Decimal("200000.00"),
            portfolio_value=Decimal("100000.00"),
            day_trade_count=0,
            pattern_day_trader=False,
        )
        acct.equity = Decimal("110000.00")
        assert acct.equity == Decimal("110000.00")


class TestSideEnum:
    """Test Side enum values."""

    def test_side_enum_values(self) -> None:
        assert Side.BUY == "buy"
        assert Side.SELL == "sell"

    def test_side_is_string(self) -> None:
        assert isinstance(Side.BUY, str)


class TestOrderTypeEnum:
    """Test OrderType enum values."""

    def test_order_type_enum_values(self) -> None:
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT == "limit"
        assert OrderType.STOP == "stop"
        assert OrderType.STOP_LIMIT == "stop_limit"
        assert OrderType.TRAILING_STOP == "trailing_stop"

    def test_all_order_types_present(self) -> None:
        assert len(OrderType) == 5


class TestTimeInForceEnum:
    """Test TimeInForce enum values."""

    def test_time_in_force_enum_values(self) -> None:
        assert TimeInForce.DAY == "day"
        assert TimeInForce.GTC == "gtc"
        assert TimeInForce.IOC == "ioc"


class TestBrokerOrderStatusEnum:
    """Test BrokerOrderStatus enum values."""

    def test_broker_order_status_enum_values(self) -> None:
        assert BrokerOrderStatus.NEW == "new"
        assert BrokerOrderStatus.ACCEPTED == "accepted"
        assert BrokerOrderStatus.FILLED == "filled"
        assert BrokerOrderStatus.PARTIALLY_FILLED == "partially_filled"
        assert BrokerOrderStatus.CANCELED == "canceled"
        assert BrokerOrderStatus.EXPIRED == "expired"
        assert BrokerOrderStatus.REJECTED == "rejected"
        assert BrokerOrderStatus.PENDING_CANCEL == "pending_cancel"
        assert BrokerOrderStatus.REPLACED == "replaced"


class TestTradeEventTypeEnum:
    """Test TradeEventType enum values."""

    def test_trade_event_type_enum_values(self) -> None:
        assert TradeEventType.NEW == "new"
        assert TradeEventType.ACCEPTED == "accepted"
        assert TradeEventType.FILL == "fill"
        assert TradeEventType.PARTIAL_FILL == "partial_fill"
        assert TradeEventType.CANCELED == "canceled"
        assert TradeEventType.EXPIRED == "expired"
        assert TradeEventType.REJECTED == "rejected"
        assert TradeEventType.REPLACED == "replaced"
        assert TradeEventType.PENDING_CANCEL == "pending_cancel"


class TestOrderRequest:
    """Test OrderRequest frozen dataclass."""

    def test_order_request_defaults(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        assert req.time_in_force == TimeInForce.DAY
        assert req.limit_price is None
        assert req.stop_price is None
        assert req.trail_price is None
        assert req.trail_percent is None

    def test_order_request_is_frozen(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        with pytest.raises(FrozenInstanceError):
            req.qty = Decimal("20")  # type: ignore[misc]

    def test_trailing_stop_fields(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.TRAILING_STOP,
            trail_percent=Decimal("1.5"),
        )
        assert req.trail_percent == Decimal("1.5")
        assert req.trail_price is None

    def test_trailing_stop_with_trail_price(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.TRAILING_STOP,
            trail_price=Decimal("2.00"),
        )
        assert req.trail_price == Decimal("2.00")
        assert req.trail_percent is None


class TestBracketOrderRequest:
    """Test BracketOrderRequest frozen dataclass."""

    def test_bracket_order_request(self) -> None:
        req = BracketOrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
            stop_loss_price=Decimal("145.00"),
        )
        assert req.stop_loss_price == Decimal("145.00")
        assert req.take_profit_price is None

    def test_bracket_order_request_with_take_profit(self) -> None:
        req = BracketOrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.00"),
            stop_loss_price=Decimal("145.00"),
            take_profit_price=Decimal("160.00"),
        )
        assert req.take_profit_price == Decimal("160.00")

    def test_bracket_order_request_is_frozen(self) -> None:
        req = BracketOrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
            stop_loss_price=Decimal("145.00"),
        )
        with pytest.raises(FrozenInstanceError):
            req.qty = Decimal("20")  # type: ignore[misc]


class TestOrderStatus:
    """Test OrderStatus mutable dataclass."""

    def test_order_status_fields(self) -> None:
        status = OrderStatus(
            broker_order_id="test-123",
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
            status=BrokerOrderStatus.NEW,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            submitted_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        assert status.broker_order_id == "test-123"
        assert status.filled_avg_price is None

    def test_order_status_is_mutable(self) -> None:
        status = OrderStatus(
            broker_order_id="test-123",
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
            status=BrokerOrderStatus.NEW,
            filled_qty=Decimal("0"),
            filled_avg_price=None,
            submitted_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        status.status = BrokerOrderStatus.FILLED
        assert status.status == BrokerOrderStatus.FILLED


class TestTradeUpdate:
    """Test TradeUpdate mutable dataclass."""

    def test_trade_update_fields(self) -> None:
        update = TradeUpdate(
            event=TradeEventType.FILL,
            order_id="test-123",
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            filled_qty=Decimal("10"),
            filled_avg_price=Decimal("150.50"),
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        assert update.event == TradeEventType.FILL
        assert update.filled_avg_price == Decimal("150.50")

    def test_trade_update_partial_fill(self) -> None:
        update = TradeUpdate(
            event=TradeEventType.PARTIAL_FILL,
            order_id="test-123",
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            filled_qty=Decimal("5"),
            filled_avg_price=Decimal("150.50"),
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        assert update.filled_qty == Decimal("5")
