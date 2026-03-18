#!/usr/bin/env python3
"""
cli.py — Binance Futures Testnet Trading Bot

Entry point for placing orders via the command line.

Usage examples
--------------
  # Market BUY
  python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001

  # Limit SELL
  python cli.py --symbol BTCUSDT --side SELL --type LIMIT --quantity 0.001 --price 60000

  # Stop-Market BUY (bonus)
  python cli.py --symbol BTCUSDT --side BUY --type STOP_MARKET --quantity 0.001 --stop-price 55000

  # Dry run (validate only, no order placed)
  python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001 --dry-run

  # JSON output for scripting
  python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001 --json

  # Debug logging to console
  python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001 --log-level DEBUG

Credentials
-----------
  Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables (or use a .env file),
  or pass --api-key / --api-secret on the command line.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from decimal import Decimal
from typing import Optional

# Load .env file if python-dotenv is available (best-effort)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from bot.client import BinanceClient, BinanceAPIError, BinanceNetworkError
from bot.logging_config import setup_logging
from bot.orders import dispatch_order
from bot.validators import validate_all

logger = logging.getLogger("trading_bot")

# ── Exit codes ────────────────────────────────────────────────────────────────

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1   # missing / invalid credentials or config
EXIT_VALIDATION_ERROR = 2   # bad user input
EXIT_API_ERROR = 3      # Binance API error
EXIT_NETWORK_ERROR = 4  # connectivity failure
EXIT_UNEXPECTED = 5     # any other unexpected error

# ── Formatting helpers ────────────────────────────────────────────────────────

_DIVIDER = "─" * 54
_HEADER = "━" * 54


def _section(title: str) -> None:
    print(f"\n{_HEADER}")
    print(f"  {title}")
    print(_HEADER)


def _row(label: str, value: object) -> None:
    if value is not None and str(value) not in ("", "0", "0.00000000"):
        print(f"  {label:<22} {value}")


def print_request_summary(params: dict) -> None:
    """Print a human-readable summary of the order about to be placed."""
    _section("ORDER REQUEST SUMMARY")
    _row("Symbol:", params["symbol"])
    _row("Side:", params["side"])
    _row("Type:", params["order_type"])
    _row("Quantity:", params["quantity"])
    if params.get("price"):
        _row("Price:", params["price"])
    if params.get("stop_price"):
        _row("Stop Price:", params["stop_price"])
    print(_DIVIDER)


def print_order_response(resp: dict) -> None:
    """Print the important fields from the Binance order response."""
    _section("ORDER RESPONSE DETAILS")
    _row("Order ID:", resp.get("orderId"))
    _row("Client Order ID:", resp.get("clientOrderId"))
    _row("Status:", resp.get("status"))
    _row("Symbol:", resp.get("symbol"))
    _row("Side:", resp.get("side"))
    _row("Type:", resp.get("type"))
    _row("Orig Qty:", resp.get("origQty"))
    _row("Executed Qty:", resp.get("executedQty"))
    _row("Avg Price:", resp.get("avgPrice"))
    _row("Price:", resp.get("price"))
    _row("Stop Price:", resp.get("stopPrice"))
    _row("Time in Force:", resp.get("timeInForce"))
    _row("Reduce Only:", resp.get("reduceOnly"))
    print(_DIVIDER)


# ── Argument parsing ──────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading_bot",
        description="Place orders on Binance Futures Testnet (USDT-M).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python cli.py --symbol BTCUSDT --side BUY  --type MARKET     --quantity 0.001
  python cli.py --symbol BTCUSDT --side SELL --type LIMIT       --quantity 0.001 --price 60000
  python cli.py --symbol BTCUSDT --side BUY  --type STOP_MARKET --quantity 0.001 --stop-price 55000
  python cli.py --symbol ETHUSDT --side BUY  --type LIMIT       --quantity 0.01  --price 3000 --dry-run
        """,
    )

    # ── Credentials (optional; fallback to env vars) ─────────────────────────
    creds = parser.add_argument_group("credentials (default: env vars)")
    creds.add_argument(
        "--api-key",
        metavar="KEY",
        default=None,
        help="Binance API key (overrides BINANCE_API_KEY env var)",
    )
    creds.add_argument(
        "--api-secret",
        metavar="SECRET",
        default=None,
        help="Binance API secret (overrides BINANCE_API_SECRET env var)",
    )

    # ── Order parameters ─────────────────────────────────────────────────────
    order = parser.add_argument_group("order parameters")
    order.add_argument(
        "--symbol", "-s",
        required=True,
        metavar="SYMBOL",
        help="Trading pair (e.g. BTCUSDT, ETHUSDT)",
    )
    order.add_argument(
        "--side",
        required=True,
        choices=["BUY", "SELL"],
        metavar="SIDE",
        help="BUY or SELL",
    )
    order.add_argument(
        "--type", "-t",
        dest="order_type",
        required=True,
        choices=["MARKET", "LIMIT", "STOP_MARKET"],
        metavar="TYPE",
        help="MARKET | LIMIT | STOP_MARKET",
    )
    order.add_argument(
        "--quantity", "-q",
        required=True,
        metavar="QTY",
        help="Order quantity (e.g. 0.001 for BTC)",
    )
    order.add_argument(
        "--price", "-p",
        default=None,
        metavar="PRICE",
        help="Limit price — required for LIMIT orders",
    )
    order.add_argument(
        "--stop-price",
        default=None,
        metavar="STOP_PRICE",
        help="Stop trigger price — required for STOP_MARKET orders",
    )
    order.add_argument(
        "--tif",
        default="GTC",
        choices=["GTC", "IOC", "FOK"],
        metavar="TIF",
        help="Time-in-force for LIMIT orders: GTC (default) | IOC | FOK",
    )

    # ── Behaviour flags ───────────────────────────────────────────────────────
    flags = parser.add_argument_group("behaviour")
    flags.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview the order without actually placing it",
    )
    flags.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print the raw Binance JSON response and nothing else",
    )
    flags.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        metavar="LEVEL",
        help="Console log level (default: INFO; file always logs DEBUG)",
    )

    return parser


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # ── 1. Set up logging ────────────────────────────────────────────────────
    setup_logging(log_level=args.log_level)
    logger.info(
        "Trading bot started | args=%s",
        {
            "symbol": args.symbol,
            "side": args.side,
            "order_type": args.order_type,
            "quantity": args.quantity,
            "price": args.price,
            "stop_price": args.stop_price,
            "tif": args.tif,
            "log_level": args.log_level,
            "dry_run": args.dry_run,
            "output_json": args.output_json,
        },
    )

    # ── 2. Validate inputs ───────────────────────────────────────────────────
    try:
        validated = validate_all(
            symbol=args.symbol,
            side=args.side,
            order_type=args.order_type,
            quantity=args.quantity,
            price=args.price,
            stop_price=args.stop_price,
        )
    except ValueError as exc:
        logger.error("Validation failed: %s", exc)
        print(f"\n✗  Validation error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION_ERROR

    # ── 3. Print request summary (unless --json flag suppresses it) ──────────
    if not args.output_json:
        print_request_summary(validated)

    # ── 4. Dry-run exit ───────────────────────────────────────────────────────
    if args.dry_run:
        logger.info("Dry-run mode — order not placed.")
        print("\n  [DRY RUN] Validation passed. No order was placed.")
        print(_DIVIDER)
        return EXIT_OK

    # ── 5. Resolve credentials ───────────────────────────────────────────────
    api_key: Optional[str] = args.api_key or os.getenv("BINANCE_API_KEY")
    # Accept both BINANCE_API_SECRET and BINANCE_SECRET_KEY
    api_secret: Optional[str] = (
        args.api_secret
        or os.getenv("BINANCE_API_SECRET")
        or os.getenv("BINANCE_SECRET_KEY")
    )

    if not api_key or not api_secret:
        msg = (
            "API credentials are missing.\n"
            "  Set BINANCE_API_KEY and BINANCE_API_SECRET (or BINANCE_SECRET_KEY)\n"
            "  environment variables, or use --api-key / --api-secret flags.\n"
            "  See .env.example for a template."
        )
        logger.error("Missing API credentials.")
        print(f"\n✗  {msg}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # ── 6. Initialise client ─────────────────────────────────────────────────
    try:
        client = BinanceClient(api_key=api_key, api_secret=api_secret)
    except ValueError as exc:
        logger.error("Client initialisation failed: %s", exc)
        print(f"\n✗  Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # ── 7. Place order ────────────────────────────────────────────────────────
    try:
        response = dispatch_order(
            client=client,
            symbol=validated["symbol"],
            side=validated["side"],
            order_type=validated["order_type"],
            quantity=validated["quantity"],
            price=validated.get("price"),
            stop_price=validated.get("stop_price"),
            time_in_force=args.tif,
        )
    except BinanceAPIError as exc:
        logger.error("Binance API error: code=%s msg=%s", exc.code, exc.message)
        print(
            f"\n✗  Binance API error (code {exc.code}): {exc.message}",
            file=sys.stderr,
        )
        return EXIT_API_ERROR
    except BinanceNetworkError as exc:
        logger.error("Network failure: %s", exc)
        print(f"\n✗  Network error: {exc}", file=sys.stderr)
        return EXIT_NETWORK_ERROR
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        print(f"\n✗  Unexpected error: {exc}", file=sys.stderr)
        return EXIT_UNEXPECTED

    # ── 8. Output results ─────────────────────────────────────────────────────
    logger.info("Order placed successfully | orderId=%s", response.get("orderId"))

    if args.output_json:
        print(json.dumps(response, indent=2))
    else:
        print_order_response(response)
        print(f"\n✔  Order placed successfully!\n")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
