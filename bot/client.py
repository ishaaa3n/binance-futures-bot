"""
Binance Futures Testnet REST client.

Handles:
  - HMAC-SHA256 request signing
  - Timestamp / recvWindow injection
  - HTTP request execution with automatic retries
  - Structured DEBUG logging of every request and response
  - Mapping HTTP / API errors to typed exceptions

Testnet base URL: https://testnet.binancefuture.com
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("trading_bot.client")

TESTNET_BASE_URL = "https://demo-fapi.binance.com"
DEFAULT_TIMEOUT = 10
RECV_WINDOW = 5_000  # ms — how long a signed request stays valid

# Retry on transient server-side errors only (never on 4xx client errors).
# 429 is excluded here and handled manually to respect the Retry-After header.
_RETRY_STATUS_CODES = {500, 502, 503, 504}


# ── Custom exceptions ────────────────────────────────────────────────────────


class BinanceAPIError(Exception):
    """Raised when Binance returns a non-2xx or error JSON payload."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Binance API error {code}: {message}")


class BinanceRateLimitError(BinanceAPIError):
    """
    Raised on HTTP 429 (rate limit exceeded).

    Callers should inspect ``retry_after`` (seconds) before retrying.
    """

    def __init__(self, retry_after: Optional[int] = None) -> None:
        self.retry_after = retry_after
        msg = "Rate limit exceeded."
        if retry_after is not None:
            msg += f" Retry after {retry_after}s."
        super().__init__(code=429, message=msg)


class BinanceNetworkError(Exception):
    """Raised on connection, timeout, or SSL failures."""


# ── Session factory ──────────────────────────────────────────────────────────


def _build_session(total_retries: int = 3) -> requests.Session:
    """Return a requests.Session with exponential-backoff retry on 5xx errors.

    429 rate-limit responses are NOT retried automatically — they are surfaced
    as BinanceRateLimitError so callers can respect the Retry-After header.
    """
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=0.5,
        status_forcelist=list(_RETRY_STATUS_CODES),
        allowed_methods=["GET", "POST", "DELETE"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ── Client ───────────────────────────────────────────────────────────────────


class BinanceClient:
    """
    Thin, authenticated wrapper around the Binance USDT-M Futures Testnet REST API.

    Parameters
    ----------
    api_key    : Testnet API key
    api_secret : Testnet API secret
    base_url   : Override for testing / different environments
    timeout    : Per-request timeout in seconds
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = TESTNET_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret must not be empty.")
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = _build_session()
        self._session.headers.update(
            {
                "X-MBX-APIKEY": self._api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )
        logger.info("BinanceClient initialised | base_url=%s", self._base_url)

    # ── Public API surface ───────────────────────────────────────────────────

    def get_server_time(self) -> int:
        """Return Binance server time in milliseconds (unsigned)."""
        return self._get("/fapi/v1/time", signed=False)["serverTime"]

    def get_account(self) -> Dict[str, Any]:
        """Return futures account info (balances, positions)."""
        return self._get("/fapi/v2/account", signed=True)

    def get_mark_price(self, symbol: str) -> float:
        """
        Return the current mark price for a symbol (unsigned, no auth required).

        Used by place_stop_market_order to validate trigger price direction
        before submitting, preventing Binance error -2021.
        """
        data = self._get(
            "/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            signed=False,
        )
        return float(data["markPrice"])

    def place_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a new futures order. ``params`` must be pre-validated."""
        return self._post("/fapi/v1/order", params=params, signed=True)

    def get_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Fetch the current state of a specific order."""
        return self._get(
            "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )

    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel an open order."""
        logger.info("Cancelling orderId=%s symbol=%s", order_id, symbol)
        return self._delete(
            "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )

    def place_algo_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a conditional (algo) order via the Algo Service endpoint.

        Required since 2025-12-09 for STOP_MARKET, TAKE_PROFIT_MARKET,
        STOP, TAKE_PROFIT, and TRAILING_STOP_MARKET order types.
        Endpoint: POST /fapi/v1/algoOrder
        """
        return self._post("/fapi/v1/algoOrder", params=params, signed=True)

    # ── Private HTTP helpers ─────────────────────────────────────────────────

    @staticmethod
    def _timestamp() -> int:
        return int(time.time() * 1000)

    def _sign(self, query_string: str) -> str:
        return hmac.new(self._api_secret, query_string.encode(), hashlib.sha256).hexdigest()

    def _inject_auth(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add timestamp, recvWindow, and HMAC signature to params in-place.

        Any previously injected signature is removed first to prevent
        double-signing (e.g. if this dict is accidentally reused).
        """
        params.pop("signature", None)  # guard against double-signing
        params["timestamp"] = self._timestamp()
        params["recvWindow"] = RECV_WINDOW
        params["signature"] = self._sign(urlencode(params))
        return params

    def _safe_log_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of params with the signature redacted for log safety."""
        return {k: ("***" if k == "signature" else v) for k, v in params.items()}

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        if signed:
            self._inject_auth(params)
        url = self._base_url + path
        logger.debug("GET  %s | params=%s", path, self._safe_log_params(params))
        try:
            resp = self._session.get(url, params=params, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error on GET %s: %s", path, exc)
            raise BinanceNetworkError(f"Connection failed: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout on GET %s: %s", path, exc)
            raise BinanceNetworkError(f"Request timed out: {exc}") from exc
        return self._handle_response(resp)

    def _post(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        if signed:
            self._inject_auth(params)
        url = self._base_url + path
        logger.debug("POST %s | body=%s", path, self._safe_log_params(params))
        try:
            resp = self._session.post(url, data=params, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error on POST %s: %s", path, exc)
            raise BinanceNetworkError(f"Connection failed: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout on POST %s: %s", path, exc)
            raise BinanceNetworkError(f"Request timed out: {exc}") from exc
        return self._handle_response(resp)

    def _delete(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        if signed:
            self._inject_auth(params)
        url = self._base_url + path
        logger.debug("DELETE %s | params=%s", path, self._safe_log_params(params))
        try:
            resp = self._session.delete(url, params=params, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error on DELETE %s: %s", path, exc)
            raise BinanceNetworkError(f"Connection failed: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout on DELETE %s: %s", path, exc)
            raise BinanceNetworkError(f"Request timed out: {exc}") from exc
        return self._handle_response(resp)

    @staticmethod
    def _handle_response(resp: requests.Response) -> Any:
        """Parse the response, log it, and raise typed exceptions on error."""
        logger.debug("← HTTP %s | %s", resp.status_code, resp.text[:500])

        # Handle 429 rate limit explicitly — respect Retry-After header
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            retry_after_int = int(retry_after) if retry_after and retry_after.isdigit() else None
            logger.warning(
                "Rate limit hit (HTTP 429) | Retry-After=%s",
                retry_after_int,
            )
            raise BinanceRateLimitError(retry_after=retry_after_int)

        try:
            data = resp.json()
        except ValueError:
            logger.error(
                "Non-JSON response (HTTP %s): %s", resp.status_code, resp.text[:200]
            )
            raise BinanceAPIError(resp.status_code, f"Non-JSON response: {resp.text[:100]}")

        # Binance signals errors with a negative 'code' integer in the JSON body
        if isinstance(data, dict) and "code" in data and int(data["code"]) < 0:
            logger.error(
                "Binance error | code=%s msg=%s", data["code"], data.get("msg")
            )
            raise BinanceAPIError(code=int(data["code"]), message=data.get("msg", "Unknown error"))

        if not resp.ok:
            raise BinanceAPIError(code=resp.status_code, message=str(data))

        return data