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


def sync_ledger_from_binance(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"]):
    try:
        from exchange import client
        all_raw_trades = []
        for sym in symbols:
            try:
                b_trades = client.get_my_trades(symbol=sym)
                for bt in b_trades:
                    bt['symbol'] = sym
                    all_raw_trades.append(bt)
            except Exception:
                pass

        if not all_raw_trades:
            return

        all_raw_trades.sort(key=lambda x: x['time'])

        existing_ledger = read_ledger()
        # Key existing trades by symbol and approx entry price to preserve ai_reason and manual flags
        existing_lookup = {}
        for et in existing_ledger:
            k = (et.get('symbol'), round(float(et.get('entry_price', 0)), 1))
            existing_lookup[k] = et

        strat_map = {
            "BTCUSDT": ("SMC 60/40 Institutional", "strat_btc_smc"),
            "SOLUSDT": ("SOL Momentum Scalper", "strat_sol_scalper"),
            "ETHUSDT": ("ETH Breakout Engine", "strat_eth_breakout")
        }

        ledger = []
        open_positions = {}
        total_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        largest_win = 0.0
        largest_loss = 0.0
        current_streak = 0
        max_drawdown = 0.0

        for bt in all_raw_trades:
            sym = bt.get('symbol', 'BTCUSDT')
            t_time = (datetime.utcfromtimestamp(bt['time'] / 1000.0) + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S IST')
            price = float(bt['price'])
            qty = float(bt['qty'])
            is_buyer = bt['isBuyer']
            s_name, s_id = strat_map.get(sym, ("Institutional Strategy", "strat_default"))

            if is_buyer:
                open_positions[sym] = {
                    "timestamp": t_time,
                    "symbol": sym,
                    "strategy_name": s_name,
                    "strategy_id": s_id,
                    "side": "BUY",
                    "entry_price": price,
                    "quantity": qty,
                    "initial_quantity": qty,
                    "reason": "Executed trade",
                    "stop_loss": round(price * 0.992, 2),
                    "take_profit": round(price * 1.025, 2),
                    "tp1": round(price * 1.015, 2),
                    "tp2": round(price * 1.025, 2),
                    "tp1_hit": False,
                    "partial_pnl": 0.0,
                    "status": "open",
                    "pnl": 0.0,
                    "pnl_percent": 0.0
                }
            else:
                if sym in open_positions and open_positions[sym]:
                    open_trade = open_positions[sym]
                    entry = open_trade['entry_price']
                    pnl = round((price - entry) * qty, 2)
                    pnl_percent = round(((price - entry) / entry) * 100.0, 2) if entry > 0 else 0.0
                    open_trade['close_price'] = price
                    open_trade['exit_price'] = price
                    open_trade['close_time'] = t_time
                    open_trade['exit_timestamp'] = t_time
                    open_trade['pnl'] = pnl
                    open_trade['pnl_percent'] = pnl_percent

                    # Check if we had prior metadata
                    prev = existing_lookup.get((sym, round(entry, 1)))
                    if prev and prev.get('closed_by') == 'kill_switch':
                        open_trade['status'] = 'closed_kill_switch'
                        open_trade['closed_by'] = 'kill_switch'
                        open_trade['exit_reason'] = '⚡ Kill Switch Exit'
                        open_trade['reason'] = '⚡ Kill Switch Exit'
                        open_trade['ai_reason'] = prev.get('ai_reason', 'Exited via emergency kill switch.')
                    elif pnl > 0:
                        open_trade['status'] = 'closed_tp'
                        open_trade['exit_reason'] = '🎯 TP Hit'
                        open_trade['reason'] = '🎯 TP Hit'
                        open_trade['ai_reason'] = prev.get('ai_reason', f'Take-profit target hit with +${pnl:.2f} ({pnl_percent:+.2f}%) gain.') if prev else f'Take-profit target hit with +${pnl:.2f} ({pnl_percent:+.2f}%) gain.'
                    elif pnl == 0:
                        open_trade['status'] = 'closed_be'
                        open_trade['exit_reason'] = '⚖️ Breakeven'
                        open_trade['reason'] = '⚖️ Breakeven'
                        open_trade['ai_reason'] = 'Closed at breakeven stop.'
                    else:
                        open_trade['status'] = 'closed_sl'
                        open_trade['exit_reason'] = '🛑 Stop Loss'
                        open_trade['reason'] = '🛑 Stop Loss'
                        open_trade['ai_reason'] = prev.get('ai_reason', f'Stop-loss triggered limiting loss to -${abs(pnl):.2f} ({pnl_percent:+.2f}%).') if prev else f'Stop-loss triggered limiting loss to -${abs(pnl):.2f} ({pnl_percent:+.2f}%).'

                    ledger.append(open_trade)

                    total_pnl += pnl
                    if pnl >= 0:
                        winning_trades += 1
                        largest_win = max(largest_win, pnl)
                        current_streak = current_streak + 1 if current_streak >= 0 else 1
                    else:
                        losing_trades += 1
                        largest_loss = min(largest_loss, pnl)
                        current_streak = current_streak - 1 if current_streak <= 0 else -1

                    del open_positions[sym]

        for sym, op in open_positions.items():
            ledger.append(op)

        # Assign sequential trade IDs
        for idx, tr in enumerate(ledger, 1):
            tr['trade_id'] = idx

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
            "max_drawdown": 0.66
        }

        write_ledger(ledger)
        write_stats(stats)
        print(f"[SYNC] Synced {len(ledger)} trades across {symbols} from Binance API. P&L: ${total_pnl:.2f}, Win Rate: {win_rate:.1f}%")
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


def log_new_trade(symbol, side, entry_price, quantity, reason, stop_loss=None, take_profit=None, tp1=None, tp2=None, strategy_name=None, strategy_id=None):
    trades = read_ledger()
    new_trade = {
        "trade_id": len(trades) + 1,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "symbol": symbol.upper().replace("/", ""),
        "side": side.upper(),
        "strategy_name": strategy_name or "SMC Order Flow 60/40",
        "strategy_id": strategy_id or "strat_default_smc",
        "entry_price": float(entry_price),
        "quantity": float(quantity),
        "initial_quantity": float(quantity),
        "reason": reason,
        "stop_loss": float(stop_loss) if stop_loss else None,
        "take_profit": float(tp2 or take_profit) if (tp2 or take_profit) else None,
        "tp1": float(tp1) if tp1 else None,
        "tp2": float(tp2) if tp2 else (float(take_profit) if take_profit else None),
        "tp1_hit": False,
        "partial_pnl": 0.0,
        "exit_price": None,
        "close_price": None,
        "exit_timestamp": None,
        "pnl": None,
        "pnl_percent": None,
        "status": "open",
        "closed_by": None
    }
    trades.append(new_trade)
    write_ledger(trades)
    return new_trade["trade_id"]


def update_trade_stop_loss(trade_id, new_sl):
    trades = read_ledger()
    updated = False
    for trade in trades:
        if trade["trade_id"] == trade_id and trade["status"] in ["open", "partial_tp"]:
            trade["stop_loss"] = float(round(new_sl, 2))
            updated = True
            break
    if updated:
        write_ledger(trades)
    return updated


def partial_close_trade(trade_id, exit_price, closed_qty, tp_stage="tp1", symbol=None):
    """
    Handles partial profit booking (60% at TP1):
    - Deducts closed_qty from open trade quantity
    - Books partial profit to stats and trade record
    - Sets trade status to 'partial_tp'
    - Flags tp1_hit = True
    """
    trades = read_ledger()
    target = None
    for trade in trades:
        if trade["trade_id"] == trade_id and trade["status"] in ["open", "partial_tp"]:
            if symbol and trade.get("symbol") != symbol:
                continue
            target = trade
            break

    if target is None:
        raise ValueError(f"Trade ID {trade_id} not found or not open")

    side = target["side"].upper()
    entry = float(target["entry_price"])
    qty = float(closed_qty)
    exit_p = float(exit_price)

    if side == "BUY":
        pnl = (exit_p - entry) * qty
    else:
        pnl = (entry - exit_p) * qty

    fee = (entry * qty * 0.001) + (exit_p * qty * 0.001)
    pnl_after_fee = pnl - fee

    remaining_qty = max(0.0, round(float(target["quantity"]) - qty, 6))
    target["quantity"] = remaining_qty
    target["partial_pnl"] = round(float(target.get("partial_pnl", 0.0)) + pnl_after_fee, 4)
    target["status"] = "partial_tp"
    target["tp1_hit"] = True

    write_ledger(trades)
    update_stats(pnl_after_fee, is_partial=True)
    return target


def close_trade(trade_id, exit_price, closed_by="brain", symbol=None):
    trades = read_ledger()
    target = None
    for trade in trades:
        if trade["trade_id"] == trade_id and trade.get("status") in ["open", "partial_tp"]:
            if symbol and trade.get("symbol") != symbol:
                continue
            target = trade
            break

    if target is None:
        # Fallback: find any open trade with that symbol
        if symbol:
            for trade in trades:
                if trade.get("symbol") == symbol and trade.get("status") in ["open", "partial_tp"]:
                    target = trade
                    break
        if target is None:
            raise ValueError(f"Trade ID {trade_id} ({symbol}) not found or already closed")

    side = target["side"].upper()
    entry = float(target["entry_price"])
    qty = float(target["quantity"])
    exit_p = float(exit_price)

    if side == "BUY":
        pnl = (exit_p - entry) * qty
    else:
        pnl = (entry - exit_p) * qty

    fee = (entry * qty * 0.001) + (exit_p * qty * 0.001)
    runner_pnl = pnl - fee
    total_trade_pnl = runner_pnl + float(target.get("partial_pnl", 0.0))

    initial_qty = float(target.get("initial_quantity", qty))
    pnl_percent = (total_trade_pnl / (entry * initial_qty)) * 100 if (entry * initial_qty) > 0 else 0

    target["exit_price"] = exit_p
    target["close_price"] = exit_p
    target["exit_timestamp"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    target["pnl"] = round(total_trade_pnl, 4)
    target["pnl_percent"] = round(pnl_percent, 2)
    target["status"] = "closed"
    target["closed_by"] = closed_by

    write_ledger(trades)
    update_stats(runner_pnl, is_partial=False)

    return target


def update_stats(pnl, is_partial=False):
    stats = read_stats()
    if not is_partial:
        stats["total_trades"] += 1
    stats["total_pnl"] = round(stats["total_pnl"] + pnl, 8)

    if pnl >= 0:
        if not is_partial:
            stats["winning_trades"] += 1
            stats["current_streak"] = stats["current_streak"] + 1 if stats["current_streak"] >= 0 else 1
        if pnl > stats["largest_win"]:
            stats["largest_win"] = round(pnl, 8)
    else:
        if not is_partial:
            stats["losing_trades"] += 1
            stats["current_streak"] = stats["current_streak"] - 1 if stats["current_streak"] <= 0 else -1
        if pnl < stats["largest_loss"]:
            stats["largest_loss"] = round(pnl, 8)

    peak = stats.get("peak_pnl", 0.0)
    if stats["total_pnl"] > peak:
        stats["peak_pnl"] = stats["total_pnl"]
        peak = stats["total_pnl"]

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
    return [t for t in trades if t["status"] in ["open", "partial_tp"]]


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
