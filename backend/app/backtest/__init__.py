"""Backtesting engine — simulated fills + performance metrics."""

__all__ = [
    "BacktestConfig",
    "BacktestDataLoader",
    "BacktestError",
    "BacktestExecution",
    "BacktestMetrics",
    "BacktestMetricsData",
    "BacktestResult",
    "BacktestRunner",
    "BacktestTradeData",
    "Fill",
]

from app.backtest.config import BacktestConfig, BacktestError, BacktestTradeData
from app.backtest.data_loader import BacktestDataLoader
from app.backtest.executor import BacktestExecution, Fill
from app.backtest.metrics import BacktestMetrics, BacktestMetricsData
from app.backtest.runner import BacktestResult, BacktestRunner
