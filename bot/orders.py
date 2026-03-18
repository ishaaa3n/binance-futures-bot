"""
Order placement logic.

Translates validated parameters into Binance API calls via BinanceClient.
Each function is responsible for:
  1. Building the correct parameter dict for its order type
  2. Logging before and after the API call
  3. Returning the raw Binance response dict
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from .client import BinanceClient, BinanceAPIError

logger = logging.getLogger("trading_bot.orders")


def _fmt(value: Decimal) -> str:
    """
    Serialize a Decimal to a string without unnecessary trailing zeros.

    Examples
    --------
    >>> _fmt(Decimal("0.00100"))
    '0.001'
    >>> _fmt(Decimal("60000.0"))
    '60000'
    """
    return format(value.normalize(), "f")


# ── Individual order functions ────────────────────────────────────────────────


def place_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: Decimal,
) -> dict:
    """Submit a MARKET order (no price required)."""
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": _fmt(quantity),
    }
    logger.info(
        "Placing MARKET order | symbol=%s side=%s qty=%s",
        symbol, side, quantity,
    )
    response = client.place_order(params)
    logger.info(
        "MARKET order response | orderId=%s status=%s executedQty=%s avgPrice=%s",
        response.get("orderId"),
        response.get("status"),
        response.get("executedQty"),
        response.get("avgPrice"),
    )
    return response


def place_limit_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    time_in_force: str = "GTC",
) -> dict:
    """Submit a LIMIT order with a specified price and time-in-force."""
    params = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "quantity": _fmt(quantity),
        "price": _fmt(price),
        "timeInForce": time_in_force,
    }
    logger.info(
        "Placing LIMIT order | symbol=%s side=%s qty=%s price=%s tif=%s",
        symbol, side, quantity, price, time_in_force,
    )
    response = client.place_order(params)
    logger.info(
        "LIMIT order response | orderId=%s status=%s",
        response.get("orderId"),
        response.get("status"),
    )
    return response


def place_stop_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: Decimal,
    stop_price: Decimal,
    time_in_force: str = "GTC",
) -> dict:
    """
    Submit a STOP_MARKET conditional order via the Algo Service endpoint.
    Validates trigger price direction against live mark price before submitting.

    Since 2025-12-09, Binance requires all conditional orders (STOP_MARKET,
    TAKE_PROFIT_MARKET, etc.) to be placed via POST /fapi/v1/algoOrder
    instead of the standard /fapi/v1/order endpoint.

    Raises
    ------
    ValueError        – if stop_price direction is invalid for the given side
    BinanceAPIError   – if Binance rejects the order
    BinanceNetworkError – on connectivity failures
    """
    mark = Decimal(str(client.get_mark_price(symbol)))
    if side == "BUY" and stop_price <= mark:
        raise ValueError(
            f"BUY STOP_MARKET trigger {stop_price} must be above current price {mark}."
        )
    if side == "SELL" and stop_price >= mark:
        raise ValueError(
            f"SELL STOP_MARKET trigger {stop_price} must be below current price {mark}."
        )

    params = {
        "algoType": "CONDITIONAL",
        "symbol": symbol,
        "side": side,
        "type": "STOP_MARKET",
        "quantity": _fmt(quantity),
        "triggerPrice": _fmt(stop_price),
        "workingType": "CONTRACT_PRICE",
        "priceProtect": "FALSE",
        "timeInForce": time_in_force,
    }
    logger.info(
        "Placing STOP_MARKET algo order | symbol=%s side=%s qty=%s triggerPrice=%s",
        symbol, side, quantity, stop_price,
    )
    try:
        response = client.place_algo_order(params)
    except BinanceAPIError as e:
        logger.error(
            "STOP_MARKET order failed | symbol=%s side=%s triggerPrice=%s error=%s",
            symbol, side, stop_price, e,
        )
        raise
    logger.info(
        "STOP_MARKET algo order response | algoId=%s algoStatus=%s",
        response.get("algoId"),
        response.get("algoStatus"),
    )
    return response


# ── Dispatch router ───────────────────────────────────────────────────────────


def dispatch_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    order_type: str,
    quantity: Decimal,
    price: Optional[Decimal] = None,
    stop_price: Optional[Decimal] = None,
    time_in_force: str = "GTC",
) -> dict:
    """
    Single entry-point: route to the appropriate order function based on type.

    Parameters
    ----------
    client       : Authenticated BinanceClient instance
    symbol       : e.g. "BTCUSDT"
    side         : "BUY" or "SELL"
    order_type   : "MARKET", "LIMIT", or "STOP_MARKET"
    quantity     : Order quantity (Decimal)
    price        : Limit price (required for LIMIT)
    stop_price   : Trigger price (required for STOP_MARKET)
    time_in_force: "GTC" | "IOC" | "FOK"  (LIMIT only, defaults to GTC for STOP_MARKET)

    Returns
    -------
    dict — raw Binance API response

    Raises
    ------
    ValueError        – if required fields are missing or stop_price direction is invalid
    BinanceAPIError   – if Binance rejects the order
    BinanceNetworkError – on connectivity failures
    """
    if order_type == "MARKET":
        return place_market_order(client, symbol, side, quantity)

    if order_type == "LIMIT":
        if price is None:
            raise ValueError("price is required for LIMIT orders.")
        return place_limit_order(client, symbol, side, quantity, price, time_in_force)

    if order_type == "STOP_MARKET":
        if stop_price is None:
            raise ValueError("stop_price is required for STOP_MARKET orders.")
        return place_stop_market_order(client, symbol, side, quantity, stop_price, time_in_force)

    raise ValueError(f"Unsupported order type: {order_type}")