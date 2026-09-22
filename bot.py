import json
import time
import datetime
from datetime import datetime, timedelta
from brain import ask_brain
from exchange import place_test_order, get_current_price, test_api_connection, MIN_QTY
from memory import (
    log_new_trade, close_trade, partial_close_trade, write_learning, get_open_trades,
    get_stats, get_trade_by_id, update_trade_stop_loss
)
from strategy import get_enhanced_signal, detect_early_reversal
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SKIP_WEEKEND_TRADING = True

def is_weekend():
    """
    Checks if current UTC time falls in weekend low-liquidity window:
    Friday 22:00 UTC to Sunday 22:00 UTC (Saturday & Sunday).
    During this period, institutional banks and CME futures are closed,
    volume drops 60-70%, leading to choppy retail stop-hunts.
    """
    if not SKIP_WEEKEND_TRADING:
        return False
    now_utc = datetime.utcnow()
    weekday = now_utc.weekday()  # Monday=0, ..., Friday=4, Saturday=5, Sunday=6
    hour = now_utc.hour

    if weekday == 4 and hour >= 22:  # Friday after 22:00 UTC
        return True
    if weekday == 5:                 # Saturday all day
        return True
    if weekday == 6 and hour < 22:   # Sunday before 22:00 UTC
        return True
    return False

def safe_float(val, default=0.0):
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default

