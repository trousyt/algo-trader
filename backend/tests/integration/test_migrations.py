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
