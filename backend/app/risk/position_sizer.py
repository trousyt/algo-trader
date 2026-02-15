"""Position sizing calculator -- pure Decimal math, no I/O.

Calculates how many shares to buy based on risk budget,
stop distance, and position limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.config import RiskConfig


@dataclass(frozen=True)
class SizingResult:
    """Result of position size calculation."""

    qty: Decimal
    risk_amount: Decimal
    stop_distance: Decimal
    position_value: Decimal
    reason: str


class PositionSizer:
    """Calculate position size from risk parameters.

    All math in Decimal. Truncates to whole shares (conservative).
    """

    def __init__(self, risk_config: RiskConfig) -> None:
        self._config = risk_config

    def calculate(
        self,
        equity: Decimal,
        buying_power: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
    ) -> SizingResult:
        """Calculate position size.

        Returns qty=0 with reason if position cannot be sized.
        """
        zero = Decimal("0")

        if entry_price <= zero:
            return SizingResult(
                qty=zero,
                risk_amount=zero,
                stop_distance=zero,
                position_value=zero,
                reason="Invalid entry price",
            )

        stop_distance = abs(entry_price - stop_loss_price)

        if stop_distance == zero:
            return SizingResult(
                qty=zero,
                risk_amount=zero,
                stop_distance=zero,
                position_value=zero,
                reason="Stop distance is zero",
            )

        # Risk budget: min of percentage-based and absolute cap
        risk_by_pct = equity * self._config.max_risk_per_trade_pct
        risk_amount = min(risk_by_pct, self._config.max_risk_per_trade_abs)

        # Raw shares from risk budget / stop distance
        raw_shares = risk_amount / stop_distance
        qty = Decimal(int(raw_shares))

        if qty < Decimal("1"):
            return SizingResult(
                qty=zero,
                risk_amount=risk_amount,
                stop_distance=stop_distance,
                position_value=zero,
                reason="Risk budget too small for stop distance",
            )

        # Clamp to max position size
        max_position_value = equity * self._config.max_position_pct
        max_qty_by_value = Decimal(int(max_position_value / entry_price))
        qty = min(qty, max_qty_by_value)

        # Clamp to buying power
        if buying_power < entry_price:
            return SizingResult(
                qty=zero,
                risk_amount=risk_amount,
                stop_distance=stop_distance,
                position_value=zero,
                reason="Insufficient buying power for even 1 share",
            )

        max_qty_by_power = Decimal(int(buying_power / entry_price))
        qty = min(qty, max_qty_by_power)

        if qty < Decimal("1"):
            return SizingResult(
                qty=zero,
                risk_amount=risk_amount,
                stop_distance=stop_distance,
                position_value=zero,
                reason="Position size clamped to zero by limits",
            )

        position_value = qty * entry_price

        return SizingResult(
            qty=qty,
            risk_amount=risk_amount,
            stop_distance=stop_distance,
            position_value=position_value,
            reason="",
        )
