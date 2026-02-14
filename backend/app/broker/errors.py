"""Broker error hierarchy.

All broker-related exceptions inherit from BrokerError, enabling
clean exception handling at the adapter boundary.
"""

from __future__ import annotations


class BrokerError(Exception):
    """Base exception for all broker-related errors."""


class BrokerConnectionError(BrokerError):
    """Connection failures, thread death, WebSocket down."""


class BrokerAuthError(BrokerError):
    """Invalid or missing API credentials (HTTP 401/403)."""


class BrokerAPIError(BrokerError):
    """REST API errors after SDK retries (4xx/5xx).

    Stores the HTTP status code and error message from the broker.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Broker API error {status_code}: {message}")


class BrokerTimeoutError(BrokerError):
    """Request timeout when communicating with the broker."""


class BrokerNotConnectedError(BrokerError):
    """Method called before connect() was called."""
