import json
import os
from pathlib import Path
from datetime import datetime

LEDGER_FILE = Path("ledger.json")
LEARNINGS_FILE = Path("learnings.txt")
STATS_FILE = Path("stats.json")


def read_ledger():
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE, 'r') as f:
            return json.load(f)
    return []


def write_ledger(trades):
    with open(LEDGER_FILE, 'w') as f:
        json.dump(trades, f, indent=2)


def read_stats():
    if STATS_FILE.exists():
        with open(STATS_FILE, 'r') as f:
            return json.load(f)
    return {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_pnl": 0.0,
        "largest_win": 0.0,
        "largest_loss": 0.0,
        "current_streak": 0,  # Positive = win streak, Negative = loss streak
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
        "symbol": symbol.upper().replace("/", ""),  # Normalize: BTC/USDT -> BTCUSDT
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
        "closed_by": None  # 'brain', 'stop_loss', 'take_profit'
    }
    trades.append(new_trade)
    write_ledger(trades)
    return new_trade["trade_id"]


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

    # FIX: Case-insensitive side check
    side = target["side"].upper()
    entry = float(target["entry_price"])
    qty = float(target["quantity"])
    exit_p = float(exit_price)
    
    # Calculate PnL
    if side == "BUY":
        pnl = (exit_p - entry) * qty
        pnl_percent = ((exit_p - entry) / entry) * 100
    else:  # SELL
        pnl = (entry - exit_p) * qty
        pnl_percent = ((entry - exit_p) / entry) * 100

    # Deduct Binance fee (0.1% per side = 0.2% total)
    fee = (entry * qty * 0.001) + (exit_p * qty * 0.001)
    pnl_after_fee = pnl - fee

    target["exit_price"] = exit_p
    target["exit_timestamp"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    target["pnl"] = round(pnl_after_fee, 8)
    target["pnl_percent"] = round(pnl_percent, 4)
    target["status"] = "closed"
    target["closed_by"] = closed_by

    write_ledger(trades)
    
    # Update stats
    update_stats(pnl_after_fee)
    
    return target


def update_stats(pnl):
    """Update trading statistics"""
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
    
    # Calculate max drawdown
    peak = max(0, stats["total_pnl"])
    if stats["total_pnl"] < peak:
        drawdown = peak - stats["total_pnl"]
        if drawdown > stats["max_drawdown"]:
            stats["max_drawdown"] = round(drawdown, 8)
    
    write_stats(stats)


def get_stats():
    """Get formatted stats"""
    stats = read_stats()
    total = stats["total_trades"]
    if total > 0:
        stats["win_rate"] = round((stats["winning_trades"] / total) * 100, 2)
    else:
        stats["win_rate"] = 0
    return stats


def write_learning(lesson_text, category="general", trade_id=None):
    """Structured learning with category"""
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
    """Get last N learnings"""
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
    
    # Test stats
    stats = get_stats()
    print(f"Current Stats: {json.dumps(stats, indent=2)}\n")
    
    # Test trade with stop loss
    trade_id = log_new_trade(
        "BTCUSDT", "BUY", 66000, 0.001, 
        "Test trade with risk management",
        stop_loss=65000, take_profit=68000
    )
    print(f"Opened trade #{trade_id} with SL/TP")
    
    # Close trade
    closed = close_trade(trade_id, 66500, "test")
    print(f"Closed trade: PnL = {closed['pnl']:.4f} ({closed['pnl_percent']:.2f}%)")
    
    # Write learning
    write_learning("Test learning with category", category="test", trade_id=trade_id)
    
    # Show updated stats
    print(f"\nUpdated Stats: {json.dumps(get_stats(), indent=2)}")
    print(f"\nRecent Learnings:\n{get_recent_learnings(5)}")


if __name__ == "__main__":
    test_bot()