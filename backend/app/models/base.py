"""SQLAlchemy base, async engine setup, DecimalText type, and SQLite pragmas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import String, TypeDecorator

DEFAULT_BUSY_TIMEOUT_MS = 5000


class DecimalText(TypeDecorator[Decimal]):
    """Store Python Decimal as TEXT in SQLite for exact precision.

    All monetary values (prices, P&L, equity, position sizing) must use
    this type to avoid floating-point errors.
    """

    impl = String
    cache_ok = True

    def process_bind_param(
        self,
        value: Decimal | None,
        dialect: Any,
    ) -> str | None:
        if value is None:
            return None
        return str(value)

    def process_result_value(
        self,
        value: str | None,
        dialect: Any,
    ) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def set_sqlite_pragmas(
    dbapi_connection: Any,
    connection_record: Any,
) -> None:
    """Set SQLite pragmas on every new connection.

    Must be registered via @event.listens_for(engine, "connect") or
    called manually for each connection. SQLite pragmas are per-connection,
    not per-database, so they must be set every time.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def register_engine_events(engine: Engine) -> None:
    """Register SQLite pragma listener on an engine."""
    event.listen(engine, "connect", set_sqlite_pragmas)
