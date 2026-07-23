import time
from datetime import datetime, timedelta
from brain import ask_brain
from exchange import place_test_order, get_current_price
from memory import (
    log_new_trade, close_trade, write_learning, get_open_trades,
    get_stats, get_trade_by_id
)
from strategy import get_enhanced_signal

# ===== CONFIGURATION =====
SYMBOL = "BTCUSDT"
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
MAX_TRADES_PER_DAY = 10
COOLDOWN_SECONDS = 300
MIN_CONFIDENCE = 6  # Minimum LLM confidence to trade
MAX_DRAWDOWN_USD = 2.0  # Stop trading if drawdown exceeds this

# Risk Management
RISK_PER_TRADE_PERCENT = 2.0  # 2% of capital per trade
ATR_MULTIPLIER_SL = 2.0  # Stop loss = 2x ATR
RISK_REWARD_RATIO = 1.5  # Take profit = 1.5x risk

# State tracking
trades_today = 0
last_trade_time = None
last_reset_date = None


def get_position_size(entry_price, stop_loss, confidence):
    """Calculate position size based on risk"""
    # Read current balance (simplified - you should get from Binance)
    # For testnet, assume $100 balance
    balance = 100.0  # TODO: Get from exchange.py
    
    risk_amount = balance * (RISK_PER_TRADE_PERCENT / 100)
    price_risk = abs(entry_price - stop_loss)
    
    if price_risk == 0:
        return 0.001  # Minimum
    
    base_size = risk_amount / price_risk
    
    # Adjust by confidence (6-10 scale)
    confidence_multiplier = confidence / 10
    
    final_size = base_size * confidence_multiplier
    
    # Limits
    max_size = (balance * 0.1) / entry_price  # Max 10% of balance
    min_size = 0.001  # Binance minimum
    
    return max(min(final_size, max_size), min_size)


def check_stop_loss_take_profit(open_trade, current_price):
    """Check if stop loss or take profit hit"""
    if not open_trade:
        return None
    
    sl = open_trade.get('stop_loss')
    tp = open_trade.get('take_profit')
    side = open_trade['side'].upper()
    
    if side == "BUY":
        if sl and current_price <= sl:
            return "stop_loss"
        if tp and current_price >= tp:
            return "take_profit"
    else:  # SELL
        if sl and current_price >= sl:
            return "stop_loss"
        if tp and current_price <= tp:
            return "take_profit"
    
    return None


def close_open_position(open_trade, current_price, reason, closed_by="brain"):
    """Close an open position"""
    global last_trade_time

    opposite_side = "SELL" if open_trade["side"].upper() == "BUY" else "BUY"

    try:
        order = place_test_order(
            symbol=SYMBOL, 
            side=opposite_side, 
            quantity=open_trade["quantity"]
        )
        closed = close_trade(open_trade["trade_id"], current_price, closed_by)

        pnl = closed["pnl"]
        pnl_pct = closed.get("pnl_percent", 0)
        outcome = "✅ PROFIT" if pnl >= 0 else "❌ LOSS"
        
        print(f"Closed trade #{open_trade['trade_id']}: {outcome} ${pnl:.4f} ({pnl_pct:.2f}%) [{closed_by}]")

        lesson = (f"Trade #{open_trade['trade_id']} ({open_trade['side']} ${open_trade['entry_price']}) "
                  f"closed at ${current_price}. Result: {outcome} ${abs(pnl):.4f}. "
                  f"Original: {open_trade['reason']}. Close reason: {reason}")
        
        write_learning(lesson, category="trade_close", trade_id=open_trade['trade_id'])
        last_trade_time = datetime.now()
        return True

    except Exception as e:
        print(f"[ERROR] Failed to close position: {e}")
        return False


def reset_daily_limits():
    """Reset daily trade count at midnight"""
    global trades_today, last_reset_date
    
    now = datetime.now()
    today = now.date()
    
    if last_reset_date != today:
        trades_today = 0
        last_reset_date = today
        print(f"[INFO] Daily limits reset for {today}")


