"""Shared broker utilities.

Centralized helpers used across all broker implementations.
"""

from __future__ import annotations

from decimal import Decimal


def to_decimal(value: float | str) -> Decimal:
    """Convert a float or string to Decimal safely.

    For string values (from REST APIs): Decimal(str_value) directly.
    For float values (from WebSocket): Decimal(str(float_value)) to avoid
    IEEE 754 precision issues.
    """
    if isinstance(value, str):
        return Decimal(value)
    return Decimal(str(value))
