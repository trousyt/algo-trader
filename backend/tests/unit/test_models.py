"""Tests for database models, DecimalText type, and SQLite pragmas.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.base import Base, set_sqlite_pragmas


@pytest.fixture()
def sync_engine() -> Engine:
    """Create an in-memory SQLite engine with pragmas for testing."""
    engine = sa.create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", set_sqlite_pragmas)
    Base.metadata.create_all(engine)

    # Create immutability triggers manually for in-memory DB
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS no_update_order_event "
                "BEFORE UPDATE ON order_event "
                "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS no_delete_order_event "
                "BEFORE DELETE ON order_event "
                "BEGIN SELECT RAISE(ABORT, 'order_event is immutable'); END;"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS no_update_trade "
                "BEFORE UPDATE ON trade "
                "BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS no_delete_trade "
                "BEFORE DELETE ON trade "
                "BEGIN SELECT RAISE(ABORT, 'trade is immutable'); END;"
            )
        )
        conn.commit()
    return engine


@pytest.fixture()
def session(sync_engine: Engine) -> Session:
    """Create a test session."""
    with Session(sync_engine) as session:
        yield session


class TestSQLitePragmas:
    """Test that SQLite pragmas are set correctly."""

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """WAL mode only works with file-based SQLite, not :memory:."""
        db_path = tmp_path / "test_wal.db"
        engine = sa.create_engine(f"sqlite:///{db_path}")
        event.listen(engine, "connect", set_sqlite_pragmas)
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert result == "wal"
        engine.dispose()

    def test_foreign_keys_enabled(self, sync_engine: Engine) -> None:
        with sync_engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert result == 1

    def test_busy_timeout_set(self, sync_engine: Engine) -> None:
        with sync_engine.connect() as conn:
            result = conn.execute(text("PRAGMA busy_timeout")).scalar()
            assert result == 5000


class TestTableCreation:
    """Test that all tables are created correctly."""

    def test_all_tables_exist(self, sync_engine: Engine) -> None:
        inspector = inspect(sync_engine)
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
        assert expected.issubset(table_names)

    def test_order_state_columns(self, sync_engine: Engine) -> None:
        inspector = inspect(sync_engine)
        columns = {col["name"] for col in inspector.get_columns("order_state")}
        expected = {
            "id",
            "local_id",
            "broker_id",
            "correlation_id",
            "symbol",
            "side",
            "order_type",
            "qty_requested",
            "qty_filled",
            "avg_fill_price",
            "state",
            "version",
            "parent_id",
            "submit_attempts",
            "last_error",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(columns)


class TestDecimalText:
    """Test DecimalText TypeDecorator for Decimal <-> TEXT round-trips."""

    def test_decimal_round_trip(self, session: Session) -> None:
        """Write Decimal -> read back exact Decimal."""
        from app.models.order import OrderStateModel

        session.execute(
            sa.insert(OrderStateModel).values(
                local_id="test-001",
                correlation_id="corr-001",
                symbol="AAPL",
                side="long",
                order_type="market",
                qty_requested="100.5",
                qty_filled="0",
                state="pending_submit",
                version=0,
                submit_attempts=0,
                created_at="2026-02-14T00:00:00.000000Z",
                updated_at="2026-02-14T00:00:00.000000Z",
            )
        )
        session.commit()

        row = session.execute(
            sa.select(OrderStateModel).where(OrderStateModel.local_id == "test-001")
        ).scalar_one()
        assert row.qty_requested == Decimal("100.5")
        assert isinstance(row.qty_requested, Decimal)

    def test_decimal_precision(self, session: Session) -> None:
        """Ensure Decimal('0.01') stores and retrieves exactly."""
        from app.models.order import TradeModel

        session.execute(
            sa.insert(TradeModel).values(
                trade_id="trade-001",
                correlation_id="corr-001",
                symbol="AAPL",
                side="long",
                qty="100",
                entry_price="150.01",
                exit_price="151.02",
                entry_at="2026-02-14T00:00:00.000000Z",
                exit_at="2026-02-14T01:00:00.000000Z",
                pnl="101.00",
                pnl_pct="0.67",
                strategy="velez",
                duration_seconds=3600,
                commission="0.01",
            )
        )
        session.commit()

        row = session.execute(
            sa.select(TradeModel).where(TradeModel.trade_id == "trade-001")
        ).scalar_one()
        assert row.commission == Decimal("0.01")
        assert row.entry_price == Decimal("150.01")


class TestOrderStateSideCheck:
    """Test CHECK constraint on side column."""

    def test_invalid_side_rejected(self, session: Session) -> None:
        from app.models.order import OrderStateModel

        with pytest.raises(sa.exc.IntegrityError):
            session.execute(
                sa.insert(OrderStateModel).values(
                    local_id="test-bad-side",
                    correlation_id="corr-001",
                    symbol="AAPL",
                    side="invalid",
                    order_type="market",
                    qty_requested="100",
                    qty_filled="0",
                    state="pending_submit",
                    version=0,
                    submit_attempts=0,
                    created_at="2026-02-14T00:00:00.000000Z",
                    updated_at="2026-02-14T00:00:00.000000Z",
                )
            )
            session.commit()


class TestImmutabilityTriggers:
    """Test that immutable tables reject UPDATE and DELETE."""

    def _insert_order_event(self, session: Session) -> None:
        from app.models.order import OrderEventModel

        session.execute(
            sa.insert(OrderEventModel).values(
                order_local_id="test-001",
                event_type="submitted",
                new_state="submitted",
                recorded_at="2026-02-14T00:00:00.000000Z",
            )
        )
        session.commit()

    def test_order_event_update_rejected(self, session: Session) -> None:
        from app.models.order import OrderEventModel

        self._insert_order_event(session)
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            session.execute(
                sa.update(OrderEventModel)
                .where(OrderEventModel.order_local_id == "test-001")
                .values(event_type="changed")
            )
            session.commit()

    def test_order_event_delete_rejected(self, session: Session) -> None:
        from app.models.order import OrderEventModel

        self._insert_order_event(session)
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            session.execute(
                sa.delete(OrderEventModel).where(
                    OrderEventModel.order_local_id == "test-001"
                )
            )
            session.commit()

    def _insert_trade(self, session: Session) -> None:
        from app.models.order import TradeModel

        session.execute(
            sa.insert(TradeModel).values(
                trade_id="trade-imm-001",
                correlation_id="corr-001",
                symbol="AAPL",
                side="long",
                qty="100",
                entry_price="150.00",
                exit_price="151.00",
                entry_at="2026-02-14T00:00:00.000000Z",
                exit_at="2026-02-14T01:00:00.000000Z",
                pnl="100.00",
                pnl_pct="0.67",
                strategy="velez",
                duration_seconds=3600,
                commission="0",
            )
        )
        session.commit()

    def test_trade_update_rejected(self, session: Session) -> None:
        from app.models.order import TradeModel

        self._insert_trade(session)
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            session.execute(
                sa.update(TradeModel)
                .where(TradeModel.trade_id == "trade-imm-001")
                .values(pnl="999")
            )
            session.commit()

    def test_trade_delete_rejected(self, session: Session) -> None:
        from app.models.order import TradeModel

        self._insert_trade(session)
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            session.execute(
                sa.delete(TradeModel).where(TradeModel.trade_id == "trade-imm-001")
            )
            session.commit()


class TestUniqueConstraints:
    """Test unique constraints on key columns."""

    def test_order_state_local_id_unique(self, session: Session) -> None:
        from app.models.order import OrderStateModel

        row = dict(
            local_id="dup-001",
            correlation_id="corr-001",
            symbol="AAPL",
            side="long",
            order_type="market",
            qty_requested="100",
            qty_filled="0",
            state="pending_submit",
            version=0,
            submit_attempts=0,
            created_at="2026-02-14T00:00:00.000000Z",
            updated_at="2026-02-14T00:00:00.000000Z",
        )
        session.execute(sa.insert(OrderStateModel).values(**row))
        session.commit()

        with pytest.raises(sa.exc.IntegrityError):
            session.execute(sa.insert(OrderStateModel).values(**row))
            session.commit()


class TestForeignKeys:
    """Test foreign key enforcement."""

    def test_trade_note_invalid_trade_id(self, session: Session) -> None:
        from app.models.order import TradeNoteModel

        with pytest.raises(sa.exc.IntegrityError):
            session.execute(
                sa.insert(TradeNoteModel).values(
                    trade_id="nonexistent-trade",
                    note="This should fail",
                    created_at="2026-02-14T00:00:00.000000Z",
                    updated_at="2026-02-14T00:00:00.000000Z",
                )
            )
            session.commit()

    def test_backtest_trade_invalid_run_id(self, session: Session) -> None:
        from app.models.backtest import BacktestTradeModel

        with pytest.raises(sa.exc.IntegrityError):
            session.execute(
                sa.insert(BacktestTradeModel).values(
                    run_id=99999,
                    symbol="AAPL",
                    side="long",
                    qty="100",
                    entry_price="150.00",
                    exit_price="151.00",
                    entry_at="2026-02-14T00:00:00.000000Z",
                    exit_at="2026-02-14T01:00:00.000000Z",
                    pnl="100.00",
                    duration_seconds=3600,
                )
            )
            session.commit()


class TestVersionDefault:
    """Test optimistic concurrency version column."""

    def test_order_state_version_default(self, session: Session) -> None:
        from app.models.order import OrderStateModel

        session.execute(
            sa.insert(OrderStateModel).values(
                local_id="ver-001",
                correlation_id="corr-001",
                symbol="AAPL",
                side="long",
                order_type="market",
                qty_requested="100",
                qty_filled="0",
                state="pending_submit",
                submit_attempts=0,
                created_at="2026-02-14T00:00:00.000000Z",
                updated_at="2026-02-14T00:00:00.000000Z",
            )
        )
        session.commit()

        row = session.execute(
            sa.select(OrderStateModel).where(OrderStateModel.local_id == "ver-001")
        ).scalar_one()
        assert row.version == 0


class TestSettingsOverride:
    """Test settings_override table operations."""

    def test_insert_and_read(self, session: Session) -> None:
        from app.models.backtest import SettingsOverrideModel

        session.execute(
            sa.insert(SettingsOverrideModel).values(
                key="risk.max_daily_loss_pct",
                value="0.05",
                updated_at="2026-02-14T00:00:00.000000Z",
            )
        )
        session.commit()

        row = session.execute(
            sa.select(SettingsOverrideModel).where(
                SettingsOverrideModel.key == "risk.max_daily_loss_pct"
            )
        ).scalar_one()
        assert row.value == "0.05"

    def test_upsert_update(self, session: Session) -> None:
        from app.models.backtest import SettingsOverrideModel

        session.execute(
            sa.insert(SettingsOverrideModel).values(
                key="log_level",
                value="INFO",
                updated_at="2026-02-14T00:00:00.000000Z",
            )
        )
        session.commit()

        session.execute(
            sa.update(SettingsOverrideModel)
            .where(SettingsOverrideModel.key == "log_level")
            .values(
                value="DEBUG",
                previous_value="INFO",
                updated_at="2026-02-14T01:00:00.000000Z",
            )
        )
        session.commit()

        row = session.execute(
            sa.select(SettingsOverrideModel).where(
                SettingsOverrideModel.key == "log_level"
            )
        ).scalar_one()
        assert row.value == "DEBUG"
        assert row.previous_value == "INFO"
