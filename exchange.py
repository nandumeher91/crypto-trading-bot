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

API_KEY = os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_TESTNET_SECRET_KEY")

if not API_KEY or not API_SECRET:
    logger.error("BINANCE API KEYS NOT FOUND!")
    raise ValueError("Binance API keys not found.")

print(f"[INIT] API Key found: {API_KEY[:5]}...{API_KEY[-4:]}")
print(f"[INIT] API Secret found: {API_SECRET[:5]}...{API_SECRET[-4:]}")

# Create client with longer timeout and 60-second recvWindow tolerance
try:
    client = Client(API_KEY, API_SECRET, testnet=True, requests_params={'timeout': 30})
    client.REQUEST_TIMEOUT = 30
    client.REQUEST_RECVWINDOW = 60000
except Exception as e:
    logger.warning(f"Failed to connect to Binance Testnet on init: {e}")
    client = None

# Time sync cache: once at startup + every 5 minutes
_last_sync_time = 0
_SYNC_INTERVAL = 300  # seconds

def sync_time(force=False):
    global _last_sync_time, client
    now = time_module.time()
    if not force and (now - _last_sync_time) < _SYNC_INTERVAL:
        return 0

    if not client:
        return 0

    # 1. Try public testnet time
    try:
        r = requests.get("https://testnet.binance.vision/api/v3/time", timeout=10)
        server_time = r.json()["serverTime"]
        local_time = int(now * 1000)
        offset = server_time - local_time
        client.timestamp_offset = offset
        client.REQUEST_RECVWINDOW = 60000
        _last_sync_time = now
        print(f"[TIME] Synced via Testnet API. Offset: {offset}ms")
        return offset
    except Exception as e:
        # 2. Try public mainnet time (always available, same epoch)
        try:
            r = requests.get("https://api.binance.com/api/v3/time", timeout=10)
            server_time = r.json()["serverTime"]
            local_time = int(now * 1000)
            offset = server_time - local_time
            client.timestamp_offset = offset
            client.REQUEST_RECVWINDOW = 60000
            _last_sync_time = now
            print(f"[TIME] Synced via Mainnet API. Offset: {offset}ms")
            return offset
        except Exception:
            pass

        # 3. Fallback to client.get_server_time()
        try:
            server_time = client.get_server_time()
            local_time = int(time_module.time() * 1000)
            offset = server_time["serverTime"] - local_time
            client.timestamp_offset = offset
            client.REQUEST_RECVWINDOW = 60000
            _last_sync_time = time_module.time()
            print(f"[TIME] Fallback client sync OK. Offset: {offset}ms")
            return offset
        except Exception as e2:
            print(f"[TIME] Time sync failed (using local clock): {e2}")
            return 0

# Initial sync attempt (safe, won't crash if network issue)
sync_time(force=True)

# Price cache to avoid hammering API and hitting rate limits
_price_cache = {}
_price_cache_ts = {}
_PRICE_CACHE_TTL = 10  # 10 seconds cache

# Binance LOT_SIZE filter for BTCUSDT (testnet)
MIN_QTY = 0.00001
STEP_SIZE = 0.00001
MAX_QTY = 9000.0


def _sanitize_symbol(symbol):
    if symbol is None:
        return "BTCUSDT"
    if not isinstance(symbol, str):
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
            qty = MIN_QTY
        if qty > MAX_QTY:
            qty = MAX_QTY
        steps = round(qty / STEP_SIZE)
        qty = round(steps * STEP_SIZE, 5)
        if qty < MIN_QTY:
            qty = MIN_QTY
        return f"{qty:.5f}"
    except Exception as e:
        print(f"[SANITIZE] WARNING: Invalid quantity '{quantity}': {e}")
        return str(quantity)


def _direct_price_check(symbol):
    """Fetches real-time price with automatic failover (Testnet -> Mainnet)."""
    # 1. Try Testnet
    try:
        url = f"https://testnet.binance.vision/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if "price" in data:
            return float(data["price"])
    except Exception:
        pass

    # 2. Resilient Fallback: Mainnet Public API (never rate-limited by testnet IP bans)
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if "price" in data:
            return float(data["price"])
    except Exception as e:
        print(f"[FALLBACK] Direct price check failed for {symbol}: {e}")

    return None


