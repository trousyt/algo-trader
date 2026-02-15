"""Indicator calculation with ring-buffer SMA optimization.

SMA is a standalone ring-buffer class with O(1) per update.
IndicatorSet is a frozen dataclass holding current and previous SMA values.
IndicatorCalculator composes SMA instances and converts Decimal → float
at the boundary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.broker.types import Bar


class SMA:
    """Simple Moving Average via ring buffer with running sum. O(1) per update.

    Note: Running-sum approach may accumulate negligible float drift over very
    long series (100K+ updates). Acceptable for signal detection; add periodic
    re-sum if needed for backtesting precision.
    """

    __slots__ = ("_buf", "_period", "_sum")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"SMA period must be >= 1, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._sum: float = 0.0

    def update(self, value: float) -> None:
        """Add a value. Evicts oldest if at capacity.

        Callers must pass float, not Decimal. The Decimal-to-float
        conversion happens at the IndicatorCalculator boundary.
        """
        if len(self._buf) == self._period:
            self._sum -= self._buf[0]
        self._buf.append(value)
        self._sum += value

    @property
    def value(self) -> float | None:
        """Current SMA, or None if not warm."""
        if len(self._buf) < self._period:
            return None
        return self._sum / self._period

    @property
    def is_warm(self) -> bool:
        """True when buffer has enough values for a valid SMA."""
        return len(self._buf) >= self._period

    @property
    def count(self) -> int:
        """Number of values currently in the buffer."""
        return len(self._buf)


@dataclass(frozen=True)
class IndicatorSet:
    """Typed indicator values passed to strategy.

    All SMA fields are None until enough candles have been processed.
    prev_* fields hold the previous candle's SMA values.
    """

    sma_fast: float | None = None
    sma_slow: float | None = None
    prev_sma_fast: float | None = None
    prev_sma_slow: float | None = None
    bar_count: int = 0


class IndicatorCalculator:
    """Computes SMA indicators from a candle stream.

    Composes two SMA instances (fast + slow). Converts Decimal → float
    at the process_candle boundary.
    """

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 200,
    ) -> None:
        self._fast = SMA(fast_period)
        self._slow = SMA(slow_period)

    def process_candle(self, candle: Bar) -> IndicatorSet:
        """Add candle to buffer and compute indicators.

        Decimal → float conversion happens here at the boundary.
        """
        close = float(candle.close)  # Decimal → float at boundary
        # TODO(step4): Add finite check when data pipeline matures

        # Save current SMAs as previous before updating
        prev_fast = self._fast.value
        prev_slow = self._slow.value

        self._fast.update(close)
        self._slow.update(close)

        return IndicatorSet(
            sma_fast=self._fast.value,
            sma_slow=self._slow.value,
            prev_sma_fast=prev_fast,
            prev_sma_slow=prev_slow,
            bar_count=self._slow.count,
        )

    @property
    def bar_count(self) -> int:
        """Number of candles in the slow buffer (max = slow_period)."""
        return self._slow.count

    @property
    def is_warm(self) -> bool:
        """True if enough candles for full SMA-slow calculation."""
        return self._slow.is_warm
