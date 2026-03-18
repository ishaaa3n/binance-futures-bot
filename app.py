"""
app.py — Streamlit UI for the Binance Futures Trading Bot

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import os
import logging
from decimal import Decimal
from datetime import datetime

import streamlit as st

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from bot.client import BinanceClient, BinanceAPIError, BinanceNetworkError
from bot.logging_config import setup_logging
from bot.orders import dispatch_order
from bot.validators import validate_all

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Futures Trading Bot",
    page_icon="₿",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;600;800&display=swap');

* { font-family: 'Syne', sans-serif; }
code, .stCode { font-family: 'JetBrains Mono', monospace !important; }

/* Dark terminal background */
.stApp {
    background-color: #0d0f14;
    color: #e2e8f0;
}

/* Hide default streamlit header */
header[data-testid="stHeader"] { background: transparent; }
.stDeployButton { display: none; }

/* Main title */
.bot-title {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 2.2rem;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, #f6c90e 0%, #ff6b35 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0;
}
.bot-subtitle {
    color: #64748b;
    font-size: 0.85rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 0.2rem;
    margin-bottom: 2rem;
}

/* Cards */
.card {
    background: #151820;
    border: 1px solid #1e2433;
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
}

/* Order summary box */
.summary-box {
    background: #0a0c10;
    border: 1px solid #f6c90e33;
    border-left: 3px solid #f6c90e;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: #94a3b8;
    margin: 1rem 0;
}
.summary-box .label { color: #64748b; }
.summary-box .value { color: #e2e8f0; font-weight: 600; }
.summary-box .value.buy { color: #22c55e; }
.summary-box .value.sell { color: #ef4444; }

/* Response box */
.response-box {
    background: #0a0c10;
    border: 1px solid #22c55e33;
    border-left: 3px solid #22c55e;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: #94a3b8;
    margin: 1rem 0;
}
.response-box .order-id { color: #f6c90e; font-weight: 700; font-size: 1rem; }
.response-box .status-filled { color: #22c55e; font-weight: 700; }
.response-box .status-new { color: #3b82f6; font-weight: 700; }

/* Error box */
.error-box {
    background: #0a0c10;
    border: 1px solid #ef444433;
    border-left: 3px solid #ef4444;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: #fca5a5;
    margin: 1rem 0;
}

/* Streamlit widget overrides */
.stSelectbox > div > div,
.stTextInput > div > div > input,
.stNumberInput > div > div > input {
    background-color: #151820 !important;
    border: 1px solid #1e2433 !important;
    color: #e2e8f0 !important;
    border-radius: 8px !important;
}
.stSelectbox > div > div:focus-within,
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus {
    border-color: #f6c90e !important;
    box-shadow: 0 0 0 1px #f6c90e44 !important;
}

/* Button */
.stButton > button {
    background: linear-gradient(135deg, #f6c90e, #ff6b35) !important;
    color: #0d0f14 !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    letter-spacing: 0.05em !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 0.6rem 2rem !important;
    width: 100% !important;
    transition: opacity 0.2s !important;
}
.stButton > button:hover { opacity: 0.85 !important; }

/* Dry run button */
.dry-btn > button {
    background: #151820 !important;
    color: #f6c90e !important;
    border: 1px solid #f6c90e44 !important;
}

/* Labels */
.stSelectbox label, .stTextInput label, .stNumberInput label {
    color: #64748b !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    font-weight: 600 !important;
}

/* Divider */
hr { border-color: #1e2433 !important; }

/* Log area */
.log-area {
    background: #080a0e;
    border: 1px solid #1e2433;
    border-radius: 8px;
    padding: 1rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    color: #475569;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
}

/* Live price badge */
.price-badge {
    display: inline-block;
    background: #1e2433;
    border: 1px solid #f6c90e22;
    border-radius: 6px;
    padding: 0.3rem 0.75rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    color: #f6c90e;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# ── Logging setup ─────────────────────────────────────────────────────────────


setup_logging(log_level="INFO")
logger = logging.getLogger("trading_bot.ui")

# ── Session state ─────────────────────────────────────────────────────────────

if "last_response" not in st.session_state:
    st.session_state.last_response = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "order_history" not in st.session_state:
    st.session_state.order_history = []


# ── Helper: build client (cached per session) ────────────────────────────────

def get_client(api_key: str, api_secret: str) -> BinanceClient | None:
    """Return a cached BinanceClient, recreating only if credentials changed."""
    cache_key = f"{api_key}:{api_secret}"
    if st.session_state.get("_client_cache_key") != cache_key:
        try:
            st.session_state["_client"] = BinanceClient(api_key=api_key, api_secret=api_secret)
            st.session_state["_client_cache_key"] = cache_key
        except ValueError as e:
            st.session_state.last_error = str(e)
            return None
    return st.session_state.get("_client")

# ── Helper: fetch mark price ──────────────────────────────────────────────────

@st.cache_data(ttl=5)
def fetch_mark_price(symbol: str, api_key: str, api_secret: str) -> str | None:
    try:
        client = get_client(api_key, api_secret)
        if client is None:
            return None
        return client.get_mark_price(symbol)
    except Exception:
        return None

# ── UI ────────────────────────────────────────────────────────────────────────

st.markdown('<div class="bot-title">₿ Futures Trading Bot</div>', unsafe_allow_html=True)
st.markdown('<div class="bot-subtitle">Binance USDT-M · Demo Environment</div>', unsafe_allow_html=True)

# ── Credentials ───────────────────────────────────────────────────────────────

with st.expander("🔑 API Credentials", expanded=not bool(os.getenv("BINANCE_API_KEY"))):
    col1, col2 = st.columns(2)
    with col1:
        api_key = st.text_input(
            "API Key",
            value=os.getenv("BINANCE_API_KEY", ""),
            type="password",
            placeholder="Your Binance API Key",
        )
    with col2:
        api_secret = st.text_input(
            "API Secret",
            value=os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_SECRET_KEY", ""),
            type="password",
            placeholder="Your Binance Secret Key",
        )

st.markdown("---")

# ── Order Form ────────────────────────────────────────────────────────────────

st.markdown("### Place Order")

col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    symbol = st.text_input("Symbol", value="BTCUSDT", placeholder="e.g. BTCUSDT").upper().strip()

with col2:
    side = st.selectbox("Side", ["BUY", "SELL"])

with col3:
    order_type = st.selectbox("Order Type", ["MARKET", "LIMIT", "STOP_MARKET"])

# Show live mark price
if symbol and api_key and api_secret:
    mark = fetch_mark_price(symbol, api_key, api_secret)
    if mark:
        st.markdown(
            f'<div style="margin-bottom:0.75rem">Live Mark Price: '
            f'<span class="price-badge">${float(mark):,.2f}</span></div>',
            unsafe_allow_html=True,
        )

col4, col5 = st.columns(2)

with col4:
    quantity = st.number_input(
        "Quantity",
        min_value=0.0,
        value=0.002,
        step=0.001,
        format="%.4f",
    )

with col5:
    if order_type == "LIMIT":
        price = st.number_input("Limit Price (USDT)", min_value=0.0, value=80000.0, step=100.0, format="%.2f")
        stop_price_val = None
    elif order_type == "STOP_MARKET":
        stop_price_val = st.number_input("Stop Price (USDT)", min_value=0.0, value=70000.0, step=100.0, format="%.2f")
        price = None
    else:
        st.markdown("<div style='height:2.5rem'></div>", unsafe_allow_html=True)
        price = None
        stop_price_val = None

if order_type == "LIMIT":
    tif = st.selectbox("Time in Force", ["GTC", "IOC", "FOK"])
else:
    tif = "GTC"

# ── Dry Run toggle ────────────────────────────────────────────────────────────

dry_run = st.checkbox("🧪 Dry Run (validate only, do not place order)", value=False)

st.markdown("---")

# ── Order Summary Preview ─────────────────────────────────────────────────────

side_class = "buy" if side == "BUY" else "sell"
price_line = f'<br><span class="label">Price        </span> <span class="value">{"${:,.2f}".format(price)}</span>' if price else ""
stop_line  = f'<br><span class="label">Stop Price   </span> <span class="value">{"${:,.2f}".format(stop_price_val)}</span>' if stop_price_val else ""
dry_line   = f'<br><span class="label">Mode         </span> <span class="value" style="color:#f6c90e">DRY RUN</span>' if dry_run else ""

st.markdown(f"""
<div class="summary-box">
<span class="label">Symbol       </span> <span class="value">{symbol or "—"}</span><br>
<span class="label">Side         </span> <span class="value {side_class}">{side}</span><br>
<span class="label">Type         </span> <span class="value">{order_type}</span><br>
<span class="label">Quantity     </span> <span class="value">{quantity}</span>{price_line}{stop_line}{dry_line}
</div>
""", unsafe_allow_html=True)

# ── Submit ────────────────────────────────────────────────────────────────────

submit = st.button("⚡ Place Order" if not dry_run else "🧪 Validate Order")

if submit:
    st.session_state.last_response = None
    st.session_state.last_error = None

    # Validate inputs
    try:
        validated = validate_all(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=str(quantity),
            price=str(price) if price else None,
            stop_price=str(stop_price_val) if stop_price_val else None,
        )
    except ValueError as e:
        st.session_state.last_error = f"Validation error: {e}"
        st.rerun()

    if dry_run:
        st.success("✅ Validation passed — dry run complete, no order placed.")
        logger.info("Dry run passed | symbol=%s side=%s type=%s qty=%s", symbol, side, order_type, quantity)
    else:
        if not api_key or not api_secret:
            st.session_state.last_error = "API credentials are missing. Fill in the API Key and Secret above."
            st.rerun()
        else:
            with st.spinner("Placing order..."):
                try:
                    client = get_client(api_key=api_key, api_secret=api_secret)
                    if client is None:
                        st.rerun()
                    response = dispatch_order(
                        client=client,
                        symbol=validated["symbol"],
                        side=validated["side"],
                        order_type=validated["order_type"],
                        quantity=validated["quantity"],
                        price=validated.get("price"),
                        stop_price=validated.get("stop_price"),
                        time_in_force=tif,
                    )
                    st.session_state.last_response = response
                    st.session_state.order_history.insert(0, {
                        "time": datetime.utcnow().strftime("%H:%M:%S"),
                        "symbol": validated["symbol"],
                        "side": validated["side"],
                        "type": validated["order_type"],
                        "qty": str(validated["quantity"]),
                        "orderId": response.get("orderId") or response.get("algoId"),
                        "status": response.get("status") or response.get("algoStatus"),
                    })
                except ValueError as e:
                    st.session_state.last_error = str(e)
                except BinanceAPIError as e:
                    st.session_state.last_error = f"Binance API error ({e.code}): {e.message}"
                except BinanceNetworkError as e:
                    st.session_state.last_error = f"Network error: {e}"
                except Exception as e:
                    st.session_state.last_error = f"Unexpected error: {e}"
            st.rerun()

# ── Response / Error display ──────────────────────────────────────────────────

if st.session_state.last_response:
    r = st.session_state.last_response
    order_id = r.get("orderId") or r.get("algoId", "—")
    status = r.get("status") or r.get("algoStatus", "—")
    status_class = "status-filled" if status == "FILLED" else "status-new"

    exec_qty  = r.get("executedQty", "—")
    avg_price = r.get("avgPrice", "—")
    client_id = r.get("clientOrderId") or r.get("clientAlgoId", "—")

    st.markdown(f"""
