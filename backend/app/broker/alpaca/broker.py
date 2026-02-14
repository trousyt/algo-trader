"""AlpacaBrokerAdapter — order execution via alpaca-py SDK.

Bridges the sync/blocking alpaca-py SDK to our async architecture:
- Trade update streaming runs in a dedicated daemon thread
- REST order/position/account calls run in a ThreadPoolExecutor
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Self

import structlog
from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest, ReplaceOrderRequest
from alpaca.trading.stream import TradingStream

from app.broker.alpaca.mappers import (
    alpaca_account_to_account_info,
    alpaca_order_to_order_status,
    alpaca_position_to_position,
    alpaca_trade_update_to_trade_update,
    bracket_request_to_alpaca,
    order_request_to_alpaca,
)
from app.broker.errors import (
    BrokerAPIError,
    BrokerAuthError,
    BrokerConnectionError,
    BrokerNotConnectedError,
)
from app.broker.types import (
    AccountInfo,
    BracketOrderRequest,
    OrderRequest,
    OrderStatus,
    Position,
    TradeUpdate,
)

logger = structlog.get_logger()


class AlpacaBrokerAdapter:
    """BrokerAdapter implementation backed by the Alpaca SDK.

    Uses TradingClient for REST operations and TradingStream
    for real-time trade update events.
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._trading_client: TradingClient | None = None
        self._stream: TradingStream | None = None
        self._ws_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        # Trade update queue is UNBOUNDED — fill events must never be dropped
        self._trade_queue: asyncio.Queue[TradeUpdate] = asyncio.Queue()
        self._connected_event = threading.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._subscribed = False

    async def connect(self) -> None:
        """Establish connection to Alpaca trading services."""
        async with self._lifecycle_lock:
            if self._connected_event.is_set():
                logger.warning("AlpacaBrokerAdapter already connected")
                return

            api_key = self._config.api_key
            secret_key = self._config.secret_key

            if not api_key:
                raise BrokerAuthError(
                    "API key is required. "
                    "Set ALGO_BROKER__API_KEY environment variable.",
                )
            if not secret_key:
                raise BrokerAuthError(
                    "API secret key is required. "
                    "Set ALGO_BROKER__SECRET_KEY environment variable.",
                )

            self._trading_client = TradingClient(
                api_key,
                secret_key,
                paper=self._config.paper,
            )

            # Validate credentials via lightweight API call
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._trading_client.get_account,
                )
            except APIError as e:
                if hasattr(e, "status_code") and e.status_code in (401, 403):
                    raise BrokerAuthError(
                        f"Invalid API credentials: {e}",
                    ) from e
                raise BrokerConnectionError(
                    f"Failed to validate credentials: {e}",
                ) from e

            self._stream = TradingStream(
                api_key,
                secret_key,
                paper=self._config.paper,
            )
            self._executor = ThreadPoolExecutor(max_workers=4)
            self._main_loop = asyncio.get_event_loop()
            self._connected_event.set()

            logger.info("AlpacaBrokerAdapter connected")

    async def disconnect(self) -> None:
        """Tear down connections and release resources."""
        async with self._lifecycle_lock:
            if not self._connected_event.is_set():
                return

            if self._stream is not None:
                self._stream.stop()

            if self._ws_thread is not None and self._ws_thread.is_alive():
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            self._ws_thread.join,
                            5.0,
                        ),
                        timeout=10.0,
                    )
                except TimeoutError:
                    logger.critical(
                        "Trade stream thread did not terminate",
                        thread=self._ws_thread.name,
                    )

            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
                self._executor = None

            self._connected_event.clear()
            self._subscribed = False
            logger.info("AlpacaBrokerAdapter disconnected")

    def _require_connected(self) -> None:
        """Raise if not connected."""
        if not self._connected_event.is_set():
            raise BrokerNotConnectedError(
                "Not connected. Call connect() first.",
            )

    def _handle_api_error(self, e: APIError) -> None:
        """Translate Alpaca APIError to our error hierarchy."""
        status = getattr(e, "status_code", 0)
        if status in (401, 403):
            raise BrokerAuthError(f"Authentication failed: {e}") from e
        raise BrokerAPIError(status, str(e)) from e

    async def submit_order(self, order: OrderRequest) -> OrderStatus:
        """Submit a single order."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        alpaca_req = order_request_to_alpaca(order)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._trading_client.submit_order,
                alpaca_req,
            )
        except APIError as e:
            self._handle_api_error(e)
        return alpaca_order_to_order_status(result)

    async def submit_bracket_order(
        self,
        bracket: BracketOrderRequest,
    ) -> OrderStatus:
        """Submit a bracket order (entry + stop-loss + optional take-profit)."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        alpaca_req = bracket_request_to_alpaca(bracket)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._trading_client.submit_order,
                alpaca_req,
            )
        except APIError as e:
            self._handle_api_error(e)
        return alpaca_order_to_order_status(result)

    async def cancel_order(self, broker_order_id: str) -> None:
        """Cancel an open order by broker order ID."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        try:
            await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._trading_client.cancel_order_by_id,
                broker_order_id,
            )
        except APIError as e:
            self._handle_api_error(e)

    async def replace_order(
        self,
        broker_order_id: str,
        qty: Decimal | None = None,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderStatus:
        """Modify an existing order (atomic replace, not cancel-resubmit)."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        replace_req = ReplaceOrderRequest(
            qty=int(qty) if qty is not None else None,
            limit_price=float(limit_price) if limit_price is not None else None,
            stop_price=float(stop_price) if stop_price is not None else None,
        )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._trading_client.replace_order_by_id,
                broker_order_id,
                replace_req,
            )
        except APIError as e:
            self._handle_api_error(e)
        return alpaca_order_to_order_status(result)

    async def get_order_status(self, broker_order_id: str) -> OrderStatus:
        """Get the current status of a specific order."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._trading_client.get_order_by_id,
                broker_order_id,
            )
        except APIError as e:
            self._handle_api_error(e)
        return alpaca_order_to_order_status(result)

    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        result = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._trading_client.get_all_positions,
        )
        return [alpaca_position_to_position(p) for p in result]

    async def get_account(self) -> AccountInfo:
        """Get account summary."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        result = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._trading_client.get_account,
        )
        return alpaca_account_to_account_info(result)

    async def get_open_orders(self) -> list[OrderStatus]:
        """Get all currently open orders."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        result = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._trading_client.get_orders,
            request,
        )
        return [alpaca_order_to_order_status(o) for o in result]

    async def get_recent_orders(
        self,
        since_hours: int = 24,
    ) -> list[OrderStatus]:
        """Get orders from the last N hours."""
        self._require_connected()
        assert self._trading_client is not None
        assert self._executor is not None

        after = datetime.now(tz=UTC) - timedelta(hours=since_hours)
        request = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            after=after,
        )
        result = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._trading_client.get_orders,
            request,
        )
        return [alpaca_order_to_order_status(o) for o in result]

    async def subscribe_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        """Start streaming trade update events."""
        self._require_connected()
        if self._subscribed:
            raise BrokerConnectionError(
                "subscribe_trade_updates() already called.",
            )

        self._subscribed = True
        assert self._stream is not None
        self._stream.subscribe_trade_updates(self._trade_update_callback)

        self._ws_thread = threading.Thread(
            target=self._run_trade_stream,
            name="alpaca-trade-stream",
            daemon=True,
        )
        self._ws_thread.start()

        return self._trade_iterator()

    async def _trade_iterator(self) -> AsyncIterator[TradeUpdate]:
        """Yield trade updates from the internal queue."""
        while self._connected_event.is_set():
            try:
                update = await asyncio.wait_for(
                    self._trade_queue.get(),
                    timeout=1.0,
                )
                yield update
            except TimeoutError:
                continue

    async def _trade_update_callback(self, alpaca_update: Any) -> None:
        """Trade update callback — runs in the SDK's internal event loop."""
        update = alpaca_trade_update_to_trade_update(alpaca_update)
        if update is not None and self._main_loop is not None:
            self._main_loop.call_soon_threadsafe(
                self._trade_queue.put_nowait,
                update,
            )

    def _run_trade_stream(self) -> None:
        """Target for the trade stream thread. Blocking call."""
        try:
            assert self._stream is not None
            self._stream.run()
        except Exception:
            logger.exception("Trade stream thread died unexpectedly")

    async def __aenter__(self) -> Self:
        """Connect on context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Disconnect on context manager exit."""
        try:
            await self.disconnect()
        except Exception:
            logger.exception("Error during disconnect in __aexit__")
