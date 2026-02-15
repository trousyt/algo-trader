"""Velez SMA convergence strategy.

Detects setups where SMA-20 and SMA-200 are tight and diverging
upward, with a strong green candle as confirmation. Entry via
buy-stop at bar.high. Trailing stop uses a 3-state machine.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from app.broker.types import Bar, Position
from app.config import VelezConfig
from app.engine.indicators import IndicatorSet
from app.strategy.base import Strategy

_HUNDRED = Decimal("100")


class _TrailState(str, Enum):
    """Trailing stop state machine states."""

    WATCHING = "watching"
    PULLING_BACK = "pulling_back"
    TRAILING = "trailing"


class VelezStrategy(Strategy):
    """Velez SMA convergence strategy.

    Signal: SMA-20 and SMA-200 are tight (within threshold%),
    diverging upward, with a strong green candle.

    Entry: buy-stop at bar.high.
    Stop: bar.low minus buffer.
    Trail: 3-state machine (WATCHING -> PULLING_BACK -> TRAILING).
    Exit: max run of consecutive strong candles post-trail.
    """

    def __init__(self, symbol: str, config: VelezConfig) -> None:
        super().__init__(symbol)
        self._config = config
        self._trail_state = _TrailState.WATCHING
        self._pullback_low = Decimal("0")
        self._green_count = 0
        self._strong_run_count = 0

    # --- Signal detection (float math) ---

    def should_long(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> bool:
        """Detect SMA convergence setup with strong green candle."""
        # 1. Warm-up check
        if indicators.bar_count < self._config.sma_slow:
            return False

        # 2. SMAs must be non-None (mypy-safe narrowing)
        sma_f = indicators.sma_fast
        sma_s = indicators.sma_slow
        prev_f = indicators.prev_sma_fast
        prev_s = indicators.prev_sma_slow
        if sma_f is None or sma_s is None or prev_f is None or prev_s is None:
            return False

        # 3. Division-by-zero guard + SMAs tight check
        price = float(bar.close)
        if price == 0:
            return False
        spread = abs(sma_f - sma_s)
        if spread / price * 100.0 >= self._config.tightness_threshold_pct:
            return False

        # 4. SMA-20 diverging upward from SMA-200
        current_gap = sma_f - sma_s
        prev_gap = prev_f - prev_s
        if current_gap <= prev_gap:
            return False
        if sma_f <= sma_s:
            return False

        # 5. Strong green candle
        if bar.close <= bar.open:
            return False
        return self._is_strong_candle(bar)

    # --- Entry and stop prices (Decimal math) ---

    def entry_price(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> Decimal:
        """Buy-stop at bar.high."""
        return bar.high

    def stop_loss_price(
        self,
        bar: Bar,
        indicators: IndicatorSet,
    ) -> Decimal:
        """Stop at bar.low minus buffer (max of pct and min)."""
        low = bar.low
        pct_buffer = low * self._config.stop_buffer_pct / _HUNDRED
        buffer = max(pct_buffer, self._config.stop_buffer_min)
        return low - buffer

    # --- Buy-stop expiry ---

    def should_cancel_pending(
        self,
        bar: Bar,
        candles_since_order: int,
    ) -> bool:
        """Cancel pending buy-stop after configured candle count."""
        return candles_since_order >= self._config.buy_stop_expiry_candles

    # --- Trailing stop state machine ---

    def should_update_stop(
        self,
        bar: Bar,
        position: Position,
        indicators: IndicatorSet,
    ) -> Decimal | None:
        """3-state trailing stop via method-per-state dispatch."""
        if self._trail_state == _TrailState.WATCHING:
            return self._on_watching(bar)
        if self._trail_state == _TrailState.PULLING_BACK:
            return self._on_pulling_back(bar)
        # TRAILING
        return self._on_trailing(bar)

    def _on_watching(self, bar: Bar) -> Decimal | None:
        """WATCHING: look for red candle to start pullback."""
        if self._is_doji(bar):
            return None
        if bar.close < bar.open:
            self._trail_state = _TrailState.PULLING_BACK
            self._pullback_low = bar.low
            self._green_count = 0
        return None

    def _on_pulling_back(self, bar: Bar) -> Decimal | None:
        """PULLING_BACK: count greens, update low on reds."""
        if self._is_doji(bar):
            return None

        if bar.close < bar.open:
            # Another red: update pullback low, reset green count
            self._pullback_low = min(self._pullback_low, bar.low)
            self._green_count = 0
            return None

        # Green candle
        self._green_count += 1
        if self._green_count >= 2:
            # Trail stop to pullback low
            self._trail_state = _TrailState.TRAILING
            self._strong_run_count = 0
            return self._pullback_low

        return None

    def _on_trailing(self, bar: Bar) -> Decimal | None:
        """TRAILING: count strong run, detect next pullback."""
        if self._is_doji(bar):
            return None
        if bar.close < bar.open:
            # Red candle -> back to WATCHING for new cycle
            self._trail_state = _TrailState.WATCHING
        return None

    # --- Max run exit ---

    def should_exit(
        self,
        bar: Bar,
        position: Position,
        indicators: IndicatorSet,
    ) -> bool:
        """Exit after max_run_candles consecutive strong candles."""
        if self._trail_state != _TrailState.TRAILING:
            self._strong_run_count = 0
            return False

        if self._is_strong_candle(bar) and not self._is_doji(bar):
            self._strong_run_count += 1
        else:
            self._strong_run_count = 0

        return self._strong_run_count >= self._config.max_run_candles

    # --- Lifecycle ---

    def on_position_closed(self) -> None:
        """Reset trailing stop state."""
        self._trail_state = _TrailState.WATCHING
        self._pullback_low = Decimal("0")
        self._green_count = 0
        self._strong_run_count = 0

    @property
    def required_history(self) -> int:
        """Candles needed = slow SMA period."""
        return self._config.sma_slow

    # --- Helpers (float math for signal detection) ---

    def _body_pct(self, bar: Bar) -> float:
        """Body as percentage of total range."""
        total_range = float(bar.high - bar.low)  # Decimal subtraction first
        if total_range == 0:
            return 0.0
        body = abs(float(bar.close - bar.open))  # Decimal subtraction first
        return body / total_range * 100.0

    def _is_strong_candle(self, bar: Bar) -> bool:
        """True if body percentage >= strong candle threshold."""
        return self._body_pct(bar) >= self._config.strong_candle_body_pct

    def _is_doji(self, bar: Bar) -> bool:
        """True if body percentage < doji threshold."""
        return self._body_pct(bar) < self._config.doji_threshold_pct
