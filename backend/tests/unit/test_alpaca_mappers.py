"""Tests for Alpaca SDK to domain type mappers.

TDD: These tests are written BEFORE the implementation.

These tests use mock objects to simulate Alpaca SDK types, since
we're testing pure conversion functions (the Decimal boundary).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.broker.alpaca.mappers import (
    alpaca_account_to_account_info,
    alpaca_bar_to_bar,
    alpaca_order_to_order_status,
    alpaca_position_to_position,
    alpaca_trade_update_to_trade_update,
    bracket_request_to_alpaca,
    order_request_to_alpaca,
)
from app.broker.types import (
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderType,
    Side,
    TradeEventType,
)
from app.broker.utils import to_decimal


class TestToDecimal:
    """Test the shared to_decimal helper."""

    def test_from_string(self) -> None:
        result = to_decimal("123.45")
        assert result == Decimal("123.45")
        assert isinstance(result, Decimal)

    def test_from_float(self) -> None:
        result = to_decimal(123.45)
        assert result == Decimal("123.45")
        assert isinstance(result, Decimal)

    def test_float_edge_case(self) -> None:
        """0.1 + 0.2 should not produce floating point artifacts."""
        result = to_decimal(0.3)
        # Decimal(str(0.3)) == Decimal("0.3")
        assert result == Decimal("0.3")

    def test_from_zero(self) -> None:
        assert to_decimal(0.0) == Decimal("0.0")
        assert to_decimal("0") == Decimal("0")

    def test_from_int_like_float(self) -> None:
        assert to_decimal(100.0) == Decimal("100.0")


class TestAlpacaBarToBar:
    """Test conversion from Alpaca SDK bar to domain Bar."""

    def _make_alpaca_bar(self) -> SimpleNamespace:
        return SimpleNamespace(
            symbol="AAPL",
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            open=150.25,
            high=151.50,
            low=149.75,
            close=150.80,
            volume=12345.0,
        )

    def test_converts_float_prices_to_decimal(self) -> None:
        alpaca_bar = self._make_alpaca_bar()
        bar = alpaca_bar_to_bar(alpaca_bar)
        assert bar.open == Decimal("150.25")
        assert bar.high == Decimal("151.5")
        assert bar.low == Decimal("149.75")
        assert bar.close == Decimal("150.8")
        assert isinstance(bar.open, Decimal)
        assert isinstance(bar.close, Decimal)

    def test_volume_is_int(self) -> None:
        alpaca_bar = self._make_alpaca_bar()
        bar = alpaca_bar_to_bar(alpaca_bar)
        assert bar.volume == 12345
        assert isinstance(bar.volume, int)

    def test_timestamp_preserved(self) -> None:
        alpaca_bar = self._make_alpaca_bar()
        bar = alpaca_bar_to_bar(alpaca_bar)
        assert bar.timestamp == datetime(
            2026,
            1,
            15,
            10,
            0,
            tzinfo=UTC,
        )

    def test_symbol_preserved(self) -> None:
        alpaca_bar = self._make_alpaca_bar()
        bar = alpaca_bar_to_bar(alpaca_bar)
        assert bar.symbol == "AAPL"


class TestAlpacaPositionToPosition:
    """Test conversion from Alpaca SDK position to domain Position."""

    def test_converts_string_prices_to_decimal(self) -> None:
        alpaca_pos = SimpleNamespace(
            symbol="AAPL",
            qty="10",
            side="long",
            avg_entry_price="150.25",
            market_value="1502.50",
            unrealized_pl="2.50",
            unrealized_plpc="0.0017",
        )
        pos = alpaca_position_to_position(alpaca_pos)
        assert pos.symbol == "AAPL"
        assert pos.qty == Decimal("10")
        assert pos.avg_entry_price == Decimal("150.25")
        assert pos.market_value == Decimal("1502.50")
        assert pos.unrealized_pl == Decimal("2.50")
        assert pos.unrealized_pl_pct == Decimal("0.0017")
        assert isinstance(pos.avg_entry_price, Decimal)

    def test_side_mapping(self) -> None:
        alpaca_pos = SimpleNamespace(
            symbol="AAPL",
            qty="10",
            side="long",
            avg_entry_price="150.00",
            market_value="1500.00",
            unrealized_pl="0",
            unrealized_plpc="0",
        )
        pos = alpaca_position_to_position(alpaca_pos)
        assert pos.side == Side.BUY

    def test_short_side_mapping(self) -> None:
        alpaca_pos = SimpleNamespace(
            symbol="AAPL",
            qty="-10",
            side="short",
            avg_entry_price="150.00",
            market_value="-1500.00",
            unrealized_pl="0",
            unrealized_plpc="0",
        )
        pos = alpaca_position_to_position(alpaca_pos)
        assert pos.side == Side.SELL


class TestAlpacaAccountToAccountInfo:
    """Test conversion from Alpaca SDK account to domain AccountInfo."""

    def test_converts_string_fields_to_decimal(self) -> None:
        alpaca_acct = SimpleNamespace(
            equity="100000.00",
            cash="50000.00",
            buying_power="200000.00",
            portfolio_value="100000.00",
            daytrade_count=0,
            pattern_day_trader=False,
        )
        acct = alpaca_account_to_account_info(alpaca_acct)
        assert acct.equity == Decimal("100000.00")
        assert acct.cash == Decimal("50000.00")
        assert acct.buying_power == Decimal("200000.00")
        assert acct.portfolio_value == Decimal("100000.00")
        assert acct.day_trade_count == 0
        assert acct.pattern_day_trader is False
        assert isinstance(acct.equity, Decimal)


class TestAlpacaOrderToOrderStatus:
    """Test conversion from Alpaca SDK order to domain OrderStatus."""

    def test_maps_all_relevant_fields(self) -> None:
        alpaca_order = SimpleNamespace(
            id="order-uuid-123",
            symbol="AAPL",
            side="buy",
            qty="10",
            type="market",
            status="new",
            filled_qty="0",
            filled_avg_price=None,
            submitted_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        status = alpaca_order_to_order_status(alpaca_order)
        assert status.broker_order_id == "order-uuid-123"
        assert status.symbol == "AAPL"
        assert status.side == Side.BUY
        assert status.qty == Decimal("10")
        assert status.order_type == OrderType.MARKET
        assert status.status == BrokerOrderStatus.NEW
        assert status.filled_qty == Decimal("0")
        assert status.filled_avg_price is None

    def test_maps_filled_order(self) -> None:
        alpaca_order = SimpleNamespace(
            id="order-uuid-456",
            symbol="TSLA",
            side="sell",
            qty="5",
            type="limit",
            status="filled",
            filled_qty="5",
            filled_avg_price="250.50",
            submitted_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        status = alpaca_order_to_order_status(alpaca_order)
        assert status.side == Side.SELL
        assert status.order_type == OrderType.LIMIT
        assert status.status == BrokerOrderStatus.FILLED
        assert status.filled_avg_price == Decimal("250.50")


class TestAlpacaTradeUpdateToTradeUpdate:
    """Test conversion from Alpaca SDK trade update to domain TradeUpdate."""

    def test_fill_event_maps_correctly(self) -> None:
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
        update = alpaca_trade_update_to_trade_update(alpaca_update)
        assert update is not None
        assert update.event == TradeEventType.FILL
        assert update.order_id == "order-uuid-123"
        assert update.symbol == "AAPL"
        assert update.filled_avg_price == Decimal("150.50")

    def test_canceled_event(self) -> None:
        alpaca_update = SimpleNamespace(
            event="canceled",
            order=SimpleNamespace(
                id="order-uuid-789",
                symbol="AAPL",
                side="buy",
                qty="10",
                filled_qty="0",
                filled_avg_price=None,
            ),
            price=None,
            qty=None,
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        )
        update = alpaca_trade_update_to_trade_update(alpaca_update)
        assert update is not None
        assert update.event == TradeEventType.CANCELED

    def test_filtered_events_return_none(self) -> None:
        """PENDING_NEW, RESTATED, etc. are filtered out."""
        for event_name in ("pending_new", "pending_replace", "restated"):
            alpaca_update = SimpleNamespace(
                event=event_name,
                order=SimpleNamespace(
                    id="order-uuid",
                    symbol="AAPL",
                    side="buy",
                    qty="10",
                    filled_qty="0",
                    filled_avg_price=None,
                ),
                price=None,
                qty=None,
                timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            )
            result = alpaca_trade_update_to_trade_update(alpaca_update)
            assert result is None, f"Expected None for event '{event_name}'"


class TestOrderRequestToAlpaca:
    """Test conversion from domain OrderRequest to Alpaca SDK request."""

    def test_market_order(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
        )
        alpaca_req = order_request_to_alpaca(req)
        assert alpaca_req.symbol == "AAPL"
        assert alpaca_req.qty == 10.0
        assert alpaca_req.time_in_force.value == "day"

    def test_limit_order(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.00"),
        )
        alpaca_req = order_request_to_alpaca(req)
        assert alpaca_req.limit_price == 150.0

    def test_stop_order(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.STOP,
            stop_price=Decimal("145.50"),
        )
        alpaca_req = order_request_to_alpaca(req)
        assert alpaca_req.stop_price == 145.5

    def test_trailing_stop_with_percent(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.TRAILING_STOP,
            trail_percent=Decimal("1.5"),
        )
        alpaca_req = order_request_to_alpaca(req)
        assert alpaca_req.trail_percent == 1.5

    def test_trailing_stop_with_price(self) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.TRAILING_STOP,
            trail_price=Decimal("2.00"),
        )
        alpaca_req = order_request_to_alpaca(req)
        assert alpaca_req.trail_price == 2.0

    def test_decimal_to_float_precision(self) -> None:
        """Decimal('123.45') -> 123.45 without precision loss."""
        req = OrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("123.45"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("999.99"),
        )
        alpaca_req = order_request_to_alpaca(req)
        assert alpaca_req.qty == 123.45
        assert alpaca_req.limit_price == 999.99


class TestBracketRequestToAlpaca:
    """Test conversion from domain BracketOrderRequest to Alpaca SDK request."""

    def test_bracket_with_stop_loss_only(self) -> None:
        req = BracketOrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.MARKET,
            stop_loss_price=Decimal("145.00"),
        )
        alpaca_req = bracket_request_to_alpaca(req)
        assert alpaca_req.symbol == "AAPL"
        assert alpaca_req.qty == 10.0
        assert alpaca_req.order_class.value == "bracket"
        assert alpaca_req.stop_loss is not None
        assert alpaca_req.stop_loss.stop_price == 145.0

    def test_bracket_with_take_profit(self) -> None:
        req = BracketOrderRequest(
            symbol="AAPL",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.00"),
            stop_loss_price=Decimal("145.00"),
            take_profit_price=Decimal("160.00"),
        )
        alpaca_req = bracket_request_to_alpaca(req)
        assert alpaca_req.take_profit is not None
        assert alpaca_req.take_profit.limit_price == 160.0
        assert alpaca_req.stop_loss.stop_price == 145.0
