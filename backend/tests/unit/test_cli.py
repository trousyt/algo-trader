"""Tests for CLI commands.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from app.cli.commands import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestCliHelp:
    """Test CLI help output."""

    def test_cli_help_shows_commands(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output
        assert "backtest" in result.output
        assert "config" in result.output


class TestStartCommand:
    """Test the start command."""

    def test_start_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["start", "--help"])
        assert result.exit_code == 0


class TestStopCommand:
    """Test the stop command."""

    def test_stop_engine_not_running(self, runner: CliRunner) -> None:
        """Stop when engine not running prints friendly error."""
        result = runner.invoke(cli, ["stop"])
        assert result.exit_code == 1
        out = result.output.lower()
        assert "not running" in out or "could not connect" in out


class TestStatusCommand:
    """Test the status command."""

    def test_status_engine_not_running(self, runner: CliRunner) -> None:
        """Status when engine not running prints friendly error."""
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        out = result.output.lower()
        assert "not running" in out or "could not connect" in out


class TestBacktestCommand:
    """Test the backtest command."""

    def test_backtest_help_shows_options(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["backtest", "--help"])
        assert result.exit_code == 0
        assert "--strategy" in result.output
        assert "--symbols" in result.output
        assert "--start-date" in result.output
        assert "--end-date" in result.output
        assert "--capital" in result.output
        assert "--slippage" in result.output

    def test_backtest_missing_symbols_fails(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["backtest", "--start-date", "2026-01-01", "--end-date", "2026-02-01"],
        )
        assert result.exit_code != 0

    def test_backtest_invalid_strategy_fails(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "backtest",
                "--strategy", "nonexistent",
                "--symbols", "AAPL",
                "--start-date", "2026-01-01",
                "--end-date", "2026-02-01",
            ],
        )
        assert result.exit_code != 0


class TestConfigCommand:
    """Test the config command."""

    def test_config_shows_defaults(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        # Should show key config values
        assert "broker" in result.output.lower()
        assert "risk" in result.output.lower()
        assert "watchlist" in result.output.lower()

    def test_config_shows_env_override(self, runner: CliRunner) -> None:
        with patch.dict("os.environ", {"ALGO_LOG_LEVEL": "DEBUG"}):
            result = runner.invoke(cli, ["config"])
            assert result.exit_code == 0
            assert "DEBUG" in result.output
