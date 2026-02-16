"""Tests for BacktestExecution — fill simulation engine.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.executor import BacktestExecution
from app.broker.types import (
    AccountInfo,
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from app.orders.types import OrderRole
from tests.factories import make_bar


# ---------------------------------------------------------------------------
# Helper: create a BacktestExecution with defaults
# ---------------------------------------------------------------------------
def _make_executor(
    *,
    capital: Decimal = Decimal("25000"),
    slippage: Decimal = Decimal("0.01"),
) -> BacktestExecution:
    return BacktestExecution(
        initial_capital=capital,
        slippage_per_share=slippage,
    )


# Timestamps
T0 = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)  # 9:30 ET
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
T3 = T0 + timedelta(minutes=3)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------
class TestInitialState:
    def test_initial_equity_equals_capital(self) -> None:
        ex = _make_executor(capital=Decimal("50000"))
        assert ex.equity == Decimal("50000")

    def test_initial_cash_equals_capital(self) -> None:
        ex = _make_executor(capital=Decimal("50000"))
        assert ex.cash == Decimal("50000")

    def test_initial_no_positions(self) -> None:
        ex = _make_executor()
        assert ex.open_position_count == 0

    def test_process_bar_with_no_orders_returns_empty(self) -> None:
        ex = _make_executor()
        bar = make_bar(timestamp=T0)
        fills = ex.process_bar(bar)
        assert fills == []


# ---------------------------------------------------------------------------
# Buy-stop entry fills
# ---------------------------------------------------------------------------
class TestBuyStopFills:
    @pytest.mark.asyncio
    async def test_buy_stop_triggers_when_high_reaches_stop(self) -> None:
        """Buy-stop at $151. Bar high=$152 → triggers."""
        ex = _make_executor(slippage=Decimal("0.01"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("151"),
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("150"),
            high=Decimal("152"),
            low=Decimal("149"),
            close=Decimal("151"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.side == Side.BUY
        assert fill.qty == Decimal("100")
        assert fill.order_role == OrderRole.ENTRY
        # Fill at max(open, stop) + slippage, clamped to high
        # max(150, 151) + 0.01 = 151.01, < 152 → 151.01
        assert fill.fill_price == Decimal("151.01")

    @pytest.mark.asyncio
    async def test_buy_stop_does_not_trigger_below_stop(self) -> None:
        """Buy-stop at $155. Bar high=$152 → no fill."""
        ex = _make_executor()
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("150"),
            high=Decimal("152"),
            low=Decimal("149"),
            close=Decimal("151"),
        )
        fills = ex.process_bar(bar)
        assert fills == []

    @pytest.mark.asyncio
    async def test_buy_stop_gap_up_fills_at_open(self) -> None:
        """Buy-stop at $100. Bar opens at $105 (gap up) → fill at open + slippage."""
        ex = _make_executor(slippage=Decimal("0.02"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("50"),
                order_type=OrderType.STOP,
                stop_price=Decimal("100"),
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("105"),
            high=Decimal("108"),
            low=Decimal("104"),
            close=Decimal("107"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        # max(105, 100) + 0.02 = 105.02, < 108 → 105.02
        assert fills[0].fill_price == Decimal("105.02")


# ---------------------------------------------------------------------------
# Stop-loss fills
# ---------------------------------------------------------------------------
class TestStopLossFills:
    @pytest.mark.asyncio
    async def test_stop_loss_triggers_when_low_reaches_stop(self) -> None:
        """Stop-loss at $148. Bar low=$147 → triggers."""
        ex = _make_executor(slippage=Decimal("0.01"))

        # First: create a position by submitting and filling a buy
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        buy_bar = make_bar(
            timestamp=T0,
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("150"),
        )
        buy_fills = ex.process_bar(buy_bar)
        assert len(buy_fills) == 1

        # Now place stop-loss
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("148"),
            )
        )

        stop_bar = make_bar(
            timestamp=T1,
            open=Decimal("149"),
            high=Decimal("150"),
            low=Decimal("147"),
            close=Decimal("148"),
        )
        fills = ex.process_bar(stop_bar)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.side == Side.SELL
        assert fill.order_role == OrderRole.STOP_LOSS
        # min(open=149, stop=148) - slippage = 148 - 0.01 = 147.99, > low=147 → 147.99
        assert fill.fill_price == Decimal("147.99")

    @pytest.mark.asyncio
    async def test_stop_loss_not_triggered_above_stop(self) -> None:
        """Stop-loss at $145. Bar low=$147 → no fill."""
        ex = _make_executor()

        # Create position first
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("145"),
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("149"),
            high=Decimal("150"),
            low=Decimal("147"),
            close=Decimal("148"),
        )
        fills = ex.process_bar(bar)
        assert fills == []

    @pytest.mark.asyncio
    async def test_stop_loss_gap_down_fills_at_open(self) -> None:
        """Stop-loss at $148. Bar opens at $145 (gap down) → fill at open - slippage."""
        ex = _make_executor(slippage=Decimal("0.02"))

        # Create position
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("148"),
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("145"),
            high=Decimal("146"),
            low=Decimal("143"),
            close=Decimal("144"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        # min(open=145, stop=148) - 0.02 = 145 - 0.02 = 144.98, > low=143 → 144.98
        assert fills[0].fill_price == Decimal("144.98")


# ---------------------------------------------------------------------------
# Market order fills
# ---------------------------------------------------------------------------
class TestMarketOrderFills:
    @pytest.mark.asyncio
    async def test_market_buy_fills_at_open_plus_slippage(self) -> None:
        ex = _make_executor(slippage=Decimal("0.05"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("150"),
            high=Decimal("152"),
            low=Decimal("149"),
            close=Decimal("151"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        # open + slippage = 150.05, < high=152 → 150.05
        assert fills[0].fill_price == Decimal("150.05")

    @pytest.mark.asyncio
    async def test_market_sell_fills_at_open_minus_slippage(self) -> None:
        ex = _make_executor(slippage=Decimal("0.05"))

        # Create position first
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("152"),
                low=Decimal("149"),
                close=Decimal("151"),
            )
        )

        # Market sell
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("151"),
            high=Decimal("153"),
            low=Decimal("150"),
            close=Decimal("152"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        # open - slippage = 151 - 0.05 = 150.95, > low=150 → 150.95
        assert fills[0].fill_price == Decimal("150.95")


# ---------------------------------------------------------------------------
# Slippage clamping
# ---------------------------------------------------------------------------
class TestSlippageClamping:
    @pytest.mark.asyncio
    async def test_buy_slippage_clamped_to_bar_high(self) -> None:
        """Slippage pushes price above bar.high → clamp to high."""
        ex = _make_executor(slippage=Decimal("5.00"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("150.50"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        # 150 + 5 = 155 > high=151 → clamped to 151
        assert fills[0].fill_price == Decimal("151")

    @pytest.mark.asyncio
    async def test_sell_slippage_clamped_to_bar_low(self) -> None:
        """Slippage pushes price below bar.low → clamp to low."""
        ex = _make_executor(slippage=Decimal("5.00"))

        # Create position
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("155"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        # Market sell
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T1,
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("150"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        # 150 - 5 = 145 < low=149 → clamped to 149
        assert fills[0].fill_price == Decimal("149")

    @pytest.mark.asyncio
    async def test_fill_price_floor_prevents_negative(self) -> None:
        """Extremely low price with slippage should never go below $0.01."""
        ex = _make_executor(slippage=Decimal("0.50"))

        # Create position at low price
        await ex.submit_order(
            OrderRequest(
                symbol="PENNY",
                side=Side.BUY,
                qty=Decimal("1000"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                symbol="PENNY",
                timestamp=T0,
                open=Decimal("0.10"),
                high=Decimal("0.12"),
                low=Decimal("0.08"),
                close=Decimal("0.10"),
                volume=100000,
            )
        )

        # Stop-loss that would produce negative price
        await ex.submit_order(
            OrderRequest(
                symbol="PENNY",
                side=Side.SELL,
                qty=Decimal("1000"),
                order_type=OrderType.STOP,
                stop_price=Decimal("0.05"),
            )
        )

        bar = make_bar(
            symbol="PENNY",
            timestamp=T1,
            open=Decimal("0.03"),
            high=Decimal("0.04"),
            low=Decimal("0.01"),
            close=Decimal("0.02"),
            volume=100000,
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        assert fills[0].fill_price >= Decimal("0.01")


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------
class TestPositionTracking:
    @pytest.mark.asyncio
    async def test_buy_creates_position(self) -> None:
        ex = _make_executor(capital=Decimal("25000"), slippage=Decimal("0"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T0,
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("150"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        assert ex.open_position_count == 1
        assert ex.has_position("AAPL")

    @pytest.mark.asyncio
    async def test_sell_closes_position(self) -> None:
        ex = _make_executor(capital=Decimal("25000"), slippage=Decimal("0"))

        # Buy
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        # Sell
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        fills = ex.process_bar(
            make_bar(
                timestamp=T1,
                open=Decimal("155"),
                high=Decimal("156"),
                low=Decimal("154"),
                close=Decimal("155"),
            )
        )
        assert len(fills) == 1
        assert ex.open_position_count == 0
        assert not ex.has_position("AAPL")


# ---------------------------------------------------------------------------
# Account / equity tracking
# ---------------------------------------------------------------------------
class TestAccountTracking:
    @pytest.mark.asyncio
    async def test_cash_debited_on_buy(self) -> None:
        ex = _make_executor(capital=Decimal("25000"), slippage=Decimal("0"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T0,
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("150"),
        )
        ex.process_bar(bar)

        # 100 shares * $150 = $15,000 debited
        assert ex.cash == Decimal("10000")

    @pytest.mark.asyncio
    async def test_equity_includes_position_value(self) -> None:
        ex = _make_executor(capital=Decimal("25000"), slippage=Decimal("0"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )

        bar = make_bar(
            timestamp=T0,
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("155"),
        )
        ex.process_bar(bar)
        ex.update_market_prices(bar)

        # cash = 25000 - 15000 = 10000, position value = 100 * 155 = 15500
        assert ex.equity == Decimal("25500")

    @pytest.mark.asyncio
    async def test_cash_credited_on_sell(self) -> None:
        ex = _make_executor(capital=Decimal("25000"), slippage=Decimal("0"))

        # Buy at 150
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        # Sell at 155
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T1,
                open=Decimal("155"),
                high=Decimal("156"),
                low=Decimal("154"),
                close=Decimal("155"),
            )
        )

        # P&L = (155 - 150) * 100 = $500
        assert ex.cash == Decimal("25500")
        assert ex.equity == Decimal("25500")


# ---------------------------------------------------------------------------
# Multiple symbols independent
# ---------------------------------------------------------------------------
class TestMultiSymbol:
    @pytest.mark.asyncio
    async def test_independent_symbols(self) -> None:
        ex = _make_executor(capital=Decimal("50000"), slippage=Decimal("0"))

        # Buy AAPL and TSLA
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        await ex.submit_order(
            OrderRequest(
                symbol="TSLA",
                side=Side.BUY,
                qty=Decimal("50"),
                order_type=OrderType.MARKET,
            )
        )

        # Fill AAPL
        ex.process_bar(
            make_bar(
                symbol="AAPL",
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )
        # Fill TSLA
        ex.process_bar(
            make_bar(
                symbol="TSLA",
                timestamp=T0,
                open=Decimal("200"),
                high=Decimal("201"),
                low=Decimal("199"),
                close=Decimal("200"),
            )
        )

        assert ex.open_position_count == 2
        assert ex.has_position("AAPL")
        assert ex.has_position("TSLA")
        # Cash: 50000 - 15000 - 10000 = 25000
        assert ex.cash == Decimal("25000")


# ---------------------------------------------------------------------------
# Same-bar stop + entry prevention
# ---------------------------------------------------------------------------
class TestSameBarPrevention:
    @pytest.mark.asyncio
    async def test_stop_loss_not_triggered_on_entry_bar(self) -> None:
        """Entry and stop for SAME symbol should NOT both trigger on same bar."""
        ex = _make_executor(slippage=Decimal("0"))

        # Submit buy-stop entry at 151
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("151"),
            )
        )
        # Pre-set stop loss at 148
        ex.set_planned_stop("AAPL", Decimal("148"))

        # This bar triggers the buy-stop (high >= 151)
        # AND would trigger stop-loss (low <= 148) if it were active
        bar = make_bar(
            timestamp=T1,
            open=Decimal("150"),
            high=Decimal("153"),
            low=Decimal("147"),
            close=Decimal("150"),
        )
        fills = ex.process_bar(bar)

        # Only the entry should fill, NOT the stop-loss
        assert len(fills) == 1
        assert fills[0].side == Side.BUY


# ---------------------------------------------------------------------------
# Order cancellation
# ---------------------------------------------------------------------------
class TestOrderCancellation:
    @pytest.mark.asyncio
    async def test_cancel_removes_pending_order(self) -> None:
        ex = _make_executor()
        status = await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )

        await ex.cancel_order(status.broker_order_id)

        # Order should not fill even if price hits
        bar = make_bar(
            timestamp=T1,
            open=Decimal("156"),
            high=Decimal("158"),
            low=Decimal("155"),
            close=Decimal("157"),
        )
        fills = ex.process_bar(bar)
        assert fills == []

    @pytest.mark.asyncio
    async def test_cancel_all_pending(self) -> None:
        ex = _make_executor()
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )
        await ex.submit_order(
            OrderRequest(
                symbol="TSLA",
                side=Side.BUY,
                qty=Decimal("50"),
                order_type=OrderType.STOP,
                stop_price=Decimal("255"),
            )
        )

        ex.cancel_all_pending()

        bar1 = make_bar(
            symbol="AAPL",
            timestamp=T1,
            open=Decimal("156"),
            high=Decimal("160"),
            low=Decimal("155"),
            close=Decimal("158"),
        )
        bar2 = make_bar(
            symbol="TSLA",
            timestamp=T1,
            open=Decimal("256"),
            high=Decimal("260"),
            low=Decimal("255"),
            close=Decimal("258"),
        )
        assert ex.process_bar(bar1) == []
        assert ex.process_bar(bar2) == []


# ---------------------------------------------------------------------------
# BrokerAdapter protocol compliance
# ---------------------------------------------------------------------------
class TestBrokerAdapterProtocol:
    @pytest.mark.asyncio
    async def test_get_account_returns_account_info(self) -> None:
        ex = _make_executor(capital=Decimal("25000"))
        account = await ex.get_account()
        assert isinstance(account, AccountInfo)
        assert account.equity == Decimal("25000")
        assert account.cash == Decimal("25000")

    @pytest.mark.asyncio
    async def test_get_positions_returns_list(self) -> None:
        ex = _make_executor()
        positions = await ex.get_positions()
        assert isinstance(positions, list)
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_get_open_orders_returns_list(self) -> None:
        ex = _make_executor()
        orders = await ex.get_open_orders()
        assert isinstance(orders, list)

    @pytest.mark.asyncio
    async def test_submit_order_returns_order_status(self) -> None:
        ex = _make_executor()
        status = await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )
        assert isinstance(status, OrderStatus)
        assert status.status == BrokerOrderStatus.ACCEPTED
        assert status.broker_order_id.startswith("bt-")

    @pytest.mark.asyncio
    async def test_connect_and_disconnect_are_noops(self) -> None:
        ex = _make_executor()
        await ex.connect()
        await ex.disconnect()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        from app.backtest.executor import BacktestExecution

        ex = BacktestExecution(initial_capital=Decimal("25000"))
        async with ex as ctx:
            assert ctx is ex


# ---------------------------------------------------------------------------
# Convenience methods for runner
# ---------------------------------------------------------------------------
class TestConvenienceMethods:
    @pytest.mark.asyncio
    async def test_has_pending_entry(self) -> None:
        ex = _make_executor()
        assert not ex.has_pending_entry("AAPL")

        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )
        assert ex.has_pending_entry("AAPL")

    @pytest.mark.asyncio
    async def test_cancel_pending_entry(self) -> None:
        ex = _make_executor()
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )
        ex.cancel_pending_entry("AAPL")
        assert not ex.has_pending_entry("AAPL")

    @pytest.mark.asyncio
    async def test_candle_counter(self) -> None:
        ex = _make_executor()
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("155"),
            )
        )
        assert ex.candles_since_order("AAPL") == 0
        ex.increment_candle_count("AAPL")
        assert ex.candles_since_order("AAPL") == 1

    @pytest.mark.asyncio
    async def test_set_and_get_planned_stop(self) -> None:
        ex = _make_executor()
        ex.set_planned_stop("AAPL", Decimal("148.50"))
        assert ex.get_planned_stop("AAPL") == Decimal("148.50")

    @pytest.mark.asyncio
    async def test_update_stop(self) -> None:
        """Updating stop modifies the pending stop-loss order price."""
        ex = _make_executor(slippage=Decimal("0"))

        # Create position
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        # Place stop-loss at 145
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.SELL,
                qty=Decimal("100"),
                order_type=OrderType.STOP,
                stop_price=Decimal("145"),
            )
        )

        # Update stop to 148
        ex.update_stop("AAPL", Decimal("148"))

        # Bar with low=147 should trigger the updated stop at 148
        bar = make_bar(
            timestamp=T1,
            open=Decimal("149"),
            high=Decimal("150"),
            low=Decimal("147"),
            close=Decimal("148"),
        )
        fills = ex.process_bar(bar)
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("148")  # zero slippage

    @pytest.mark.asyncio
    async def test_get_position(self) -> None:
        ex = _make_executor(slippage=Decimal("0"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        pos = ex.get_position("AAPL")
        assert isinstance(pos, Position)
        assert pos.qty == Decimal("100")
        assert pos.avg_entry_price == Decimal("150")

    @pytest.mark.asyncio
    async def test_update_market_prices(self) -> None:
        ex = _make_executor(slippage=Decimal("0"))
        await ex.submit_order(
            OrderRequest(
                symbol="AAPL",
                side=Side.BUY,
                qty=Decimal("100"),
                order_type=OrderType.MARKET,
            )
        )
        ex.process_bar(
            make_bar(
                timestamp=T0,
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
            )
        )

        # Price goes up
        bar2 = make_bar(
            timestamp=T1,
            open=Decimal("155"),
            high=Decimal("156"),
            low=Decimal("154"),
            close=Decimal("155"),
        )
        ex.update_market_prices(bar2)

        pos = ex.get_position("AAPL")
        assert pos.market_value == Decimal("15500")
        assert pos.unrealized_pl == Decimal("500")
