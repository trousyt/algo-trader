"""Tests for OrderManager -- async lifecycle orchestrator.

Tests cover: submit_entry, handle_trade_update (fill/partial/cancel/reject/expire),
cancel_pending_entry, request_exit, update_stop_loss, on_candle, cancel_all_pending,
submit_stop_loss, trade record creation, and unknown order handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.broker.fake.broker import FakeBrokerAdapter
from app.broker.types import (
    OrderType,
    Position,
    Side,
    TradeEventType,
    TradeUpdate,
)
from app.models.base import Base
from app.models.order import OrderEventModel, OrderStateModel, TradeModel
from app.orders.order_manager import OrderManager
from app.orders.types import (
    OrderRole,
    OrderState,
    RiskApproval,
)
from tests.factories import make_signal

_NOW = datetime(2026, 2, 14, 15, 0, tzinfo=UTC)


def _make_trade_update(
    *,
    event: TradeEventType = TradeEventType.FILL,
    order_id: str = "broker-001",
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    qty: Decimal = Decimal("10"),
    filled_qty: Decimal = Decimal("10"),
    filled_avg_price: Decimal | None = Decimal("155.20"),
    timestamp: datetime = _NOW,
) -> TradeUpdate:
    return TradeUpdate(
        event=event,
        order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
        timestamp=timestamp,
    )


@pytest.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create in-memory async SQLite with all tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def broker() -> FakeBrokerAdapter:
    return FakeBrokerAdapter()


@pytest.fixture
def om(
    broker: FakeBrokerAdapter,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> OrderManager:
    return OrderManager(broker, db_session_factory)


def _approval(qty: Decimal = Decimal("10")) -> RiskApproval:
    return RiskApproval(approved=True, qty=qty, reason="")


class TestSubmitEntry:
    """Submit entry order lifecycle."""

    async def test_submit_entry_creates_order_in_db(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        signal = make_signal()
        result = await om.submit_entry(signal, _approval())

        assert result.state == OrderState.SUBMITTED
        assert result.error == ""
        assert result.local_id != ""
        assert result.correlation_id != ""

        # Verify DB record
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.SUBMITTED.value
            assert order.symbol == "AAPL"
            assert order.side == Side.BUY.value
            assert order.order_role == OrderRole.ENTRY.value
            assert order.strategy == "velez"
            assert order.broker_id is not None

    async def test_submit_entry_records_audit_event(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.order_local_id == result.local_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert events[0].event_type == "submitted"
            assert events[0].new_state == OrderState.SUBMITTED.value

    async def test_submit_entry_broker_error_transitions_to_submit_failed(
        self,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        broker.submit_order = AsyncMock(side_effect=RuntimeError("API down"))
        om = OrderManager(broker, db_session_factory)

        result = await om.submit_entry(make_signal(), _approval())

        assert result.state == OrderState.SUBMIT_FAILED
        assert "API down" in result.error

    async def test_submit_entry_sends_correct_order_to_broker(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
    ) -> None:
        signal = make_signal(
            symbol="TSLA",
            entry_price=Decimal("300.00"),
            order_type=OrderType.STOP,
        )
        await om.submit_entry(signal, _approval(qty=Decimal("5")))

        assert len(broker.submitted_orders) == 1
        req = broker.submitted_orders[0]
        assert req.symbol == "TSLA"
        assert req.side == Side.BUY
        assert req.qty == Decimal("5")
        assert req.stop_price == Decimal("300.00")

    async def test_submit_entry_initializes_candle_counter(
        self,
        om: OrderManager,
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())
        assert om.get_candles_since_order(result.local_id) == 0


class TestHandleFill:
    """Fill event processing."""

    async def test_fill_transitions_to_filled(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        # Get broker_id from DB
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        update = _make_trade_update(
            event=TradeEventType.FILL,
            order_id=broker_id,
            filled_qty=Decimal("10"),
            filled_avg_price=Decimal("155.20"),
        )
        await om.handle_trade_update(update)

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.FILLED.value
            assert order.qty_filled == Decimal("10")
            assert order.avg_fill_price == Decimal("155.20")

    async def test_fill_clears_candle_counter(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(event=TradeEventType.FILL, order_id=broker_id)
        )

        assert om.get_candles_since_order(result.local_id) == 0


class TestHandlePartialFill:
    """Partial fill event processing."""

    async def test_partial_fill_transitions_to_partially_filled(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        # First need ACCEPTED transition
        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.ACCEPTED,
                order_id=broker_id,
            )
        )

        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.PARTIAL_FILL,
                order_id=broker_id,
                filled_qty=Decimal("5"),
                filled_avg_price=Decimal("155.20"),
            )
        )

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.PARTIALLY_FILLED.value
            assert order.qty_filled == Decimal("5")


class TestHandleCanceled:
    """Canceled event processing."""

    async def test_cancel_transitions_to_canceled(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(event=TradeEventType.CANCELED, order_id=broker_id)
        )

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.CANCELED.value


class TestHandleRejected:
    """Rejected event processing."""

    async def test_reject_transitions_to_rejected(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(event=TradeEventType.REJECTED, order_id=broker_id)
        )

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.REJECTED.value


class TestHandleExpired:
    """Expired event processing."""

    async def test_expire_transitions_to_expired(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(event=TradeEventType.EXPIRED, order_id=broker_id)
        )

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.EXPIRED.value


class TestUnknownOrder:
    """Unknown broker order_id handling."""

    async def test_unknown_order_logs_warning_no_crash(
        self,
        om: OrderManager,
    ) -> None:
        """Broker sends update for an order we don't track."""
        update = _make_trade_update(order_id="nonexistent-broker-id")
        # Should not raise
        await om.handle_trade_update(update)


