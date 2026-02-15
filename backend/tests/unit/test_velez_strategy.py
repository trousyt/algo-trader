"""Tests for VelezStrategy.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from decimal import Decimal

from app.broker.types import Bar, Position, Side
from app.config import VelezConfig
from app.engine.indicators import IndicatorSet
from app.strategy.base import Strategy
from app.strategy.velez import VelezStrategy
from tests.factories import make_bar, make_green_bar, make_red_bar

# --- Helpers ---


def _default_config(**overrides: object) -> VelezConfig:
    """Create a VelezConfig with optional overrides."""
    defaults: dict[str, object] = {}
    defaults.update(overrides)
    return VelezConfig(**defaults)  # type: ignore[arg-type]


def _warm_indicators(
    *,
    sma_fast: Decimal = Decimal("150.00"),
    sma_slow: Decimal = Decimal("149.50"),
    prev_sma_fast: Decimal = Decimal("149.90"),
    prev_sma_slow: Decimal = Decimal("149.50"),
    bar_count: int = 200,
) -> IndicatorSet:
    """Create an IndicatorSet that passes the warm-up check."""
    return IndicatorSet(
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        prev_sma_fast=prev_sma_fast,
        prev_sma_slow=prev_sma_slow,
        bar_count=bar_count,
    )


def _setup_bar() -> Bar:
    """Create a strong green bar that satisfies signal conditions.

    Body = |152 - 150| = 2, range = |153 - 149| = 4.
    Body% = 50%, which equals the default strong_candle_body_pct.
    """
    return make_bar(
        open=Decimal("150.00"),
        close=Decimal("152.00"),
        high=Decimal("153.00"),
        low=Decimal("149.00"),
        volume=5000,
    )


def _position(
    symbol: str = "AAPL",
    avg_entry: Decimal = Decimal("150.00"),
) -> Position:
    """Create a minimal Position for testing."""
    return Position(
        symbol=symbol,
        qty=Decimal("100"),
        side=Side.BUY,
        avg_entry_price=avg_entry,
        market_value=avg_entry * Decimal("100"),
        unrealized_pl=Decimal("0"),
        unrealized_pl_pct=Decimal("0"),
    )


# --- isinstance ---


class TestVelezIsStrategy:
    """VelezStrategy is a Strategy."""

    def test_is_subclass(self) -> None:
        assert issubclass(VelezStrategy, Strategy)

    def test_instantiates(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        assert s.symbol == "AAPL"


# --- Signal detection (should_long) ---


class TestShouldLong:
    """Test VelezStrategy.should_long() signal detection."""

    def test_false_when_not_warm(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()
        indicators = _warm_indicators(bar_count=199)
        assert s.should_long(bar, indicators) is False

    def test_false_when_indicators_none(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()
        indicators = IndicatorSet(bar_count=200)  # All SMAs None
        assert s.should_long(bar, indicators) is False

    def test_false_when_smas_not_tight(self) -> None:
        """Spread > tightness threshold."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()
        # Spread = |160 - 150| = 10. price=152. 10/152*100 = 6.6% > 2%
        indicators = _warm_indicators(
            sma_fast=Decimal("160.00"),
            sma_slow=Decimal("150.00"),
        )
        assert s.should_long(bar, indicators) is False

    def test_false_when_not_diverging(self) -> None:
        """Gap not widening."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()
        # Current gap = 150 - 149.50 = 0.50
        # Previous gap = 150 - 149.40 = 0.60 → gap narrowing
        indicators = _warm_indicators(
            sma_fast=Decimal("150.00"),
            sma_slow=Decimal("149.50"),
            prev_sma_fast=Decimal("150.00"),
            prev_sma_slow=Decimal("149.40"),
        )
        assert s.should_long(bar, indicators) is False

    def test_false_when_fast_below_slow(self) -> None:
        """SMA-20 below SMA-200."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()
        indicators = _warm_indicators(
            sma_fast=Decimal("149.00"),
            sma_slow=Decimal("149.50"),
            prev_sma_fast=Decimal("148.50"),
            prev_sma_slow=Decimal("149.50"),
        )
        assert s.should_long(bar, indicators) is False

    def test_false_when_candle_red(self) -> None:
        """Red candle (close <= open)."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_red_bar()
        indicators = _warm_indicators()
        assert s.should_long(bar, indicators) is False

    def test_false_when_candle_not_strong(self) -> None:
        """Green but weak candle (small body %)."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        # Body = |150.10 - 150.00| = 0.10, range = |151 - 149| = 2
        # Body% = 5% < 50% threshold
        bar = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.10"),
            high=Decimal("151.00"),
            low=Decimal("149.00"),
        )
        indicators = _warm_indicators()
        assert s.should_long(bar, indicators) is False

    def test_true_when_all_conditions_met(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()
        indicators = _warm_indicators()
        assert s.should_long(bar, indicators) is True

    def test_boundary_spread_at_threshold_is_false(self) -> None:
        """Spread exactly at threshold% → False (exclusive)."""
        s = VelezStrategy(
            symbol="AAPL",
            config=_default_config(tightness_threshold_pct=Decimal("2.0")),
        )
        bar = _setup_bar()  # close=152
        # Spread / price * 100 = 2.0% exactly → should be False
        # spread = sma_fast - sma_slow = X
        # X / 152 * 100 = 2.0 → X = 3.04
        indicators = _warm_indicators(
            sma_fast=Decimal("151.52"),
            sma_slow=Decimal("148.48"),
            prev_sma_fast=Decimal("151.00"),
            prev_sma_slow=Decimal("148.48"),
        )
        assert s.should_long(bar, indicators) is False

    def test_zero_range_candle_not_strong(self) -> None:
        """Zero range (high == low) → not strong → False."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.00"),
            high=Decimal("150.00"),
            low=Decimal("150.00"),
        )
        indicators = _warm_indicators()
        assert s.should_long(bar, indicators) is False

    def test_zero_price_bar_returns_false(self) -> None:
        """Division-by-zero guard: price == 0."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar(
            open=Decimal("0"),
            close=Decimal("0"),
            high=Decimal("0"),
            low=Decimal("0"),
        )
        indicators = _warm_indicators()
        assert s.should_long(bar, indicators) is False


