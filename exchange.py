import os
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_SECRET_KEY")

import time as time_module

client = Client(API_KEY, API_SECRET, testnet=True)

# Auto-correct for clock drift
server_time = client.get_server_time()
time_offset = server_time['serverTime'] - int(time_module.time() * 1000)
client.timestamp_offset = time_offset


def get_current_price(symbol="BTCUSDT"):
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def get_account_balance():
    account = client.get_account()
    balances = account["balances"]
    non_zero = [b for b in balances if float(b["free"]) > 0 or float(b["locked"]) > 0]
    return non_zero


def place_test_order(symbol="BTCUSDT", side="BUY", quantity=0.001):
    order = client.create_order(
        symbol=symbol,
        side=side,
        type="MARKET",
        quantity=quantity
    )
    return order


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