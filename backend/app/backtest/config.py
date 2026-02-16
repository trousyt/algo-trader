"""Backtest configuration and shared data types.

BacktestConfig is a standalone BaseModel (not nested under AppConfig)
because backtests are run via CLI with explicit parameters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import VALID_CANDLE_INTERVALS

MAX_BACKTEST_DAYS = 365
MAX_BACKTEST_SYMBOLS = 10


class BacktestConfig(BaseModel):
    """Configuration for a single backtest run."""

    strategy: str = "velez"
    symbols: list[str]
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(
        default=Decimal("25000"),
        ge=Decimal("1000"),
        le=Decimal("10000000"),
    )
    slippage_per_share: Decimal = Field(
        default=Decimal("0.01"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    candle_interval_minutes: int = Field(default=2)

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Fail fast on unknown strategy (before expensive data loading)."""
        valid = {"velez"}
        if v not in valid:
            raise ValueError(
                f"Unknown strategy: {v!r}. Available: {', '.join(sorted(valid))}"
            )
        return v

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one symbol required")
        if len(v) > MAX_BACKTEST_SYMBOLS:
            raise ValueError(f"Maximum {MAX_BACKTEST_SYMBOLS} symbols per backtest")
        for s in v:
            if not re.match(r"^[A-Z]{1,5}$", s):
                raise ValueError(f"Invalid symbol: {s}")
        return v

    @field_validator("candle_interval_minutes")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v not in VALID_CANDLE_INTERVALS:
            raise ValueError(
                f"Invalid interval: {v}. "
                f"Must be one of {sorted(VALID_CANDLE_INTERVALS)}"
            )
        return v

    @model_validator(mode="after")
    def validate_date_range(self) -> BacktestConfig:
        """Cross-field validation using model_validator (not fragile field ordering)."""
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        delta = (self.end_date - self.start_date).days
        if delta > MAX_BACKTEST_DAYS:
            raise ValueError(
                f"Date range exceeds {MAX_BACKTEST_DAYS} days ({delta} days)"
            )
        return self


@dataclass(frozen=True)
class BacktestTradeData:
    """One completed round-trip trade in a backtest."""

    symbol: str
    side: str
    qty: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_at: datetime
    exit_at: datetime
    pnl: Decimal
    duration_seconds: int


class BacktestError(Exception):
    """Raised for backtest-specific errors."""
