"""Tests for configuration system.

TDD: These tests are written BEFORE the implementation.
"""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import AppConfig, RiskConfig, VelezConfig


class TestDefaultConfig:
    """Test that default configuration loads correctly."""

    def test_default_config_loads(self) -> None:
        """AppConfig() with no env vars produces valid defaults."""
        config = AppConfig()
        assert config.broker.provider == "alpaca"
        assert config.broker.paper is True
        assert config.risk.max_open_positions == 5
        assert config.velez.sma_fast == 20
        assert config.web.port == 8000
        assert config.log_level == "INFO"
        assert config.log_format == "console"

    def test_broker_paper_default_true(self) -> None:
        config = AppConfig()
        assert config.broker.paper is True

    def test_default_watchlist(self) -> None:
        config = AppConfig()
        assert config.watchlist == ["AAPL", "TSLA", "AMD", "NVDA", "META"]

    def test_default_db_path(self) -> None:
        config = AppConfig()
        assert config.db_path == "data/trading.db"

    def test_default_db_busy_timeout(self) -> None:
        config = AppConfig()
        assert config.db_busy_timeout_ms == 5000


class TestDecimalFields:
    """Test that monetary config values are Decimal, not float."""

    def test_risk_fields_are_decimal(self) -> None:
        config = AppConfig()
        assert isinstance(config.risk.max_risk_per_trade_pct, Decimal)
        assert isinstance(config.risk.max_risk_per_trade_abs, Decimal)
        assert isinstance(config.risk.max_position_pct, Decimal)
        assert isinstance(config.risk.max_daily_loss_pct, Decimal)

    def test_velez_signal_fields_are_float(self) -> None:
        config = AppConfig()
        assert isinstance(config.velez.tightness_threshold_pct, float)
        assert isinstance(config.velez.strong_candle_body_pct, float)
        assert isinstance(config.velez.doji_threshold_pct, float)

    def test_velez_money_fields_are_decimal(self) -> None:
        config = AppConfig()
        assert isinstance(config.velez.stop_buffer_pct, Decimal)
        assert isinstance(config.velez.stop_buffer_min, Decimal)


class TestRiskValidation:
    """Test risk parameter bounds validation."""

    def test_max_risk_per_trade_too_high(self) -> None:
        with pytest.raises(ValidationError):
            RiskConfig(max_risk_per_trade_pct=Decimal("0.1"))

    def test_max_risk_per_trade_too_low(self) -> None:
        with pytest.raises(ValidationError):
            RiskConfig(max_risk_per_trade_pct=Decimal("0.0001"))

    def test_max_risk_per_trade_at_upper_bound(self) -> None:
        config = RiskConfig(max_risk_per_trade_pct=Decimal("0.05"))
        assert config.max_risk_per_trade_pct == Decimal("0.05")

    def test_max_risk_per_trade_at_lower_bound(self) -> None:
        config = RiskConfig(max_risk_per_trade_pct=Decimal("0.001"))
        assert config.max_risk_per_trade_pct == Decimal("0.001")

    def test_max_daily_loss_too_high(self) -> None:
        with pytest.raises(ValidationError):
            RiskConfig(max_daily_loss_pct=Decimal("0.15"))

    def test_max_open_positions_too_high(self) -> None:
        with pytest.raises(ValidationError):
            RiskConfig(max_open_positions=25)

    def test_max_open_positions_too_low(self) -> None:
        with pytest.raises(ValidationError):
            RiskConfig(max_open_positions=0)

    def test_consecutive_loss_pause_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RiskConfig(consecutive_loss_pause=1)
        with pytest.raises(ValidationError):
            RiskConfig(consecutive_loss_pause=11)


class TestWatchlistValidation:
    """Test watchlist symbol validation."""

    def test_invalid_symbol_lowercase(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(watchlist=["aapl"])

    def test_invalid_symbol_too_long(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(watchlist=["TOOLONG"])

    def test_empty_watchlist_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(watchlist=[])

    def test_valid_single_char_symbol(self) -> None:
        config = AppConfig(watchlist=["F"])
        assert config.watchlist == ["F"]

    def test_valid_five_char_symbol(self) -> None:
        config = AppConfig(watchlist=["GOOGL"])
        assert config.watchlist == ["GOOGL"]


class TestVelezValidation:
    """Test Velez strategy config validation."""

    def test_candle_interval_invalid(self) -> None:
        with pytest.raises(ValidationError):
            VelezConfig(candle_interval_minutes=3)

    def test_candle_interval_valid_values(self) -> None:
        for interval in [1, 2, 5, 10]:
            config = VelezConfig(candle_interval_minutes=interval)
            assert config.candle_interval_minutes == interval

    def test_sma_fast_bounds(self) -> None:
        with pytest.raises(ValidationError):
            VelezConfig(sma_fast=4)
        with pytest.raises(ValidationError):
            VelezConfig(sma_fast=51)

    def test_sma_slow_bounds(self) -> None:
        with pytest.raises(ValidationError):
            VelezConfig(sma_slow=99)
        with pytest.raises(ValidationError):
            VelezConfig(sma_slow=501)


class TestLogLevelValidation:
    """Test log level validation."""

    def test_invalid_log_level(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(log_level="TRACE")

    def test_valid_log_levels(self) -> None:
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = AppConfig(log_level=level)
            assert config.log_level == level

    def test_invalid_log_format(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(log_format="xml")

    def test_valid_log_formats(self) -> None:
        for fmt in ["console", "json"]:
            config = AppConfig(log_format=fmt)
            assert config.log_format == fmt


class TestEnvVarOverride:
    """Test environment variable override behavior."""

    def test_env_var_overrides_default(self) -> None:
        with patch.dict(os.environ, {"ALGO_LOG_LEVEL": "DEBUG"}):
            config = AppConfig()
            assert config.log_level == "DEBUG"

    def test_nested_env_var_override(self) -> None:
        with patch.dict(os.environ, {"ALGO_BROKER__PAPER": "false"}):
            config = AppConfig()
            assert config.broker.paper is False

    def test_risk_env_var_override(self) -> None:
        with patch.dict(os.environ, {"ALGO_RISK__MAX_DAILY_LOSS_PCT": "0.05"}):
            config = AppConfig()
            assert config.risk.max_daily_loss_pct == Decimal("0.05")

    def test_watchlist_env_var_json(self) -> None:
        with patch.dict(os.environ, {"ALGO_WATCHLIST": '["SPY","QQQ"]'}):
            config = AppConfig()
            assert config.watchlist == ["SPY", "QQQ"]

    def test_web_port_env_var(self) -> None:
        with patch.dict(os.environ, {"ALGO_WEB__PORT": "9000"}):
            config = AppConfig()
            assert config.web.port == 9000
