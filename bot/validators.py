from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional


VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_MARKET"}

MIN_QUANTITY = Decimal("0.000001") 
MIN_PRICE = Decimal("0.01")


def validate_symbol(symbol: str) -> str:
    """Return upper-cased, stripped symbol or raise ValueError."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol must not be empty.")
    if not symbol.isalnum():
        raise ValueError(
            f"Symbol '{symbol}' contains invalid characters – expected letters and digits only (e.g. BTCUSDT)."
        )
    if len(symbol) < 5:
        raise ValueError(f"Symbol '{symbol}' is too short – did you mean e.g. BTCUSDT or ETHUSDT?")
    return symbol


def validate_side(side: str) -> str:
    """Return upper-cased side or raise ValueError."""
    side = side.strip().upper()
    if side not in VALID_SIDES:
        raise ValueError(f"Side must be one of {sorted(VALID_SIDES)}, got '{side}'.")
    return side


def validate_order_type(order_type: str) -> str:
    """Return upper-cased order type or raise ValueError."""
    order_type = order_type.strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ValueError(
            f"Order type must be one of {sorted(VALID_ORDER_TYPES)}, got '{order_type}'."
        )
    return order_type


def validate_quantity(quantity: object) -> Decimal:
    """Parse and validate order quantity."""
    try:
        qty = Decimal(str(quantity))
    except InvalidOperation:
        raise ValueError(f"Quantity '{quantity}' is not a valid number.")
    if qty <= 0:
        raise ValueError(f"Quantity must be greater than 0, got {qty}.")
    if qty < MIN_QUANTITY:
        raise ValueError(f"Quantity {qty} is below the minimum allowed ({MIN_QUANTITY}).")
    return qty


def validate_price(
    price: Optional[object],
    order_type: str,
) -> Optional[Decimal]:
    """
    Validate limit price.

    Required for LIMIT orders.
    Must be positive when supplied.
    Ignored (returns None) for MARKET / STOP_MARKET.
    """
    order_type = order_type.upper()
    needs_price = order_type == "LIMIT"

    if price is None or str(price).strip() == "":
        if needs_price:
            raise ValueError(f"Price is required for {order_type} orders.")
        return None

    try:
        p = Decimal(str(price))
    except InvalidOperation:
        raise ValueError(f"Price '{price}' is not a valid number.")
    if p <= 0:
        raise ValueError(f"Price must be greater than 0, got {p}.")
    if p < MIN_PRICE:
        raise ValueError(f"Price {p} is below the minimum allowed ({MIN_PRICE}).")
    return p


def validate_stop_price(
    stop_price: Optional[object],
    order_type: str,
) -> Optional[Decimal]:
    """
    Validate stop trigger price.

    Required for STOP_MARKET orders.
    Ignored for MARKET / LIMIT.
    """
    order_type = order_type.upper()
    needs_stop = order_type == "STOP_MARKET"

    if stop_price is None or str(stop_price).strip() == "":
        if needs_stop:
            raise ValueError("stop_price is required for STOP_MARKET orders.")
        return None

    try:
        sp = Decimal(str(stop_price))
    except InvalidOperation:
        raise ValueError(f"stop_price '{stop_price}' is not a valid number.")
    if sp <= 0:
        raise ValueError(f"stop_price must be greater than 0, got {sp}.")
    return sp


def validate_all(
    symbol: str,
    side: str,
    order_type: str,
    quantity: object,
    price: Optional[object] = None,
    stop_price: Optional[object] = None,
) -> dict:
    """
    Run all validators and return a clean, typed parameter dict.

    Raises ``ValueError`` on the first validation failure encountered.

    Returns
    -------
    dict with keys: symbol, side, order_type, quantity (Decimal),
                    price (Decimal | None), stop_price (Decimal | None)
    """
    v_symbol = validate_symbol(symbol)
    v_side = validate_side(side)
    v_type = validate_order_type(order_type)
    v_qty = validate_quantity(quantity)
    v_price = validate_price(price, v_type)
    v_stop = validate_stop_price(stop_price, v_type)
    return {
        "symbol": v_symbol,
        "side": v_side,
        "order_type": v_type,
        "quantity": v_qty,
        "price": v_price,
        "stop_price": v_stop,
    }
