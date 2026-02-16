"""Tests for BacktestMetrics — verifies all metric calculations."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.config import BacktestTradeData
from app.backtest.metrics import BacktestMetrics

_ZERO = Decimal("0")


def _make_trade(
    *,
    pnl: Decimal,
    symbol: str = "AAPL",
    duration_seconds: int = 3600,
) -> BacktestTradeData:
    """Helper to create a trade with minimal required fields."""
    entry = Decimal("150.00")
    exit_price = entry + pnl / Decimal("100")
    return BacktestTradeData(
        symbol=symbol,
        side="buy",
        qty=Decimal("100"),
        entry_price=entry,
        exit_price=exit_price,
        entry_at=datetime(2025, 1, 2, 10, 0, tzinfo=UTC),
        exit_at=datetime(2025, 1, 2, 10, 0, tzinfo=UTC)
        + timedelta(seconds=duration_seconds),
        pnl=pnl,
        duration_seconds=duration_seconds,
    )


def _make_daily_equity(
    values: list[Decimal],
    start: date | None = None,
) -> list[tuple[date, Decimal]]:
    """Helper to create daily equity snapshots."""
    d = start or date(2025, 1, 2)
    result: list[tuple[date, Decimal]] = []
    for i, v in enumerate(values):
        result.append((d + timedelta(days=i), v))
    return result


def _make_equity_curve(
    values: list[Decimal],
) -> list[tuple[datetime, Decimal]]:
    """Helper to create per-candle equity curve."""
    base = datetime(2025, 1, 2, 10, 0, tzinfo=UTC)
    return [(base + timedelta(minutes=i), v) for i, v in enumerate(values)]


class TestZeroTrades:
    """Edge case: no trades executed."""

    def test_zero_trades_returns_zero_metrics(self) -> None:
        initial = Decimal("25000")
        metrics = BacktestMetrics.calculate(
            trades=[],
            daily_equity=[],
            equity_curve=[],
            initial_capital=initial,
        )
        assert metrics.total_trades == 0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.profit_factor == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
        assert metrics.final_equity == initial
        assert metrics.total_return == _ZERO
        assert metrics.avg_win == _ZERO
        assert metrics.avg_loss == _ZERO
        assert metrics.largest_win == _ZERO
        assert metrics.largest_loss == _ZERO


class TestAllWins:
    """All trades are profitable."""

    def test_all_wins(self) -> None:
        trades = [
            _make_trade(pnl=Decimal("100")),
            _make_trade(pnl=Decimal("200")),
            _make_trade(pnl=Decimal("50")),
        ]
        initial = Decimal("25000")
        daily_eq = _make_daily_equity(
            [Decimal("25100"), Decimal("25300"), Decimal("25350")]
        )
        eq_curve = _make_equity_curve(
            [initial, Decimal("25100"), Decimal("25300"), Decimal("25350")]
        )

        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=daily_eq,
            equity_curve=eq_curve,
            initial_capital=initial,
        )
        assert metrics.total_trades == 3
        assert metrics.winning_trades == 3
        assert metrics.losing_trades == 0
        assert metrics.win_rate == pytest.approx(1.0)
        assert metrics.profit_factor == pytest.approx(9999.99)  # capped
        assert metrics.final_equity == initial + Decimal("350")
        assert metrics.avg_win == Decimal("350") / Decimal("3")
        assert metrics.avg_loss == _ZERO
        assert metrics.largest_win == Decimal("200")
        assert metrics.largest_loss == _ZERO


class TestAllLosses:
    """All trades are losers."""

    def test_all_losses(self) -> None:
        trades = [
            _make_trade(pnl=Decimal("-100")),
            _make_trade(pnl=Decimal("-50")),
        ]
        initial = Decimal("25000")
        daily_eq = _make_daily_equity([Decimal("24900"), Decimal("24850")])
        eq_curve = _make_equity_curve([initial, Decimal("24900"), Decimal("24850")])

        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=daily_eq,
            equity_curve=eq_curve,
            initial_capital=initial,
        )
        assert metrics.total_trades == 2
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 2
        assert metrics.win_rate == pytest.approx(0.0)
        assert metrics.profit_factor == pytest.approx(0.0)
        assert metrics.final_equity == Decimal("24850")
        assert metrics.avg_win == _ZERO
        assert metrics.largest_win == _ZERO
        assert metrics.largest_loss == Decimal("-100")


class TestMixedTrades:
    """Mix of winners and losers."""

    def test_mixed_trades(self) -> None:
        trades = [
            _make_trade(pnl=Decimal("300")),
            _make_trade(pnl=Decimal("-100")),
            _make_trade(pnl=Decimal("200")),
            _make_trade(pnl=Decimal("-50")),
        ]
        initial = Decimal("25000")
        daily_eq = _make_daily_equity(
            [
                Decimal("25300"),
                Decimal("25200"),
                Decimal("25400"),
                Decimal("25350"),
            ]
        )
        eq_curve = _make_equity_curve(
            [
                initial,
                Decimal("25300"),
                Decimal("25200"),
                Decimal("25400"),
                Decimal("25350"),
            ]
        )

        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=daily_eq,
            equity_curve=eq_curve,
            initial_capital=initial,
        )
        assert metrics.total_trades == 4
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 2
        assert metrics.win_rate == pytest.approx(0.5)
        # Profit factor: 500 / 150 = 3.333...
        assert metrics.profit_factor == pytest.approx(500.0 / 150.0)
        assert metrics.final_equity == Decimal("25350")
        assert metrics.total_return == Decimal("350")


class TestSingleTrade:
    """Single trade edge case."""

    def test_single_winning_trade(self) -> None:
        trades = [_make_trade(pnl=Decimal("150"))]
        initial = Decimal("25000")
        daily_eq = _make_daily_equity([Decimal("25150")])
        eq_curve = _make_equity_curve([initial, Decimal("25150")])

        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=daily_eq,
            equity_curve=eq_curve,
            initial_capital=initial,
        )
        assert metrics.total_trades == 1
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 0
        assert metrics.win_rate == pytest.approx(1.0)
        assert metrics.avg_win == Decimal("150")

    def test_single_losing_trade(self) -> None:
        trades = [_make_trade(pnl=Decimal("-80"))]
        initial = Decimal("25000")
        daily_eq = _make_daily_equity([Decimal("24920")])
        eq_curve = _make_equity_curve([initial, Decimal("24920")])

        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=daily_eq,
            equity_curve=eq_curve,
            initial_capital=initial,
        )
        assert metrics.total_trades == 1
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 1
        assert metrics.win_rate == pytest.approx(0.0)
        assert metrics.avg_loss == Decimal("-80")


class TestBreakEvenTrades:
    """Break-even trades (P&L = 0) are neither winners nor losers."""

    def test_all_break_even(self) -> None:
        trades = [
            _make_trade(pnl=_ZERO),
            _make_trade(pnl=_ZERO),
        ]
        initial = Decimal("25000")
        daily_eq = _make_daily_equity([initial, initial])
        eq_curve = _make_equity_curve([initial, initial, initial])

        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=daily_eq,
            equity_curve=eq_curve,
            initial_capital=initial,
        )
        assert metrics.total_trades == 2
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0
        assert metrics.win_rate == pytest.approx(0.0)
        assert metrics.profit_factor == pytest.approx(0.0)
        assert metrics.final_equity == initial


class TestSharpeRatio:
    """Sharpe ratio calculation verification."""

    def test_sharpe_known_dataset(self) -> None:
        """Verify Sharpe against hand-calculated values.

        Daily returns: [0.01, -0.005, 0.008, 0.003, -0.002]
        Mean: 0.0028
        Sample std (ddof=1): sqrt(sum((r-mean)^2)/(n-1))
        Annualized: (mean / std) * sqrt(252)
        """
        initial = Decimal("10000")
        daily_values = [
            Decimal("10100"),  # +1.0%
            Decimal("10049.50"),  # -0.5% from 10100
            Decimal("10129.90"),  # +0.8% from 10049.50
            Decimal("10160.29"),  # +0.3% from 10129.90
            Decimal("10139.97"),  # -0.2% from 10160.29
        ]
        daily_eq = _make_daily_equity(daily_values)

        metrics = BacktestMetrics.calculate(
            trades=[_make_trade(pnl=Decimal("139.97"))],
            daily_equity=daily_eq,
            equity_curve=_make_equity_curve([initial, *daily_values]),
            initial_capital=initial,
        )

        # Manual calculation:
        returns = [0.01, -0.005, 0.008, 0.003, -0.002]
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(var_r)
        expected_sharpe = (mean_r / std_r) * math.sqrt(252)

        assert metrics.sharpe_ratio == pytest.approx(expected_sharpe, rel=1e-2)

    def test_sharpe_with_ddof_1(self) -> None:
        """Verify sample std (n-1) is used, not population std (n)."""
        initial = Decimal("10000")
        # Two data points: different returns
        daily_eq = _make_daily_equity(
            [
                Decimal("10100"),  # +1%
                Decimal("10050"),  # -0.495% from 10100
            ]
        )

        metrics = BacktestMetrics.calculate(
            trades=[_make_trade(pnl=Decimal("50"))],
            daily_equity=daily_eq,
            equity_curve=_make_equity_curve(
                [initial, Decimal("10100"), Decimal("10050")]
            ),
            initial_capital=initial,
        )

        # With only 2 returns, ddof=1 makes a significant difference
        returns = [0.01, (10050 - 10100) / 10100]
        mean_r = sum(returns) / 2
        # ddof=1: divide by (n-1)=1
        var_ddof1 = sum((r - mean_r) ** 2 for r in returns) / 1
        std_ddof1 = math.sqrt(var_ddof1)
        expected = (mean_r / std_ddof1) * math.sqrt(252)

        assert metrics.sharpe_ratio == pytest.approx(expected, rel=1e-3)

    def test_sharpe_fewer_than_2_days_returns_zero(self) -> None:
        initial = Decimal("25000")
        daily_eq = _make_daily_equity([Decimal("25100")])

        metrics = BacktestMetrics.calculate(
            trades=[_make_trade(pnl=Decimal("100"))],
            daily_equity=daily_eq,
            equity_curve=_make_equity_curve([initial, Decimal("25100")]),
            initial_capital=initial,
        )
        assert metrics.sharpe_ratio == 0.0

    def test_sharpe_zero_std_returns_zero(self) -> None:
        """All days have zero return → std=0 → sharpe=0."""
        initial = Decimal("10000")
        daily_eq = _make_daily_equity(
            [
                Decimal("10000"),
                Decimal("10000"),
                Decimal("10000"),
            ]
        )

        metrics = BacktestMetrics.calculate(
            trades=[],
            daily_equity=daily_eq,
            equity_curve=_make_equity_curve([initial, initial, initial, initial]),
            initial_capital=initial,
        )
        assert metrics.sharpe_ratio == 0.0

    def test_sharpe_no_daily_equity(self) -> None:
        metrics = BacktestMetrics.calculate(
            trades=[],
            daily_equity=[],
            equity_curve=[],
            initial_capital=Decimal("25000"),
        )
        assert metrics.sharpe_ratio == 0.0


class TestMaxDrawdown:
    """Max drawdown calculation verification."""

    def test_known_equity_curve(self) -> None:
        """Peak 100 → trough 90 = 10% drawdown."""
        eq = _make_equity_curve(
            [
                Decimal("100"),
                Decimal("105"),
                Decimal("110"),  # peak
                Decimal("100"),
                Decimal("99"),  # trough
                Decimal("108"),
            ]
        )
        metrics = BacktestMetrics.calculate(
            trades=[_make_trade(pnl=Decimal("8"))],
            daily_equity=_make_daily_equity([Decimal("108")]),
            equity_curve=eq,
            initial_capital=Decimal("100"),
        )
        # Max drawdown: (110 - 99) / 110 = 0.1
        assert metrics.max_drawdown == pytest.approx(11.0 / 110.0, rel=1e-6)
        assert metrics.max_drawdown_pct == pytest.approx(10.0, rel=1e-3)

    def test_no_drawdown(self) -> None:
        """Monotonically increasing equity."""
        eq = _make_equity_curve(
            [
                Decimal("100"),
                Decimal("101"),
                Decimal("102"),
            ]
        )
        metrics = BacktestMetrics.calculate(
            trades=[_make_trade(pnl=Decimal("2"))],
            daily_equity=_make_daily_equity([Decimal("102")]),
            equity_curve=eq,
            initial_capital=Decimal("100"),
        )
        assert metrics.max_drawdown == pytest.approx(0.0)

    def test_empty_equity_curve(self) -> None:
        metrics = BacktestMetrics.calculate(
            trades=[],
            daily_equity=[],
            equity_curve=[],
            initial_capital=Decimal("25000"),
        )
        assert metrics.max_drawdown == 0.0

    def test_multiple_drawdowns_picks_largest(self) -> None:
        """Two drawdowns: 5% and 8%. Picks 8%."""
        eq = _make_equity_curve(
            [
                Decimal("100"),
                Decimal("105"),  # peak 1
                Decimal("100"),  # dd1: 5/105 ≈ 4.76%
                Decimal("110"),  # peak 2
                Decimal("101"),  # dd2: 9/110 ≈ 8.18%
                Decimal("115"),
            ]
        )
        metrics = BacktestMetrics.calculate(
            trades=[_make_trade(pnl=Decimal("15"))],
            daily_equity=_make_daily_equity([Decimal("115")]),
            equity_curve=eq,
            initial_capital=Decimal("100"),
        )
        assert metrics.max_drawdown == pytest.approx(9.0 / 110.0, rel=1e-6)


class TestProfitFactor:
    """Profit factor edge cases."""

    def test_profit_factor_capped_not_infinity(self) -> None:
        """All wins, no losses → capped at 9999.99."""
        trades = [_make_trade(pnl=Decimal("100"))]
        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=_make_daily_equity([Decimal("25100")]),
            equity_curve=_make_equity_curve([Decimal("25000"), Decimal("25100")]),
            initial_capital=Decimal("25000"),
        )
        assert metrics.profit_factor == pytest.approx(9999.99)
        # Ensure it's a regular float, not inf
        assert math.isfinite(metrics.profit_factor)

    def test_profit_factor_zero_with_no_trades(self) -> None:
        metrics = BacktestMetrics.calculate(
            trades=[],
            daily_equity=[],
            equity_curve=[],
            initial_capital=Decimal("25000"),
        )
        assert metrics.profit_factor == pytest.approx(0.0)


class TestTotalReturn:
    """Total return computation."""

    def test_total_return_positive(self) -> None:
        trades = [_make_trade(pnl=Decimal("500"))]
        initial = Decimal("25000")
        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=_make_daily_equity([Decimal("25500")]),
            equity_curve=_make_equity_curve([initial, Decimal("25500")]),
            initial_capital=initial,
        )
        assert metrics.total_return == Decimal("500")
        assert metrics.total_return_pct == Decimal("2.0")  # 500/25000 * 100

    def test_total_return_negative(self) -> None:
        trades = [_make_trade(pnl=Decimal("-1000"))]
        initial = Decimal("25000")
        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=_make_daily_equity([Decimal("24000")]),
            equity_curve=_make_equity_curve([initial, Decimal("24000")]),
            initial_capital=initial,
        )
        assert metrics.total_return == Decimal("-1000")
        assert metrics.total_return_pct == Decimal("-4.0")


class TestAvgTradeDuration:
    """Average trade duration."""

    def test_avg_duration(self) -> None:
        trades = [
            _make_trade(pnl=Decimal("100"), duration_seconds=3600),  # 1 hour
            _make_trade(pnl=Decimal("50"), duration_seconds=7200),  # 2 hours
            _make_trade(pnl=Decimal("-30"), duration_seconds=1800),  # 30 min
        ]
        initial = Decimal("25000")
        metrics = BacktestMetrics.calculate(
            trades=trades,
            daily_equity=_make_daily_equity([Decimal("25120")]),
            equity_curve=_make_equity_curve([initial, Decimal("25120")]),
            initial_capital=initial,
        )
        # (3600 + 7200 + 1800) / 3 = 4200
        assert metrics.avg_trade_duration == 4200


class TestMetricsDataFrozen:
    """BacktestMetricsData is immutable."""

    def test_frozen(self) -> None:
        metrics = BacktestMetrics.calculate(
            trades=[],
            daily_equity=[],
            equity_curve=[],
            initial_capital=Decimal("25000"),
        )
        with pytest.raises(AttributeError):
            metrics.total_trades = 99  # type: ignore[misc]
