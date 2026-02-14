"""Alpaca SDK type to domain type converters.

All float-to-Decimal conversion happens here — this is the Decimal boundary.
Alpaca REST returns strings for monetary fields; WebSocket returns floats.
"""

from __future__ import annotations

from typing import Any

from alpaca.trading.enums import OrderClass, OrderSide
from alpaca.trading.enums import TimeInForce as AlpacaTIF
from alpaca.trading.requests import (
    LimitOrderRequest as AlpacaLimitOrder,
)
from alpaca.trading.requests import (
    MarketOrderRequest as AlpacaMarketOrder,
)
from alpaca.trading.requests import (
    StopLimitOrderRequest as AlpacaStopLimitOrder,
)
from alpaca.trading.requests import (
    StopLossRequest,
    TakeProfitRequest,
)
from alpaca.trading.requests import (
    StopOrderRequest as AlpacaStopOrder,
)
from alpaca.trading.requests import (
    TrailingStopOrderRequest as AlpacaTrailingStopOrder,
)

from app.broker.types import (
    AccountInfo,
    Bar,
    BracketOrderRequest,
    BrokerOrderStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TimeInForce,
    TradeEventType,
    TradeUpdate,
)
from app.broker.utils import to_decimal

# Trade events we pass through to the engine.
# Others (pending_new, pending_replace, restated) are informational noise.
_ACTIONABLE_EVENTS: dict[str, TradeEventType] = {
    "new": TradeEventType.NEW,
    "accepted": TradeEventType.ACCEPTED,
    "fill": TradeEventType.FILL,
    "partial_fill": TradeEventType.PARTIAL_FILL,
    "canceled": TradeEventType.CANCELED,
    "expired": TradeEventType.EXPIRED,
    "rejected": TradeEventType.REJECTED,
    "replaced": TradeEventType.REPLACED,
    "pending_cancel": TradeEventType.PENDING_CANCEL,
}

# Alpaca side string -> our Side enum
_POSITION_SIDE_MAP: dict[str, Side] = {
    "long": Side.BUY,
    "short": Side.SELL,
}

# Alpaca order side string -> our Side enum
_ORDER_SIDE_MAP: dict[str, Side] = {
    "buy": Side.BUY,
    "sell": Side.SELL,
}

# Alpaca order type string -> our OrderType enum
_ORDER_TYPE_MAP: dict[str, OrderType] = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP,
    "stop_limit": OrderType.STOP_LIMIT,
    "trailing_stop": OrderType.TRAILING_STOP,
}

# Alpaca order status string -> our BrokerOrderStatus enum
_ORDER_STATUS_MAP: dict[str, BrokerOrderStatus] = {
    "new": BrokerOrderStatus.NEW,
    "accepted": BrokerOrderStatus.ACCEPTED,
    "filled": BrokerOrderStatus.FILLED,
    "partially_filled": BrokerOrderStatus.PARTIALLY_FILLED,
    "canceled": BrokerOrderStatus.CANCELED,
    "expired": BrokerOrderStatus.EXPIRED,
    "rejected": BrokerOrderStatus.REJECTED,
    "pending_cancel": BrokerOrderStatus.PENDING_CANCEL,
    "replaced": BrokerOrderStatus.REPLACED,
}

# Our Side enum -> Alpaca OrderSide
_SIDE_TO_ALPACA: dict[Side, OrderSide] = {
    Side.BUY: OrderSide.BUY,
    Side.SELL: OrderSide.SELL,
}

# Our TimeInForce -> Alpaca TimeInForce
_TIF_TO_ALPACA: dict[TimeInForce, AlpacaTIF] = {
    TimeInForce.DAY: AlpacaTIF.DAY,
    TimeInForce.GTC: AlpacaTIF.GTC,
    TimeInForce.IOC: AlpacaTIF.IOC,
}


def alpaca_bar_to_bar(alpaca_bar: Any) -> Bar:
    """Convert an Alpaca SDK bar to a domain Bar.

    WebSocket bars have float OHLC values; REST bars may have strings.
    """
    return Bar(
        symbol=alpaca_bar.symbol,
        timestamp=alpaca_bar.timestamp,
        open=to_decimal(alpaca_bar.open),
        high=to_decimal(alpaca_bar.high),
        low=to_decimal(alpaca_bar.low),
        close=to_decimal(alpaca_bar.close),
        volume=int(alpaca_bar.volume),
    )


def alpaca_position_to_position(alpaca_pos: Any) -> Position:
    """Convert an Alpaca SDK position to a domain Position.

    REST positions return string values for monetary fields.
    """
    return Position(
        symbol=alpaca_pos.symbol,
        qty=to_decimal(alpaca_pos.qty),
        side=_POSITION_SIDE_MAP[alpaca_pos.side],
        avg_entry_price=to_decimal(alpaca_pos.avg_entry_price),
        market_value=to_decimal(alpaca_pos.market_value),
        unrealized_pl=to_decimal(alpaca_pos.unrealized_pl),
        unrealized_pl_pct=to_decimal(alpaca_pos.unrealized_plpc),
    )


