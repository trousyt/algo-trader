"""Tests for CandleAggregator.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.broker.types import Bar
from app.engine.candle_aggregator import CandleAggregator
from tests.factories import make_bar

# --- Helpers ---


def _bar_at(minutes_after_open: int, **kwargs: object) -> Bar:
    """Create a bar N minutes after market open on 2026-02-10 (Tuesday).

    Market opens at 14:30 UTC (9:30 ET) on a regular day.
    """
    ts = datetime(2026, 2, 10, 14, 30, tzinfo=UTC) + timedelta(
        minutes=minutes_after_open,
    )
    defaults: dict[str, object] = {
        "symbol": "AAPL",
        "timestamp": ts,
        "open": Decimal("150.00"),
        "high": Decimal("151.00"),
        "low": Decimal("149.00"),
        "close": Decimal("150.50"),
        "volume": 1000,
    }
    defaults.update(kwargs)
    return make_bar(**defaults)  # type: ignore[arg-type]


# --- Construction & validation ---


class TestCandleAggregatorConstruction:
    """Test construction and interval validation."""

    def test_rejects_invalid_interval(self) -> None:
        with pytest.raises(ValueError, match="interval"):
            CandleAggregator(symbol="AAPL", interval_minutes=3)

    def test_rejects_interval_7(self) -> None:
        with pytest.raises(ValueError, match="interval"):
            CandleAggregator(symbol="AAPL", interval_minutes=7)

    def test_accepts_interval_1(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=1)
        assert agg.symbol == "AAPL"
        assert agg.interval_minutes == 1

    def test_accepts_interval_2(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        assert agg.interval_minutes == 2

    def test_accepts_interval_5(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        assert agg.interval_minutes == 5

    def test_accepts_interval_10(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=10)
        assert agg.interval_minutes == 10


# --- 1-min pass-through ---


class TestOneMinutePassThrough:
    """Test 1-minute interval (no buffering)."""

    def test_returns_bar_immediately(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=1)
        bar = _bar_at(0)
        result = agg.process_bar(bar)
        assert result is not None

    def test_preserves_all_fields(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=1)
        bar = _bar_at(0, open=Decimal("100.00"), high=Decimal("105.00"))
        result = agg.process_bar(bar)
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.open == Decimal("100.00")
        assert result.high == Decimal("105.00")


# --- 2-min aggregation ---


class TestTwoMinuteAggregation:
    """Test 2-minute candle aggregation."""

    def test_first_bar_returns_none(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        result = agg.process_bar(_bar_at(0))
        assert result is None

    def test_second_bar_returns_completed_candle(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        agg.process_bar(_bar_at(0))
        result = agg.process_bar(_bar_at(1))
        assert result is not None

    def test_ohlcv_math(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        agg.process_bar(
            _bar_at(
                0,
                open=Decimal("100.00"),
                high=Decimal("102.00"),
                low=Decimal("99.00"),
                close=Decimal("101.00"),
                volume=500,
            ),
        )
        result = agg.process_bar(
            _bar_at(
                1,
                open=Decimal("101.00"),
                high=Decimal("103.00"),
                low=Decimal("100.00"),
                close=Decimal("102.50"),
                volume=600,
            ),
        )
        assert result is not None
        assert result.open == Decimal("100.00")  # First bar's open
        assert result.high == Decimal("103.00")  # Max of highs
        assert result.low == Decimal("99.00")  # Min of lows
        assert result.close == Decimal("102.50")  # Last bar's close
        assert result.volume == 1100  # Sum of volumes

    def test_candle_timestamp_is_window_start(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        agg.process_bar(_bar_at(0))
        result = agg.process_bar(_bar_at(1))
        assert result is not None
        # Window start = market open = 14:30 UTC
        assert result.timestamp == datetime(2026, 2, 10, 14, 30, tzinfo=UTC)

    def test_candle_symbol_preserved(self) -> None:
        agg = CandleAggregator(symbol="TSLA", interval_minutes=2)
        bar0 = _bar_at(0, symbol="TSLA")
        bar1 = _bar_at(1, symbol="TSLA")
        agg.process_bar(bar0)
        result = agg.process_bar(bar1)
        assert result is not None
        assert result.symbol == "TSLA"

    def test_second_window(self) -> None:
        """Bars at minutes 2-3 form the second 2-min candle."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        agg.process_bar(_bar_at(0))
        agg.process_bar(_bar_at(1))  # Completes first candle
        agg.process_bar(_bar_at(2))  # Starts second window
        result = agg.process_bar(_bar_at(3))  # Completes second candle
        assert result is not None
        # Window start = 14:32
        assert result.timestamp == datetime(2026, 2, 10, 14, 32, tzinfo=UTC)


# --- 5-min and 10-min aggregation ---


