"""Tests for broker protocols.

TDD: These tests are written BEFORE the implementation.

Note: runtime_checkable Protocol isinstance checks only verify that
the required method names exist as attributes — they do NOT verify
return types or async signatures. Real type safety comes from
mypy --strict, which the project already requires.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import runtime_checkable

from app.broker.broker_adapter import BrokerAdapter
from app.broker.data_provider import DataProvider
from app.broker.types import (
    AccountInfo,
    Bar,
    BracketOrderRequest,
    OrderRequest,
    OrderStatus,
    Position,
    Quote,
    TradeUpdate,
)


class TestDataProviderProtocol:
    """Test DataProvider is a runtime-checkable Protocol."""

    def test_data_provider_is_runtime_checkable(self) -> None:
        assert hasattr(DataProvider, "__protocol_attrs__") or runtime_checkable

    def test_data_provider_has_required_methods(self) -> None:
        """Verify all expected methods are defined in the protocol."""
        assert hasattr(DataProvider, "connect")
        assert hasattr(DataProvider, "disconnect")
        assert hasattr(DataProvider, "subscribe_bars")
        assert hasattr(DataProvider, "update_bar_subscription")
        assert hasattr(DataProvider, "get_historical_bars")
        assert hasattr(DataProvider, "get_latest_quote")

    def test_data_provider_has_context_manager(self) -> None:
        assert hasattr(DataProvider, "__aenter__")
        assert hasattr(DataProvider, "__aexit__")


class TestBrokerAdapterProtocol:
    """Test BrokerAdapter is a runtime-checkable Protocol."""

    def test_broker_adapter_has_required_methods(self) -> None:
        """Verify all expected methods are defined in the protocol."""
        assert hasattr(BrokerAdapter, "connect")
        assert hasattr(BrokerAdapter, "disconnect")
        assert hasattr(BrokerAdapter, "submit_order")
        assert hasattr(BrokerAdapter, "submit_bracket_order")
        assert hasattr(BrokerAdapter, "cancel_order")
        assert hasattr(BrokerAdapter, "replace_order")
        assert hasattr(BrokerAdapter, "get_order_status")
        assert hasattr(BrokerAdapter, "get_positions")
        assert hasattr(BrokerAdapter, "get_account")
        assert hasattr(BrokerAdapter, "get_open_orders")
        assert hasattr(BrokerAdapter, "get_recent_orders")
        assert hasattr(BrokerAdapter, "subscribe_trade_updates")

    def test_broker_adapter_has_context_manager(self) -> None:
        assert hasattr(BrokerAdapter, "__aenter__")
        assert hasattr(BrokerAdapter, "__aexit__")


class TestProtocolSatisfaction:
    """Test that minimal implementations satisfy the protocols.

    Note: isinstance checks on Protocols only verify method names exist,
    not that signatures match. Full type checking is done by mypy.
    """

    def test_minimal_data_provider_satisfies_protocol(self) -> None:
        """A class with all required methods passes isinstance check."""

        class MinimalDataProvider:
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def subscribe_bars(
                self, symbols: list[str],
            ) -> AsyncIterator[Bar]: ...
            async def update_bar_subscription(
                self, symbols: list[str],
            ) -> None: ...
            async def get_historical_bars(
                self,
                symbol: str,
                count: int,
                timeframe: str = "1Min",
            ) -> list[Bar]: ...
            async def get_latest_quote(self, symbol: str) -> Quote: ...
            async def __aenter__(self) -> MinimalDataProvider: ...
            async def __aexit__(self, *args: object) -> None: ...

        assert isinstance(MinimalDataProvider(), DataProvider)

    def test_minimal_broker_adapter_satisfies_protocol(self) -> None:
        """A class with all required methods passes isinstance check."""

        class MinimalBrokerAdapter:
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def submit_order(
                self, order: OrderRequest,
            ) -> OrderStatus: ...
            async def submit_bracket_order(
                self, bracket: BracketOrderRequest,
            ) -> OrderStatus: ...
            async def cancel_order(
                self, broker_order_id: str,
            ) -> None: ...
            async def replace_order(
                self,
                broker_order_id: str,
                qty: Decimal | None = None,
                limit_price: Decimal | None = None,
                stop_price: Decimal | None = None,
            ) -> OrderStatus: ...
            async def get_order_status(
                self, broker_order_id: str,
            ) -> OrderStatus: ...
            async def get_positions(self) -> list[Position]: ...
            async def get_account(self) -> AccountInfo: ...
            async def get_open_orders(self) -> list[OrderStatus]: ...
            async def get_recent_orders(
                self, since_hours: int = 24,
            ) -> list[OrderStatus]: ...
            async def subscribe_trade_updates(
                self,
            ) -> AsyncIterator[TradeUpdate]: ...
            async def __aenter__(self) -> MinimalBrokerAdapter: ...
            async def __aexit__(self, *args: object) -> None: ...

        assert isinstance(MinimalBrokerAdapter(), BrokerAdapter)

    def test_incomplete_class_does_not_satisfy_data_provider(self) -> None:
        """A class missing methods fails isinstance check."""

        class IncompleteProvider:
            async def connect(self) -> None: ...

        assert not isinstance(IncompleteProvider(), DataProvider)

    def test_incomplete_class_does_not_satisfy_broker_adapter(self) -> None:
        """A class missing methods fails isinstance check."""

        class IncompleteBroker:
            async def connect(self) -> None: ...

        assert not isinstance(IncompleteBroker(), BrokerAdapter)