def can_open_new_trade():
    """Check if we can open a new trade"""
    global trades_today, last_trade_time

    reset_daily_limits()

    if trades_today >= MAX_TRADES_PER_DAY:
        print(f"[SAFETY] Daily trade limit ({MAX_TRADES_PER_DAY}) reached.")
        return False

    if last_trade_time is not None:
        elapsed = (datetime.now() - last_trade_time).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            print(f"[SAFETY] Cooldown active ({int(COOLDOWN_SECONDS - elapsed)}s remaining).")
            return False

    # Check drawdown
    stats = get_stats()
    if stats.get('max_drawdown', 0) > MAX_DRAWDOWN_USD:
        print(f"[SAFETY] Max drawdown (${stats['max_drawdown']:.2f}) exceeded limit (${MAX_DRAWDOWN_USD}). STOPPING.")
        return False
    
    # Check losing streak
    if stats.get('current_streak', 0) <= -3:
        print(f"[SAFETY] Losing streak ({stats['current_streak']}). Taking break.")
        return False

    return True


def run_bot_once():
    """Main bot loop - single iteration"""
    global trades_today, last_trade_time

    print(f"\n{'='*60}")
    print(f"Check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Get market data first
    signal_data = get_enhanced_signal(SYMBOL)
    print(f"Signal: {signal_data['signal']} (Score: {signal_data['score']}/100)")
    
    # Get brain decision
    action, reasoning, confidence, risk_level = ask_brain(SYMBOL)
    print(f"Brain: {action} | Confidence: {confidence}/10 | Risk: {risk_level}")
    print(f"Reason: {reasoning}")

    # Check open positions first (SL/TP check)
    price = get_current_price(SYMBOL)
    open_trades = get_open_trades()
    
    if open_trades:
        current_open = open_trades[0]
        sl_tp_hit = check_stop_loss_take_profit(current_open, price)
        
        if sl_tp_hit:
            print(f"🚨 {sl_tp_hit.upper()} HIT for trade #{current_open['trade_id']}!")
            close_open_position(current_open, price, f"{sl_tp_hit} triggered", sl_tp_hit)
            return
        
        # Check if brain wants to reverse
        if action in ["BUY", "SELL"] and current_open["side"].upper() != action:
            if confidence >= MIN_CONFIDENCE and signal_data['score'] >= 60:
                print(f"Brain says reverse. Closing trade #{current_open['trade_id']}...")
                close_open_position(current_open, price, reasoning)
            else:
                print(f"Brain suggests reverse but confidence ({confidence}) or score ({signal_data['score']}) too low. Holding.")
            return
        else:
            print("Holding current position.")
            return

    # No open position - check if we should enter
    if action not in ("BUY", "SELL"):
        print("No trade signal. Waiting.")
        return

    if confidence < MIN_CONFIDENCE:
        print(f"Confidence too low ({confidence} < {MIN_CONFIDENCE}). Skipping.")
        return

    if not can_open_new_trade():
        return

    # Calculate risk parameters
    atr = signal_data.get('atr', price * 0.02)  # Default 2% if ATR unavailable
    stop_loss = price - (atr * ATR_MULTIPLIER_SL) if action == "BUY" else price + (atr * ATR_MULTIPLIER_SL)
    take_profit = price + (abs(price - stop_loss) * RISK_REWARD_RATIO) if action == "BUY" else price - (abs(price - stop_loss) * RISK_REWARD_RATIO)
    
    # Calculate position size
    quantity = get_position_size(price, stop_loss, confidence)
    
    print(f"Risk Params: SL=${stop_loss:,.2f}, TP=${take_profit:,.2f}, Qty={quantity:.6f}")

    try:
        # Place order
        order = place_test_order(symbol=SYMBOL, side=action, quantity=quantity)
        trade_id = log_new_trade(
            SYMBOL, action, price, quantity, reasoning,
            stop_loss=stop_loss, take_profit=take_profit
        )

        print(f"✅ Order placed: {order['status']}, trade_id={trade_id}")
        print(f"   SL: ${stop_loss:,.2f} | TP: ${take_profit:,.2f}")

        trades_today += 1
        last_trade_time = datetime.now()

    except Exception as e:
        print(f"[ERROR] Order failed: {e}")
        write_learning(f"Order failed for {action}: {str(e)}", category="error")


def main():
    print("🤖 Enhanced Trading Bot Started")
    print(f"Symbol: {SYMBOL} | Check: {CHECK_INTERVAL_SECONDS}s | Min Confidence: {MIN_CONFIDENCE}")
    print(f"Risk/Trade: {RISK_PER_TRADE_PERCENT}% | SL: {ATR_MULTIPLIER_SL}x ATR | RR: 1:{RISK_REWARD_RATIO}")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            run_bot_once()
        except KeyboardInterrupt:
            print("\n👋 Bot stopped by user.")
            break
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
            write_learning(f"Bot error: {str(e)}", category="error")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()