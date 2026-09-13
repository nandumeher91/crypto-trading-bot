
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

API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_SECRET_KEY")

if not API_KEY or not API_SECRET:
    logger.error("BINANCE API KEYS NOT FOUND!")
    raise ValueError("Binance API keys not found.")

print(f"[INIT] API Key found: {API_KEY[:5]}...{API_KEY[-4:]}")
print(f"[INIT] API Secret found: {API_SECRET[:5]}...{API_SECRET[-4:]}")

# Create client with longer timeout and larger recvWindow
client = Client(API_KEY, API_SECRET, testnet=True)
client.REQUEST_TIMEOUT = 30

# Sync time immediately and store offset
def sync_time():
    try:
        server_time = client.get_server_time()
        local_time = int(time_module.time() * 1000)
        offset = server_time["serverTime"] - local_time
        client.timestamp_offset = offset
        print(f"[TIME] Synced. Server: {server_time['serverTime']}, Local: {local_time}, Offset: {offset}ms")
        return offset
    except Exception as e:
        print(f"[TIME] Sync failed: {e}")
        return 0

sync_time()

# Binance LOT_SIZE filter for BTCUSDT (testnet)
MIN_QTY = 0.00001
STEP_SIZE = 0.00001
MAX_QTY = 9000.0


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
        steps = round(qty / STEP_SIZE)
        qty = round(steps * STEP_SIZE, 5)
        if qty < MIN_QTY:
            qty = MIN_QTY
        qty_str = f"{qty:.5f}"
        print(f"[SANITIZE] Original: {quantity} → Sanitized: {qty_str}")
        return qty_str
    except Exception as e:
        print(f"[SANITIZE] WARNING: Invalid quantity '{quantity}': {e}")
        return "0.00001"


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
    # Re-sync time before test
    sync_time()
    print(f"[TEST] Testing API with symbol: '{symbol}' (len={len(symbol)}, type={type(symbol).__name__})")
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        price = float(ticker["price"])
        print(f"[TEST] API test PASSED. BTC price: ${price:,.2f}")
        return True
    except Exception as e:
        print(f"[TEST] python-binance failed: {e}")
        print(f"[TEST] Trying fallback HTTP request...")
        price = _direct_price_check(symbol)
        if price:
            print(f"[TEST] Fallback PASSED. BTC price: ${price:,.2f}")
            return True
        print(f"[TEST] Fallback also FAILED.")
        return False


def get_current_price(symbol="BTCUSDT"):
    symbol = _sanitize_symbol(symbol)
    # Re-sync time before API call
    sync_time()
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except Exception as e:
        print(f"[ERROR] get_current_price failed (library): {e}")
        price = _direct_price_check(symbol)
        if price:
            return price
        raise


def get_klines_direct(symbol, interval="1m", limit=100):
    try:
        url = "https://testnet.binance.vision/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        print(f"[FALLBACK] Getting klines: {params}")
        response = requests.get(url, params=params, timeout=30)
        klines = response.json()
        if not isinstance(klines, list):
            print(f"[FALLBACK] Invalid response (not a list): {klines}")
            return None
        if len(klines) == 0:
            print("[FALLBACK] Empty klines response")
            return None
        return {
            "open": [float(k[1]) for k in klines],
            "high": [float(k[2]) for k in klines],
            "low": [float(k[3]) for k in klines],
            "close": [float(k[4]) for k in klines],
            "volume": [float(k[5]) for k in klines]
        }
    except Exception as e:
        print(f"[FALLBACK] Direct klines failed: {e}")
        return None


def get_account_balance():
    sync_time()
    try:
        account = client.get_account()
        balances = account["balances"]
        non_zero = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
        return non_zero
    except Exception as e:
        print(f"[ERROR] get_account_balance failed: {e}")
        raise


def place_test_order(symbol="BTCUSDT", side="BUY", quantity=0.001):
    symbol = _sanitize_symbol(symbol)
    side = str(side).strip().upper()
    quantity_str = _sanitize_quantity(quantity)

    # CRITICAL: Re-sync time before every order to avoid timestamp errors
    sync_time()

    print(f"[ORDER] Placing {side} order: symbol={symbol}, quantity={quantity_str} (original={quantity})")

    try:
        order = client.create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity_str,
            recvWindow=10000  # 10 second window for timestamp tolerance
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