"""Tests for CircuitBreaker -- daily loss limit and consecutive loss pause."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.risk.circuit_breaker import CircuitBreaker


def _make_cb(
    max_daily_loss_pct: Decimal = Decimal("0.03"),
    consecutive_loss_pause: int = 3,
) -> CircuitBreaker:
    cb = CircuitBreaker(
        max_daily_loss_pct=max_daily_loss_pct,
        consecutive_loss_pause=consecutive_loss_pause,
    )
    cb.reset_daily(Decimal("25000"))
    return cb


class TestCircuitBreakerConsecutiveLosses:
    """Consecutive loss tracking and pause."""

    def test_trips_after_n_consecutive_losses(self) -> None:
        cb = _make_cb(consecutive_loss_pause=3)
        cb.record_trade(Decimal("-50"))
        cb.record_trade(Decimal("-30"))
        assert cb.can_trade() == (True, "")
        cb.record_trade(Decimal("-20"))
        can, reason = cb.can_trade()
        assert can is False
        assert "Consecutive loss limit" in reason

    def test_win_resets_consecutive_count(self) -> None:
        cb = _make_cb(consecutive_loss_pause=3)
        cb.record_trade(Decimal("-50"))
        cb.record_trade(Decimal("-30"))
        assert cb.consecutive_losses == 2
        cb.record_trade(Decimal("100"))
        assert cb.consecutive_losses == 0
        assert cb.can_trade() == (True, "")

    def test_break_even_counts_as_loss(self) -> None:
        """pnl <= 0 counts as loss (including $0.00)."""
        cb = _make_cb(consecutive_loss_pause=3)
        cb.record_trade(Decimal("0"))
        cb.record_trade(Decimal("0"))
        cb.record_trade(Decimal("0"))
        can, reason = cb.can_trade()
        assert can is False
        assert "Consecutive loss limit" in reason

    def test_consecutive_losses_property(self) -> None:
        cb = _make_cb()
        assert cb.consecutive_losses == 0
        cb.record_trade(Decimal("-10"))
        assert cb.consecutive_losses == 1
        cb.record_trade(Decimal("10"))
        assert cb.consecutive_losses == 0


class TestCircuitBreakerDailyLoss:
    """Daily loss limit tracking."""

    def test_trips_when_daily_loss_exceeds_limit(self) -> None:
        cb = _make_cb(max_daily_loss_pct=Decimal("0.03"))
        # Max loss = 25000 * 0.03 = 750
        cb.record_trade(Decimal("-400"))
        assert cb.can_trade() == (True, "")
        cb.record_trade(Decimal("-351"))
        # Total loss = -751, exceeds -750
        can, reason = cb.can_trade()
        assert can is False
        assert "Daily loss limit" in reason

    def test_exactly_at_limit_trips(self) -> None:
        """Exactly at limit (<=) trips the breaker."""
        cb = _make_cb(max_daily_loss_pct=Decimal("0.03"))
        # Max loss = 25000 * 0.03 = 750
        cb.record_trade(Decimal("-750"))
        can, reason = cb.can_trade()
        assert can is False

    def test_wins_offset_losses(self) -> None:
        cb = _make_cb(max_daily_loss_pct=Decimal("0.03"))
        cb.record_trade(Decimal("-500"))
        cb.record_trade(Decimal("300"))
        # Net = -200, under -750 threshold
        assert cb.can_trade() == (True, "")
        assert cb.daily_realized_pnl == Decimal("-200")


class TestCircuitBreakerReset:
    """Daily reset clears all state."""

    def test_reset_clears_everything(self) -> None:
        cb = _make_cb()
        cb.record_trade(Decimal("-100"))
        cb.record_trade(Decimal("-100"))
        cb.record_trade(Decimal("-100"))
        assert cb.is_paused is True

        cb.reset_daily(Decimal("24700"))
        assert cb.is_paused is False
        assert cb.daily_realized_pnl == Decimal("0")
        assert cb.consecutive_losses == 0
        assert cb.can_trade() == (True, "")


class TestCircuitBreakerReconstruct:
    """State reconstruction from trade records."""

    def test_reconstruct_from_trades(self) -> None:
        cb = _make_cb(consecutive_loss_pause=3)

        # Create mock trade models
        trades = []
        for pnl_val in [Decimal("-50"), Decimal("100"), Decimal("-30")]:
            trade = MagicMock()
            trade.pnl = pnl_val
            trades.append(trade)

        cb.reconstruct_from_trades(trades, Decimal("25000"))
        assert cb.daily_realized_pnl == Decimal("20")
        assert cb.consecutive_losses == 1
        assert cb.can_trade() == (True, "")

    def test_reconstruct_trips_breaker(self) -> None:
        cb = _make_cb(consecutive_loss_pause=3)

        trades = []
        for pnl_val in [Decimal("-50"), Decimal("-30"), Decimal("-20")]:
            trade = MagicMock()
            trade.pnl = pnl_val
            trades.append(trade)

        cb.reconstruct_from_trades(trades, Decimal("25000"))
        assert cb.is_paused is True
        assert cb.consecutive_losses == 3

    def test_reconstruct_empty_trades(self) -> None:
        cb = _make_cb()
        cb.record_trade(Decimal("-100"))  # Pre-existing state

        cb.reconstruct_from_trades([], Decimal("25000"))
        assert cb.daily_realized_pnl == Decimal("0")
        assert cb.consecutive_losses == 0
        assert cb.is_paused is False


class TestCircuitBreakerPausePersistence:
    """Once paused, stay paused until reset."""

    def test_stays_paused_after_win(self) -> None:
        cb = _make_cb(consecutive_loss_pause=3)
        cb.record_trade(Decimal("-50"))
        cb.record_trade(Decimal("-50"))
        cb.record_trade(Decimal("-50"))
        assert cb.is_paused is True

        # A win doesn't un-pause
        cb.record_trade(Decimal("1000"))
        assert cb.is_paused is True

    def test_daily_pnl_continues_tracking_when_paused(self) -> None:
        """P&L tracking continues even when paused (for reporting)."""
        cb = _make_cb(consecutive_loss_pause=2)
        cb.record_trade(Decimal("-50"))
        cb.record_trade(Decimal("-50"))
        assert cb.is_paused is True
        assert cb.daily_realized_pnl == Decimal("-100")
