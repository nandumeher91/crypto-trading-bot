
import os
import re
import logging
import requests
import time as time_module
from dotenv import load_dotenv
from binance.client import Client

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

API_KEY    = os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_TESTNET_SECRET_KEY")

if not API_KEY or not API_SECRET:
    logger.error("BINANCE API KEYS NOT FOUND!")
    raise ValueError("Binance API keys not found.")

print(f"[INIT] API Key found: {API_KEY[:5]}...{API_KEY[-4:]}")
print(f"[INIT] API Secret found: {API_SECRET[:5]}...{API_SECRET[-4:]}")

# Create client with longer timeout
client = Client(API_KEY, API_SECRET, testnet=True, requests_params={'timeout': 30})
client.REQUEST_TIMEOUT = 30
client.REQUEST_RECVWINDOW = 60000

# ── Time sync: once at startup + every 5 minutes (not every API call) ─────────
_last_sync_time = 0
_SYNC_INTERVAL  = 300  # seconds

def sync_time(force=False):
    global _last_sync_time
    now = time_module.time()
    if not force and (now - _last_sync_time) < _SYNC_INTERVAL:
        return  # skip — synced recently
    try:
        r = requests.get("https://testnet.binance.vision/api/v3/time", timeout=10)
        server_time = r.json()["serverTime"]
        local_time  = int(now * 1000)
        offset = server_time - local_time
        client.timestamp_offset = offset
        client.REQUEST_RECVWINDOW = 60000
        _last_sync_time = now
        print(f"[TIME] Synced. Offset: {offset}ms")
    except Exception as e:
        print(f"[TIME] Direct sync failed, trying fallback: {e}")
        try:
            server_time = client.get_server_time()
            local_time  = int(time_module.time() * 1000)
            offset = server_time["serverTime"] - local_time
            client.timestamp_offset = offset
            client.REQUEST_RECVWINDOW = 60000
            _last_sync_time = time_module.time()
            print(f"[TIME] Fallback sync OK. Offset: {offset}ms")
        except Exception as e2:
            print(f"[TIME] Sync completely failed: {e2}")

sync_time(force=True)  # sync once at startup

# ── Price cache: avoid hammering API every call ────────────────────────────────
_price_cache     = {}   # {symbol: price}
_price_cache_ts  = {}   # {symbol: timestamp}
_PRICE_CACHE_TTL = 10   # seconds — reuse price if < 10s old

# Binance LOT_SIZE filter for BTCUSDT (testnet)
MIN_QTY   = 0.00001
STEP_SIZE = 0.00001
MAX_QTY   = 9000.0


def _sanitize_symbol(symbol):
    if symbol is None:
        return "BTCUSDT"
    if not isinstance(symbol, str):
        print(f"[SANITIZE] WARNING: Expected string, got {type(symbol).__name__}: {symbol}")
        return "BTCUSDT"
    symbol = symbol.strip().upper()
    symbol = re.sub(r"[^A-Z0-9_.-]", "", symbol)
    if not symbol or len(symbol) < 2 or len(symbol) > 20:
        return "BTCUSDT"
    return symbol


def _sanitize_quantity(quantity):
    try:
        qty = float(quantity)
        if qty < MIN_QTY:
            print(f"[SANITIZE] Quantity {qty} below min {MIN_QTY}, using min")
            qty = MIN_QTY
        if qty > MAX_QTY:
            print(f"[SANITIZE] Quantity {qty} above max {MAX_QTY}, capping")
            qty = MAX_QTY
        steps   = round(qty / STEP_SIZE)
        qty     = round(steps * STEP_SIZE, 5)
        if qty < MIN_QTY:
            qty = MIN_QTY
        qty_str = f"{qty:.5f}"
        print(f"[SANITIZE] Original: {quantity} -> Sanitized: {qty_str}")
        return qty_str
    except Exception as e:
        print(f"[SANITIZE] WARNING: Invalid quantity '{quantity}': {e}")
        return str(quantity)


