"""Tests for Strategy abstract base class.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.broker.types import Bar, Position
from app.engine.indicators import IndicatorSet
from app.strategy.base import Strategy
from tests.factories import make_bar, make_green_bar

# --- Concrete stub for testing ---


class _StubStrategy(Strategy):
    """Minimal concrete implementation for testing the ABC."""

    def should_long(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> bool:
        return False

    def entry_price(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> Decimal:
        return bar.high

    def stop_loss_price(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> Decimal:
        return bar.low

    def should_update_stop(
        self,
        bar: Bar,
        position: Position,
        indicators: IndicatorSet,
    ) -> Decimal | None:
        return None

    def should_exit(
        self,
        bar: Bar,
        position: Position,
        indicators: IndicatorSet,
    ) -> bool:
        return False


# --- Tests ---


class TestStrategyABC:
    """Test Strategy abstract base class behavior."""

    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            Strategy(symbol="AAPL")  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self) -> None:
        strategy = _StubStrategy(symbol="AAPL")
        assert strategy is not None

    def test_symbol_set_on_init(self) -> None:
        strategy = _StubStrategy(symbol="TSLA")
        assert strategy.symbol == "TSLA"

    def test_should_short_returns_false(self) -> None:
        strategy = _StubStrategy(symbol="AAPL")
        bar = make_bar()
        indicators = IndicatorSet()
        assert strategy.should_short(bar, indicators) is False

    def test_should_cancel_pending_default(self) -> None:
        """Default: cancel after 1 candle."""
        strategy = _StubStrategy(symbol="AAPL")
        bar = make_bar()
        assert strategy.should_cancel_pending(bar, 0) is False
        assert strategy.should_cancel_pending(bar, 1) is True
        assert strategy.should_cancel_pending(bar, 5) is True

    def test_required_history_is_property(self) -> None:
        strategy = _StubStrategy(symbol="AAPL")
        assert strategy.required_history == 200

    def test_on_position_closed_is_noop(self) -> None:
        """Default on_position_closed does nothing (no error)."""
        strategy = _StubStrategy(symbol="AAPL")
        strategy.on_position_closed()  # Should not raise

    def test_entry_price_accepts_indicators(self) -> None:
        """entry_price signature takes (bar, indicators)."""
        strategy = _StubStrategy(symbol="AAPL")
        bar = make_green_bar()
        indicators = IndicatorSet()
        result = strategy.entry_price(bar, indicators)
        assert isinstance(result, Decimal)

    def test_stop_loss_price_accepts_indicators(self) -> None:
        """stop_loss_price signature takes (bar, indicators)."""
        strategy = _StubStrategy(symbol="AAPL")
        bar = make_green_bar()
        indicators = IndicatorSet()
        result = strategy.stop_loss_price(bar, indicators)
        assert isinstance(result, Decimal)
