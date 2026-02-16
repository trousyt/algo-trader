"""Shared test fixtures for algo-trader."""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def alpaca_config() -> Any:
    """Load Alpaca config from environment variables.

    Skips the test if API keys are not set.
    """
    api_key = os.environ.get("ALGO_BROKER__API_KEY", "")
    secret_key = os.environ.get("ALGO_BROKER__SECRET_KEY", "")

    if not api_key or not secret_key:
        pytest.skip(
            "Alpaca API keys not set. "
            "Set ALGO_BROKER__API_KEY and ALGO_BROKER__SECRET_KEY.",
        )

    return SimpleNamespace(
        api_key=api_key,
        secret_key=secret_key,
        paper=True,
        feed="iex",
    )


@pytest.fixture
async def data_provider(
    alpaca_config: Any,
) -> AsyncIterator[Any]:
    """Create and connect an AlpacaDataProvider for integration tests."""
    from app.broker.alpaca.data import AlpacaDataProvider

    provider = AlpacaDataProvider(alpaca_config)
    await provider.connect()
    try:
        yield provider
    finally:
        await provider.disconnect()


@pytest.fixture
async def broker_adapter(
    alpaca_config: Any,
) -> AsyncIterator[Any]:
    """Create and connect an AlpacaBrokerAdapter for integration tests.

    Cleans up open orders on teardown.
    """
    from app.broker.alpaca.broker import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(alpaca_config)
    await adapter.connect()
    try:
        yield adapter
    finally:
        # Clean up: cancel all open orders
        try:
            open_orders = await adapter.get_open_orders()
            for order in open_orders:
                with contextlib.suppress(Exception):
                    await adapter.cancel_order(order.broker_order_id)
        except Exception:
            pass
        await adapter.disconnect()
