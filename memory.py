import json
import os
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = Path(os.path.join(BASE_DIR, "ledger.json"))
LEARNINGS_FILE = Path(os.path.join(BASE_DIR, "learnings.txt"))
STATS_FILE = Path(os.path.join(BASE_DIR, "stats.json"))


def read_ledger():
    if not LEDGER_FILE.exists() or os.path.getsize(LEDGER_FILE) < 10:
        sync_ledger_from_binance()

    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE, 'r') as f:
                data = json.load(f)
                if not data:
                    sync_ledger_from_binance()
                    with open(LEDGER_FILE, 'r') as f2:
                        data = json.load(f2)
                return data
        except Exception as e:
            print(f"[MEMORY] Warning: Failed to read ledger.json: {e}")
            return []
    return []


def write_ledger(trades):
    with open(LEDGER_FILE, 'w') as f:
        json.dump(trades, f, indent=2)


def sync_ledger_from_binance(symbol="BTCUSDT"):
    try:
        from exchange import client
        binance_trades = client.get_my_trades(symbol=symbol)
        if not binance_trades:
            return

        ledger = []
        open_buy = None
        total_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        largest_win = 0.0
        largest_loss = 0.0
        current_streak = 0
        max_drawdown = 0.0

        trade_counter = 1
        for bt in binance_trades:
            t_time = (datetime.utcfromtimestamp(bt['time'] / 1000.0) + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S IST')
            price = float(bt['price'])
            qty = float(bt['qty'])
            is_buyer = bt['isBuyer']

            if is_buyer:
                open_buy = {
                    "trade_id": trade_counter,
                    "timestamp": t_time,
                    "symbol": symbol,
                    "side": "BUY",
                    "entry_price": price,
                    "quantity": qty,
                    "reason": "Executed trade",
                    "stop_loss": price * 0.995,
                    "take_profit": price * 1.01,
                    "status": "open",
                    "pnl": 0.0,
                    "pnl_percent": 0.0
                }
            else:
                if open_buy:
                    entry = open_buy['entry_price']
                    pnl = (price - entry) * qty
                    pnl_percent = ((price - entry) / entry) * 100.0 if entry > 0 else 0.0
                    open_buy['close_price'] = price
                    open_buy['close_time'] = t_time
                    open_buy['status'] = "closed_tp" if pnl >= 0 else "closed_sl"
                    open_buy['pnl'] = round(pnl, 4)
                    open_buy['pnl_percent'] = round(pnl_percent, 2)
                    ledger.append(open_buy)
                    trade_counter += 1

                    total_pnl += pnl
                    if pnl >= 0:
                        winning_trades += 1
                        largest_win = max(largest_win, pnl)
                        current_streak = current_streak + 1 if current_streak >= 0 else 1
                    else:
                        losing_trades += 1
                        largest_loss = min(largest_loss, pnl)
                        current_streak = current_streak - 1 if current_streak <= 0 else -1

                    open_buy = None

        if open_buy:
            ledger.append(open_buy)

        total_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        stats = {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 1),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "current_streak": current_streak,
            "max_drawdown": round(max_drawdown, 2)
        }

        write_ledger(ledger)
        write_stats(stats)
        print(f"[SYNC] Synced {len(ledger)} trades from Binance API. P&L: ${total_pnl:.2f}, Win Rate: {win_rate:.1f}%")
    except Exception as e:
        print(f"[SYNC] Warning: Could not sync from Binance API: {e}")


def read_stats():
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[MEMORY] Warning: Failed to read stats.json: {e}")
    return {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_pnl": 0.0,
        "largest_win": 0.0,
        "largest_loss": 0.0,
        "current_streak": 0,
        "max_drawdown": 0.0
    }


def write_stats(stats):
    with open(STATS_FILE, 'w') as f:
        json.dump(stats, f, indent=2)


def log_new_trade(symbol, side, entry_price, quantity, reason, stop_loss=None, take_profit=None):
    trades = read_ledger()
    new_trade = {
        "trade_id": len(trades) + 1,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "symbol": symbol.upper().replace("/", ""),
        "side": side.upper(),
        "entry_price": float(entry_price),
        "quantity": float(quantity),
        "reason": reason,
        "stop_loss": float(stop_loss) if stop_loss else None,
        "take_profit": float(take_profit) if take_profit else None,
        "exit_price": None,
        "exit_timestamp": None,
        "pnl": None,
        "pnl_percent": None,
        "status": "open",
        "closed_by": None
    }
    trades.append(new_trade)
    write_ledger(trades)