<div class="response-box">
✔ &nbsp;<strong>Order placed successfully</strong><br><br>
<span class="label">Order ID     </span> <span class="order-id">{order_id}</span><br>
<span class="label">Client ID    </span> <span class="value">{client_id}</span><br>
<span class="label">Status       </span> <span class="{status_class}">{status}</span><br>
<span class="label">Executed Qty </span> <span class="value">{exec_qty}</span><br>
<span class="label">Avg Price    </span> <span class="value">{avg_price}</span>
</div>
""", unsafe_allow_html=True)

if st.session_state.last_error:
    st.markdown(f"""
<div class="error-box">
✗ &nbsp;{st.session_state.last_error}
</div>
""", unsafe_allow_html=True)

# ── Order History ─────────────────────────────────────────────────────────────

if st.session_state.order_history:
    st.markdown("---")
    st.markdown("### Order History")
    for o in st.session_state.order_history[:10]:
        side_color = "#22c55e" if o["side"] == "BUY" else "#ef4444"
        st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            padding:0.6rem 1rem;background:#151820;border-radius:8px;
            margin-bottom:0.4rem;font-family:'JetBrains Mono',monospace;font-size:0.8rem;">
  <span style="color:#475569">{o['time']}</span>
  <span style="color:#e2e8f0;font-weight:600">{o['symbol']}</span>
  <span style="color:{side_color};font-weight:700">{o['side']}</span>
  <span style="color:#94a3b8">{o['type']}</span>
  <span style="color:#94a3b8">{o['qty']}</span>
  <span style="color:#f6c90e">#{o['orderId']}</span>
  <span style="color:#3b82f6">{o['status']}</span>
</div>
""", unsafe_allow_html=True)