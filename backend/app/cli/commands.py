"""Click CLI commands for algo-trader."""

from __future__ import annotations

import sys

import click
import httpx

from app.config import AppConfig


@click.group()
def cli() -> None:
    """Algo-trader: algorithmic trading engine for US equities."""


@cli.command()
def start() -> None:
    """Start the trading engine."""
    click.echo("Starting algo-trader engine...")
    click.echo("Not yet implemented.")


@cli.command()
def stop() -> None:
    """Stop the trading engine."""
    config = AppConfig()
    url = f"http://{config.web.host}:{config.web.port}/api/shutdown"
    try:
        httpx.post(url, timeout=5.0)
        click.echo("Shutdown signal sent.")
    except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
        click.echo("Engine is not running (could not connect).")
        sys.exit(1)


@cli.command()
def status() -> None:
    """Show engine status."""
    config = AppConfig()
    url = f"http://{config.web.host}:{config.web.port}/api/dashboard"
    try:
        resp = httpx.get(url, timeout=5.0)
        click.echo(resp.text)
    except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
        click.echo("Engine is not running (could not connect).")
        sys.exit(1)


@cli.command()
@click.option("--strategy", required=True, help="Strategy name to backtest.")
@click.option("--symbols", required=True, help="Comma-separated symbols.")
@click.option("--start-date", required=True, help="Backtest start date (YYYY-MM-DD).")
@click.option("--end-date", required=True, help="Backtest end date (YYYY-MM-DD).")
def backtest(
    strategy: str,
    symbols: str,
    start_date: str,
    end_date: str,
) -> None:
    """Run a strategy backtest."""
    click.echo(
        f"Backtest not yet implemented. "
        f"Strategy={strategy}, symbols={symbols}, "
        f"start={start_date}, end={end_date}"
    )


@cli.command()
def config() -> None:
    """Show current configuration."""
    cfg = AppConfig()

    click.echo("=== Algo-Trader Configuration ===\n")

    click.echo(f"Log Level:    {cfg.log_level}")
    click.echo(f"Log Format:   {cfg.log_format}")
    click.echo(f"DB Path:      {cfg.db_path}")
    click.echo("")

    click.echo("[Broker]")
    click.echo(f"  Provider:   {cfg.broker.provider}")
    click.echo(f"  Paper:      {cfg.broker.paper}")
    click.echo(f"  Feed:       {cfg.broker.feed}")
    click.echo("")

    click.echo("[Risk]")
    click.echo(f"  Max Risk/Trade:      {cfg.risk.max_risk_per_trade_pct}")
    click.echo(f"  Max Daily Loss:      {cfg.risk.max_daily_loss_pct}")
    click.echo(f"  Max Open Positions:  {cfg.risk.max_open_positions}")
    click.echo("")

    click.echo(f"Watchlist:    {', '.join(cfg.watchlist)}")
