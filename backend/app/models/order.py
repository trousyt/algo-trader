"""Order-related database models.

Tables: order_state, order_event, trade, trade_note
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DecimalText


class OrderStateModel(Base):
    """Mutable order lifecycle tracking."""

    __tablename__ = "order_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    local_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    broker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(
        String,
        CheckConstraint("side IN ('buy', 'sell')", name="ck_order_state_side"),
        nullable=False,
    )
    order_type: Mapped[str] = mapped_column(String, nullable=False)
    order_role: Mapped[str] = mapped_column(
        String,
        CheckConstraint(
            "order_role IN ('entry', 'stop_loss', 'exit_market')",
            name="ck_order_state_role",
        ),
        nullable=False,
        server_default="entry",
    )
    strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    qty_requested: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    qty_filled: Mapped[DecimalText] = mapped_column(
        DecimalText, nullable=False, server_default="0"
    )
    avg_fill_price: Mapped[DecimalText | None] = mapped_column(
        DecimalText, nullable=True
    )
    state: Mapped[str] = mapped_column(
        String, nullable=False, server_default="pending_submit"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    submit_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ix_order_state_broker_id", "broker_id"),
        Index("ix_order_state_correlation_id", "correlation_id"),
        Index("ix_order_state_state", "state"),
        Index("ix_order_state_symbol_created", "symbol", "created_at"),
        Index("ix_order_state_parent_id", "parent_id"),
    )


class OrderEventModel(Base):
    """Immutable append-only audit log for order events."""

    __tablename__ = "order_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_local_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    old_state: Mapped[str | None] = mapped_column(String, nullable=True)
    new_state: Mapped[str] = mapped_column(String, nullable=False)
    qty_filled: Mapped[DecimalText | None] = mapped_column(DecimalText, nullable=True)
    fill_price: Mapped[DecimalText | None] = mapped_column(DecimalText, nullable=True)
    broker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ix_order_event_local_id", "order_local_id"),
        Index("ix_order_event_recorded", "recorded_at"),
    )


class TradeModel(Base):
    """Immutable completed round-trip trades."""

    __tablename__ = "trade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(
        String,
        CheckConstraint("side IN ('long', 'short')", name="ck_trade_side"),
        nullable=False,
    )
    qty: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    entry_price: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    exit_price: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    entry_at: Mapped[str] = mapped_column(String, nullable=False)
    exit_at: Mapped[str] = mapped_column(String, nullable=False)
    pnl: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    pnl_pct: Mapped[DecimalText] = mapped_column(DecimalText, nullable=False)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    commission: Mapped[DecimalText] = mapped_column(
        DecimalText, nullable=False, server_default="0"
    )

    __table_args__ = (
        Index("ix_trade_symbol_exit", "symbol", "exit_at"),
        Index("ix_trade_correlation", "correlation_id"),
        Index("ix_trade_strategy_exit", "strategy", "exit_at"),
    )


class TradeNoteModel(Base):
    """Mutable user annotations on trades."""

    __tablename__ = "trade_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("trade.trade_id"),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