# --- Entry and stop prices ---


class TestEntryAndStopPrices:
    """Test entry_price and stop_loss_price."""

    def test_entry_price_is_bar_high(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar(high=Decimal("155.50"))
        indicators = _warm_indicators()
        assert s.entry_price(bar, indicators) == Decimal("155.50")

    def test_stop_loss_uses_buffer_pct(self) -> None:
        """Stop = low - max(low * pct/100, min_buffer)."""
        s = VelezStrategy(
            symbol="AAPL",
            config=_default_config(
                stop_buffer_pct=Decimal("0.1"),
                stop_buffer_min=Decimal("0.02"),
            ),
        )
        bar = make_bar(low=Decimal("148.00"))
        indicators = _warm_indicators()
        # pct buffer = 148 * 0.1 / 100 = 0.148
        # min buffer = 0.02
        # max(0.148, 0.02) = 0.148
        # stop = 148 - 0.148 = 147.852
        result = s.stop_loss_price(bar, indicators)
        assert result == Decimal("148.00") - Decimal("0.148")

    def test_stop_loss_uses_min_buffer_when_larger(self) -> None:
        """Min buffer used when percentage buffer is smaller."""
        s = VelezStrategy(
            symbol="AAPL",
            config=_default_config(
                stop_buffer_pct=Decimal("0.05"),
                stop_buffer_min=Decimal("0.10"),
            ),
        )
        bar = make_bar(low=Decimal("5.00"))
        indicators = _warm_indicators()
        # pct buffer = 5.00 * 0.05 / 100 = 0.0025
        # min buffer = 0.10
        # max(0.0025, 0.10) = 0.10
        # stop = 5.00 - 0.10 = 4.90
        result = s.stop_loss_price(bar, indicators)
        assert result == Decimal("4.90")

    def test_decimal_precision_maintained(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar(high=Decimal("123.456789"))
        indicators = _warm_indicators()
        result = s.entry_price(bar, indicators)
        assert result == Decimal("123.456789")


# --- Buy-stop expiry ---


class TestBuyStopExpiry:
    """Test should_cancel_pending behavior."""

    def test_cancel_at_0_is_false(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar()
        assert s.should_cancel_pending(bar, 0) is False

    def test_cancel_at_1_is_true(self) -> None:
        """Default buy_stop_expiry_candles = 1."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar()
        assert s.should_cancel_pending(bar, 1) is True

    def test_configurable_expiry(self) -> None:
        """With buy_stop_expiry_candles=3."""
        s = VelezStrategy(
            symbol="AAPL",
            config=_default_config(buy_stop_expiry_candles=3),
        )
        bar = make_bar()
        assert s.should_cancel_pending(bar, 0) is False
        assert s.should_cancel_pending(bar, 1) is False
        assert s.should_cancel_pending(bar, 2) is False
        assert s.should_cancel_pending(bar, 3) is True


# --- Trailing stop state machine ---


class TestTrailingStop:
    """Test 3-state trailing stop state machine."""

    def test_initial_state_is_watching(self) -> None:
        """Trailing stop starts in WATCHING."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_green_bar()
        pos = _position()
        indicators = _warm_indicators()
        # Green bar in WATCHING → no stop change
        result = s.should_update_stop(bar, pos, indicators)
        assert result is None

    def test_red_candle_starts_pullback(self) -> None:
        """WATCHING + red candle → PULLING_BACK, returns None."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        red = make_red_bar(low=Decimal("148.00"))
        result = s.should_update_stop(red, pos, indicators)
        assert result is None  # No stop change yet

    def test_pullback_plus_1_green_returns_none(self) -> None:
        """PULLING_BACK + 1 green → still need 2."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Enter PULLING_BACK
        s.should_update_stop(make_red_bar(low=Decimal("148.00")), pos, indicators)
        # 1 green — not enough
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        assert result is None

    def test_pullback_plus_2_greens_returns_pullback_low(self) -> None:
        """PULLING_BACK + 2 greens → trail stop to pullback low."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Enter PULLING_BACK with low=148
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        # 2 greens
        s.should_update_stop(make_green_bar(), pos, indicators)
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        assert result == Decimal("148.00")

    def test_multiple_reds_use_lowest_low(self) -> None:
        """Multiple consecutive reds → pullback low = lowest."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Two red candles
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(
            make_red_bar(low=Decimal("147.00")),
            pos,
            indicators,
        )
        # 2 greens
        s.should_update_stop(make_green_bar(), pos, indicators)
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        assert result == Decimal("147.00")

    def test_green_then_red_resets_count(self) -> None:
        """Green, then red → green count resets, need 2 fresh."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Enter PULLING_BACK
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        # 1 green
        s.should_update_stop(make_green_bar(), pos, indicators)
        # Red resets count
        s.should_update_stop(
            make_red_bar(low=Decimal("147.50")),
            pos,
            indicators,
        )
        # Need 2 fresh greens now
        s.should_update_stop(make_green_bar(), pos, indicators)
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        # Pullback low should be min(148, 147.50) = 147.50
        assert result == Decimal("147.50")

    def test_after_trail_new_red_starts_new_cycle(self) -> None:
        """TRAILING + red → WATCHING → new pullback cycle."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Cycle 1: pullback + 2 greens → trail
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        s.should_update_stop(make_green_bar(), pos, indicators)
        # Now in TRAILING. Red → back to WATCHING
        s.should_update_stop(
            make_red_bar(low=Decimal("149.00")),
            pos,
            indicators,
        )
        # This red should start a new pullback
        s.should_update_stop(
            make_red_bar(low=Decimal("147.00")),
            pos,
            indicators,
        )
        # 2 greens for new cycle
        s.should_update_stop(make_green_bar(), pos, indicators)
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        assert result == Decimal("147.00")

    def test_doji_is_neutral(self) -> None:
        """Doji: does not advance green count, does not start pullback."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Enter PULLING_BACK
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        # 1 green
        s.should_update_stop(make_green_bar(), pos, indicators)
        # Doji (body < 10% of range = doji threshold)
        doji = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.05"),
            high=Decimal("151.00"),
            low=Decimal("149.00"),
        )
        s.should_update_stop(doji, pos, indicators)
        # Still need 1 more green (doji didn't count)
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        assert result == Decimal("148.00")

    def test_on_position_closed_resets_state(self) -> None:
        """on_position_closed resets to WATCHING."""
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Get into PULLING_BACK state
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        # Reset
        s.on_position_closed()
        # After reset, red should start fresh pullback
        s.should_update_stop(
            make_red_bar(low=Decimal("145.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        result = s.should_update_stop(make_green_bar(), pos, indicators)
        assert result == Decimal("145.00")


# --- Max run rule (should_exit) ---


class TestMaxRunExit:
    """Test should_exit max run rule."""

    def test_false_during_normal_trailing(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        pos = _position()
        indicators = _warm_indicators()
        # Get into TRAILING state
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        s.should_update_stop(make_green_bar(), pos, indicators)
        # 1 strong candle — not at max run yet
        assert s.should_exit(_setup_bar(), pos, indicators) is False

    def test_true_after_max_run_candles(self) -> None:
        """Exit after max_run_candles consecutive strong candles."""
        config = _default_config(max_run_candles=3)
        s = VelezStrategy(symbol="AAPL", config=config)
        pos = _position()
        indicators = _warm_indicators()
        # Get into TRAILING state
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        s.should_update_stop(make_green_bar(), pos, indicators)
        # 3 strong candles = max_run_candles
        s.should_exit(_setup_bar(), pos, indicators)
        s.should_exit(_setup_bar(), pos, indicators)
        assert s.should_exit(_setup_bar(), pos, indicators) is True

    def test_non_strong_resets_counter(self) -> None:
        """Non-strong candle resets max run counter."""
        config = _default_config(max_run_candles=3)
        s = VelezStrategy(symbol="AAPL", config=config)
        pos = _position()
        indicators = _warm_indicators()
        # Get into TRAILING state
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        s.should_update_stop(make_green_bar(), pos, indicators)
        # 2 strong, then weak, then 2 more strong
        s.should_exit(_setup_bar(), pos, indicators)
        s.should_exit(_setup_bar(), pos, indicators)
        # Weak candle resets
        weak = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.05"),
            high=Decimal("151.00"),
            low=Decimal("149.00"),
        )
        s.should_exit(weak, pos, indicators)
        # 2 more strong — still not 3 consecutive
        s.should_exit(_setup_bar(), pos, indicators)
        assert s.should_exit(_setup_bar(), pos, indicators) is False

    def test_doji_resets_counter(self) -> None:
        """Doji resets the max run counter."""
        config = _default_config(max_run_candles=3)
        s = VelezStrategy(symbol="AAPL", config=config)
        pos = _position()
        indicators = _warm_indicators()
        # Get into TRAILING state
        s.should_update_stop(
            make_red_bar(low=Decimal("148.00")),
            pos,
            indicators,
        )
        s.should_update_stop(make_green_bar(), pos, indicators)
        s.should_update_stop(make_green_bar(), pos, indicators)
        # 2 strong then doji
        s.should_exit(_setup_bar(), pos, indicators)
        s.should_exit(_setup_bar(), pos, indicators)
        doji = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.05"),
            high=Decimal("151.00"),
            low=Decimal("149.00"),
        )
        s.should_exit(doji, pos, indicators)
        # 2 more strong — not 3 consecutive
        s.should_exit(_setup_bar(), pos, indicators)
        assert s.should_exit(_setup_bar(), pos, indicators) is False


# --- Helper method tests ---


class TestHelperMethods:
    """Test _is_strong_candle, _is_doji, _body_pct."""

    def test_is_strong_candle(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = _setup_bar()  # Body% = 50%
        assert s._is_strong_candle(bar) is True

    def test_is_strong_candle_zero_range(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        bar = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.00"),
            high=Decimal("150.00"),
            low=Decimal("150.00"),
        )
        assert s._is_strong_candle(bar) is False

    def test_is_doji(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        # Body = 0.05, range = 2.0 → body% = 2.5% < 10%
        doji = make_bar(
            open=Decimal("150.00"),
            close=Decimal("150.05"),
            high=Decimal("151.00"),
            low=Decimal("149.00"),
        )
        assert s._is_doji(doji) is True

    def test_body_pct_calculation(self) -> None:
        s = VelezStrategy(symbol="AAPL", config=_default_config())
        # Body = |152 - 150| = 2, range = |153 - 149| = 4
        # Body% = 2/4 * 100 = 50
        bar = make_bar(
            open=Decimal("150.00"),
            close=Decimal("152.00"),
            high=Decimal("153.00"),
            low=Decimal("149.00"),
        )
        assert s._body_pct(bar) == Decimal("50.0")
