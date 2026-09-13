import json
import time
import datetime
from datetime import datetime, timedelta
from brain import ask_brain
from exchange import place_test_order, get_current_price, test_api_connection, MIN_QTY
from memory import (
    log_new_trade, close_trade, write_learning, get_open_trades,
    get_stats, get_trade_by_id, update_trade_stop_loss
)
from strategy import get_enhanced_signal
import logging
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def write_market_state(signal_data, current_price, brain_decision):
    try:
        state_file = os.path.join(BASE_DIR, "market_state.json")
        data = {
            "price": current_price,
            "signal": signal_data.get("signal", "HOLD"),
            "score": signal_data.get("score", 50),
            "rsi": round(signal_data.get("rsi", 50) or 50, 1),
            "atr": round(signal_data.get("atr", 0) or 0, 2),
            "adx": round(signal_data.get("adx", 0) or 0, 1),
            "volume_ratio": round(signal_data.get("volume_ratio", 1) or 1, 2),
            "action": brain_decision.get("action", "HOLD"),
            "confidence": brain_decision.get("confidence", 0),
            "reason": brain_decision.get("reason", ""),
            "risk_level": brain_decision.get("risk_level", "MEDIUM"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[BOT] Warning: Failed to write market_state.json: {e}")

# ====== LOGGING SETUP (File + Console both) ======
log_path = os.path.join(BASE_DIR, "bot.log")

file_handler = logging.FileHandler(log_path, mode='w')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ====== CONFIGURATION ======
SYMBOL = "BTCUSDT"
CHECK_INTERVAL_SECONDS = 300
MAX_TRADES_PER_DAY = 10
COOLDOWN_SECONDS = 300
MIN_CONFIDENCE = 5
MAX_DRAWDOWN_USD = 2.0

RISK_PER_TRADE_PERCENT = 2.0
ATR_MULTIPLIER_SL = 1.5
RISK_REWARD_RATIO = 2.0

# State tracking
trades_today = 0
last_trade_time = None
last_reset_date = None


MIN_NOTIONAL_USD = 10.0  # Binance minimum order value in USDT

def get_position_size(entry_price, stop_loss, confidence):
    """Calculate position size based on risk with safety checks"""
    balance = 100.0
    risk_amount = balance * (RISK_PER_TRADE_PERCENT / 100)
    price_risk = abs(entry_price - stop_loss)

    if price_risk == 0:
        price_risk = entry_price * 0.01

    position_size = risk_amount / price_risk

    # Enforce Binance MIN_NOTIONAL filter (Must be >= $10.00 USDT)
    notional_value = position_size * entry_price
    if notional_value < MIN_NOTIONAL_USD:
        position_size = MIN_NOTIONAL_USD / entry_price
        print(f"[POSITION] Adjusted size to meet Binance MIN_NOTIONAL (${MIN_NOTIONAL_USD:.2f}): {position_size:.5f} BTC")

    position_size = round(position_size, 5)

    if position_size < MIN_QTY:
        position_size = MIN_QTY

    print(f"[POSITION] Entry: ${entry_price:.2f}, SL: ${stop_loss:.2f}, Risk: ${price_risk:.2f}, Size: {position_size} (${position_size * entry_price:.2f} USD)")
    return position_size


def manage_open_positions(current_price, atr=None):

    open_trades = get_open_trades()
    for trade in open_trades:
        trade_id = trade["trade_id"]
        entry = float(trade["entry_price"])
        sl = float(trade["stop_loss"]) if trade.get("stop_loss") else None
        tp = float(trade["take_profit"]) if trade.get("take_profit") else None
        side = trade["side"].upper()

        if side == "BUY":
            # 1. Stop Loss Hit
            if sl and current_price <= sl:
                logger.info(f"STOP LOSS HIT | Trade #{trade_id} | Price: ${current_price:.2f} | SL: ${sl:.2f}")
                close_open_position(trade, current_price, "Stop Loss hit", "stop_loss")
                continue

            # 2. Take Profit Hit
            if tp and current_price >= tp:
                logger.info(f"TAKE PROFIT HIT | Trade #{trade_id} | Price: ${current_price:.2f} | TP: ${tp:.2f}")
                close_open_position(trade, current_price, "Take Profit hit", "take_profit")
                continue

            # 3. Breakeven Lock & Trailing Stop-Loss
            if tp and sl:
                tp_distance = tp - entry
                # Move to Breakeven if price reaches 50% towards TP
                be_trigger_price = entry + (tp_distance * 0.5)
                be_sl_price = entry * 1.001  # Entry + 0.1% fee buffer

                if current_price >= be_trigger_price and sl < be_sl_price:
                    logger.info(f"PROTECTION | Trade #{trade_id} | Moving SL to Breakeven (+0.1%): ${be_sl_price:.2f}")
                    update_trade_stop_loss(trade_id, be_sl_price)
                    write_learning(f"Trade #{trade_id}: Profit reached 50% target. SL moved to Breakeven (${be_sl_price:.2f}).", category="risk_management", trade_id=trade_id)
                    sl = be_sl_price

                # Trailing Stop-Loss if ATR is available
                if atr and atr > 0:
                    trail_sl = current_price - (atr * 1.5)
                    if trail_sl > sl:
                        logger.info(f"TRAILING STOP | Trade #{trade_id} | Trailed SL up from ${sl:.2f} to ${trail_sl:.2f}")
                        update_trade_stop_loss(trade_id, trail_sl)

        else:  # SELL position
            # 1. Stop Loss Hit
            if sl and current_price >= sl:
                logger.info(f"STOP LOSS HIT | Trade #{trade_id} | Price: ${current_price:.2f} | SL: ${sl:.2f}")
                close_open_position(trade, current_price, "Stop Loss hit", "stop_loss")
                continue

            # 2. Take Profit Hit
            if tp and current_price <= tp:
                logger.info(f"TAKE PROFIT HIT | Trade #{trade_id} | Price: ${current_price:.2f} | TP: ${tp:.2f}")
                close_open_position(trade, current_price, "Take Profit hit", "take_profit")
                continue

            # 3. Breakeven Lock & Trailing Stop-Loss
            if tp and sl:
                tp_distance = entry - tp
                be_trigger_price = entry - (tp_distance * 0.5)
                be_sl_price = entry * 0.999

                if current_price <= be_trigger_price and sl > be_sl_price:
                    logger.info(f"PROTECTION | Trade #{trade_id} | Moving SL to Breakeven (-0.1%): ${be_sl_price:.2f}")
                    update_trade_stop_loss(trade_id, be_sl_price)
                    write_learning(f"Trade #{trade_id}: Profit reached 50% target. SL moved to Breakeven (${be_sl_price:.2f}).", category="risk_management", trade_id=trade_id)
                    sl = be_sl_price

                if atr and atr > 0:
                    trail_sl = current_price + (atr * 1.5)
                    if trail_sl < sl:
                        logger.info(f"TRAILING STOP | Trade #{trade_id} | Trailed SL down from ${sl:.2f} to ${trail_sl:.2f}")
                        update_trade_stop_loss(trade_id, trail_sl)



def close_open_position(open_trade, current_price, reason, closed_by="brain"):
    global last_trade_time
    opposite_side = "SELL" if open_trade["side"].upper() == "BUY" else "BUY"
    try:
        order = place_test_order(symbol=SYMBOL, side=opposite_side, quantity=open_trade["quantity"])
        closed = close_trade(open_trade["trade_id"], current_price, closed_by)
        pnl = closed["pnl"]
        pnl_pct = closed.get("pnl_percent", 0)
        outcome = "[PROFIT]" if pnl >= 0 else "[LOSS]"
        logger.info(f"CLOSED | Trade #{open_trade['trade_id']} | {outcome} ${pnl:.4f} ({pnl_pct:.2f}%) | {closed_by}")
        lesson = (f"Trade #{open_trade['trade_id']} ({open_trade['side']} ${open_trade['entry_price']}) "
                  f"closed at ${current_price}. Result: {outcome} ${abs(pnl):.4f}. "
                  f"Original: {open_trade['reason']}. Close reason: {reason}")
        write_learning(lesson, category="trade_close", trade_id=open_trade['trade_id'])
        last_trade_time = datetime.now()
        return True
    except Exception as e:
        logger.error(f"[ERROR] Failed to close position: {e}")
        return False


def reset_daily_limits():
    global trades_today, last_reset_date
    now = datetime.now()
    today = now.date()
    if last_reset_date != today:
        trades_today = 0
        last_reset_date = today
        logger.info("Daily limits reset")


def run_bot_once():
    global trades_today, last_trade_time
    reset_daily_limits()
    if last_trade_time and (datetime.now() - last_trade_time).total_seconds() < COOLDOWN_SECONDS:
        return
    try:
        print(f"[BOT] Getting signal for symbol: {SYMBOL} (type: {type(SYMBOL).__name__})")
        signal_data = get_enhanced_signal(SYMBOL)
        signal = signal_data["signal"]
        score = signal_data["score"]

        current_price = get_current_price(SYMBOL)
        manage_open_positions(current_price, atr=signal_data.get("atr"))
        open_trades = get_open_trades()
        stats = get_stats()

        brain_input = {
            "signal": signal,
            "score": score,
            "price": current_price,
            "stats": stats,
            "open_positions": len(open_trades)
        }

        print(f"[BOT] Calling brain with input keys: {list(brain_input.keys())}")
        brain_decision = ask_brain(brain_input)

        if not isinstance(brain_decision, dict):
            print(f"[BOT] WARNING: brain_decision is not dict, got {type(brain_decision).__name__}. Using HOLD.")
            brain_decision = {"action": "HOLD", "confidence": 0, "reason": "Invalid brain response"}

        action = brain_decision.get("action", "HOLD")
        confidence = brain_decision.get("confidence", 0)
        reason = brain_decision.get("reason", "")

        # Write latest state to market_state.json for GUI real-time display
        write_market_state(signal_data, current_price, brain_decision)

        logger.info("=" * 50)
        logger.info(f"CHECK #{stats.get('total_trades', 0) + 1} | {SYMBOL} | ${current_price:.2f}")
        logger.info(f"SIGNAL: {signal} | Score: {score}/100")
        logger.info(f"BRAIN: {action} | Confidence: {confidence}/10")

        if action == "HOLD":
            logger.info(f"DECISION: NO TRADE | Reason: {reason[:80]}...")
            return
        if confidence < MIN_CONFIDENCE:
            logger.info(f"DECISION: NO TRADE | Confidence too low ({confidence}/{MIN_CONFIDENCE})")
            return
        if trades_today >= MAX_TRADES_PER_DAY:
            logger.info(f"DECISION: NO TRADE | Daily limit reached ({trades_today}/{MAX_TRADES_PER_DAY})")
            return
        total_pnl = stats.get("total_pnl", 0)
        if total_pnl < -MAX_DRAWDOWN_USD:
            logger.info(f"DECISION: NO TRADE | Max drawdown exceeded (${total_pnl:.2f})")
            return
        if action in ["BUY", "SELL"]:
            if action == "SELL" and len(open_trades) == 0:
                logger.info(f"DECISION: NO TRADE | Spot trading: Cannot open SELL (short) position without holding base asset.")
                return

            atr = signal_data.get("atr", current_price * 0.01)
            if action == "BUY":
                stop_loss = current_price - (atr * ATR_MULTIPLIER_SL)
                take_profit = current_price + (atr * ATR_MULTIPLIER_SL * RISK_REWARD_RATIO)
            else:
                stop_loss = current_price + (atr * ATR_MULTIPLIER_SL)
                take_profit = current_price - (atr * ATR_MULTIPLIER_SL * RISK_REWARD_RATIO)

            position_size = get_position_size(current_price, stop_loss, confidence)

            print(f"[BOT] Executing {action} | Price: ${current_price:.2f} | Qty: {position_size}")

            order = place_test_order(symbol=SYMBOL, side=action, quantity=position_size)
            trade_id = log_new_trade(
                symbol=SYMBOL, side=action, entry_price=current_price,
                quantity=position_size, reason=reason,
                stop_loss=stop_loss, take_profit=take_profit
            )
            trades_today += 1
            last_trade_time = datetime.now()
            logger.info(f"TRADE EXECUTED | #{trade_id} | {action} | ${current_price:.2f} | Qty: {position_size}")
            logger.info(f"SL: ${stop_loss:.2f} | TP: ${take_profit:.2f}")
            write_learning(
                f"New trade #{trade_id}: {action} {SYMBOL} at ${current_price} "
                f"with SL=${stop_loss:.2f}, TP=${take_profit:.2f}. Reason: {reason}",
                category="trade_open", trade_id=trade_id
            )
    except Exception as e:
        logger.error(f"[ERROR] Bot cycle failed: {e}")
        print(f"[BOT] ERROR in cycle: {e}")
        write_learning(f"Bot error: {str(e)}", category="error")


def main():
    print("\n" + "=" * 60)
    print("  ENHANCED TRADING BOT STARTING...")
    print("=" * 60)

    logger.info("=" * 50)
    logger.info("ENHANCED TRADING BOT STARTED")
    logger.info(f"Symbol: {SYMBOL} | Check: {CHECK_INTERVAL_SECONDS}s | Min Confidence: {MIN_CONFIDENCE}")
    logger.info(f"Risk/Trade: {RISK_PER_TRADE_PERCENT}% | SL: {ATR_MULTIPLIER_SL}x ATR | RR: 1:{RISK_REWARD_RATIO}")
    logger.info("=" * 50)

    print("[MAIN] Testing Binance API connection...")
    if not test_api_connection():
        logger.error("CRITICAL: Binance API connection test failed. Bot will not start.")
        print("[MAIN] CRITICAL: API test failed.")
        return

    print(f"[MAIN] API OK. Starting main loop (every {CHECK_INTERVAL_SECONDS}s)...")
    print("[MAIN] Press Ctrl+C to stop\n")

    while True:
        try:
            print(f"[MAIN] Running bot cycle at {datetime.now().strftime('%H:%M:%S')}...")
            run_bot_once()
            print(f"[MAIN] Cycle complete. Sleeping {CHECK_INTERVAL_SECONDS}s...\n")
            time.sleep(CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            print("[MAIN] Bot stopped by user.")
            break
        except Exception as e:
            logger.warning(f"[NETWORK LAG] Temporary error: {e}. Retrying in 10s...")
            print(f"[MAIN] Temporary network error: {e}. Retrying in 10s...")
            time.sleep(10)


if __name__ == "__main__":
    main()
