"""Initial schema: all Phase 1 tables, indexes, constraints, and triggers.

Revision ID: 001
Revises:
Create Date: 2026-02-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def create_immutability_triggers() -> None:
    """Create immutability triggers for audit tables.

    Call this function from any migration that uses batch mode on
    order_event or trade tables, as batch mode drops and recreates
    tables which silently destroys triggers.
    """
    # order_event: no updates
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_update_order_event "
        "BEFORE UPDATE ON order_event "
        "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
    )
    # order_event: no deletes
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_delete_order_event "
        "BEFORE DELETE ON order_event "
        "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
    )
    # trade: no updates
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_update_trade "
        "BEFORE UPDATE ON trade "
        "BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;"
    )
    # trade: no deletes
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_delete_trade "
        "BEFORE DELETE ON trade "
        "BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;"
    )


def upgrade() -> None:
    # --- order_state ---
    op.create_table(
        "order_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("local_id", sa.String(), nullable=False),
        sa.Column("broker_id", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("qty_requested", sa.String(), nullable=False),
        sa.Column("qty_filled", sa.String(), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.String(), nullable=True),
        sa.Column(
            "state", sa.String(), nullable=False, server_default="pending_submit"
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("submit_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("local_id"),
        sa.CheckConstraint("side IN ('long', 'short')", name="ck_order_state_side"),
    )
    op.create_index("ix_order_state_broker_id", "order_state", ["broker_id"])
    op.create_index(
        "ix_order_state_correlation_id", "order_state", ["correlation_id"]
    )
    op.create_index("ix_order_state_state", "order_state", ["state"])
    op.create_index(
        "ix_order_state_symbol_created", "order_state", ["symbol", "created_at"]
    )

    # --- order_event ---
    op.create_table(
        "order_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_local_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("old_state", sa.String(), nullable=True),
        sa.Column("new_state", sa.String(), nullable=False),
        sa.Column("qty_filled", sa.String(), nullable=True),
        sa.Column("fill_price", sa.String(), nullable=True),
        sa.Column("broker_id", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_event_local_id", "order_event", ["order_local_id"])
    op.create_index("ix_order_event_recorded", "order_event", ["recorded_at"])

    # --- trade ---
    op.create_table(
        "trade",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_id", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.String(), nullable=False),
        sa.Column("entry_price", sa.String(), nullable=False),
        sa.Column("exit_price", sa.String(), nullable=False),
        sa.Column("entry_at", sa.String(), nullable=False),
        sa.Column("exit_at", sa.String(), nullable=False),
        sa.Column("pnl", sa.String(), nullable=False),
        sa.Column("pnl_pct", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("commission", sa.String(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id"),
        sa.CheckConstraint("side IN ('long', 'short')", name="ck_trade_side"),
    )
    op.create_index("ix_trade_symbol_exit", "trade", ["symbol", "exit_at"])
    op.create_index("ix_trade_correlation", "trade", ["correlation_id"])
    op.create_index("ix_trade_strategy_exit", "trade", ["strategy", "exit_at"])

    # --- trade_note ---
    op.create_table(
        "trade_note",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_id", sa.String(), sa.ForeignKey("trade.trade_id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- backtest_run ---
    op.create_table(
        "backtest_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("symbols", sa.Text(), nullable=False),
        sa.Column("start_date", sa.String(), nullable=False),
        sa.Column("end_date", sa.String(), nullable=False),
        sa.Column("initial_capital", sa.String(), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("total_return", sa.String(), nullable=True),
        sa.Column("win_rate", sa.String(), nullable=True),
        sa.Column("profit_factor", sa.String(), nullable=True),
        sa.Column("sharpe_ratio", sa.String(), nullable=True),
        sa.Column("max_drawdown", sa.String(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("equity_curve", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- backtest_trade ---
    op.create_table(
        "backtest_trade",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("backtest_run.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.String(), nullable=False),
        sa.Column("entry_price", sa.String(), nullable=False),
        sa.Column("exit_price", sa.String(), nullable=False),
        sa.Column("entry_at", sa.String(), nullable=False),
        sa.Column("exit_at", sa.String(), nullable=False),
        sa.Column("pnl", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_trade_run", "backtest_trade", ["run_id"])

    # --- settings_override ---
    op.create_table(
        "settings_override",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("previous_value", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )

    # --- Immutability triggers ---
    create_immutability_triggers()


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported. Use backup-and-restore for rollback."
    )
