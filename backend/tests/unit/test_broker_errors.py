"""Tests for broker error hierarchy.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from app.broker.errors import (
    BrokerAPIError,
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerNotConnectedError,
    BrokerTimeoutError,
)


class TestBrokerErrorHierarchy:
    """Test that all errors inherit from BrokerError."""

    def test_broker_connection_error_is_broker_error(self) -> None:
        assert issubclass(BrokerConnectionError, BrokerError)

    def test_broker_auth_error_is_broker_error(self) -> None:
        assert issubclass(BrokerAuthError, BrokerError)

    def test_broker_api_error_is_broker_error(self) -> None:
        assert issubclass(BrokerAPIError, BrokerError)

    def test_broker_timeout_error_is_broker_error(self) -> None:
        assert issubclass(BrokerTimeoutError, BrokerError)

    def test_broker_not_connected_error_is_broker_error(self) -> None:
        assert issubclass(BrokerNotConnectedError, BrokerError)


class TestBrokerAPIError:
    """Test BrokerAPIError stores status code and message."""

    def test_status_code_and_message(self) -> None:
        err = BrokerAPIError(422, "Unprocessable Entity")
        assert err.status_code == 422
        assert err.message == "Unprocessable Entity"
        assert "422" in str(err)
        assert "Unprocessable Entity" in str(err)

    def test_status_code_5xx(self) -> None:
        err = BrokerAPIError(500, "Internal Server Error")
        assert err.status_code == 500


class TestBrokerAuthError:
    """Test BrokerAuthError includes helpful instructions."""

    def test_auth_error_message(self) -> None:
        err = BrokerAuthError(
            "Invalid API credentials. "
            "Set ALGO_BROKER__API_KEY and ALGO_BROKER__SECRET_KEY."
        )
        assert "ALGO_BROKER__API_KEY" in str(err)

    def test_auth_error_is_catchable_as_broker_error(self) -> None:
        try:
            raise BrokerAuthError("bad creds")
        except BrokerError:
            pass  # Should be caught


class TestBrokerConnectionError:
    """Test BrokerConnectionError includes endpoint context."""

    def test_connection_error_message(self) -> None:
        err = BrokerConnectionError("WebSocket thread died unexpectedly")
        assert "WebSocket" in str(err)


class TestBrokerNotConnectedError:
    """Test BrokerNotConnectedError message."""

    def test_not_connected_error(self) -> None:
        err = BrokerNotConnectedError("Not connected. Call connect() first.")
        assert "connect()" in str(err)