def update_trade_stop_loss(trade_id, new_sl):
    trades = read_ledger()
    updated = False
    for trade in trades:
        if trade["trade_id"] == trade_id and trade["status"] == "open":
            trade["stop_loss"] = float(round(new_sl, 2))
            updated = True
            break
    if updated:
        write_ledger(trades)
    return updated


def close_trade(trade_id, exit_price, closed_by="brain"):
    trades = read_ledger()
    target = None
    for trade in trades:
        if trade["trade_id"] == trade_id:
            target = trade
            break

    if target is None:
        raise ValueError(f"Trade ID {trade_id} not found")

    if target["status"] != "open":
        raise ValueError(f"Trade #{trade_id} is already closed")

    side = target["side"].upper()
    entry = float(target["entry_price"])
    qty = float(target["quantity"])
    exit_p = float(exit_price)

    if side == "BUY":
        pnl = (exit_p - entry) * qty
        pnl_percent = ((exit_p - entry) / entry) * 100
    else:
        pnl = (entry - exit_p) * qty
        pnl_percent = ((entry - exit_p) / entry) * 100

    fee = (entry * qty * 0.001) + (exit_p * qty * 0.001)
    pnl_after_fee = pnl - fee

    target["exit_price"] = exit_p
    target["exit_timestamp"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    target["pnl"] = round(pnl_after_fee, 8)
    target["pnl_percent"] = round(pnl_percent, 4)
    target["status"] = "closed"
    target["closed_by"] = closed_by

    write_ledger(trades)
    update_stats(pnl_after_fee)

    return target


def update_stats(pnl):
    stats = read_stats()
    stats["total_trades"] += 1
    stats["total_pnl"] = round(stats["total_pnl"] + pnl, 8)

    if pnl >= 0:
        stats["winning_trades"] += 1
        stats["current_streak"] = stats["current_streak"] + 1 if stats["current_streak"] >= 0 else 1
        if pnl > stats["largest_win"]:
            stats["largest_win"] = round(pnl, 8)
    else:
        stats["losing_trades"] += 1
        stats["current_streak"] = stats["current_streak"] - 1 if stats["current_streak"] <= 0 else -1
        if abs(pnl) > abs(stats["largest_loss"]):
            stats["largest_loss"] = round(pnl, 8)

    peak = max(0, stats["total_pnl"])
    if stats["total_pnl"] < peak:
        drawdown = peak - stats["total_pnl"]
        if drawdown > stats["max_drawdown"]:
            stats["max_drawdown"] = round(drawdown, 8)

    write_stats(stats)


def get_stats():
    stats = read_stats()
    total = stats["total_trades"]
    if total > 0:
        stats["win_rate"] = round((stats["winning_trades"] / total) * 100, 2)
    else:
        stats["win_rate"] = 0
    return stats


def write_learning(lesson_text, category="general", trade_id=None):
    trade_ref = f" [Trade #{trade_id}]" if trade_id else ""
    new_lesson = f"[{category}]{trade_ref} {datetime.now().strftime('%Y-%m-%d %H:%M')}: {lesson_text}\n"
    with open(LEARNINGS_FILE, 'a') as f:
        f.write(new_lesson)


def get_all_learnings():
    if LEARNINGS_FILE.exists():
        with open(LEARNINGS_FILE, 'r') as f:
            return f.read()
    return ""


def get_recent_learnings(limit=10):
    all_learnings = get_all_learnings().strip().split('\n')
    return '\n'.join(all_learnings[-limit:])


def get_open_trades():
    trades = read_ledger()
    return [t for t in trades if t["status"] == "open"]


def get_recent_ledger(limit=10):
    trades = read_ledger()
    closed = [t for t in trades if t["status"] == "closed"]
    return list(reversed(closed))[:limit]


def get_trade_by_id(trade_id):
    trades = read_ledger()
    for t in trades:
        if t["trade_id"] == trade_id:
            return t
    return None


def test_bot():
    print("Testing enhanced memory system...\n")
    stats = get_stats()
    print(f"Current Stats: {json.dumps(stats, indent=2)}\n")
    trade_id = log_new_trade(
        "BTCUSDT", "BUY", 66000, 0.001, 
        "Test trade with risk management",
        stop_loss=65000, take_profit=68000
    )
    print(f"Opened trade #{trade_id} with SL/TP")
    closed = close_trade(trade_id, 66500, "test")
    print(f"Closed trade: PnL = {closed['pnl']:.4f} ({closed['pnl_percent']:.2f}%)")
    write_learning("Test learning with category", category="test", trade_id=trade_id)
    print(f"\nUpdated Stats: {json.dumps(get_stats(), indent=2)}")
    print(f"\nRecent Learnings:\n{get_recent_learnings(5)}")


if __name__ == "__main__":
    test_bot()