def alpaca_account_to_account_info(alpaca_acct: Any) -> AccountInfo:
    """Convert an Alpaca SDK account to a domain AccountInfo."""
    return AccountInfo(
        equity=to_decimal(alpaca_acct.equity),
        cash=to_decimal(alpaca_acct.cash),
        buying_power=to_decimal(alpaca_acct.buying_power),
        portfolio_value=to_decimal(alpaca_acct.portfolio_value),
        day_trade_count=int(alpaca_acct.daytrade_count),
        pattern_day_trader=bool(alpaca_acct.pattern_day_trader),
    )


def alpaca_order_to_order_status(alpaca_order: Any) -> OrderStatus:
    """Convert an Alpaca SDK order to a domain OrderStatus."""
    filled_avg = (
        to_decimal(alpaca_order.filled_avg_price)
        if alpaca_order.filled_avg_price is not None
        else None
    )
    return OrderStatus(
        broker_order_id=str(alpaca_order.id),
        symbol=alpaca_order.symbol,
        side=_ORDER_SIDE_MAP[alpaca_order.side],
        qty=to_decimal(alpaca_order.qty),
        order_type=_ORDER_TYPE_MAP[alpaca_order.type],
        status=_ORDER_STATUS_MAP[alpaca_order.status],
        filled_qty=to_decimal(alpaca_order.filled_qty),
        filled_avg_price=filled_avg,
        submitted_at=alpaca_order.submitted_at,
    )


def alpaca_trade_update_to_trade_update(
    update: Any,
) -> TradeUpdate | None:
    """Convert an Alpaca SDK trade update to a domain TradeUpdate.

    Returns None for filtered (non-actionable) events like
    PENDING_NEW, PENDING_REPLACE, RESTATED.
    """
    event_type = _ACTIONABLE_EVENTS.get(update.event)
    if event_type is None:
        return None

    order = update.order
    filled_avg = (
        to_decimal(order.filled_avg_price)
        if order.filled_avg_price is not None
        else None
    )

    return TradeUpdate(
        event=event_type,
        order_id=str(order.id),
        symbol=order.symbol,
        side=_ORDER_SIDE_MAP[order.side],
        qty=to_decimal(order.qty),
        filled_qty=to_decimal(order.filled_qty),
        filled_avg_price=filled_avg,
        timestamp=update.timestamp,
    )


def order_request_to_alpaca(
    req: OrderRequest,
) -> Any:
    """Convert a domain OrderRequest to an Alpaca SDK order request."""
    side = _SIDE_TO_ALPACA[req.side]
    tif = _TIF_TO_ALPACA[req.time_in_force]
    qty = float(req.qty)

    if req.order_type == OrderType.MARKET:
        return AlpacaMarketOrder(
            symbol=req.symbol,
            qty=qty,
            side=side,
            time_in_force=tif,
        )
    elif req.order_type == OrderType.LIMIT:
        return AlpacaLimitOrder(
            symbol=req.symbol,
            qty=qty,
            side=side,
            time_in_force=tif,
            limit_price=float(req.limit_price) if req.limit_price else None,
        )
    elif req.order_type == OrderType.STOP:
        return AlpacaStopOrder(
            symbol=req.symbol,
            qty=qty,
            side=side,
            time_in_force=tif,
            stop_price=float(req.stop_price) if req.stop_price else None,
        )
    elif req.order_type == OrderType.STOP_LIMIT:
        return AlpacaStopLimitOrder(
            symbol=req.symbol,
            qty=qty,
            side=side,
            time_in_force=tif,
            limit_price=float(req.limit_price) if req.limit_price else None,
            stop_price=float(req.stop_price) if req.stop_price else None,
        )
    elif req.order_type == OrderType.TRAILING_STOP:
        kwargs: dict[str, Any] = {
            "symbol": req.symbol,
            "qty": qty,
            "side": side,
            "time_in_force": tif,
        }
        if req.trail_percent is not None:
            kwargs["trail_percent"] = float(req.trail_percent)
        if req.trail_price is not None:
            kwargs["trail_price"] = float(req.trail_price)
        return AlpacaTrailingStopOrder(**kwargs)
    else:
        msg = f"Unsupported order type: {req.order_type}"
        raise ValueError(msg)


def bracket_request_to_alpaca(req: BracketOrderRequest) -> Any:
    """Convert a domain BracketOrderRequest to an Alpaca SDK bracket order."""
    side = _SIDE_TO_ALPACA[req.side]
    tif = _TIF_TO_ALPACA[req.time_in_force]

    stop_loss = StopLossRequest(
        stop_price=float(req.stop_loss_price),
    )

    take_profit = (
        TakeProfitRequest(limit_price=float(req.take_profit_price))
        if req.take_profit_price is not None
        else None
    )

    if req.order_type == OrderType.MARKET:
        return AlpacaMarketOrder(
            symbol=req.symbol,
            qty=float(req.qty),
            side=side,
            time_in_force=tif,
            order_class=OrderClass.BRACKET,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
    elif req.order_type == OrderType.LIMIT:
        return AlpacaLimitOrder(
            symbol=req.symbol,
            qty=float(req.qty),
            side=side,
            time_in_force=tif,
            limit_price=float(req.limit_price) if req.limit_price else None,
            order_class=OrderClass.BRACKET,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
    else:
        msg = f"Unsupported bracket order type: {req.order_type}"
        raise ValueError(msg)
