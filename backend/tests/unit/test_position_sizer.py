"""Tests for PositionSizer -- pure Decimal math position sizing."""

from __future__ import annotations

from decimal import Decimal

from app.config import RiskConfig
from app.risk.position_sizer import PositionSizer, SizingResult


def _default_config(**overrides: object) -> RiskConfig:
    """Create a RiskConfig with overrides."""
    defaults = {
        "max_risk_per_trade_pct": Decimal("0.01"),
        "max_risk_per_trade_abs": Decimal("500"),
        "max_position_pct": Decimal("0.05"),
        "max_daily_loss_pct": Decimal("0.03"),
        "max_open_positions": 5,
        "consecutive_loss_pause": 3,
    }
    defaults.update(overrides)
    return RiskConfig(**defaults)  # type: ignore[arg-type]


class TestPositionSizerBasic:
    """Core position sizing calculations."""

    def test_standard_calculation(self) -> None:
        """1% risk, $0.50 stop, $25K equity = 500 shares."""
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("154.70"),
        )
        # risk_amount = min(25000 * 0.01, 500) = 250
        # stop_distance = |155.20 - 154.70| = 0.50
        # raw_shares = 250 / 0.50 = 500
        # max_qty_by_value = int(25000 * 0.05 / 155.20) = int(8.05) = 8
        # qty = min(500, 8) = 8 (clamped by max_position_pct)
        assert result.qty == Decimal("8")
        assert result.risk_amount == Decimal("250")
        assert result.stop_distance == Decimal("0.50")
        assert result.position_value == Decimal("8") * Decimal("155.20")
        assert result.reason == ""

    def test_risk_per_trade_abs_cap(self) -> None:
        """Absolute cap limits risk amount."""
        config = _default_config(max_risk_per_trade_abs=Decimal("100"))
        sizer = PositionSizer(config)
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("50.00"),
            stop_loss_price=Decimal("49.00"),
        )
        # risk_by_pct = 25000 * 0.01 = 250
        # risk_amount = min(250, 100) = 100 (capped)
        # stop_distance = 1.00
        # raw_shares = 100 / 1.00 = 100
        # max_qty_by_value = int(25000 * 0.05 / 50) = 25
        # qty = min(100, 25) = 25
        assert result.qty == Decimal("25")
        assert result.risk_amount == Decimal("100")

    def test_max_position_pct_clamp(self) -> None:
        """Max position % clamps share count."""
        config = _default_config(max_position_pct=Decimal("0.02"))
        sizer = PositionSizer(config)
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("99.50"),
        )
        # risk_amount = min(250, 500) = 250
        # stop_distance = 0.50
        # raw_shares = 500
        # max_qty_by_value = int(25000 * 0.02 / 100) = 5
        # qty = min(500, 5) = 5
        assert result.qty == Decimal("5")
        assert result.reason == ""

    def test_buying_power_clamp(self) -> None:
        """Buying power limits share count."""
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("500"),  # Only $500 buying power
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("99.50"),
        )
        # max_qty_by_power = int(500 / 100) = 5
        # qty clamped to 5
        assert result.qty == Decimal("5")

    def test_truncates_to_whole_shares(self) -> None:
        """Position size rounds DOWN (conservative)."""
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("154.47"),
        )
        # stop_distance = 0.73
        # raw_shares = 250 / 0.73 = 342.465...
        # truncated to 342
        # max_qty_by_value = int(1250 / 155.20) = 8
        # qty = min(342, 8) = 8
        assert result.qty == Decimal("8")


class TestPositionSizerRejections:
    """Edge cases that result in rejection (qty=0)."""

    def test_zero_stop_distance(self) -> None:
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("155.20"),
        )
        assert result.qty == Decimal("0")
        assert result.reason == "Stop distance is zero"

    def test_invalid_entry_price_zero(self) -> None:
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("0"),
            stop_loss_price=Decimal("1.00"),
        )
        assert result.qty == Decimal("0")
        assert result.reason == "Invalid entry price"

    def test_invalid_entry_price_negative(self) -> None:
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("-10"),
            stop_loss_price=Decimal("1.00"),
        )
        assert result.qty == Decimal("0")
        assert result.reason == "Invalid entry price"

    def test_risk_budget_too_small(self) -> None:
        """Very wide stop makes raw_shares < 1."""
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("1000"),
            buying_power=Decimal("2000"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("85.00"),
        )
        # risk_amount = min(10, 500) = 10
        # stop_distance = 15
        # raw_shares = 10 / 15 = 0.66 -> truncated to 0
        assert result.qty == Decimal("0")
        assert result.reason == "Risk budget too small for stop distance"

    def test_insufficient_buying_power(self) -> None:
        """Cannot afford even 1 share."""
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("10"),  # $10 buying power
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("99.50"),
        )
        assert result.qty == Decimal("0")
        assert result.reason == "Insufficient buying power for even 1 share"


class TestPositionSizerAllDecimal:
    """All monetary calculations use Decimal."""

    def test_result_types_are_decimal(self) -> None:
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("154.70"),
        )
        assert isinstance(result.qty, Decimal)
        assert isinstance(result.risk_amount, Decimal)
        assert isinstance(result.stop_distance, Decimal)
        assert isinstance(result.position_value, Decimal)

    def test_rejected_result_types_are_decimal(self) -> None:
        sizer = PositionSizer(_default_config())
        result = sizer.calculate(
            equity=Decimal("25000"),
            buying_power=Decimal("50000"),
            entry_price=Decimal("155.20"),
            stop_loss_price=Decimal("155.20"),
        )
        assert isinstance(result.qty, Decimal)
        assert isinstance(result.risk_amount, Decimal)


class TestSizingResultFrozen:
    """SizingResult is frozen."""

    def test_frozen(self) -> None:
        result = SizingResult(
            qty=Decimal("10"),
            risk_amount=Decimal("100"),
            stop_distance=Decimal("1.00"),
            position_value=Decimal("1000"),
            reason="",
        )
        import pytest

        with pytest.raises(AttributeError):
            result.qty = Decimal("20")  # type: ignore[misc]
