"""Broker abstraction layer.

Re-exports all public types, protocols, and errors for convenient imports:
    from app.broker import Bar, DataProvider, BrokerAdapter, BrokerError
"""

from app.broker.broker_adapter import BrokerAdapter
from app.broker.data_provider import DataProvider
from app.broker.errors import (
    BrokerAPIError,
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerNotConnectedError,
    BrokerTimeoutError,
)
from app.broker.types import (
    AccountInfo,
    Bar,
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    TimeInForce,
    TradeEventType,
    TradeUpdate,
)

__all__ = [
    "AccountInfo",
    "Bar",
    "BracketOrderRequest",
    "BrokerAPIError",
    "BrokerAdapter",
    "BrokerAuthError",
    "BrokerConnectionError",
    "BrokerError",
    "BrokerNotConnectedError",
    "BrokerOrderStatus",
    "BrokerTimeoutError",
    "DataProvider",
    "OrderRequest",
    "OrderStatus",
    "OrderType",
    "Position",
    "Quote",
    "Side",
    "TimeInForce",
    "TradeEventType",
    "TradeUpdate",
]