def _direct_price_check(symbol):
    try:
        url = f"https://testnet.binance.vision/api/v3/ticker/price?symbol={symbol}"
        print(f"[FALLBACK] Calling: {url}")
        response = requests.get(url, timeout=30)
        data = response.json()
        if "price" in data:
            return float(data["price"])
        else:
            print(f"[FALLBACK] Error response: {data}")
            return None
    except Exception as e:
        print(f"[FALLBACK] Direct request failed: {e}")
        return None


def test_api_connection():
    symbol = _sanitize_symbol("BTCUSDT")
    sync_time()
    print(f"[TEST] Testing API with symbol: '{symbol}'")
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        price  = float(ticker["price"])
        print(f"[TEST] API test PASSED. BTC price: ${price:,.2f}")
        return True
    except Exception as e:
        print(f"[TEST] python-binance failed: {e}")
        price = _direct_price_check(symbol)
        if price:
            print(f"[TEST] Fallback PASSED. BTC price: ${price:,.2f}")
            return True
        print(f"[TEST] Fallback also FAILED.")
        return False


def get_current_price(symbol="BTCUSDT"):
    """Return price — uses a 10-second cache to avoid Binance rate limits."""
    symbol = _sanitize_symbol(symbol)
    now    = time_module.time()

    # Return cached price if fresh enough
    if symbol in _price_cache and (now - _price_cache_ts.get(symbol, 0)) < _PRICE_CACHE_TTL:
        return _price_cache[symbol]

    # Sync time only if needed (every 5 min)
    sync_time()

    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        price  = float(ticker["price"])
        _price_cache[symbol]    = price
        _price_cache_ts[symbol] = now
        return price
    except Exception as e:
        print(f"[ERROR] get_current_price failed (library): {e}")
        price = _direct_price_check(symbol)
        if price:
            _price_cache[symbol]    = price
            _price_cache_ts[symbol] = now
            return price
        raise


def get_klines_direct(symbol, interval="1m", limit=100):
    try:
        url    = "https://testnet.binance.vision/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        print(f"[FALLBACK] Getting klines: {params}")
        response = requests.get(url, params=params, timeout=30)
        klines   = response.json()
        if not isinstance(klines, list):
            print(f"[FALLBACK] Invalid response (not a list): {klines}")
            return None
        if len(klines) == 0:
            print("[FALLBACK] Empty klines response")
            return None
        return {
            "open":   [float(k[1]) for k in klines],
            "high":   [float(k[2]) for k in klines],
            "low":    [float(k[3]) for k in klines],
            "close":  [float(k[4]) for k in klines],
            "volume": [float(k[5]) for k in klines]
        }
    except Exception as e:
        print(f"[FALLBACK] Direct klines failed: {e}")
        return None


def get_account_balance():
    sync_time()
    try:
        account  = client.get_account()
        balances = account["balances"]
        non_zero = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
        return non_zero
    except Exception as e:
        print(f"[ERROR] get_account_balance failed: {e}")
        raise


def place_test_order(symbol="BTCUSDT", side="BUY", quantity=0.001):
    symbol       = _sanitize_symbol(symbol)
    side         = str(side).strip().upper()
    quantity_str = _sanitize_quantity(quantity)

    sync_time()  # sync before every order

    print(f"[ORDER] Placing {side} order: symbol={symbol}, quantity={quantity_str} (original={quantity})")

    try:
        order = client.create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity_str,
            recvWindow=60000
        )
        print(f"[ORDER] Order placed successfully: {order['orderId']}")
        return order
    except Exception as e:
        print(f"[ERROR] place_test_order failed: {e}")
        raise


def test_connection():
    print("Testing Binance Testnet connection...\n")
    price    = get_current_price("BTCUSDT")
    print(f"Current BTCUSDT price: {price}")
    balances = get_account_balance()
    print("\nAccount balances (non-zero):")
    for b in balances:
        print(f"  {b['asset']}: free={b['free']}, locked={b['locked']}")


if __name__ == "__main__":
    test_connection()