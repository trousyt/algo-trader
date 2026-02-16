"""Click CLI commands for algo-trader."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import click
import httpx

from app.config import AppConfig

if TYPE_CHECKING:
    from app.backtest.config import BacktestConfig
    from app.backtest.runner import BacktestResult


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
@click.option("--strategy", default="velez", help="Strategy name (default: velez).")
@click.option(
    "--symbols", required=True, help="Comma-separated symbols (e.g. AAPL,TSLA)."
)
@click.option(
    "--start-date",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date (YYYY-MM-DD).",
)
@click.option(
    "--end-date",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="End date (YYYY-MM-DD).",
)
@click.option(
    "--capital", default="25000", type=str, help="Initial capital (default: 25000)."
)
@click.option(
    "--slippage", default="0.01", type=str, help="Slippage per share (default: 0.01)."
)
def backtest(
    strategy: str,
    symbols: str,
    start_date: datetime,
    end_date: datetime,
    capital: str,
    slippage: str,
) -> None:
    """Run a strategy backtest against historical data."""
    from app.backtest.config import BacktestConfig, BacktestError

    try:
        bt_config = BacktestConfig(
            strategy=strategy,
            symbols=[s.strip().upper() for s in symbols.split(",")],
            start_date=start_date.date(),
            end_date=end_date.date(),
            initial_capital=Decimal(capital),
            slippage_per_share=Decimal(slippage),
        )
    except (ValueError, Exception) as e:
        raise click.ClickException(str(e)) from e

    try:
        result = asyncio.run(_run_backtest(bt_config))
    except BacktestError as e:
        raise click.ClickException(str(e)) from e
    except Exception as e:
        raise click.ClickException(f"Backtest failed: {e}") from e

    _print_backtest_results(result, bt_config)


async def _run_backtest(bt_config: BacktestConfig) -> BacktestResult:
    """Run the backtest with proper DB session."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.backtest.runner import BacktestRunner

    app_config = AppConfig()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{app_config.db_path}",
        echo=False,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    runner = BacktestRunner(
        config=bt_config,
        app_config=app_config,
        session_factory=session_factory,
    )
    return await runner.run()


def _print_backtest_results(
    result: BacktestResult,
    config: BacktestConfig,
) -> None:
    """Format and print backtest results to CLI."""
    m = result.metrics

    click.echo(f"\nBacktest Results: {config.strategy}")
    click.echo(f"Period: {config.start_date} to {config.end_date}")
    click.echo(f"Symbols: {', '.join(config.symbols)}")
    click.echo(f"Initial Capital: ${config.initial_capital:,.2f}")

    click.echo("\nPerformance:")
    click.echo(f"  Total Return:    ${m.total_return:,.2f} ({m.total_return_pct:.2f}%)")
    click.echo(f"  Final Equity:    ${m.final_equity:,.2f}")
    click.echo(f"  Sharpe Ratio:    {m.sharpe_ratio:.2f}")
    click.echo(f"  Max Drawdown:    -{m.max_drawdown_pct:.2f}%")
    click.echo(f"  Profit Factor:   {m.profit_factor:.2f}")

    click.echo("\nTrades:")
    click.echo(f"  Total:           {m.total_trades}")
    if m.total_trades > 0:
        click.echo(f"  Winners:         {m.winning_trades} ({m.win_rate * 100:.1f}%)")
        click.echo(
            f"  Losers:          {m.losing_trades} ({(1 - m.win_rate) * 100:.1f}%)"
        )
        click.echo(f"  Avg Win:         ${m.avg_win:,.2f}")
        click.echo(f"  Avg Loss:        -${abs(m.avg_loss):,.2f}")
        click.echo(f"  Largest Win:     ${m.largest_win:,.2f}")
        click.echo(f"  Largest Loss:    -${abs(m.largest_loss):,.2f}")
        avg_mins = m.avg_trade_duration // 60
        click.echo(f"  Avg Duration:    {avg_mins} min")

    click.echo(f"\nResults saved to database (run_id: {result.run_id})")


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
