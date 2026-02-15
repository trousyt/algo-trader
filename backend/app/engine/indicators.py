"""Indicator calculation with running-sum SMA optimization.

IndicatorSet is a frozen dataclass holding current and previous SMA values.
IndicatorCalculator maintains two ring buffers (fast + slow) with running
Decimal sums for O(1) SMA computation per candle.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from app.broker.types import Bar


@dataclass(frozen=True)
class IndicatorSet:
    """Typed indicator values passed to strategy.

    All SMA fields are None until enough candles have been processed.
    prev_* fields hold the previous candle's SMA values.
    """

    sma_fast: Decimal | None = None
    sma_slow: Decimal | None = None
    prev_sma_fast: Decimal | None = None
    prev_sma_slow: Decimal | None = None
    bar_count: int = 0


class IndicatorCalculator:
    """Computes SMA indicators from a candle stream.

    Maintains two ring buffers (deques) with running Decimal sums
    for O(1) SMA computation per candle. One deque per period.
    Decimal running sums have zero accumulated drift.
    """

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 200,
    ) -> None:
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._fast_buf: deque[Decimal] = deque(maxlen=fast_period)
        self._slow_buf: deque[Decimal] = deque(maxlen=slow_period)
        self._fast_sum = Decimal(0)
        self._slow_sum = Decimal(0)
        self._prev_fast: Decimal | None = None
        self._prev_slow: Decimal | None = None

    def process_candle(self, candle: Bar) -> IndicatorSet:
        """Add candle to buffer and compute indicators.

        Running sum update: subtract evicted value (if at capacity),
        add new close, divide by length.
        """
        close = candle.close

        # Save current SMAs as previous before updating
        prev_fast = self._compute_sma(self._fast_buf, self._fast_sum, self._fast_period)
        prev_slow = self._compute_sma(self._slow_buf, self._slow_sum, self._slow_period)

        # Update fast buffer
        if len(self._fast_buf) == self._fast_period:
            self._fast_sum -= self._fast_buf[0]
        self._fast_buf.append(close)
        self._fast_sum += close

        # Update slow buffer
        if len(self._slow_buf) == self._slow_period:
            self._slow_sum -= self._slow_buf[0]
        self._slow_buf.append(close)
        self._slow_sum += close

        # Compute current SMAs
        current_fast = self._compute_sma(
            self._fast_buf,
            self._fast_sum,
            self._fast_period,
        )
        current_slow = self._compute_sma(
            self._slow_buf,
            self._slow_sum,
            self._slow_period,
        )

        return IndicatorSet(
            sma_fast=current_fast,
            sma_slow=current_slow,
            prev_sma_fast=prev_fast,
            prev_sma_slow=prev_slow,
            bar_count=len(self._slow_buf),
        )

    @property
    def bar_count(self) -> int:
        """Number of candles in the slow buffer (max = slow_period)."""
        return len(self._slow_buf)

    @property
    def is_warm(self) -> bool:
        """True if enough candles for full SMA-slow calculation."""
        return len(self._slow_buf) >= self._slow_period

    @staticmethod
    def _compute_sma(
        buf: deque[Decimal],
        running_sum: Decimal,
        period: int,
    ) -> Decimal | None:
        """Compute SMA from running sum. Returns None if not enough data."""
        if len(buf) < period:
            return None
        return running_sum / Decimal(period)
