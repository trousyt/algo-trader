"""Backtest and settings database models.

Tables: backtest_run, backtest_trade, settings_override
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DecimalText


class BacktestRunModel(Base):
    """Backtest run metadata and results."""

    __tablename__ = "backtest_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    symbols: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    start_date: Mapped[str] = mapped_column(String, nullable=False)
    end_date: Mapped[str] = mapped_column(String, nullable=False)
    initial_capital: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    params: Mapped[str] = mapped_column(Text, nullable=False)  # JSON of strategy params
    total_return: Mapped[DecimalText | None] = mapped_column(DecimalText, nullable=True)
    win_rate: Mapped[DecimalText | None] = mapped_column(DecimalText, nullable=True)
    profit_factor: Mapped[DecimalText | None] = mapped_column(
        DecimalText, nullable=True
    )
    sharpe_ratio: Mapped[DecimalText | None] = mapped_column(DecimalText, nullable=True)
    max_drawdown: Mapped[DecimalText | None] = mapped_column(DecimalText, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equity_curve: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class BacktestTradeModel(Base):
    """Individual trades within a backtest run."""

    __tablename__ = "backtest_trade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("backtest_run.id"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    entry_price: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    exit_price: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    entry_at: Mapped[str] = mapped_column(String, nullable=False)
    exit_at: Mapped[str] = mapped_column(String, nullable=False)
    pnl: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_backtest_trade_run", "run_id"),)


class SettingsOverrideModel(Base):
    """Runtime configuration overrides from web UI."""

    __tablename__ = "settings_override"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
