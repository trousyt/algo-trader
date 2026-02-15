"""Abstract base class for trading strategies.

One instance per symbol. The TradingEngine creates instances
and passes bar + indicators each candle.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from app.broker.types import Bar, Position
from app.engine.indicators import IndicatorSet


class Strategy(ABC):
    """Abstract base class for trading strategies.

    Subclasses implement signal detection, entry/stop pricing,
    and position management. The TradingEngine calls these methods
    each candle in a defined order.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @abstractmethod
    def should_long(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> bool:
        """Return True if a long entry signal is detected."""

    def should_short(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> bool:
        """Phase 2 stub. Returns False."""
        return False

    @abstractmethod
    def entry_price(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> Decimal:
        """Return the entry price for a new order."""

    @abstractmethod
    def stop_loss_price(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> Decimal:
        """Return the initial stop-loss price."""

    @abstractmethod
    def should_update_stop(
        self,
        bar: Bar,
        position: Position,
        indicators: IndicatorSet,
    ) -> Decimal | None:
        """Return new stop price, or None for no change."""

    @abstractmethod
    def should_exit(
        self,
        bar: Bar,
        position: Position,
        indicators: IndicatorSet,
    ) -> bool:
        """Return True if the position should be exited."""

    def should_cancel_pending(
        self,
        bar: Bar,
        candles_since_order: int,
    ) -> bool:
        """Whether to cancel an unfilled pending order.

        Default: cancel after 1 candle.
        """
        return candles_since_order >= 1

    @property
    def required_history(self) -> int:
        """Number of candles needed before strategy is warm."""
        return 200

    def on_position_closed(self) -> None:  # noqa: B027
        """Called by TradingEngine when a position is fully closed.

        Override to reset internal state (e.g., trailing stop state).
        Default: no-op.
        """
