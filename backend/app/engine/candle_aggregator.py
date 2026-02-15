"""Candle aggregation from 1-minute bars to multi-minute candles.

Push-based: call process_bar() with each incoming 1-min bar.
Returns a completed candle when the window fills.
Call flush() to emit a partial candle (market close, timeout).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.broker.types import Bar
from app.config import VALID_CANDLE_INTERVALS
from app.utils.time import market_close, market_open


class CandleAggregator:
    """Aggregates 1-min bars into multi-minute candles.

    Candle windows are aligned to market open (9:30 ET). For 5-min intervals:
    9:30-9:34, 9:35-9:39, etc. Uses market_open()/market_close() for DST-safe
    market hours filtering.
    """

    def __init__(self, symbol: str, interval_minutes: int) -> None:
        if interval_minutes not in VALID_CANDLE_INTERVALS:
            raise ValueError(
                f"interval_minutes must be one of "
                f"{sorted(VALID_CANDLE_INTERVALS)}, got {interval_minutes}"
            )
        self.symbol = symbol
        self.interval_minutes = interval_minutes
        self._buffer: list[Bar] = []
        self._current_window_start: datetime | None = None
        self._last_bar_timestamp: datetime | None = None

    def process_bar(self, bar: Bar) -> Bar | None:
        """Process a 1-min bar. Returns completed candle or None."""
        # Deduplication
        if (
            self._last_bar_timestamp is not None
            and bar.timestamp <= self._last_bar_timestamp
        ):
            return None

        # Market hours filter
        if not self._is_market_hours(bar.timestamp):
            return None

        self._last_bar_timestamp = bar.timestamp

        # 1-min pass-through
        if self.interval_minutes == 1:
            return bar

        window_start = self._calculate_window_start(bar.timestamp)

        # If we're in a new window and have buffered bars, emit the old candle
        if (
            self._current_window_start is not None
            and window_start != self._current_window_start
        ):
            candle = self._emit_candle()
            self._buffer = [bar]
            self._current_window_start = window_start
            return candle

        # Same window or first bar ever
        self._current_window_start = window_start
        self._buffer.append(bar)

        # Check if window is complete
        if len(self._buffer) >= self.interval_minutes:
            candle = self._emit_candle()
            self._buffer = []
            self._current_window_start = None
            return candle

        return None

    def flush(self) -> Bar | None:
        """Flush any buffered bars as a partial candle."""
        if not self._buffer:
            return None
        candle = self._emit_candle()
        self._buffer = []
        self._current_window_start = None
        return candle

    def _emit_candle(self) -> Bar:
        """Build a candle from the current buffer."""
        bars = self._buffer
        return Bar(
            symbol=self.symbol,
            timestamp=self._current_window_start or bars[0].timestamp,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
        )

    def _calculate_window_start(self, timestamp: datetime) -> datetime:
        """Calculate the window start time aligned to market open."""
        d = timestamp.date()
        open_dt = market_open(d)
        minutes_since_open = int((timestamp - open_dt).total_seconds() // 60)
        window_offset = (
            (minutes_since_open // self.interval_minutes)
            * self.interval_minutes
        )
        return open_dt + timedelta(minutes=window_offset)

    def _is_market_hours(self, timestamp: datetime) -> bool:
        """Check if the timestamp is within market hours."""
        d = timestamp.date()
        try:
            open_dt = market_open(d)
            close_dt = market_close(d)
        except ValueError:
            return False
        return open_dt <= timestamp < close_dt
