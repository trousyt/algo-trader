"""Tests for IndicatorSet and IndicatorCalculator.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.broker.types import Bar
from app.engine.indicators import IndicatorCalculator, IndicatorSet
from tests.factories import make_bar

# --- IndicatorSet dataclass tests ---


class TestIndicatorSet:
    """Test IndicatorSet frozen dataclass."""

    def test_is_frozen(self) -> None:
        ind = IndicatorSet(
            sma_fast=150.0,
            sma_slow=148.0,
            prev_sma_fast=149.0,
            prev_sma_slow=147.0,
            bar_count=200,
        )
        with pytest.raises(FrozenInstanceError):
            ind.sma_fast = 999.0  # type: ignore[misc]

    def test_all_fields_have_correct_types(self) -> None:
        ind = IndicatorSet(
            sma_fast=150.0,
            sma_slow=148.0,
            prev_sma_fast=149.0,
            prev_sma_slow=147.0,
            bar_count=200,
        )
        assert isinstance(ind.sma_fast, float)
        assert isinstance(ind.sma_slow, float)
        assert isinstance(ind.prev_sma_fast, float)
        assert isinstance(ind.prev_sma_slow, float)
        assert isinstance(ind.bar_count, int)

    def test_default_values(self) -> None:
        ind = IndicatorSet()
        assert ind.sma_fast is None
        assert ind.sma_slow is None
        assert ind.prev_sma_fast is None
        assert ind.prev_sma_slow is None
        assert ind.bar_count == 0

    def test_construct_with_all_values(self) -> None:
        ind = IndicatorSet(
            sma_fast=20.5,
            sma_slow=19.3,
            prev_sma_fast=20.4,
            prev_sma_slow=19.2,
            bar_count=250,
        )
        assert ind.sma_fast == pytest.approx(20.5)
        assert ind.bar_count == 250


# --- Helpers ---


def _candle_at(
    minute: int,
    close: Decimal = Decimal("100.00"),
) -> Bar:
    """Create a candle with the given close price."""
    return make_bar(
        timestamp=datetime(2026, 2, 10, 15, 0, tzinfo=UTC) + timedelta(minutes=minute),
        close=close,
        open=close - Decimal("1"),
        high=close + Decimal("1"),
        low=close - Decimal("2"),
    )


# --- Basic SMA calculation ---


class TestSMACalculation:
    """Test SMA computation correctness."""

    def test_sma_20_correct(self) -> None:
        """SMA-20 with exactly 20 candles at known prices."""
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        # Prices 1..20, SMA-20 = (1+2+...+20) / 20 = 210/20 = 10.5
        for i in range(1, 21):
            result = calc.process_candle(_candle_at(i, Decimal(str(i))))
        assert result.sma_fast == pytest.approx(10.5)

    def test_sma_200_correct(self) -> None:
        """SMA-200 with exactly 200 candles."""
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        # Prices 1..200, SMA-200 = (1+2+...+200)/200 = 20100/200 = 100.5
        for i in range(1, 201):
            result = calc.process_candle(_candle_at(i, Decimal(str(i))))
        assert result.sma_slow == pytest.approx(100.5)

    def test_sma_values_are_float(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        for i in range(1, 6):
            result = calc.process_candle(_candle_at(i, Decimal(str(i * 10))))
        assert isinstance(result.sma_fast, float)
        assert isinstance(result.sma_slow, float)

    def test_sma_matches_known_series(self) -> None:
        """Verify against manually computed values."""
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        prices = [
            Decimal("10"),
            Decimal("20"),
            Decimal("30"),
            Decimal("40"),
            Decimal("50"),
        ]
        for i, p in enumerate(prices):
            result = calc.process_candle(_candle_at(i, p))
        # SMA-3 of last 3 (30,40,50) = 120/3 = 40
        assert result.sma_fast == pytest.approx(40.0)
        # SMA-5 of all 5 = 150/5 = 30
        assert result.sma_slow == pytest.approx(30.0)

    def test_running_sum_matches_naive_sum(self) -> None:
        """Running sum optimization matches naive sum() for correctness."""
        calc = IndicatorCalculator(fast_period=20, slow_period=50)
        prices: list[Decimal] = []
        for i in range(60):
            p = Decimal(str(100 + i * 3 - (i % 7)))
            prices.append(p)
            result = calc.process_candle(_candle_at(i, p))

        # Verify fast SMA
        last_20 = [float(p) for p in prices[-20:]]
        expected_fast = sum(last_20) / 20
        assert result.sma_fast == pytest.approx(expected_fast)

        # Verify slow SMA
        last_50 = [float(p) for p in prices[-50:]]
        expected_slow = sum(last_50) / 50
        assert result.sma_slow == pytest.approx(expected_slow)


# --- Warm-up behavior ---


class TestWarmUp:
    """Test warm-up behavior."""

    def test_first_candle(self) -> None:
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        result = calc.process_candle(_candle_at(0, Decimal("100")))
        assert result.sma_fast is None
        assert result.sma_slow is None
        assert result.bar_count == 1

    def test_after_fast_period_candles(self) -> None:
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        for i in range(20):
            result = calc.process_candle(_candle_at(i, Decimal("100")))
        assert result.sma_fast is not None
        assert result.sma_slow is None
        assert result.bar_count == 20

    def test_after_slow_period_candles(self) -> None:
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        for i in range(200):
            result = calc.process_candle(_candle_at(i, Decimal("100")))
        assert result.sma_fast is not None
        assert result.sma_slow is not None
        assert result.bar_count == 200

    def test_is_warm_false_until_slow_period(self) -> None:
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        for i in range(199):
            calc.process_candle(_candle_at(i, Decimal("100")))
        assert calc.is_warm is False

    def test_is_warm_true_at_slow_period(self) -> None:
        calc = IndicatorCalculator(fast_period=20, slow_period=200)
        for i in range(200):
            calc.process_candle(_candle_at(i, Decimal("100")))
        assert calc.is_warm is True


# --- Previous values ---


class TestPreviousValues:
    """Test previous SMA value tracking."""

    def test_first_candle_prev_none(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        result = calc.process_candle(_candle_at(0, Decimal("100")))
        assert result.prev_sma_fast is None
        assert result.prev_sma_slow is None

    def test_prev_values_track_previous_candle(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        prices = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")]
        results = []
        for i, p in enumerate(prices):
            results.append(calc.process_candle(_candle_at(i, p)))

        # After 4 candles: sma_fast at candle 3 = (20+30+40)/3 = 30
        # prev_sma_fast at candle 3 = sma_fast at candle 2 = (10+20+30)/3 = 20
        assert results[3].sma_fast == pytest.approx(30.0)
        assert results[3].prev_sma_fast == pytest.approx(20.0)

    def test_values_shift_each_candle(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        prices = [
            Decimal("10"),
            Decimal("20"),
            Decimal("30"),
            Decimal("40"),
            Decimal("50"),
        ]
        results = []
        for i, p in enumerate(prices):
            results.append(calc.process_candle(_candle_at(i, p)))

        # Candle 4 (50): sma_fast = (30+40+50)/3 = 40
        # Candle 3 (40): sma_fast = (20+30+40)/3 = 30  ← this should be prev_sma_fast
        assert results[4].sma_fast == pytest.approx(40.0)
        assert results[4].prev_sma_fast == pytest.approx(30.0)


# --- Ring buffer ---


class TestRingBuffer:
    """Test ring buffer behavior."""

    def test_bar_count_capped_at_slow_period(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        for i in range(10):
            result = calc.process_candle(_candle_at(i, Decimal("100")))
        assert result.bar_count == 5  # Capped at slow_period

    def test_sma_correct_after_eviction(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        # Feed 6 candles: 10, 20, 30, 40, 50, 60
        prices = [
            Decimal("10"),
            Decimal("20"),
            Decimal("30"),
            Decimal("40"),
            Decimal("50"),
            Decimal("60"),
        ]
        for i, p in enumerate(prices):
            result = calc.process_candle(_candle_at(i, p))
        # After 6: fast buffer has [40, 50, 60], slow buffer has [20, 30, 40, 50, 60]
        # SMA-3 = (40+50+60)/3 = 50
        assert result.sma_fast == pytest.approx(50.0)
        # SMA-5 = (20+30+40+50+60)/5 = 40
        assert result.sma_slow == pytest.approx(40.0)


# --- Edge cases ---


class TestIndicatorEdgeCases:
    """Test edge cases."""

    def test_all_same_price(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        for i in range(5):
            result = calc.process_candle(_candle_at(i, Decimal("42.50")))
        assert result.sma_fast == pytest.approx(42.5)
        assert result.sma_slow == pytest.approx(42.5)

    def test_monotonically_increasing(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        for i in range(5):
            result = calc.process_candle(_candle_at(i, Decimal(str(100 + i))))
        # SMA-3 of [102, 103, 104] = 309/3 = 103
        assert result.sma_fast == pytest.approx(103.0)
        # SMA-5 of [100..104] = 510/5 = 102
        assert result.sma_slow == pytest.approx(102.0)
        # Fast SMA > Slow SMA (lagging)
        assert result.sma_fast > result.sma_slow  # type: ignore[operator]

    def test_large_price_differences(self) -> None:
        calc = IndicatorCalculator(fast_period=3, slow_period=5)
        prices = [
            Decimal("0.01"),
            Decimal("99999.99"),
            Decimal("50000.00"),
            Decimal("0.01"),
            Decimal("99999.99"),
        ]
        for i, p in enumerate(prices):
            result = calc.process_candle(_candle_at(i, p))
        # SMA-3 = (50000.00 + 0.01 + 99999.99) / 3 = 150000.00 / 3 = 50000
        expected_fast = 150000.0 / 3
        assert result.sma_fast == pytest.approx(expected_fast)