def test_api_connection():
    symbol = _sanitize_symbol("BTCUSDT")
    sync_time()
    print(f"[TEST] Testing Binance API connection with symbol: '{symbol}'")
    try:
        if client:
            ticker = client.get_symbol_ticker(symbol=symbol)
            price = float(ticker["price"])
            print(f"[TEST] API test PASSED (via library). BTC price: ${price:,.2f}")
            return True
    except Exception as e:
        print(f"[TEST] python-binance library call failed: {e}")

    # Fallback to direct HTTP
    price = _direct_price_check(symbol)
    if price:
        print(f"[TEST] Fallback HTTP test PASSED. BTC price: ${price:,.2f}")
        return True

    print("[TEST] All API connection tests failed.")
    return False


def get_current_price(symbol="BTCUSDT"):
    """Returns price using 10-second cache to prevent rate-limit bans."""
    symbol = _sanitize_symbol(symbol)
    now = time_module.time()

    if symbol in _price_cache and (now - _price_cache_ts.get(symbol, 0)) < _PRICE_CACHE_TTL:
        return _price_cache[symbol]

    sync_time()

    # 1. Try Binance Client
    if client:
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            price = float(ticker["price"])
            _price_cache[symbol] = price
            _price_cache_ts[symbol] = now
            return price
        except Exception as e:
            print(f"[PRICE] Client ticker failed ({e}), using direct HTTP fallback...")

    # 2. Resilient fallback (Testnet or Mainnet)
    price = _direct_price_check(symbol)
    if price:
        _price_cache[symbol] = price
        _price_cache_ts[symbol] = now
        return price

    # 3. Return last cached price if available
    if symbol in _price_cache:
        print(f"[PRICE] Returning stale cached price for {symbol}: ${_price_cache[symbol]:,.2f}")
        return _price_cache[symbol]

    return 65000.0  # Safe default if entirely offline


def get_klines_direct(symbol, interval="1m", limit=100):
    """Fetches klines with failover (Testnet -> Mainnet)."""
    # 1. Try Testnet
    try:
        url = "https://testnet.binance.vision/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        response = requests.get(url, params=params, timeout=15)
        klines = response.json()
        if isinstance(klines, list) and len(klines) > 0:
            return {
                "open": [float(k[1]) for k in klines],
                "high": [float(k[2]) for k in klines],
                "low": [float(k[3]) for k in klines],
                "close": [float(k[4]) for k in klines],
                "volume": [float(k[5]) for k in klines]
            }
    except Exception:
        pass

    # 2. Resilient Fallback: Mainnet Public API
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        response = requests.get(url, params=params, timeout=15)
        klines = response.json()
        if isinstance(klines, list) and len(klines) > 0:
            return {
                "open": [float(k[1]) for k in klines],
                "high": [float(k[2]) for k in klines],
                "low": [float(k[3]) for k in klines],
                "close": [float(k[4]) for k in klines],
                "volume": [float(k[5]) for k in klines]
            }
    except Exception as e:
        print(f"[KLINES] Fallback to mainnet also failed: {e}")

    return None


def get_account_balance():
    sync_time()
    try:
        if not client:
            return []
        account = client.get_account()
        balances = account["balances"]
        non_zero = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
        return non_zero
    except Exception as e:
        print(f"[ERROR] get_account_balance failed: {e}")
        return []


def place_test_order(symbol="BTCUSDT", side="BUY", quantity=0.001):
    symbol = _sanitize_symbol(symbol)
    side = str(side).strip().upper()
    quantity_str = _sanitize_quantity(quantity)

    sync_time()

    print(f"[ORDER] Placing {side} order: symbol={symbol}, quantity={quantity_str} (original={quantity})")

    try:
        if not client:
            raise RuntimeError("Binance client not initialized")
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
    price = get_current_price("BTCUSDT")
    print(f"Current BTCUSDT price: {price}")
    balances = get_account_balance()
    print("\nAccount balances (non-zero):")
    for b in balances:
        print(f"  {b['asset']}: free={b['free']}, locked={b['locked']}")


if __name__ == "__main__":
    test_connection()