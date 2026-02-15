"""Tests for order domain types."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.broker.types import OrderType, Side
from app.orders.types import (
    TERMINAL_STATES,
    OrderRole,
    OrderState,
    RiskApproval,
    Signal,
    SubmitResult,
)


class TestOrderState:
    """OrderState enum values and properties."""

    def test_all_states_are_strings(self) -> None:
        for state in OrderState:
            assert isinstance(state, str)
            assert isinstance(state.value, str)

    def test_terminal_states_are_subset(self) -> None:
        for state in TERMINAL_STATES:
            assert state in OrderState


class TestOrderRole:
    """OrderRole enum values."""

    def test_values(self) -> None:
        assert OrderRole.ENTRY.value == "entry"
        assert OrderRole.STOP_LOSS.value == "stop_loss"
        assert OrderRole.EXIT_MARKET.value == "exit_market"


class TestSignal:
    """Signal frozen dataclass."""

    def test_creation(self) -> None:
        ts = datetime(2026, 2, 15, 14, 30, tzinfo=UTC)
        signal = Signal(
            symbol="AAPL",
            side=Side.BUY,
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("154.70"),
            order_type=OrderType.STOP,
            strategy_name="velez",
            timestamp=ts,
        )
        assert signal.symbol == "AAPL"
        assert signal.side == Side.BUY
        assert signal.entry_price == Decimal("155.20")
        assert signal.stop_loss_price == Decimal("154.70")
        assert signal.order_type == OrderType.STOP
        assert signal.strategy_name == "velez"
        assert signal.timestamp == ts

    def test_frozen(self) -> None:
        signal = Signal(
            symbol="AAPL",
            side=Side.BUY,
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("154.70"),
            order_type=OrderType.STOP,
            strategy_name="velez",
            timestamp=datetime(2026, 2, 15, 14, 30, tzinfo=UTC),
        )
        with __import__("pytest").raises(AttributeError):
            signal.symbol = "TSLA"  # type: ignore[misc]


class TestRiskApproval:
    """RiskApproval frozen dataclass."""

    def test_approved(self) -> None:
        approval = RiskApproval(
            approved=True,
            qty=Decimal("500"),
            reason="",
        )
        assert approval.approved is True
        assert approval.qty == Decimal("500")
        assert approval.reason == ""

    def test_rejected(self) -> None:
        approval = RiskApproval(
            approved=False,
            qty=Decimal("0"),
            reason="Circuit breaker tripped",
        )
        assert approval.approved is False
        assert approval.qty == Decimal("0")


class TestSubmitResult:
    """SubmitResult frozen dataclass."""

    def test_success(self) -> None:
        result = SubmitResult(
            local_id="ord-123",
            correlation_id="corr-456",
            state=OrderState.SUBMITTED,
            error="",
        )
        assert result.local_id == "ord-123"
        assert result.correlation_id == "corr-456"
        assert result.state == OrderState.SUBMITTED
        assert result.error == ""

    def test_failure(self) -> None:
        result = SubmitResult(
            local_id="ord-123",
            correlation_id="corr-456",
            state=OrderState.SUBMIT_FAILED,
            error="Connection refused",
        )
        assert result.state == OrderState.SUBMIT_FAILED
        assert result.error == "Connection refused"
