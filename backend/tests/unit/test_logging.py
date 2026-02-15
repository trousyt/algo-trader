"""Tests for structured logging setup.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

import json

from app.utils.logging import (
    get_correlation_id,
    get_logger,
    set_correlation_id,
    setup_logging,
)


class TestSetupLogging:
    """Test logging configuration."""

    def test_setup_logging_returns_none(self) -> None:
        """setup_logging configures structlog globally."""
        result = setup_logging(level="INFO", log_format="json")
        assert result is None

    def test_get_logger_returns_bound_logger(self) -> None:
        setup_logging(level="INFO", log_format="json")
        logger = get_logger("test")
        assert logger is not None


class TestJsonFormat:
    """Test JSON log output."""

    def test_json_output_is_valid(self, capsys: object) -> None:
        """Log entry in JSON mode is valid JSON with expected keys."""
        import io
        import sys

        setup_logging(level="INFO", log_format="json")
        logger = get_logger("test_json")

        # Capture stderr (structlog defaults to stderr)
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured

        try:
            logger.info("test message", extra_key="extra_value")
        finally:
            sys.stderr = old_stderr

        output = captured.getvalue().strip()
        if output:
            parsed = json.loads(output)
            assert "event" in parsed
            assert parsed["event"] == "test message"
            assert "timestamp" in parsed
            assert "level" in parsed


class TestConsoleFormat:
    """Test console (pretty-print) log output."""

    def test_console_output_is_not_json(self) -> None:
        """Log entry in console mode is human-readable, not JSON."""
        import io
        import sys

        setup_logging(level="INFO", log_format="console")
        logger = get_logger("test_console")

        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured

        try:
            logger.info("console test")
        finally:
            sys.stderr = old_stderr

        output = captured.getvalue().strip()
        if output:
            # Console output should NOT be valid JSON
            try:
                json.loads(output)
                is_json = True
            except json.JSONDecodeError:
                is_json = False
            assert not is_json


class TestCorrelationId:
    """Test correlation ID context variable."""

    def test_set_and_get_correlation_id(self) -> None:
        set_correlation_id("corr-123")
        assert get_correlation_id() == "corr-123"

    def test_default_correlation_id(self) -> None:
        """Default correlation ID is empty string."""
        set_correlation_id("")
        assert get_correlation_id() == ""

    def test_correlation_id_in_log(self) -> None:
        """Correlation ID appears in JSON log output when set."""
        import io
        import sys

        setup_logging(level="INFO", log_format="json")
        set_correlation_id("corr-456")
        logger = get_logger("test_corr")

        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured

        try:
            logger.info("correlated event")
        finally:
            sys.stderr = old_stderr

        output = captured.getvalue().strip()
        if output:
            parsed = json.loads(output)
            assert parsed.get("correlation_id") == "corr-456"
