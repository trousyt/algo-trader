"""Pydantic Settings configuration models.

4-tier config hierarchy (lowest to highest priority):
1. Pydantic defaults (in code below)
2. .env file (loaded by Pydantic Settings)
3. Environment variables (e.g., ALGO_RISK__MAX_DAILY_LOSS_PCT=0.05)
4. SQLite settings_override table (from web UI) — loaded at
   runtime via get_effective_value()
"""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_CANDLE_INTERVALS = frozenset({1, 2, 5, 10})
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
VALID_LOG_FORMATS = frozenset({"console", "json"})


class BrokerConfig(BaseModel):
    """Broker connection configuration."""

    provider: str = "alpaca"
    paper: bool = True
    feed: str = "iex"
    api_key: str = ""
    secret_key: str = ""


class RiskConfig(BaseModel):
    """Risk management parameters with validation bounds."""

    max_risk_per_trade_pct: Decimal = Field(
        default=Decimal("0.01"),
        ge=Decimal("0.001"),
        le=Decimal("0.05"),
    )
    max_risk_per_trade_abs: Decimal = Field(
        default=Decimal("500"),
        ge=Decimal("10"),
        le=Decimal("5000"),
    )
    max_position_pct: Decimal = Field(
        default=Decimal("0.05"),
        ge=Decimal("0.01"),
        le=Decimal("0.25"),
    )
    max_daily_loss_pct: Decimal = Field(
        default=Decimal("0.03"),
        ge=Decimal("0.01"),
        le=Decimal("0.10"),
    )
    max_open_positions: int = Field(default=5, ge=1, le=20)
    consecutive_loss_pause: int = Field(default=3, ge=2, le=10)


class VelezConfig(BaseModel):
    """Velez SMA convergence strategy parameters."""

    enabled: bool = True
    sma_fast: int = Field(default=20, ge=5, le=50)
    sma_slow: int = Field(default=200, ge=100, le=500)
    candle_interval_minutes: int = Field(default=2)
    tightness_threshold_pct: float = Field(default=2.0, ge=0.5, le=5.0)
    strong_candle_body_pct: float = Field(default=50.0, ge=30.0, le=80.0)
    stop_buffer_pct: Decimal = Field(
        default=Decimal("0.1"),
        ge=Decimal("0.05"),
        le=Decimal("1.0"),
    )
    stop_buffer_min: Decimal = Field(
        default=Decimal("0.02"),
        ge=Decimal("0.01"),
        le=Decimal("0.10"),
    )
    buy_stop_expiry_candles: int = Field(default=1, ge=1, le=5)
    max_run_candles: int = Field(default=3, ge=2, le=10)
    doji_threshold_pct: float = Field(default=10.0)

    @field_validator("candle_interval_minutes")
    @classmethod
    def validate_candle_interval(cls, v: int) -> int:
        if v not in VALID_CANDLE_INTERVALS:
            raise ValueError(
                f"candle_interval_minutes must be one of "
                f"{sorted(VALID_CANDLE_INTERVALS)}, got {v}"
            )
        return v


class WebConfig(BaseModel):
    """Web server configuration."""

    host: str = "127.0.0.1"
    port: int = 8000


class AppConfig(BaseSettings):
    """Top-level application configuration.

    Env var examples:
        ALGO_LOG_LEVEL=DEBUG
        ALGO_BROKER__API_KEY=your-key
        ALGO_RISK__MAX_DAILY_LOSS_PCT=0.05
        ALGO_WATCHLIST='["AAPL","TSLA"]'
    """

    model_config = SettingsConfigDict(
        env_prefix="ALGO_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    log_format: str = "console"
    broker: BrokerConfig = BrokerConfig()
    risk: RiskConfig = RiskConfig()
    velez: VelezConfig = VelezConfig()
    web: WebConfig = WebConfig()
    watchlist: list[str] = Field(
        default=["AAPL", "TSLA", "AMD", "NVDA", "META"],
    )
    db_path: str = "data/trading.db"
    db_busy_timeout_ms: int = 5000

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level must be one of {sorted(VALID_LOG_LEVELS)}, got {v}"
            )
        return v

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        v = v.lower()
        if v not in VALID_LOG_FORMATS:
            raise ValueError(
                f"log_format must be one of {sorted(VALID_LOG_FORMATS)}, got {v}"
            )
        return v

    @field_validator("watchlist")
    @classmethod
    def validate_watchlist(cls, v: list[str]) -> list[str]:
        if len(v) == 0:
            raise ValueError("Watchlist must not be empty")
        for symbol in v:
            if not re.match(r"^[A-Z]{1,5}$", symbol):
                raise ValueError(f"Invalid symbol: {symbol}")
        return v
