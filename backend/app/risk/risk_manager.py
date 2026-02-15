"""Risk manager facade -- orchestrates all pre-order checks.

Serializes access via asyncio.Lock to prevent concurrent signals
from bypassing limits.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.broker_adapter import BrokerAdapter
from app.config import RiskConfig
from app.models.order import OrderStateModel
from app.orders.types import TERMINAL_STATES, OrderRole, RiskApproval, Signal
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.position_sizer import PositionSizer

log = structlog.get_logger()


class RiskManager:
    """Orchestrates all pre-order checks.

    Checks in order (fail-fast):
    1. Circuit breaker: can_trade()?
    2. Open positions: count < max_open_positions?
    3. Account data: fetch from broker
    4. Position sizer: calculate qty
    5. Return RiskApproval
    """

    def __init__(
        self,
        risk_config: RiskConfig,
        broker: BrokerAdapter,
        circuit_breaker: CircuitBreaker,
        position_sizer: PositionSizer,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._config = risk_config
        self._broker = broker
        self._circuit_breaker = circuit_breaker
        self._sizer = position_sizer
        self._session_factory = session_factory
        self._lock = asyncio.Lock()

    async def approve(self, signal: Signal) -> RiskApproval:
        """Pre-order approval. Serialized via asyncio.Lock."""
        async with self._lock:
            return await self._approve_inner(signal)

    async def _approve_inner(self, signal: Signal) -> RiskApproval:
        """Inner approval logic (called under lock)."""
        zero = Decimal("0")

        # 1. Circuit breaker check
        can_trade, reason = self._circuit_breaker.can_trade()
        if not can_trade:
            log.info(
                "risk_rejected",
                symbol=signal.symbol,
                reason=reason,
            )
            return RiskApproval(approved=False, qty=zero, reason=reason)

        # 2. Open positions check
        open_count = await self._count_open_positions()
        if open_count >= self._config.max_open_positions:
            reason = (
                f"Max open positions reached: "
                f"{open_count}/{self._config.max_open_positions}"
            )
            log.info(
                "risk_rejected",
                symbol=signal.symbol,
                reason=reason,
            )
            return RiskApproval(approved=False, qty=zero, reason=reason)

        # 3. Fetch account data (no cache)
        account = await self._broker.get_account()

        # 4. Position sizing
        sizing = self._sizer.calculate(
            equity=account.equity,
            buying_power=account.buying_power,
            entry_price=signal.entry_price,
            stop_loss_price=signal.stop_loss_price,
        )

        if sizing.qty == zero:
            log.info(
                "risk_rejected",
                symbol=signal.symbol,
                reason=sizing.reason,
            )
            return RiskApproval(
                approved=False,
                qty=zero,
                reason=sizing.reason,
            )

        return RiskApproval(approved=True, qty=sizing.qty, reason="")

    async def _count_open_positions(self) -> int:
        """Count non-terminal entry orders in the database."""
        terminal_values = [s.value for s in TERMINAL_STATES]
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderStateModel.id).where(
                    OrderStateModel.order_role == OrderRole.ENTRY.value,
                    OrderStateModel.state.notin_(terminal_values),
                )
            )
            return len(result.all())