DASHBOARD_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background-color: #0b0e14;
    background-image: radial-gradient(circle at 50% 0%, #171d2b 0%, #0b0e14 75%);
    color: #c9d1d9;
    padding: 24px 16px;
    line-height: 1.5;
    min-height: 100vh;
}
.container {
    max-width: 1100px;
    margin: 0 auto;
}
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #151b26;
    border: 1px solid #283347;
    border-radius: 12px;
    padding: 18px 24px;
    margin-bottom: 22px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    flex-wrap: wrap;
    gap: 12px;
}
.badge-live {
    background: rgba(35, 134, 54, 0.2);
    border: 1px solid #238636;
    color: #3fb950;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 700;
}
.badge-pause {
    background: rgba(210, 153, 34, 0.2);
    border: 1px solid #d29922;
    color: #e3b341;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 700;
}
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 16px;
    margin-bottom: 20px;
}
.card {
    background: #151b26;
    border: 1px solid #283347;
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.card:hover {
    border-color: #58a6ff;
    transform: translateY(-2px);
}
.card-title {
    font-size: 12px;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 6px;
    font-weight: 600;
}
.card-value {
    font-size: 24px;
    font-weight: 700;
    color: #f0f6fc;
}
.reason-box {
    background: #151b26;
    border: 1px solid #283347;
    border-left: 4px solid #58a6ff;
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 24px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}
table {
    width: 100%;
    border-collapse: collapse;
    background: #151b26;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #283347;
    font-size: 13.5px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}
th {
    background: #1e2638;
    text-align: left;
    padding: 14px 12px;
    color: #8b949e;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    border-bottom: 1px solid #283347;
}
td {
    padding: 12px 12px;
    border-bottom: 1px solid #1f2738;
}
tr:hover td {
    background: rgba(255, 255, 255, 0.02);
}
"""

def generate_dashboard_html():
    state_file = os.path.join(BASE_DIR, "market_state.json")
    stats_file = os.path.join(BASE_DIR, "stats.json")
    ledger_file = os.path.join(BASE_DIR, "ledger.json")

    state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
        except Exception:
            pass

    stats = {}
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r') as f:
                stats = json.load(f)
        except Exception:
            pass

    ledger = []
    if os.path.exists(ledger_file):
        try:
            with open(ledger_file, 'r') as f:
                ledger = json.load(f)
        except Exception:
            pass

    sym_label = state.get("symbol", PRIMARY_SYMBOL)
    raw_price = state.get('price', 0)
    price = f"${safe_float(raw_price):,.2f}" if raw_price else "N/A"
    signal = state.get("signal", "HOLD")
    score = state.get("score", 50)
    rsi = safe_float(state.get("rsi", 50))
    atr = safe_float(state.get("atr", 0))
    adx = safe_float(state.get("adx", 0))
    vol = safe_float(state.get("volume_ratio", 1))
    action = state.get("action", "HOLD")
    confidence = state.get("confidence", 0)
    reason = state.get("reason", "Market scan active...")
    updated_at = state.get("updated_at", "Just now")

    pnl = safe_float(stats.get("total_pnl", 0.0))
    pnl_color = "#3fb950" if pnl >= 0 else "#f85149"
    pnl_str = f"${pnl:+.2f}"
    win_rate = f"{safe_float(stats.get('win_rate', 0.0)):.1f}%"
    total_trades = stats.get("total_trades", 0)
    streak = stats.get("current_streak", 0)
    streak_str = f"{streak} {'🔥' if streak > 0 else '❄️' if streak < 0 else '➖'}"

    open_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["open", "partial_tp"]]
    weekend_active = is_weekend()
    if open_trades:
        open_trade_html = ""
        for ot in open_trades:
            ot_sym = ot.get('symbol', PRIMARY_SYMBOL)
            ot_entry = safe_float(ot.get('entry_price'))
            ot_sl = safe_float(ot.get('stop_loss'))
            ot_tp1 = safe_float(ot.get('tp1', ot.get('take_profit')))
            ot_tp2 = safe_float(ot.get('tp2', ot.get('take_profit')))
            ot_qty = safe_float(ot.get('quantity', ot.get('qty', 0)))
            is_runner = ot.get('status') == 'partial_tp'
            card_border = "#e3b341" if is_runner else "#238636"
            card_title_color = "#e3b341" if is_runner else "#3fb950"
            card_title = f"🛡️ 60% BOOKED (TP1 HIT) | 40% RISK-FREE RUNNER: {ot.get('side', '').upper()} #{ot.get('trade_id')} ({ot_sym})" if is_runner else f"🟢 ACTIVE POSITION: {ot.get('side', '').upper()} #{ot.get('trade_id')} ({ot_sym})"
            sl_label = "SL (+0.35% Green Lock)" if is_runner else "SL (Structure)"
            sl_color = "#3fb950" if is_runner else "#f85149"

            open_trade_html += f"""
            <div class="card" style="background:#151b26; border:1px solid {card_border}; border-radius:12px; padding:20px; margin-bottom:16px; box-shadow:0 6px 20px rgba(0,0,0,0.3);">
                <div style="color:{card_title_color}; font-weight:bold; font-size:16px; display:flex; align-items:center; gap:8px;">{card_title}</div>
                <div style="margin-top:12px; display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:12px; background:#0d1117; padding:14px; border-radius:8px; border:1px solid #283347;">
                    <div><div style="font-size:11px; color:#8b949e; text-transform:uppercase;">Entry Price</div><div style="font-size:16px; font-weight:bold; color:#f0f6fc;">${ot_entry:,.2f}</div></div>
                    <div><div style="font-size:11px; color:#8b949e; text-transform:uppercase;">{sl_label}</div><div style="font-size:16px; font-weight:bold; color:{sl_color};">${ot_sl:,.2f}</div></div>
                    <div><div style="font-size:11px; color:#8b949e; text-transform:uppercase;">TP1 (60% Target)</div><div style="font-size:16px; font-weight:bold; color:#3fb950;">${ot_tp1:,.2f}</div></div>
                    <div><div style="font-size:11px; color:#8b949e; text-transform:uppercase;">TP2 (40% Target)</div><div style="font-size:16px; font-weight:bold; color:#58a6ff;">${ot_tp2:,.2f}</div></div>
                    <div><div style="font-size:11px; color:#8b949e; text-transform:uppercase;">Quantity</div><div style="font-size:16px; font-weight:bold; color:#f0f6fc;">{ot_qty}</div></div>
                </div>
            </div>
            """
    elif weekend_active:
        open_trade_html = """
        <div class="card" style="background:#1a1710; border:1px solid #d29922; border-radius:10px; padding:16px; margin-bottom:20px; color:#e3b341;">
            ⏸️ <b>WEEKEND PAUSE:</b> Institutional banks & CME futures are closed (Fri 22:00 UTC - Sun 22:00 UTC). Bot has paused new entries to prevent low-liquidity chop losses. Positions management (SL/TP/Breakeven) remains active. Scanning resumes Sunday 22:00 UTC (Monday 03:30 IST).
        </div>
        """
    else:
        open_trade_html = """
        <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:16px; margin-bottom:20px; color:#8b949e;">
            📡 No open positions right now. Scanning BTC, ETH, SOL for 60/40 Liquidity SMC setups...
        </div>
        """

    rows_html = ""
    recent_trades = list(reversed([t for t in ledger if isinstance(t, dict)][-15:]))
    for t in recent_trades:
        status_color = "#3fb950" if t.get('status') == 'closed_tp' else ("#f85149" if t.get('status') == 'closed_sl' else "#58a6ff")
        t_pnl = safe_float(t.get('pnl', 0.0))
        t_price = safe_float(t.get('entry_price', 0.0))
        t_sym = t.get('symbol', 'BTCUSDT')
        pnl_text = f"${t_pnl:+.2f}" if t_pnl != 0 else "-"
        rows_html += f"""
        <tr style="border-bottom:1px solid #1f2738;">
            <td style="padding:12px;">#{t.get('trade_id', '-')}</td>
            <td style="padding:12px; color:#8b949e;">{t.get('timestamp', '')}</td>
            <td style="padding:12px; font-weight:bold; color:#58a6ff;">{t_sym}</td>
            <td style="padding:12px; font-weight:bold; color:{'#3fb950' if t.get('side')=='BUY' else '#f85149'};">{t.get('side', '')}</td>
            <td style="padding:12px;">${t_price:,.2f}</td>
            <td style="padding:12px; color:{status_color}; font-weight:bold;">{t.get('status', '').upper()}</td>
            <td style="padding:12px; font-weight:bold; color:{'#3fb950' if t_pnl>0 else ('#f85149' if t_pnl<0 else '#8b949e')};">{pnl_text}</td>
        </tr>
        """

    if not rows_html:
        rows_html = "<tr><td colspan='7' style='padding:18px; text-align:center; color:#8b949e;'>No trades recorded yet. Bot is scanning market.</td></tr>"

    status_badge = '<span class="badge-pause">⏸️ WEEKEND PAUSED</span>' if weekend_active else '<span class="badge-live">🟢 LIVE 24/7 CLOUD</span>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="20">
    <title>SMC Institutional Trading Bot</title>
    <style>
""" + DASHBOARD_CSS + f"""
    </style>
</head>
<body style="background-color:#0b0e14; color:#c9d1d9; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding:20px; margin:0;">
    <div class="container" style="max-width:1100px; margin:0 auto;">
        <div class="header" style="display:flex; justify-content:space-between; align-items:center; background:#151b26; border:1px solid #283347; border-radius:12px; padding:18px 24px; margin-bottom:20px;">
            <div>
                <h2 style="margin:0; color:#f0f6fc; font-size:22px; display:flex; align-items:center; gap:10px;">
                    🤖 SMC Institutional Trading Bot
                </h2>
                <div style="font-size:13px; color:#8b949e; margin-top:5px;">
                    1H Fib Golden Zone (0.618-0.786) • 5m FVG • 60/40 Liquidity Targeting
                </div>
            </div>
            <div style="text-align:right;">
                {status_badge}
                <div style="font-size:11px; color:#8b949e; margin-top:6px;">Updated: {updated_at}</div>
            </div>
        </div>

        <div class="grid" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:15px; margin-bottom:20px;">
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px; box-shadow:0 4px 12px rgba(0,0,0,0.25);">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">{sym_label} Price</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:#58a6ff;">{price}</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Binance Spot Market Price</div>
            </div>
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px; box-shadow:0 4px 12px rgba(0,0,0,0.25);">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">SMC Confluence Score</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:#f0f6fc;">{score} <span style="font-size:14px; color:#8b949e;">/ 100</span></div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Golden Zone + FVG + Volume</div>
            </div>
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px; box-shadow:0 4px 12px rgba(0,0,0,0.25);">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">Brain AI Action</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:{'#3fb950' if action=='BUY' else ('#f85149' if action=='SELL' else '#e3b341')};">{action} ({confidence}/10)</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Groq LLM Confirmation</div>
            </div>
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px; box-shadow:0 4px 12px rgba(0,0,0,0.25);">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">Total Realized P&L</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:{pnl_color};">{pnl_str}</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Across BTC, ETH & SOL</div>
            </div>
        </div>

        <div class="grid" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:15px; margin-bottom:20px;">
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px;">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">Win Rate</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:#f0f6fc;">{win_rate}</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Target: 75-80% Asymmetric R:R</div>
            </div>
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px;">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">Total Trades</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:#f0f6fc;">{total_trades}</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Binance Testnet Synced</div>
            </div>
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px;">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">Current Streak</div>
                <div class="card-value" style="font-size:24px; font-weight:bold; color:#f0f6fc;">{streak_str}</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">Consecutive Wins/Losses</div>
            </div>
            <div class="card" style="background:#151b26; border:1px solid #283347; border-radius:10px; padding:18px;">
                <div class="card-title" style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px;">Technical Gauges</div>
                <div class="card-value" style="font-size:18px; font-weight:bold; color:#f0f6fc; margin-top:4px;">RSI: {rsi} | ATR: {atr}</div>
                <div style="font-size:11px; color:#8b949e; margin-top:4px;">5m Volatility & Momentum</div>
            </div>
        </div>

        {open_trade_html}

        <div class="reason-box" style="background:#151b26; border:1px solid #283347; border-left:4px solid #58a6ff; border-radius:10px; padding:18px 22px; margin-bottom:24px;">
            <div style="font-size:12px; color:#58a6ff; text-transform:uppercase; font-weight:bold; margin-bottom:6px; letter-spacing:0.5px;">
                🧠 Latest AI Brain Market Analysis
            </div>
            <div style="color:#f0f6fc; font-size:14px; line-height:1.6;">
                {reason}
            </div>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h3 style="color:#f0f6fc; margin:0; font-size:18px;">📋 Trade & Activity History</h3>
            <span style="font-size:12px; color:#8b949e;">Live Binance Testnet Ledger</span>
        </div>
        <div style="background:#151b26; border:1px solid #283347; border-radius:10px; overflow-x:auto; box-shadow:0 4px 12px rgba(0,0,0,0.2);">
            <table style="width:100%; border-collapse:collapse; text-align:left; font-size:13px;">
                <thead>
                    <tr style="background:#1e2638; border-bottom:1px solid #283347;">
                        <th style="padding:12px 14px; color:#8b949e;">ID</th>
                        <th style="padding:12px 14px; color:#8b949e;">Timestamp</th>
                        <th style="padding:12px 14px; color:#8b949e;">Pair</th>
                        <th style="padding:12px 14px; color:#8b949e;">Side</th>
                        <th style="padding:12px 14px; color:#8b949e;">Price</th>
                        <th style="padding:12px 14px; color:#8b949e;">Status</th>
                        <th style="padding:12px 14px; color:#8b949e;">P&L</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
    return html

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        try:
            dashboard_content = generate_dashboard_html()
            self.wfile.write(dashboard_content.encode('utf-8'))
        except Exception as e:
            self.wfile.write(f"OK - Bot Active (Dashboard error: {e})".encode('utf-8'))

    def log_message(self, format, *args):
        pass

def start_health_server():
    try:
        port = int(os.environ.get("PORT", 10000))
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        print(f"[HEALTH] HTTP Health Check Server running on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"[HEALTH] Warning: Could not start HTTP server: {e}")

threading.Thread(target=start_health_server, daemon=True).start()

def write_market_state(signal_data, current_price, brain_decision):
    try:
        state_file = os.path.join(BASE_DIR, "market_state.json")
        data = {
            "symbol": signal_data.get("symbol", PRIMARY_SYMBOL),
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
            "updated_at": (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST")
        }
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[BOT] Warning: Failed to write market_state.json: {e}")

# ====== LOGGING SETUP (File + Console both) ======
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

log_path = os.path.join(BASE_DIR, "bot.log")

file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ====== CONFIGURATION ======
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PRIMARY_SYMBOL = "BTCUSDT"
SYMBOL = PRIMARY_SYMBOL
CHECK_INTERVAL_SECONDS = 300
MAX_TRADES_PER_DAY = 10
LOSS_COOLDOWN_SECONDS = 1800    # 30-min cooldown after a loss (bypassed if Grade-A+ setup)
PROFIT_COOLDOWN_SECONDS = 60    # 60-second safety buffer after a win
MIN_CONFIDENCE = 6
MAX_DRAWDOWN_USD = 10.0
MAX_OPEN_POSITIONS = 3

TARGET_NOTIONAL_USD = 15.0      # $15 entry -> 60% is $9.00, 40% is $6.00 (Both > $5 Binance MIN_NOTIONAL)

# State tracking
trades_today = 0
last_trade_time = None
last_trade_was_loss = False
last_reset_date = None

def get_position_size(symbol, entry_price, stop_loss, confidence):
    """
    Sizes position to approximately $15.00 notional:
    - 60% partial exit at TP1 = ~$9.00 (satisfies Binance $5 minNotional)
    - 40% runner exit at TP2 = ~$6.00 (satisfies Binance $5 minNotional)
    """
    raw_qty = TARGET_NOTIONAL_USD / entry_price

    if "BTC" in symbol:
        position_size = round(raw_qty, 5)
    elif "ETH" in symbol:
        position_size = round(raw_qty, 4)
    elif "SOL" in symbol:
        position_size = round(raw_qty, 2)
    else:
        position_size = round(raw_qty, 4)

    if position_size < MIN_QTY:
        position_size = MIN_QTY

    print(f"[POSITION] {symbol} Entry: ${entry_price:.2f}, SL: ${stop_loss:.2f}, Size: {position_size} (~${position_size * entry_price:.2f} USD)")
    return position_size


def manage_open_positions():
    global last_trade_time, last_trade_was_loss
    open_trades = get_open_trades()
    for trade in open_trades:
        trade_id = trade["trade_id"]
        t_sym = trade.get("symbol", PRIMARY_SYMBOL)
        status = trade.get("status", "open")
        tp1_hit = trade.get("tp1_hit", False)

        try:
            current_price = get_current_price(t_sym)
        except Exception:
            continue

        entry = float(trade["entry_price"])
        sl = float(trade["stop_loss"]) if trade.get("stop_loss") else None
        side = trade["side"].upper()
        # Ensure robust TP1 and TP2 targets even if missing in old records
        tp1 = float(trade.get("tp1")) if trade.get("tp1") else (round(entry * 1.015, 2) if side == "BUY" else round(entry * 0.985, 2))
        tp2 = float(trade.get("tp2") or trade.get("take_profit")) if (trade.get("tp2") or trade.get("take_profit")) else (round(entry * 1.025, 2) if side == "BUY" else round(entry * 0.975, 2))
        current_qty = float(trade["quantity"])

        if side == "BUY":
            # 1. Direct Stop Loss Hit
            if sl and current_price <= sl:
                logger.info(f"STOP LOSS HIT | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} | SL: ${sl:.2f}")
                close_open_position(trade, current_price, "Stop Loss hit", "stop_loss", is_loss=True)
                continue

            # 2. Direct TP2 Hit -> Price exceeded full major liquidity target, bank 100% full profit!
            if tp2 and current_price >= tp2:
                logger.info(f"🏆 FULL TP2 HIT (Major Liquidity Sweep) | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} >= TP2: ${tp2:.2f}")
                close_open_position(trade, current_price, "TP2 Major Liquidity hit", "take_profit", is_loss=False)
                continue

            # 3. Runner Management (if TP1 was already taken)
            if tp1_hit:
                # Early Structure Reversal Exit (Securing floating profit)
                if detect_early_reversal(t_sym, "BUY"):
                    logger.info(f"⚠️ EARLY REVERSAL DETECTED | Trade #{trade_id} ({t_sym}) | Closing runner early at ${current_price:.2f} to secure profit!")
                    close_open_position(trade, current_price, "Early Structure Reversal exit", "early_reversal", is_loss=False)
                    continue

                # Protected Green SL Hit (Price pulled back to Entry + 0.35%)
                if sl and current_price <= sl:
                    logger.info(f"🛡️ PROTECTED GREEN STOP HIT | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} | SL: ${sl:.2f} (Green Win)")
                    close_open_position(trade, current_price, "Protected Green SL hit", "protected_green_sl", is_loss=False)
                    continue

            # 4. Take Profit 1 Hit (Nearest Liquidity -> Book 60%)
            elif tp1 and current_price >= tp1:
                logger.info(f"🎯 TP1 HIT (Nearest Liquidity) | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} | TP1: ${tp1:.2f}")
                if "BTC" in t_sym:
                    close_qty = round(current_qty * 0.60, 5)
                elif "ETH" in t_sym:
                    close_qty = round(current_qty * 0.60, 4)
                elif "SOL" in t_sym:
                    close_qty = round(current_qty * 0.60, 2)
                else:
                    close_qty = round(current_qty * 0.60, 4)

                rem_qty = round(current_qty - close_qty, 6)
                if close_qty * current_price >= 5.0 and rem_qty * current_price >= 5.0:
                    try:
                        place_test_order(symbol=t_sym, side="SELL", quantity=close_qty)
                        partial_close_trade(trade_id, current_price, close_qty, tp_stage="tp1", symbol=t_sym)
                        
                        # Shift remaining 40% SL to Protected Green Lock (Entry + 0.35%)
                        green_sl = round(entry * 1.0035, 2)
                        update_trade_stop_loss(trade_id, green_sl)
                        logger.info(f"🛡️ PROTECTED GREEN LOCK | Trade #{trade_id} ({t_sym}) | Booked 60% ({close_qty}) | Runner SL set to +0.35% Green (${green_sl:.2f})")
                        write_learning(f"Trade #{trade_id} ({t_sym}): Booked 60% at TP1 (${current_price:.2f}). Protected Green SL set to ${green_sl:.2f}.", category="partial_tp", trade_id=trade_id)
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to execute partial TP1 for {t_sym}: {e}")
                else:
                    close_open_position(trade, current_price, "Take Profit 1 hit", "take_profit", is_loss=False)
                continue

        else:  # SELL Position
            # 1. Direct Stop Loss Hit
            if sl and current_price >= sl:
                logger.info(f"STOP LOSS HIT | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} | SL: ${sl:.2f}")
                close_open_position(trade, current_price, "Stop Loss hit", "stop_loss", is_loss=True)
                continue

            # 2. Direct TP2 Hit -> Bank 100% full profit!
            if tp2 and current_price <= tp2:
                logger.info(f"🏆 FULL TP2 HIT (Major Liquidity Sweep) | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} <= TP2: ${tp2:.2f}")
                close_open_position(trade, current_price, "TP2 Major Liquidity hit", "take_profit", is_loss=False)
                continue

            # 3. Runner Management
            if tp1_hit:
                if detect_early_reversal(t_sym, "SELL"):
                    logger.info(f"⚠️ EARLY REVERSAL DETECTED | Trade #{trade_id} ({t_sym}) | Closing runner early at ${current_price:.2f} to secure profit!")
                    close_open_position(trade, current_price, "Early Structure Reversal exit", "early_reversal", is_loss=False)
                    continue

                if sl and current_price >= sl:
                    logger.info(f"🛡️ PROTECTED GREEN STOP HIT | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} | SL: ${sl:.2f} (Green Win)")
                    close_open_position(trade, current_price, "Protected Green SL hit", "protected_green_sl", is_loss=False)
                    continue

            # 4. Take Profit 1 Hit
            elif tp1 and current_price <= tp1:
                logger.info(f"🎯 TP1 HIT (Nearest Liquidity) | Trade #{trade_id} ({t_sym}) | Price: ${current_price:.2f} | TP1: ${tp1:.2f}")
                if "BTC" in t_sym:
                    close_qty = round(current_qty * 0.60, 5)
                elif "ETH" in t_sym:
                    close_qty = round(current_qty * 0.60, 4)
                elif "SOL" in t_sym:
                    close_qty = round(current_qty * 0.60, 2)
                else:
                    close_qty = round(current_qty * 0.60, 4)

                rem_qty = round(current_qty - close_qty, 6)
                if close_qty * current_price >= 5.0 and rem_qty * current_price >= 5.0:
                    try:
                        place_test_order(symbol=t_sym, side="BUY", quantity=close_qty)
                        partial_close_trade(trade_id, current_price, close_qty, tp_stage="tp1", symbol=t_sym)
                        
                        green_sl = round(entry * 0.9965, 2)
                        update_trade_stop_loss(trade_id, green_sl)
                        logger.info(f"🛡️ PROTECTED GREEN LOCK | Trade #{trade_id} ({t_sym}) | Booked 60% ({close_qty}) | Runner SL set to -0.35% Green (${green_sl:.2f})")
                        write_learning(f"Trade #{trade_id} ({t_sym}): Booked 60% at TP1 (${current_price:.2f}). Protected Green SL set to ${green_sl:.2f}.", category="partial_tp", trade_id=trade_id)
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to execute partial TP1 for {t_sym}: {e}")
                else:
                    close_open_position(trade, current_price, "Take Profit 1 hit", "take_profit", is_loss=False)
                continue


def close_open_position(open_trade, current_price, reason, closed_by="brain", is_loss=False):
    global last_trade_time, last_trade_was_loss
    trade_symbol = open_trade.get("symbol", PRIMARY_SYMBOL)
    opposite_side = "SELL" if open_trade["side"].upper() == "BUY" else "BUY"
    try:
        order = place_test_order(symbol=trade_symbol, side=opposite_side, quantity=open_trade["quantity"])
        closed = close_trade(open_trade["trade_id"], current_price, closed_by, symbol=trade_symbol)
        pnl = closed["pnl"]
        pnl_pct = closed.get("pnl_percent", 0)
        outcome = "[PROFIT]" if pnl >= 0 else "[LOSS]"
        logger.info(f"CLOSED | Trade #{open_trade['trade_id']} ({trade_symbol}) | {outcome} ${pnl:.4f} ({pnl_pct:.2f}%) | {closed_by}")
        lesson = (f"Trade #{open_trade['trade_id']} ({trade_symbol} {open_trade['side']} ${open_trade['entry_price']}) "
                  f"closed at ${current_price}. Result: {outcome} ${abs(pnl):.4f}. "
                  f"Original: {open_trade['reason']}. Close reason: {reason}")
        write_learning(lesson, category="trade_close", trade_id=open_trade['trade_id'])
        last_trade_time = datetime.now()
        last_trade_was_loss = bool(is_loss or pnl < 0)
        return True
    except Exception as e:
        logger.error(f"[ERROR] Failed to close position for {trade_symbol}: {e}")
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
    global trades_today, last_trade_time, last_trade_was_loss
    reset_daily_limits()

    # 1. Manage all open positions first (always active: TP1/TP2/Green Lock)
    manage_open_positions()

    # 2. Weekend Filter: Skip new entries if institutional markets closed
    if is_weekend():
        logger.info("⏸️ WEEKEND PAUSE: Institutions Closed (Fri 22:00 UTC - Sun 22:00 UTC). Skipping new entries to avoid low-volume chop.")
        return

    # 3. Dynamic Cooldown Status
    active_cooldown = LOSS_COOLDOWN_SECONDS if last_trade_was_loss else PROFIT_COOLDOWN_SECONDS
    time_since_last_trade = (datetime.now() - last_trade_time).total_seconds() if last_trade_time else 999999
    is_in_cooldown = time_since_last_trade < active_cooldown

    open_trades = get_open_trades()
    open_symbols = [t.get("symbol") for t in open_trades if t.get("status") in ["open", "partial_tp"]]
    stats = get_stats()

    # Always write current market state for PRIMARY_SYMBOL so dashboard never freezes
    try:
        btc_price = get_current_price(PRIMARY_SYMBOL)
        sig = get_enhanced_signal(PRIMARY_SYMBOL)
        fallback_action = "ACTIVE" if open_trades else "SCAN"
        fallback_reason = f"{len(open_trades)} positions active: {', '.join(open_symbols)}" if open_trades else "Active 5m SMC scanning..."
        write_market_state(sig, btc_price, {"action": fallback_action, "confidence": 5, "reason": fallback_reason})
    except Exception as e:
        logger.warning(f"Could not update dashboard market state: {e}")

    if len(open_trades) >= MAX_OPEN_POSITIONS:
        logger.info(f"Max open positions reached ({len(open_trades)}/{MAX_OPEN_POSITIONS}): {open_symbols}. Managing active positions.")
        return

    # 4. Multi-Symbol Scanning: BTCUSDT, ETHUSDT, SOLUSDT
    for sym in SYMBOLS:
        if sym in open_symbols:
            continue

        try:
            signal_data = get_enhanced_signal(sym)
            signal = signal_data["signal"]
            score = signal_data["score"]
            current_price = signal_data["current_price"]

            brain_input = {
                "symbol": sym,
                "signal": signal,
                "score": score,
                "price": current_price,
                "stats": stats,
                "open_positions": len(open_trades)
            }

            brain_decision = ask_brain(brain_input, symbol=sym)
            if not isinstance(brain_decision, dict):
                brain_decision = {"action": "HOLD", "confidence": 0, "reason": "Invalid brain response"}

            action = brain_decision.get("action", "HOLD")
            confidence = brain_decision.get("confidence", 0)
            reason = brain_decision.get("reason", "")

            # Write primary state for live dashboard
            if sym == PRIMARY_SYMBOL or action in ["BUY", "SELL"]:
                write_market_state(signal_data, current_price, brain_decision)

            logger.info("=" * 50)
            logger.info(f"SCAN | {sym} | ${current_price:,.2f} | Score: {score}/100 | Brain: {action} ({confidence}/10)")

            if action == "HOLD":
                continue
            if confidence < MIN_CONFIDENCE:
                logger.info(f"DECISION ({sym}): NO TRADE | Confidence too low ({confidence}/{MIN_CONFIDENCE})")
                continue

            # Opportunity Cooldown Check:
            # If in cooldown, allow trade ONLY if it's a Grade-A+ setup (Score >= 80 and Confidence >= 8)
            if is_in_cooldown:
                if score >= 80 and confidence >= 8:
                    logger.info(f"🚀 GRADE-A+ OPPORTUNITY OVERRIDE ({sym}): High conviction setup (Score: {score}, Conf: {confidence}). Bypassing cooldown to seize opportunity!")
                else:
                    rem = int(active_cooldown - time_since_last_trade)
                    logger.info(f"⏳ COOLDOWN ACTIVE ({sym}): {rem}s remaining after loss. Skipping setup.")
                    continue

            if trades_today >= MAX_TRADES_PER_DAY:
                logger.info(f"DECISION ({sym}): NO TRADE | Daily limit reached ({trades_today}/{MAX_TRADES_PER_DAY})")
                break
            total_pnl = stats.get("total_pnl", 0)
            if total_pnl < -MAX_DRAWDOWN_USD:
                logger.info(f"DECISION ({sym}): NO TRADE | Max drawdown exceeded (${total_pnl:.2f})")
                break

            if action in ["BUY", "SELL"]:
                if action == "SELL" and len(open_trades) == 0:
                    logger.info(f"DECISION ({sym}): NO TRADE | Spot trading: Cannot open SELL short without holding base asset.")
                    continue

                stop_loss = signal_data.get("structure_sl")
                tp1 = signal_data.get("tp1")
                tp2 = signal_data.get("tp2")

                position_size = get_position_size(sym, current_price, stop_loss, confidence)

                print(f"[BOT] Executing {action} on {sym} | Price: ${current_price:,.2f} | Qty: {position_size} | TP1: ${tp1:.2f} | TP2: ${tp2:.2f} | SL: ${stop_loss:.2f}")
                order = place_test_order(symbol=sym, side=action, quantity=position_size)
                trade_id = log_new_trade(
                    symbol=sym, side=action, entry_price=current_price,
                    quantity=position_size, reason=reason,
                    stop_loss=stop_loss, take_profit=tp2,
                    tp1=tp1, tp2=tp2
                )
                trades_today += 1
                last_trade_time = datetime.now()
                logger.info(f"TRADE EXECUTED | #{trade_id} ({sym}) | {action} | ${current_price:,.2f} | Qty: {position_size}")
                logger.info(f"SL: ${stop_loss:,.2f} | TP1 (60%): ${tp1:,.2f} | TP2 (40%): ${tp2:,.2f}")
                write_learning(
                    f"New trade #{trade_id}: {action} {sym} at ${current_price} "
                    f"with SL=${stop_loss:.2f}, TP1=${tp1:.2f}, TP2=${tp2:.2f}. Reason: {reason}",
                    category="trade_open", trade_id=trade_id
                )
                break

        except Exception as e:
            logger.error(f"[ERROR] Cycle failed for {sym}: {e}")
            print(f"[BOT] ERROR in {sym} cycle: {e}")
            write_learning(f"Bot error for {sym}: {str(e)}", category="error")


def main():
    print("\n" + "=" * 60)
    print("  ENHANCED TRADING BOT STARTING...")
    print("=" * 60)

    logger.info("=" * 50)
    logger.info("ENHANCED TRADING BOT STARTED")
    logger.info(f"Symbols: {', '.join(SYMBOLS)} | Check: {CHECK_INTERVAL_SECONDS}s | Min Confidence: {MIN_CONFIDENCE}")
    logger.info(f"Target Notional: ${TARGET_NOTIONAL_USD} | TP1: 60% Book | TP2: 40% Runner | SL: Structure")
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
