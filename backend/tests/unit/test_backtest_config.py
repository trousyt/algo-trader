"""Tests for BacktestConfig validation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.backtest.config import (
    MAX_BACKTEST_DAYS,
    MAX_BACKTEST_SYMBOLS,
    BacktestConfig,
    BacktestTradeData,
)


class TestBacktestConfig:
    """BacktestConfig validation tests."""

    def _valid_kwargs(self) -> dict:
        return {
            "strategy": "velez",
            "symbols": ["AAPL"],
            "start_date": date(2025, 1, 1),
            "end_date": date(2025, 3, 31),
            "initial_capital": Decimal("25000"),
            "slippage_per_share": Decimal("0.01"),
            "candle_interval_minutes": 2,
        }

    def test_valid_config(self) -> None:
        config = BacktestConfig(**self._valid_kwargs())
        assert config.strategy == "velez"
        assert config.symbols == ["AAPL"]
        assert config.initial_capital == Decimal("25000")

    def test_defaults(self) -> None:
        config = BacktestConfig(
            symbols=["AAPL"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
        )
        assert config.strategy == "velez"
        assert config.initial_capital == Decimal("25000")
        assert config.slippage_per_share == Decimal("0.01")
        assert config.candle_interval_minutes == 2

    def test_multiple_symbols(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = ["AAPL", "TSLA", "NVDA"]
        config = BacktestConfig(**kwargs)
        assert len(config.symbols) == 3

    # --- Strategy validation ---

    def test_unknown_strategy_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["strategy"] = "unknown"
        with pytest.raises(ValidationError, match="Unknown strategy"):
            BacktestConfig(**kwargs)

    # --- Symbol validation ---

    def test_empty_symbols_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = []
        with pytest.raises(ValidationError, match="At least one symbol"):
            BacktestConfig(**kwargs)

    def test_invalid_symbol_format_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = ["aapl"]
        with pytest.raises(ValidationError, match="Invalid symbol"):
            BacktestConfig(**kwargs)

    def test_too_long_symbol_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = ["ABCDEF"]
        with pytest.raises(ValidationError, match="Invalid symbol"):
            BacktestConfig(**kwargs)

    def test_symbol_with_numbers_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = ["A1BC"]
        with pytest.raises(ValidationError, match="Invalid symbol"):
            BacktestConfig(**kwargs)

    def test_too_many_symbols_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = [
            f"SYM{chr(65 + i)}" for i in range(MAX_BACKTEST_SYMBOLS + 1)
        ]
        with pytest.raises(ValidationError, match=f"Maximum {MAX_BACKTEST_SYMBOLS}"):
            BacktestConfig(**kwargs)

    def test_max_symbols_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["symbols"] = [f"SY{chr(65 + i)}" for i in range(MAX_BACKTEST_SYMBOLS)]
        config = BacktestConfig(**kwargs)
        assert len(config.symbols) == MAX_BACKTEST_SYMBOLS

    # --- Date validation ---

    def test_end_before_start_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["start_date"] = date(2025, 6, 1)
        kwargs["end_date"] = date(2025, 1, 1)
        with pytest.raises(ValidationError, match="end_date must be after start_date"):
            BacktestConfig(**kwargs)

    def test_same_date_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["start_date"] = date(2025, 6, 1)
        kwargs["end_date"] = date(2025, 6, 1)
        with pytest.raises(ValidationError, match="end_date must be after start_date"):
            BacktestConfig(**kwargs)

    def test_date_range_exceeds_max_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["start_date"] = date(2023, 1, 1)
        kwargs["end_date"] = date(2025, 1, 1)
        with pytest.raises(ValidationError, match=f"exceeds {MAX_BACKTEST_DAYS} days"):
            BacktestConfig(**kwargs)

    def test_max_date_range_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["start_date"] = date(2025, 1, 1)
        kwargs["end_date"] = date(2025, 12, 31)
        config = BacktestConfig(**kwargs)
        assert (config.end_date - config.start_date).days == 364

    # --- Capital validation ---

    def test_capital_too_low_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["initial_capital"] = Decimal("500")
        with pytest.raises(ValidationError):
            BacktestConfig(**kwargs)

    def test_capital_too_high_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["initial_capital"] = Decimal("20000000")
        with pytest.raises(ValidationError):
            BacktestConfig(**kwargs)

    def test_minimum_capital_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["initial_capital"] = Decimal("1000")
        config = BacktestConfig(**kwargs)
        assert config.initial_capital == Decimal("1000")

    # --- Slippage validation ---

    def test_negative_slippage_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["slippage_per_share"] = Decimal("-0.01")
        with pytest.raises(ValidationError):
            BacktestConfig(**kwargs)

    def test_slippage_too_high_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["slippage_per_share"] = Decimal("2.00")
        with pytest.raises(ValidationError):
            BacktestConfig(**kwargs)

    def test_zero_slippage_accepted(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["slippage_per_share"] = Decimal("0")
        config = BacktestConfig(**kwargs)
        assert config.slippage_per_share == Decimal("0")

    # --- Interval validation ---

    def test_invalid_interval_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["candle_interval_minutes"] = 3
        with pytest.raises(ValidationError, match="Invalid interval"):
            BacktestConfig(**kwargs)

    @pytest.mark.parametrize("interval", [1, 2, 5, 10])
    def test_valid_intervals_accepted(self, interval: int) -> None:
        kwargs = self._valid_kwargs()
        kwargs["candle_interval_minutes"] = interval
        config = BacktestConfig(**kwargs)
        assert config.candle_interval_minutes == interval


class TestBacktestTradeData:
    """BacktestTradeData tests."""

    def test_frozen(self) -> None:
        from datetime import UTC, datetime

        trade = BacktestTradeData(
            symbol="AAPL",
            side="buy",
            qty=Decimal("100"),
            entry_price=Decimal("150.00"),
            exit_price=Decimal("155.00"),
            entry_at=datetime(2025, 1, 2, 10, 0, tzinfo=UTC),
            exit_at=datetime(2025, 1, 2, 11, 0, tzinfo=UTC),
            pnl=Decimal("500.00"),
            duration_seconds=3600,
        )
        assert trade.symbol == "AAPL"
        assert trade.pnl == Decimal("500.00")

        with pytest.raises(AttributeError):
            trade.pnl = Decimal("0")  # type: ignore[misc]
