from exchange import place_test_order, get_current_price

print("Placing a small test BUY order on Binance Testnet...\n")

price_before = get_current_price("BTCUSDT")
print(f"Current BTCUSDT price: {price_before}")

order = place_test_order(symbol="BTCUSDT", side="BUY", quantity=0.001)

print("\nOrder placed successfully!")
print(f"Order ID: {order['orderId']}")
print(f"Status: {order['status']}")
print(f"Symbol: {order['symbol']}")
print(f"Side: {order['side']}")

for fill in order.get("fills", []):
    print(f"  Filled: {fill['qty']} @ {fill['price']}")