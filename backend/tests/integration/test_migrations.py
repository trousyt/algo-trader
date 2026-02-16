"""Tests for Alembic migrations.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def alembic_config(tmp_path: Path) -> Config:
    """Create Alembic config pointing to a temp database."""
    db_path = tmp_path / "test_migration.db"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


@pytest.fixture()
def migrated_engine(alembic_config: Config, tmp_path: Path) -> sa.engine.Engine:
    """Run migrations and return engine for verification."""
    command.upgrade(alembic_config, "head")
    db_path = tmp_path / "test_migration.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    return engine


class TestMigrationUpgrade:
    """Test that migrations create the expected schema."""

    def test_upgrade_from_empty(self, alembic_config: Config) -> None:
        """Alembic upgrade head on empty DB succeeds."""
        command.upgrade(alembic_config, "head")

    def test_all_tables_exist(self, migrated_engine: sa.engine.Engine) -> None:
        inspector = inspect(migrated_engine)
        table_names = set(inspector.get_table_names())
        expected = {
            "order_state",
            "order_event",
            "trade",
            "trade_note",
            "backtest_run",
            "backtest_trade",
            "settings_override",
        }
        assert expected.issubset(table_names), (
            f"Missing tables: {expected - table_names}"
        )

    def test_key_indexes_exist(self, migrated_engine: sa.engine.Engine) -> None:
        inspector = inspect(migrated_engine)
        order_indexes = {idx["name"] for idx in inspector.get_indexes("order_state")}
        assert "ix_order_state_broker_id" in order_indexes
        assert "ix_order_state_correlation_id" in order_indexes
        assert "ix_order_state_state" in order_indexes

    def test_immutability_triggers_exist(
        self, migrated_engine: sa.engine.Engine
    ) -> None:
        with migrated_engine.connect() as conn:
            triggers = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
                )
            ).fetchall()
            trigger_names = {row[0] for row in triggers}

        expected_triggers = {
            "no_update_order_event",
            "no_delete_order_event",
            "no_update_trade",
            "no_delete_trade",
        }
        assert expected_triggers.issubset(trigger_names), (
            f"Missing triggers: {expected_triggers - trigger_names}"
        )


class TestMigration002:
    """Test that migration 002 adds order_role, strategy, and parent_id index."""

    def test_order_role_column_exists(self, migrated_engine: sa.engine.Engine) -> None:
        inspector = inspect(migrated_engine)
        columns = {col["name"] for col in inspector.get_columns("order_state")}
        assert "order_role" in columns

    def test_strategy_column_exists(self, migrated_engine: sa.engine.Engine) -> None:
        inspector = inspect(migrated_engine)
        columns = {col["name"] for col in inspector.get_columns("order_state")}
        assert "strategy" in columns

    def test_parent_id_index_exists(self, migrated_engine: sa.engine.Engine) -> None:
        inspector = inspect(migrated_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("order_state")}
        assert "ix_order_state_parent_id" in indexes

    def test_side_check_allows_buy_sell(
        self, migrated_engine: sa.engine.Engine
    ) -> None:
        """Side CHECK accepts 'buy' and 'sell'."""
        with migrated_engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO order_state "
                    "(local_id, correlation_id, symbol, side, order_type, "
                    "order_role, qty_requested, state, created_at, updated_at) "
                    "VALUES "
                    "('test-buy', 'c1', 'AAPL', 'buy', 'market', 'entry', "
                    "'10', 'pending_submit', '2026-02-15', '2026-02-15')"
                )
            )
            conn.commit()

    def test_triggers_survive_migration_002(
        self, migrated_engine: sa.engine.Engine
    ) -> None:
        """Immutability triggers still exist after batch mode migration."""
        with migrated_engine.connect() as conn:
            triggers = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
                )
            ).fetchall()
            trigger_names = {row[0] for row in triggers}

        assert "no_update_order_event" in trigger_names
        assert "no_delete_order_event" in trigger_names
        assert "no_update_trade" in trigger_names
        assert "no_delete_trade" in trigger_names
