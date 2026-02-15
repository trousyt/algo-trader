"""Tests for the SMA ring-buffer class.

TDD: Written before the SMA class extraction.
"""

from __future__ import annotations

import pytest

from app.engine.indicators import SMA


class TestSMAWarmup:
    """SMA returns None until enough values are provided."""

    def test_value_none_before_period(self) -> None:
        sma = SMA(period=5)
        for i in range(4):
            sma.update(float(i + 1))
        assert sma.value is None

    def test_is_warm_false_before_period(self) -> None:
        sma = SMA(period=5)
        for i in range(4):
            sma.update(float(i + 1))
        assert sma.is_warm is False

    def test_count_tracks_values_added(self) -> None:
        sma = SMA(period=5)
        assert sma.count == 0
        sma.update(1.0)
        assert sma.count == 1
        sma.update(2.0)
        assert sma.count == 2


class TestSMACorrectness:
    """SMA produces correct values."""

    def test_value_at_exact_period(self) -> None:
        sma = SMA(period=5)
        for i in range(1, 6):
            sma.update(float(i))
        # (1+2+3+4+5) / 5 = 3.0
        assert sma.value == pytest.approx(3.0)

    def test_is_warm_true_at_period(self) -> None:
        sma = SMA(period=5)
        for i in range(5):
            sma.update(float(i))
        assert sma.is_warm is True

    def test_running_sum_matches_naive(self) -> None:
        sma = SMA(period=20)
        prices = [100.0 + i * 3.0 - (i % 7) for i in range(60)]
        for p in prices:
            sma.update(p)
        expected = sum(prices[-20:]) / 20
        assert sma.value == pytest.approx(expected)

    def test_all_same_price(self) -> None:
        sma = SMA(period=10)
        for _ in range(15):
            sma.update(42.5)
        assert sma.value == pytest.approx(42.5)


class TestSMAEviction:
    """Ring buffer correctly evicts oldest values."""

    def test_eviction_after_overflow(self) -> None:
        sma = SMA(period=3)
        # Feed 1, 2, 3, 4, 5, 6
        for i in range(1, 7):
            sma.update(float(i))
        # Buffer should be [4, 5, 6], SMA = 5.0
        assert sma.value == pytest.approx(5.0)

    def test_count_capped_at_period(self) -> None:
        sma = SMA(period=3)
        for i in range(10):
            sma.update(float(i))
        assert sma.count == 3


class TestSMAPeriodOne:
    """Degenerate case: period=1 always returns latest value."""

    def test_period_one_returns_latest(self) -> None:
        sma = SMA(period=1)
        sma.update(10.0)
        assert sma.value == pytest.approx(10.0)
        sma.update(20.0)
        assert sma.value == pytest.approx(20.0)
        sma.update(99.5)
        assert sma.value == pytest.approx(99.5)

    def test_period_one_warm_after_first(self) -> None:
        sma = SMA(period=1)
        assert sma.is_warm is False
        sma.update(1.0)
        assert sma.is_warm is True


class TestSMAValidation:
    """SMA rejects invalid periods."""

    def test_period_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="SMA period must be >= 1"):
            SMA(period=0)

    def test_period_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="SMA period must be >= 1"):
            SMA(period=-5)


class TestSMALongRunDrift:
    """Running-sum float drift stays within acceptable bounds."""

    def test_1000_values_within_approx(self) -> None:
        """After 1000+ updates, SMA still matches naive computation."""
        period = 50
        sma = SMA(period=period)
        prices = [100.0 + (i * 0.37) % 13.0 for i in range(1500)]
        for p in prices:
            sma.update(p)
        expected = sum(prices[-period:]) / period
        assert sma.value == pytest.approx(expected)

    def test_large_price_range_drift(self) -> None:
        """Wide price range (penny stock to high-cap) stays accurate."""
        period = 20
        sma = SMA(period=period)
        prices = [0.01, 99999.99, 50000.0, 0.01, 99999.99] * 200
        for p in prices:
            sma.update(p)
        expected = sum(prices[-period:]) / period
        assert sma.value == pytest.approx(expected)