class TestFiveMinuteAggregation:
    """Test 5-minute candle aggregation."""

    def test_buffers_4_bars_emits_on_5th(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        for i in range(4):
            assert agg.process_bar(_bar_at(i)) is None
        result = agg.process_bar(_bar_at(4))
        assert result is not None

    def test_ohlcv_correct_for_5_bars(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        prices = [
            (Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101"), 100),
            (Decimal("101"), Decimal("104"), Decimal("100"), Decimal("103"), 200),
            (Decimal("103"), Decimal("105"), Decimal("102"), Decimal("104"), 150),
            (Decimal("104"), Decimal("104"), Decimal("101"), Decimal("102"), 175),
            (Decimal("102"), Decimal("103"), Decimal("98"), Decimal("100"), 125),
        ]
        result = None
        for i, (op, hi, lo, cl, vol) in enumerate(prices):
            result = agg.process_bar(
                _bar_at(i, open=op, high=hi, low=lo, close=cl, volume=vol),
            )
        assert result is not None
        assert result.open == Decimal("100")
        assert result.high == Decimal("105")
        assert result.low == Decimal("98")
        assert result.close == Decimal("100")
        assert result.volume == 750


class TestTenMinuteAggregation:
    """Test 10-minute candle aggregation."""

    def test_buffers_9_bars_emits_on_10th(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=10)
        for i in range(9):
            assert agg.process_bar(_bar_at(i)) is None
        result = agg.process_bar(_bar_at(9))
        assert result is not None

    def test_ohlcv_correct_for_10_bars(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=10)
        result = None
        for i in range(10):
            result = agg.process_bar(
                _bar_at(
                    i,
                    open=Decimal(str(100 + i)),
                    high=Decimal(str(105 + i)),
                    low=Decimal(str(95 + i)),
                    close=Decimal(str(101 + i)),
                    volume=100,
                ),
            )
        assert result is not None
        assert result.open == Decimal("100")  # First bar's open
        assert result.high == Decimal("114")  # 105 + 9
        assert result.low == Decimal("95")  # 95 + 0
        assert result.close == Decimal("110")  # 101 + 9
        assert result.volume == 1000  # 100 * 10


# --- Window alignment ---


class TestWindowAlignment:
    """Test that candles are aligned to market open."""

    def test_5min_first_window(self) -> None:
        """Bars at 9:30-9:34 → candle at 9:30."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        for i in range(4):
            agg.process_bar(_bar_at(i))
        result = agg.process_bar(_bar_at(4))
        assert result is not None
        assert result.timestamp == datetime(2026, 2, 10, 14, 30, tzinfo=UTC)

    def test_5min_second_window(self) -> None:
        """Bars at 9:35-9:39 → candle at 9:35."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        # Fill first window
        for i in range(5):
            agg.process_bar(_bar_at(i))
        # Fill second window
        for i in range(5, 9):
            agg.process_bar(_bar_at(i))
        result = agg.process_bar(_bar_at(9))
        assert result is not None
        assert result.timestamp == datetime(2026, 2, 10, 14, 35, tzinfo=UTC)

    def test_2min_alignment(self) -> None:
        """Bars at 9:32-9:33 → candle at 9:32."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        # First window: 9:30-9:31
        agg.process_bar(_bar_at(0))
        agg.process_bar(_bar_at(1))
        # Second window: 9:32-9:33
        agg.process_bar(_bar_at(2))
        result = agg.process_bar(_bar_at(3))
        assert result is not None
        assert result.timestamp == datetime(2026, 2, 10, 14, 32, tzinfo=UTC)

    def test_mid_day_start(self) -> None:
        """Bar at 10:47 correctly placed in 10:46 window (2-min)."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        # 10:46 ET = minute 76 after open (9:30), 10:47 = minute 77
        bar76 = _bar_at(76)  # 10:46 ET
        bar77 = _bar_at(77)  # 10:47 ET
        agg.process_bar(bar76)
        result = agg.process_bar(bar77)
        assert result is not None
        # Window start = 14:30 + 76 min = 15:46 UTC (10:46 ET)
        assert result.timestamp == datetime(2026, 2, 10, 15, 46, tzinfo=UTC)


# --- Edge cases ---


class TestEdgeCases:
    """Test edge cases."""

    def test_duplicate_timestamp_dropped(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        bar = _bar_at(0)
        agg.process_bar(bar)
        result = agg.process_bar(bar)  # Same timestamp
        assert result is None

    def test_bar_outside_market_hours_ignored(self) -> None:
        """Bar before market open is ignored."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        # 8:00 ET = 13:00 UTC — before 9:30 open
        pre_market = make_bar(
            timestamp=datetime(2026, 2, 10, 13, 0, tzinfo=UTC),
        )
        result = agg.process_bar(pre_market)
        assert result is None

    def test_bar_after_close_ignored(self) -> None:
        """Bar after market close is ignored."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        # 4:01 PM ET = 21:01 UTC — after 4:00 close
        post_market = make_bar(
            timestamp=datetime(2026, 2, 10, 21, 1, tzinfo=UTC),
        )
        result = agg.process_bar(post_market)
        assert result is None

    def test_flush_returns_partial_candle(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        agg.process_bar(
            _bar_at(
                0,
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("99"),
                close=Decimal("101"),
                volume=500,
            )
        )
        agg.process_bar(
            _bar_at(
                1,
                open=Decimal("101"),
                high=Decimal("103"),
                low=Decimal("100"),
                close=Decimal("102"),
                volume=600,
            )
        )
        result = agg.flush()
        assert result is not None
        assert result.open == Decimal("100")
        assert result.high == Decimal("103")
        assert result.low == Decimal("99")
        assert result.close == Decimal("102")
        assert result.volume == 1100

    def test_flush_returns_none_when_empty(self) -> None:
        agg = CandleAggregator(symbol="AAPL", interval_minutes=5)
        assert agg.flush() is None

    def test_flush_clears_buffer(self) -> None:
        """After flush, buffer is empty — next bar starts fresh."""
        agg = CandleAggregator(symbol="AAPL", interval_minutes=2)
        agg.process_bar(_bar_at(0))
        agg.flush()
        # Buffer should be empty, so next bar starts a new window
        assert agg.flush() is None
