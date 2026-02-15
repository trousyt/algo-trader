"""Step 4: fix side CHECK, add order_role + strategy columns, parent_id index.

Revision ID: 002
Revises: 001
Create Date: 2026-02-15

SQLite requires batch mode for CHECK constraint changes and column adds with
constraints. Batch mode recreates the table, which destroys triggers -- so
we re-create immutability triggers at the end.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _recreate_immutability_triggers() -> None:
    """Re-create immutability triggers that batch mode may have destroyed."""
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_update_order_event "
        "BEFORE UPDATE ON order_event "
        "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_delete_order_event "
        "BEFORE DELETE ON order_event "
        "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_update_trade "
        "BEFORE UPDATE ON trade "
        "BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS no_delete_trade "
        "BEFORE DELETE ON trade "
        "BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;"
    )


def upgrade() -> None:
    # --- order_state: fix side CHECK + add order_role, strategy, parent_id index ---
    with op.batch_alter_table("order_state", schema=None) as batch_op:
        # Drop old CHECK and add corrected one
        batch_op.drop_constraint("ck_order_state_side", type_="check")
        batch_op.create_check_constraint(
            "ck_order_state_side", "side IN ('buy', 'sell')"
        )

        # Add order_role column with CHECK
        batch_op.add_column(
            sa.Column(
                "order_role",
                sa.String(),
                nullable=False,
                server_default="entry",
            )
        )
        batch_op.create_check_constraint(
            "ck_order_state_role",
            "order_role IN ('entry', 'stop_loss', 'exit_market')",
        )

        # Add strategy column (nullable)
        batch_op.add_column(sa.Column("strategy", sa.String(), nullable=True))

        # Add parent_id index
        batch_op.create_index("ix_order_state_parent_id", ["parent_id"])

    # Batch mode recreates tables, which can destroy triggers.
    # Re-create them defensively.
    _recreate_immutability_triggers()


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported. Use backup-and-restore for rollback."
    )
