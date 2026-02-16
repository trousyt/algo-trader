"""Circuit breaker -- daily loss limit and consecutive loss pause.

Tracks realized P&L and consecutive losses. Pauses new entries
when limits are hit. Existing positions remain active.
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from app.models.order import TradeModel

log = structlog.get_logger()


class CircuitBreaker:
    """Daily loss limit + consecutive loss pause.

    Design decisions:
    - Daily P&L = realized only (closed trades). Unrealized is too volatile.
    - Consecutive losses = global across all symbols.
    - Break-even (pnl <= 0) counts as a loss for consecutive tracking.
    - Reset at market open via reset_daily().
    """

    def __init__(
        self,
        max_daily_loss_pct: Decimal,
        consecutive_loss_pause: int,
    ) -> None:
        self._max_daily_loss_pct = max_daily_loss_pct
        self._consecutive_loss_pause = consecutive_loss_pause
        self._start_of_day_equity: Decimal = Decimal("0")
        self._daily_realized_pnl: Decimal = Decimal("0")
        self._consecutive_losses: int = 0
        self._paused: bool = False
        self._pause_reason: str = ""

    def reset_daily(self, start_of_day_equity: Decimal) -> None:
        """Called at market open. Resets all daily counters."""
        self._start_of_day_equity = start_of_day_equity
        self._daily_realized_pnl = Decimal("0")
        self._consecutive_losses = 0
        self._paused = False
        self._pause_reason = ""
        log.info(
            "circuit_breaker_reset",
            start_of_day_equity=str(start_of_day_equity),
        )

    def record_trade(self, pnl: Decimal) -> None:
        """Called when a Trade record is created.

        Updates daily P&L and consecutive loss tracking.
        Checks both limits and pauses if either is exceeded.
        """
        self._daily_realized_pnl += pnl

        if pnl <= Decimal("0"):
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        self._check_limits()

    def can_trade(self) -> tuple[bool, str]:
        """Returns (True, "") or (False, "reason")."""
        if self._paused:
            return False, self._pause_reason
        return True, ""

    def reconstruct_from_trades(
        self,
        today_trades: list[TradeModel],
        start_of_day_equity: Decimal,
    ) -> None:
        """Reconstruct state from trade table after restart.

        Replays all today's trades in chronological order.
        """
        self._start_of_day_equity = start_of_day_equity
        self._daily_realized_pnl = Decimal("0")
        self._consecutive_losses = 0
        self._paused = False
        self._pause_reason = ""

        for trade in today_trades:
            self.record_trade(Decimal(str(trade.pnl)))

    @property
    def daily_realized_pnl(self) -> Decimal:
        """Current daily realized P&L."""
        return self._daily_realized_pnl

    @property
    def consecutive_losses(self) -> int:
        """Current consecutive loss count."""
        return self._consecutive_losses

    @property
    def is_paused(self) -> bool:
        """Whether trading is paused."""
        return self._paused

    def _check_limits(self) -> None:
        """Check both limits and set paused if either is exceeded."""
        if self._paused:
            return

        # Check consecutive losses
        if self._consecutive_losses >= self._consecutive_loss_pause:
            self._paused = True
            self._pause_reason = (
                f"Consecutive loss limit: {self._consecutive_losses} consecutive losses"
            )
            log.info(
                "circuit_breaker_tripped",
                reason=self._pause_reason,
                daily_pnl=str(self._daily_realized_pnl),
                consecutive_losses=self._consecutive_losses,
            )
            return

        # Check daily loss limit
        if self._start_of_day_equity > Decimal("0"):
            max_loss = self._start_of_day_equity * self._max_daily_loss_pct
            if self._daily_realized_pnl <= -max_loss:
                self._paused = True
                self._pause_reason = (
                    f"Daily loss limit: "
                    f"realized P&L {self._daily_realized_pnl} "
                    f"exceeds -{max_loss}"
                )
                log.info(
                    "circuit_breaker_tripped",
                    reason=self._pause_reason,
                    daily_pnl=str(self._daily_realized_pnl),
                    consecutive_losses=self._consecutive_losses,
                )
