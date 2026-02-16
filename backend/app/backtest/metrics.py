"""Backtest performance metrics — pure functions, no I/O.

Monetary values use Decimal, ratios use float (project convention).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.backtest.config import BacktestTradeData

_ZERO = Decimal("0")
_TRADING_DAYS_PER_YEAR = 252
_MAX_PROFIT_FACTOR = 9999.99


@dataclass(frozen=True)
class BacktestMetricsData:
    """Complete performance metrics for a backtest run."""

    total_return: Decimal
    total_return_pct: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_win: Decimal
    avg_loss: Decimal
    largest_win: Decimal
    largest_loss: Decimal
    avg_trade_duration: int
    final_equity: Decimal


class BacktestMetrics:
    """Compute performance metrics from backtest results."""

    @staticmethod
    def calculate(
        trades: list[BacktestTradeData],
        daily_equity: list[tuple[date, Decimal]],
        equity_curve: list[tuple[datetime, Decimal]],
        initial_capital: Decimal,
    ) -> BacktestMetricsData:
        """Compute all metrics.

        Args:
            trades: Completed round-trip trades.
            daily_equity: EOD equity snapshots for Sharpe ratio (daily returns).
            equity_curve: Per-candle equity snapshots for max drawdown (intra-day).
            initial_capital: Starting capital.
        """
        total_trades = len(trades)

        # Separate winners, losers (break-even is neither)
        winners = [t for t in trades if t.pnl > _ZERO]
        losers = [t for t in trades if t.pnl < _ZERO]
        winning_trades = len(winners)
        losing_trades = len(losers)

        # Final equity
        final_equity = initial_capital + sum((t.pnl for t in trades), _ZERO)

        # Total return
        if initial_capital > _ZERO:
            total_return = final_equity - initial_capital
            total_return_pct = (total_return / initial_capital) * Decimal("100")
        else:
            total_return = _ZERO
            total_return_pct = _ZERO

        # Win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # Profit factor
        profit_factor = _compute_profit_factor(winners, losers)

        # Sharpe ratio (from daily equity snapshots)
        sharpe_ratio = _compute_sharpe(daily_equity, initial_capital)

        # Max drawdown (from per-candle equity curve)
        max_dd = _compute_max_drawdown(equity_curve)
        max_drawdown = max_dd
        max_drawdown_pct = max_dd * 100.0

        # Avg win / avg loss
        avg_win = (
            sum((t.pnl for t in winners), _ZERO) / Decimal(str(winning_trades))
            if winning_trades > 0
            else _ZERO
        )
        avg_loss = (
            sum((t.pnl for t in losers), _ZERO) / Decimal(str(losing_trades))
            if losing_trades > 0
            else _ZERO
        )

        # Largest win / loss
        largest_win = max((t.pnl for t in winners), default=_ZERO)
        largest_loss = min((t.pnl for t in losers), default=_ZERO)

        # Avg trade duration (seconds)
        avg_trade_duration = (
            sum(t.duration_seconds for t in trades) // total_trades
            if total_trades > 0
            else 0
        )

        return BacktestMetricsData(
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_trade_duration=avg_trade_duration,
            final_equity=final_equity,
        )


def _compute_profit_factor(
    winners: list[BacktestTradeData],
    losers: list[BacktestTradeData],
) -> float:
    """Gross profit / gross loss. Capped at 9999.99 (not infinity)."""
    gross_profit = sum((t.pnl for t in winners), _ZERO)
    gross_loss = abs(sum((t.pnl for t in losers), _ZERO))

    if gross_profit == _ZERO and gross_loss == _ZERO:
        return 0.0
    if gross_loss == _ZERO:
        return _MAX_PROFIT_FACTOR
    return float(gross_profit / gross_loss)


def _compute_sharpe(
    daily_equity: list[tuple[date, Decimal]],
    initial_capital: Decimal,
) -> float:
    """Annualized Sharpe ratio from daily equity snapshots.

    Uses sample std (ddof=1). Risk-free rate = 0.
    Returns 0.0 if fewer than 2 data points.
    """
    if len(daily_equity) < 2:
        return 0.0

    # Compute daily returns
    values = [float(initial_capital)] + [float(eq) for _, eq in daily_equity]
    daily_returns: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev == 0.0:
            daily_returns.append(0.0)
        else:
            daily_returns.append((values[i] - prev) / prev)

    n = len(daily_returns)
    if n < 2:
        return 0.0

    mean_return = sum(daily_returns) / n
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / (n - 1)  # ddof=1
    std_return = math.sqrt(variance)

    if std_return == 0.0:
        return 0.0

    return (mean_return / std_return) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def _compute_max_drawdown(
    equity_curve: list[tuple[datetime, Decimal]],
) -> float:
    """Max drawdown using high-water-mark from per-candle equity curve.

    Returns 0.0 if empty or no drawdown. Result is 0-1 range.
    """
    if not equity_curve:
        return 0.0

    peak = _ZERO
    max_dd = 0.0

    for _, equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > _ZERO:
            dd = float((peak - equity) / peak)
            if dd > max_dd:
                max_dd = dd

    return max_dd