class TestCancelPendingEntry:
    """Cancel unfilled entry orders."""

    async def test_cancel_pending_entry(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())
        broker.cancel_order = AsyncMock()

        await om.cancel_pending_entry(result.local_id)

        broker.cancel_order.assert_called_once()

    async def test_cancel_terminal_entry_noop(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        # Fill the order first
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(event=TradeEventType.FILL, order_id=broker_id)
        )

        broker.cancel_order = AsyncMock()
        await om.cancel_pending_entry(result.local_id)

        # Should not attempt to cancel a filled order
        broker.cancel_order.assert_not_called()


class TestSubmitStopLoss:
    """Stop-loss order submission with retry logic."""

    async def test_submit_stop_loss_success(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_stop_loss(
            correlation_id="corr-001",
            symbol="AAPL",
            qty=Decimal("10"),
            stop_price=Decimal("154.70"),
            parent_local_id="parent-001",
            strategy_name="velez",
        )

        assert result.state == OrderState.SUBMITTED
        assert result.error == ""

        # Verify DB record
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.order_role == OrderRole.STOP_LOSS.value
            assert order.side == Side.SELL.value
            assert order.parent_id == "parent-001"

    async def test_submit_stop_loss_retries_on_failure(
        self,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        call_count = 0
        original_submit = broker.submit_order

        async def fail_then_succeed(order: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Temporary error")
            return await original_submit(order)

        broker.submit_order = fail_then_succeed  # type: ignore[assignment]
        om = OrderManager(broker, db_session_factory)

        with patch("app.orders.order_manager.asyncio.sleep", new_callable=AsyncMock):
            result = await om.submit_stop_loss(
                correlation_id="corr-001",
                symbol="AAPL",
                qty=Decimal("10"),
                stop_price=Decimal("154.70"),
                parent_local_id="parent-001",
                strategy_name="velez",
            )

        assert result.state == OrderState.SUBMITTED
        assert call_count == 3

    async def test_submit_stop_loss_fallback_market_sell(
        self,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """All retries fail -> market sell fallback."""
        broker.submit_order = AsyncMock(side_effect=RuntimeError("Persistent error"))
        om = OrderManager(broker, db_session_factory)

        with patch("app.orders.order_manager.asyncio.sleep", new_callable=AsyncMock):
            result = await om.submit_stop_loss(
                correlation_id="corr-001",
                symbol="AAPL",
                qty=Decimal("10"),
                stop_price=Decimal("154.70"),
                parent_local_id="parent-001",
                strategy_name="velez",
            )

        assert result.state == OrderState.SUBMIT_FAILED
        assert "Persistent error" in result.error

        # The first submit_order call is for the stop loss record creation
        # (PENDING_SUBMIT already in DB), then 3 retries, then market exit.
        # Since submit_order always fails, market exit also fails.
        # But the OrderStateModel for stop-loss should exist.
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.SUBMIT_FAILED.value


class TestOnCandle:
    """Candle counter tracking."""

    async def test_on_candle_increments_counter(
        self,
        om: OrderManager,
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        await om.on_candle("AAPL")
        assert om.get_candles_since_order(result.local_id) == 1

        await om.on_candle("AAPL")
        assert om.get_candles_since_order(result.local_id) == 2

    async def test_on_candle_ignores_other_symbols(
        self,
        om: OrderManager,
    ) -> None:
        result = await om.submit_entry(make_signal(symbol="AAPL"), _approval())

        await om.on_candle("TSLA")
        assert om.get_candles_since_order(result.local_id) == 0

    async def test_on_candle_removes_terminal_orders(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        # Fill the entry order (terminal state)
        await om.handle_trade_update(
            _make_trade_update(event=TradeEventType.FILL, order_id=broker_id)
        )

        # Candle should clean up the terminal entry
        await om.on_candle("AAPL")
        assert om.get_candles_since_order(result.local_id) == 0


class TestCancelAllPending:
    """Cancel all pending orders at startup."""

    async def test_cancel_all_pending(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
    ) -> None:
        await om.submit_entry(make_signal(symbol="AAPL"), _approval())
        await om.submit_entry(make_signal(symbol="TSLA"), _approval())

        broker.cancel_order = AsyncMock()
        await om.cancel_all_pending()

        assert broker.cancel_order.call_count == 2


class TestTradeRecord:
    """Trade record creation on exit fill."""

    async def _submit_and_fill_entry(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
        symbol: str = "AAPL",
        entry_price: Decimal = Decimal("155.20"),
        qty: Decimal = Decimal("10"),
    ) -> tuple[str, str, str]:
        """Submit entry, fill it, return (local_id, correlation_id, broker_id)."""
        signal = make_signal(symbol=symbol, entry_price=entry_price)
        result = await om.submit_entry(signal, _approval(qty=qty))

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.FILL,
                order_id=broker_id,
                symbol=symbol,
                filled_qty=qty,
                filled_avg_price=entry_price,
            )
        )
        return result.local_id, result.correlation_id, broker_id

    async def test_trade_record_created_on_exit_fill(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        local_id, corr_id, _ = await self._submit_and_fill_entry(om, db_session_factory)

        # Submit and fill a stop-loss
        stop_result = await om.submit_stop_loss(
            correlation_id=corr_id,
            symbol="AAPL",
            qty=Decimal("10"),
            stop_price=Decimal("154.70"),
            parent_local_id=local_id,
            strategy_name="velez",
        )

        async with db_session_factory() as session:
            stop_order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == stop_result.local_id,
                    )
                )
            ).scalar_one()
            stop_broker_id = stop_order.broker_id

        # Fill the stop-loss (simulate stop triggered at 154.70)
        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.FILL,
                order_id=stop_broker_id,
                symbol="AAPL",
                side=Side.SELL,
                filled_qty=Decimal("10"),
                filled_avg_price=Decimal("154.70"),
            )
        )

        # Verify trade record
        async with db_session_factory() as session:
            trades = (
                (
                    await session.execute(
                        select(TradeModel).where(
                            TradeModel.correlation_id == corr_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(trades) == 1
            trade = trades[0]
            assert trade.symbol == "AAPL"
            assert trade.side == "long"
            assert trade.entry_price == Decimal("155.20")
            assert trade.exit_price == Decimal("154.70")
            # P&L = (154.70 - 155.20) * 10 = -5.00
            assert trade.pnl == Decimal("-5.00")

    async def test_trade_record_not_created_without_exit(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry fill alone should not create a trade record."""
        _, corr_id, _ = await self._submit_and_fill_entry(om, db_session_factory)

        async with db_session_factory() as session:
            trades = (
                (
                    await session.execute(
                        select(TradeModel).where(
                            TradeModel.correlation_id == corr_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(trades) == 0


class TestRequestExit:
    """Exit signal: cancel stop -> wait -> market sell."""

    async def test_request_exit_submits_market_sell(
        self,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        om = OrderManager(broker, db_session_factory)

        # Submit and fill entry
        signal = make_signal()
        result = await om.submit_entry(signal, _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            entry_broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.FILL,
                order_id=entry_broker_id,
            )
        )

        # Submit stop-loss
        await om.submit_stop_loss(
            correlation_id=result.correlation_id,
            symbol="AAPL",
            qty=Decimal("10"),
            stop_price=Decimal("154.70"),
            parent_local_id=result.local_id,
            strategy_name="velez",
        )

        # Set up broker to return a position
        broker._positions = [
            Position(
                symbol="AAPL",
                qty=Decimal("10"),
                side=Side.BUY,
                avg_entry_price=Decimal("155.20"),
                market_value=Decimal("1560.00"),
                unrealized_pl=Decimal("8.00"),
                unrealized_pl_pct=Decimal("0.005"),
            )
        ]

        # Mock cancel_order to simulate broker cancel confirmation
        original_cancel = broker.cancel_order

        async def cancel_and_confirm(bid: str) -> None:
            await original_cancel(bid)
            # Simulate broker sending cancel confirmation
            await om.handle_trade_update(
                _make_trade_update(
                    event=TradeEventType.CANCELED,
                    order_id=bid,
                )
            )

        broker.cancel_order = cancel_and_confirm  # type: ignore[assignment]

        await om.request_exit("AAPL", result.correlation_id)

        # Should have submitted a market sell order
        market_sells = [
            o
            for o in broker.submitted_orders
            if o.order_type == OrderType.MARKET and o.side == Side.SELL
        ]
        assert len(market_sells) == 1
        assert market_sells[0].qty == Decimal("10")


class TestUpdateStopLoss:
    """Stop-loss price update via replace_order."""

    async def test_update_stop_loss_calls_replace(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Submit entry and fill
        signal = make_signal()
        entry_result = await om.submit_entry(signal, _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == entry_result.local_id,
                    )
                )
            ).scalar_one()
            entry_broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.FILL,
                order_id=entry_broker_id,
            )
        )

        # Submit stop-loss
        await om.submit_stop_loss(
            correlation_id=entry_result.correlation_id,
            symbol="AAPL",
            qty=Decimal("10"),
            stop_price=Decimal("154.70"),
            parent_local_id=entry_result.local_id,
            strategy_name="velez",
        )

        broker.replace_order = AsyncMock(
            return_value=await broker.replace_order("any", stop_price=Decimal("155.50"))
        )

        await om.update_stop_loss(
            entry_result.correlation_id,
            new_stop_price=Decimal("155.50"),
        )

        broker.replace_order.assert_called_once()

    async def test_update_stop_loss_no_active_stop_noop(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
    ) -> None:
        broker.replace_order = AsyncMock()
        await om.update_stop_loss("nonexistent-corr", Decimal("155.00"))
        broker.replace_order.assert_not_called()


class TestHandleReplaced:
    """In-place broker_id update on REPLACED event."""

    async def test_replaced_writes_audit_event(
        self,
        om: OrderManager,
        broker: FakeBrokerAdapter,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            old_broker_id = order.broker_id

        # Broker sends REPLACED with old broker_id (lookup key)
        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.REPLACED,
                order_id=old_broker_id,
            )
        )

        async with db_session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.order_local_id == result.local_id,
                            OrderEventModel.event_type == "replaced",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1


class TestAtomicTransitions:
    """State + event are persisted atomically."""

    async def test_transition_writes_state_and_event(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.SUBMITTED.value

            events = (
                (
                    await session.execute(
                        select(OrderEventModel).where(
                            OrderEventModel.order_local_id == result.local_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            # PENDING_SUBMIT -> SUBMITTED = 1 event
            assert len(events) == 1
            assert events[0].old_state == OrderState.PENDING_SUBMIT.value
            assert events[0].new_state == OrderState.SUBMITTED.value

    async def test_invalid_transition_does_not_modify_state(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        # Try to go SUBMITTED -> SUBMITTED (invalid)
        # NEW event would try to transition to SUBMITTED again
        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.NEW,
                order_id=broker_id,
            )
        )

        # State should still be SUBMITTED (transition was no-op)
        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.SUBMITTED.value


class TestAcceptedTransition:
    """NEW/ACCEPTED event transitions."""

    async def test_accepted_transition(
        self,
        om: OrderManager,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        result = await om.submit_entry(make_signal(), _approval())

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            broker_id = order.broker_id

        await om.handle_trade_update(
            _make_trade_update(
                event=TradeEventType.ACCEPTED,
                order_id=broker_id,
            )
        )

        async with db_session_factory() as session:
            order = (
                await session.execute(
                    select(OrderStateModel).where(
                        OrderStateModel.local_id == result.local_id,
                    )
                )
            ).scalar_one()
            assert order.state == OrderState.ACCEPTED.value
