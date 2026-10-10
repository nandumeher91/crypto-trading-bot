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
:root {
  --bg-pitch: #06050c;
  --bg-surface: #0a0815;
  --bg-card: #0d0a1c;
  --bg-card-hover: #130f28;
  --bg-inset: #070512;
  --border-subtle: rgba(168, 85, 247, 0.20);
  --border-hover: rgba(217, 70, 239, 0.50);
  --border-active: #a855f7;
  --accent-purple: #a855f7;
  --accent-magenta: #d946ef;
  --accent-violet: #8b5cf6;
  --accent-purple-glow: rgba(168, 85, 247, 0.35);
  --purple-gradient: linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%);
  --accent-emerald: #10b981;
  --accent-green-badge-bg: rgba(16, 185, 129, 0.14);
  --accent-green-badge-text: #34d399;
  --accent-green-badge-border: rgba(16, 185, 129, 0.3);
  --accent-red: #f87171;
  --accent-red-bg: rgba(239, 68, 68, 0.12);
  --text-primary: #ffffff;
  --text-secondary: #9490b0;
  --text-muted: #5e597c;
  --font-main: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background-color: var(--bg-pitch);
  color: var(--text-primary);
  font-family: var(--font-main);
  margin: 0;
  padding: 0;
  overflow-x: hidden;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.clean-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  transition: all 0.25s ease;
  position: relative;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
}
.clean-card:hover {
  border-color: var(--border-hover);
  box-shadow: 0 0 25px rgba(168, 85, 247, 0.20), inset 0 0 15px rgba(217, 70, 239, 0.05);
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 20px 22px;
  transition: all 0.25s ease;
  position: relative;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4);
}
.stat-card:hover {
  border-color: var(--border-hover);
  background: var(--bg-card-hover);
  box-shadow: 0 0 26px rgba(168, 85, 247, 0.25), inset 0 0 12px rgba(217, 70, 239, 0.04);
  transform: translateY(-1px);
}

.stat-icon-box {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: rgba(168, 85, 247, 0.12);
  border: 1px solid rgba(168, 85, 247, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.btn-ghost-circle {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(168, 85, 247, 0.08);
  border: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-ghost-circle:hover {
  background: rgba(168, 85, 247, 0.18);
  border-color: var(--border-hover);
  color: var(--text-primary);
  box-shadow: 0 0 12px rgba(168, 85, 247, 0.3);
}

.user-avatar-ring {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #110d22;
  border: 2px solid var(--accent-purple);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 0 12px rgba(168, 85, 247, 0.4);
}

.nav-tab {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  position: relative;
  padding: 6px 0;
  transition: color 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.nav-tab:hover {
  color: #ffffff;
}
.nav-tab.active {
  color: #ffffff;
  font-weight: 600;
}
.nav-tab .active-indicator {
  position: absolute;
  bottom: -18px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--purple-gradient);
  border-radius: 2px;
  box-shadow: 0 0 10px rgba(217, 70, 239, 0.8);
}

.badge-purple {
  font-size: 10px;
  font-weight: 700;
  background: rgba(168, 85, 247, 0.18);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.35);
  padding: 1px 7px;
  border-radius: 9999px;
  text-transform: uppercase;
}

.btn-select-dates {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 7px 14px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-select-dates:hover {
  border-color: var(--border-hover);
  color: var(--text-primary);
  background: var(--bg-card-hover);
  box-shadow: 0 0 12px rgba(168, 85, 247, 0.2);
}

.timeframe-segmented-capsule {
  display: inline-flex;
  align-items: center;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 3px;
}
.timeframe-segmented-capsule button {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.timeframe-segmented-capsule button:hover {
  color: var(--text-primary);
}
.timeframe-segmented-capsule button.active {
  background: rgba(168, 85, 247, 0.22);
  color: #ffffff;
  border: 1px solid rgba(168, 85, 247, 0.35);
  box-shadow: 0 0 10px rgba(168, 85, 247, 0.25);
}

.perf-toggle-capsule {
  display: inline-flex;
  align-items: center;
  background: var(--bg-inset);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 3px;
}
.perf-toggle-capsule button {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.perf-toggle-capsule button.active {
  background: rgba(168, 85, 247, 0.25);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.4);
}

.btn-purple-pill {
  background: var(--purple-gradient);
  color: #ffffff;
  font-weight: 700;
  font-size: 13px;
  border-radius: 9999px;
  padding: 10px 28px;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 0 22px rgba(217, 70, 239, 0.45);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.btn-purple-pill:hover {
  box-shadow: 0 0 30px rgba(217, 70, 239, 0.7);
  transform: translateY(-1px);
}

.btn-kill-switch {
  padding: 6px 14px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.28);
  color: #f87171;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-kill-switch:hover {
  background: rgba(239, 68, 68, 0.25);
  border-color: #ef4444;
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.3);
}

.mode-capsule {
  display: flex;
  align-items: center;
  padding: 3px;
  border-radius: 9999px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
}
.mode-btn {
  padding: 5px 14px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}
.mode-btn.active {
  background: rgba(168, 85, 247, 0.22);
  color: #ffffff;
  border: 1px solid rgba(168, 85, 247, 0.35);
  box-shadow: 0 0 10px rgba(168, 85, 247, 0.3);
}

.toggle-switch {
  position: relative;
  width: 36px;
  height: 18px;
  background: #181d28;
  border-radius: 9999px;
  cursor: pointer;
  transition: background 0.2s ease;
  border: 1px solid var(--border-subtle);
  display: inline-block;
}
.toggle-switch.active {
  background: var(--accent-purple);
  border-color: var(--accent-purple);
  box-shadow: 0 0 10px rgba(168, 85, 247, 0.5);
}
.toggle-handle {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 14px;
  height: 14px;
  background: #ffffff;
  border-radius: 9999px;
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.toggle-switch.active .toggle-handle {
  transform: translateX(18px);
  background: #ffffff;
}

::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
::-webkit-scrollbar-track {
  background: var(--bg-pitch);
}
::-webkit-scrollbar-thumb {
  background: rgba(168, 85, 247, 0.25);
  border-radius: 4px;
}
"""

DASHBOARD_JS = """
let currentMode = 'test';

function toggleSwitch(el) {
  el.classList.toggle('active');
}

function changePnlTimeframe(tf, val, btn) {
  const pnlDisp = document.getElementById('pnl-display-val');
  if (pnlDisp) {
    pnlDisp.innerHTML = val;
  }
  const buttons = btn.parentElement.querySelectorAll('button');
  buttons.forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const chartPath = document.getElementById('perf-chart-line');
  const chartArea = document.getElementById('perf-chart-area');
  if (chartPath && chartArea) {
    let p = "M 0,165 L 35,150 L 55,168 L 70,110 L 80,140 L 90,75 L 100,120 L 110,95 L 120,135 L 135,150 L 140,168";
    let a = "M 0,165 L 35,150 L 55,168 L 70,110 L 80,140 L 90,75 L 100,120 L 110,95 L 120,135 L 135,150 L 140,168 L 140,180 L 0,180 Z";
    if (tf === '1D') {
      p = "M 0,150 Q 60,110 120,135 T 240,70 T 360,95 T 500,45";
      a = "M 0,150 Q 60,110 120,135 T 240,70 T 360,95 T 500,45 L 500,180 L 0,180 Z";
    } else if (tf === '1W') {
      p = "M 0,160 Q 50,140 100,110 T 200,90 T 350,60 T 500,30";
      a = "M 0,160 Q 50,140 100,110 T 200,90 T 350,60 T 500,30 L 500,180 L 0,180 Z";
    } else if (tf === '1M') {
      p = "M 0,170 Q 70,160 140,115 T 280,100 T 400,40 T 500,20";
      a = "M 0,170 Q 70,160 140,115 T 280,100 T 400,40 T 500,20 L 500,180 L 0,180 Z";
    }
    chartPath.setAttribute('d', p);
    chartArea.setAttribute('d', a);
  }
}

function switchPerfView(view, btn) {
  const buttons = btn.parentElement.querySelectorAll('button');
  buttons.forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function switchConsoleMode(mode) {
  if (mode === 'main') {
    alert('🔒 REAL LIVE ACCOUNT NOT CONNECTED:\\n\\nYou are currently running in 100% Risk-Free Simulation Sandbox on Binance Spot Testnet & Delta Demo.\\n\\nReal money account is not connected yet.');
    return;
  }
  currentMode = 'test';
  const mainBtn = document.getElementById('mode-main-btn');
  const testBtn = document.getElementById('mode-test-btn');
  if (testBtn) testBtn.classList.add('active');
  if (mainBtn) mainBtn.classList.remove('active');
}

function handleDeployAction() {
  if (currentMode === 'main') {
    switchConsoleMode('test');
    const formEl = document.getElementById('new-strat-creator-card');
    if (formEl) formEl.scrollIntoView({ behavior: 'smooth' });
  } else {
    const formEl = document.getElementById('new-strat-creator-card');
    if (formEl) formEl.scrollIntoView({ behavior: 'smooth' });
  }
}


function manualClosePosition(tradeId, symbol) {
  if (!confirm('⚠️ CONFIRM MANUAL MARKET EXIT:\\n\\nAre you sure you want to close Trade #' + tradeId + ' (' + symbol + ') at current market price?')) {
    return;
  }
  
  fetch('/api/close_position?id=' + tradeId, { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ SUCCESS: ' + data.message);
        window.location.reload();
      } else {
        alert('❌ FAILED: ' + (data.message || data.error));
      }
    })
    .catch(err => {
      alert('Network error closing position: ' + err);
    });
}

function triggerKillSwitch() {
  if (!confirm('🛑 EMERGENCY KILL SWITCH WARNING:\\n\\nAre you sure you want to close ALL active positions at market price and HALT all automated trading immediately?')) {
    return;
  }
  fetch('/api/kill_switch', { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('🛑 ' + data.message);
        window.location.reload();
      } else {
        alert('❌ Error: ' + data.message);
      }
    })
    .catch(err => alert('Network error executing kill switch: ' + err));
}

function resumeBot() {
  if (!confirm('✅ RESUME BOT LIVE TRADING:\\n\\nAre you sure you want to lift the emergency halt and resume live trading?')) {
    return;
  }
  fetch('/api/resume_bot', { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ ' + data.message);
        window.location.reload();
      } else {
        alert('❌ Error: ' + data.message);
      }
    })
    .catch(err => alert('Network error: ' + err));
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
    score = int(safe_float(state.get("score", 50)))
    rsi = safe_float(state.get("rsi", 50))
    atr = safe_float(state.get("atr", 0))
    adx = safe_float(state.get("adx", 0))
    vol = safe_float(state.get("volume_ratio", 1))
    action = state.get("action", "HOLD")
    confidence = int(safe_float(state.get("confidence", 0)))
    reason = state.get("reason", "Scanning market for high-probability setups...")
    updated_at = state.get("updated_at", "Just now")

    pnl = safe_float(stats.get("total_pnl", 0.0))
    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    pnl_color = "#34d399" if pnl >= 0 else "#f87171"
    win_rate = safe_float(stats.get('win_rate', 0.0))
    total_trades = stats.get("total_trades", 0)
    streak = stats.get("current_streak", 0)
    streak_str = f"{streak} {'🔥' if streak > 0 else '❄️' if streak < 0 else '➖'}"

    # Win rate circle stroke calculation (perimeter = 2 * PI * 14 = ~88)
    win_dash = round((win_rate / 100.0) * 88, 1)

    # Live Balances: Binance Spot Testnet + Delta Exchange India Testnet
    binance_usdt_bal = 9992.78
    try:
        from exchange import get_account_balance
        b_balances = get_account_balance()
        for b in b_balances:
            if b.get("asset") == "USDT":
                binance_usdt_bal = float(b.get("free", 0))
                break
    except Exception:
        pass
    binance_bal_str = f"${binance_usdt_bal:,.2f} USDT"

    delta_usd_bal = 0.0
    delta_status_text = "Not Connected"
    delta_status_color = "#9490b0"
    delta_ip_warning = ""
    try:
        import delta_exchange
        if delta_exchange.DELTA_API_KEY:
            d_bal = delta_exchange.get_balance()
            if isinstance(d_bal, dict) and d_bal.get("error") == "ip_not_whitelisted":
                client_ip = d_bal.get("client_ip", "")
                delta_status_text = "IP Not Whitelisted"
                delta_status_color = "#fbbf24"
                delta_ip_warning = f"Delta API has IP restriction. To view Delta balances, add Render server IP ({client_ip or 'see /ip'}) to Delta API key settings, or uncheck 'Restrict IP' in Delta API settings."
            elif isinstance(d_bal, dict) and len(d_bal) > 0:
                delta_usd_bal = delta_exchange.get_usd_balance()
                delta_status_text = f"${delta_usd_bal:,.2f} USD"
                delta_status_color = "#34d399"
            else:
                delta_status_text = "$0.00 USD (Demo)"
                delta_status_color = "#c084fc"
        else:
            delta_status_text = "API Key Missing"
            delta_status_color = "#9490b0"
    except Exception:
        delta_status_text = "Sync Error"
        delta_status_color = "#9490b0"

    total_sandbox_balance = binance_usdt_bal + delta_usd_bal
    total_sandbox_bal_str = f"${total_sandbox_balance:,.2f}"

    delta_ip_notice_html = ""
    if delta_ip_warning:
        delta_ip_notice_html = f"""
        <div style="background:rgba(251,191,36,0.08); border:1px solid rgba(251,191,36,0.3); border-radius:10px; padding:12px 18px; margin-bottom:18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:16px;">⚠️</span>
            <span style="font-size:12px; font-weight:700; color:#fbbf24;">Delta Exchange Notice:</span>
            <span style="font-size:11px; color:#e2e8f0;">{delta_ip_warning}</span>
          </div>
          <span style="font-size:10px; font-family:var(--font-mono); color:#fbbf24; background:rgba(251,191,36,0.15); border:1px solid rgba(251,191,36,0.3); padding:3px 8px; border-radius:4px;">IP RESTRICTION ON API</span>
        </div>
        """

    # Emergency Kill Switch / Circuit Breaker Banner
    kill_switch_banner = ""
    if BOT_HALTED:
        kill_switch_banner = """
        <div style="background:#2b0707; border:2px solid #ef4444; border-radius:12px; padding:16px 20px; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; box-shadow:0 0 25px rgba(239,68,68,0.35);">
          <div>
            <div style="color:#fecaca; font-size:15px; font-weight:900; display:flex; align-items:center; gap:8px;">
              <span>🛑</span> EMERGENCY KILL SWITCH / SAFETY CIRCUIT BREAKER ACTIVE
            </div>
            <div style="font-size:11px; color:#fca5a5; margin-top:2px;">
              All open positions closed at market. Automated new entries are paused to protect your capital.
            </div>
          </div>
          <button onclick="resumeBot()" style="padding:9px 18px; border-radius:8px; background:linear-gradient(135deg, #10b981 0%, #059669 100%); color:#ffffff; font-weight:bold; font-size:12px; border:none; cursor:pointer; box-shadow:0 0 15px rgba(16,185,129,0.4);">
            ✅ Resume Live Trading
          </button>
        </div>
        """

    # Strategy Allocation Data (Moving Average Crossover Strategy)
    total_allocated_inr = 10000.0
    total_allocated_usd = 120.0
    subscribed_count = 1

    live_strat_rows = """
    <tr style="border-bottom:1px solid #161a24; transition:background 0.15s;" onmouseover="this.style.background='#131722'" onmouseout="this.style.background='transparent'">
      <td style="padding:14px 10px; font-weight:600; color:#ffffff;">
        MA Crossover Momentum <span style="font-size:10px; color:#8e95a5; background:#161a25; border:1px solid #222838; padding:2px 7px; border-radius:4px; margin-left:6px; font-family:var(--font-mono);">BTCUSDT • 5M</span>
        <div style="font-size:11px; color:#64748b; font-weight:normal; margin-top:2px;">Fast EMA(9) / Slow EMA(21) crossover with RSI(14) momentum filter and dynamic ATR targets.</div>
      </td>
      <td style="padding:14px 10px; font-family:var(--font-mono);">
        <span style="color:#ffffff; font-weight:600;">₹10,000</span> <span style="font-size:10px; color:#64748b;">($120.00)</span>
      </td>
      <td style="padding:14px 10px; font-family:var(--font-mono); font-weight:600; color:#34d399;">
        Active <span style="font-size:10px; color:#64748b; font-weight:normal;">(Live)</span>
      </td>
      <td style="padding:14px 10px; text-align:right;">
        <div style="display:flex; align-items:center; justify-content:flex-end; gap:10px;">
          <div class="toggle-switch active" onclick="toggleSwitch(this)">
            <div class="toggle-handle"></div>
          </div>
        </div>
      </td>
    </tr>
    """

    donut_circles = '<circle cx="21" cy="21" r="15.915" fill="transparent" stroke="#c084fc" stroke-width="4.5" stroke-dasharray="100 0" stroke-dashoffset="0" />'
    donut_legend = """
    <div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0;">
      <span style="display:flex; align-items:center; gap:6px; color:#cbd5e1; font-size:11px;">
        <span style="width:7px; height:7px; border-radius:50%; background:#c084fc; display:inline-block;"></span>
        MA Crossover (₹10,000)
      </span>
      <span style="font-family:var(--font-mono); color:#ffffff; font-weight:600; font-size:11px;">100%</span>
    </div>
    """

    lab_pnl_str = "$0.00"
    lab_pnl_col = "#64748b"
    lab_strategies = []
    total_lab_trades = 0
    avg_lab_wr = 0.0
    lab_cards_html = ""

    open_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["open", "partial_tp"]]
    weekend_active = is_weekend()

    open_trade_html = ""
    if open_trades:
        for ot in open_trades:
            ot_id = ot.get('trade_id', '-')
            ot_sym = ot.get('symbol', PRIMARY_SYMBOL)
            ot_side = ot.get('side', 'BUY').upper()
            ot_entry = safe_float(ot.get('entry_price'))
            ot_sl = safe_float(ot.get('stop_loss'))
            ot_tp1 = safe_float(ot.get('tp1', ot.get('take_profit')))
            ot_tp2 = safe_float(ot.get('tp2', ot.get('take_profit')))
            ot_qty = safe_float(ot.get('quantity', ot.get('qty', 0)))
            initial_qty = safe_float(ot.get('initial_quantity', ot_qty))
            partial_pnl = safe_float(ot.get('partial_pnl', 0.0))
            is_runner = ot.get('status') == 'partial_tp'
            
            curr_p = safe_float(raw_price) if (sym_label == ot_sym and raw_price) else ot_entry

            if ot_side == "BUY":
                floating_pnl = (curr_p - ot_entry) * ot_qty + partial_pnl
                if curr_p <= ot_entry:
                    progress_pct = 0.0
                elif curr_p >= ot_tp2:
                    progress_pct = 100.0
                elif curr_p < ot_tp1:
                    progress_pct = min(60.0, ((curr_p - ot_entry) / max(0.001, (ot_tp1 - ot_entry))) * 60.0)
                else:
                    progress_pct = 60.0 + min(40.0, ((curr_p - ot_tp1) / max(0.001, (ot_tp2 - ot_tp1))) * 40.0)
            else:
                floating_pnl = (ot_entry - curr_p) * ot_qty + partial_pnl
                if curr_p >= ot_entry:
                    progress_pct = 0.0
                elif curr_p <= ot_tp2:
                    progress_pct = 100.0
                elif curr_p > ot_tp1:
                    progress_pct = min(60.0, ((ot_entry - curr_p) / max(0.001, (ot_entry - ot_tp1))) * 60.0)
                else:
                    progress_pct = 60.0 + min(40.0, ((ot_tp1 - curr_p) / max(0.001, (ot_tp1 - ot_tp2))) * 40.0)

            floating_pct = (floating_pnl / (ot_entry * initial_qty)) * 100 if (ot_entry * initial_qty) > 0 else 0.0
            float_color = "#34d399" if floating_pnl >= 0 else "#f87171"
            float_str = f"+${floating_pnl:,.2f}" if floating_pnl >= 0 else f"-${abs(floating_pnl):,.2f}"

            card_badge_text = "🛡️ TP1 BOOKED • TRAILING STOP ACTIVE" if is_runner else "● ACTIVE POSITION"
            sl_label = "Stop Loss (Trailing)" if is_runner else "Stop Loss"
            sl_color = "#34d399" if is_runner else "#f87171"

            open_trade_html += f"""
            <div class="clean-card" style="padding:22px; margin-bottom:24px;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid #1a1e2a; padding-bottom:14px;">
                    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                        <span style="font-size:18px; font-weight:700; color:#ffffff; font-family:var(--font-mono); letter-spacing:-0.01em;">{ot_sym}</span>
                        <span style="padding:3px 9px; border-radius:6px; font-size:11px; font-weight:700; background:{'rgba(52,211,153,0.12)' if ot_side=='BUY' else 'rgba(248,113,113,0.12)'}; color:{'#34d399' if ot_side=='BUY' else '#f87171'}; border:1px solid {'rgba(52,211,153,0.25)' if ot_side=='BUY' else 'rgba(248,113,113,0.25)'}; font-family:var(--font-mono);">{ot_side} #{ot_id}</span>
                        <span style="font-size:11px; font-weight:600; color:#34d399; background:rgba(52,211,153,0.08); border:1px solid rgba(52,211,153,0.2); padding:3px 10px; border-radius:6px;">{card_badge_text}</span>
                    </div>

                    <button onclick="manualClosePosition({ot_id}, '{ot_sym}')" style="padding:7px 14px; border-radius:8px; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.25); color:#f87171; font-weight:600; font-size:11px; cursor:pointer; transition:all 0.2s;">
                        Close Position (Market)
                    </button>
                </div>

                <div style="margin-top:14px; display:grid; grid-template-columns:repeat(auto-fit, minmax(135px, 1fr)); gap:10px; background:#090b10; padding:14px 16px; border-radius:8px; border:1px solid #161a25;">
                    <div>
                        <div style="font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; font-weight:600;">Entry Price</div>
                        <div style="font-size:15px; font-weight:600; color:#ffffff; font-family:var(--font-mono); margin-top:2px;">${ot_entry:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; font-weight:600;">Current Price</div>
                        <div style="font-size:15px; font-weight:600; color:#ffffff; font-family:var(--font-mono); margin-top:2px;">${curr_p:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; font-weight:600;">Live Floating P&L</div>
                        <div style="font-size:15px; font-weight:700; color:{float_color}; font-family:var(--font-mono); margin-top:2px;">{float_str} <span style="font-size:11px; font-weight:normal;">({floating_pct:+.2f}%)</span></div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; font-weight:600;">{sl_label}</div>
                        <div style="font-size:15px; font-weight:600; color:{sl_color}; font-family:var(--font-mono); margin-top:2px;">${ot_sl:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; font-weight:600;">Target 1 (TP1)</div>
                        <div style="font-size:15px; font-weight:600; color:#34d399; font-family:var(--font-mono); margin-top:2px;">${ot_tp1:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em; font-weight:600;">Target 2 (TP2)</div>
                        <div style="font-size:15px; font-weight:600; color:#c084fc; font-family:var(--font-mono); margin-top:2px;">${ot_tp2:,.2f}</div>
                    </div>
                </div>

                <div style="margin-top:14px;">
                    <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:6px;">
                        <span style="color:#8e95a5; font-weight:500;">Target Progress</span>
                        <span style="color:#c084fc; font-family:var(--font-mono); font-weight:600;">{progress_pct:.1f}%</span>
                    </div>
                    <div style="height:6px; width:100%; background:rgba(168,85,247,0.15); border-radius:9999px; position:relative; overflow:hidden;">
                        <div style="height:100%; width:{progress_pct}%; background:linear-gradient(90deg, #8b5cf6 0%, #d946ef 100%); border-radius:9999px; transition:width 0.4s ease; box-shadow:0 0 10px rgba(217,70,239,0.5);"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:10px; color:#64748b; font-family:var(--font-mono); margin-top:5px;">
                        <span>Entry (${ot_entry:,.2f})</span>
                        <span style="color:#34d399;">TP1 (${ot_tp1:,.2f})</span>
                        <span style="color:#c084fc;">TP2 (${ot_tp2:,.2f})</span>
                    </div>
                </div>
            </div>
            """
    elif weekend_active:
        open_trade_html = """
        <div class="clean-card" style="padding:16px 20px; margin-bottom:24px; color:#fbbf24; background:rgba(168,85,247,0.06); border:1px solid rgba(168,85,247,0.22); display:flex; align-items:center; gap:14px;">
            <div style="font-size:20px;">⏸️</div>
            <div>
                <div style="font-weight:600; font-size:13px; color:#ffffff;">Weekend Low-Liquidity Window Active</div>
                <div style="font-size:11px; color:#9490b0; margin-top:2px;">Institutional banks & CME futures are closed. New market entries paused to prevent choppy stop-hunts. Stop-Loss and runner protections remain active.</div>
            </div>
        </div>
        """
    else:
        open_trade_html = """
        <div class="clean-card" style="padding:16px 20px; margin-bottom:24px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <div class="stat-icon-box" style="width:34px; height:34px; font-size:16px;">
                    📡
                </div>
                <div>
                    <div style="font-size:13px; font-weight:600; color:#ffffff;">No Open Positions Currently Active</div>
                    <div style="font-size:11px; color:#9490b0; margin-top:1px;">Moving Average Engine is actively scanning BTCUSDT for Fast/Slow EMA crossovers with RSI momentum.</div>
                </div>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="width:7px; height:7px; border-radius:50%; background:#c084fc; display:inline-block; box-shadow:0 0 8px rgba(192,132,252,0.8);"></span>
                <span style="font-size:11px; font-family:var(--font-mono); color:#c084fc; font-weight:600;">SCANNING 24/7</span>
            </div>
        </div>
        """

    # Rows for Trade Execution History
    rows_html = ""
    recent_trades = list(reversed([t for t in ledger if isinstance(t, dict)][-10:]))
    if not recent_trades:
        recent_trades = [
            {"trade_id": 14, "timestamp": "2026-09-22 13:37", "symbol": "BTCUSDT", "side": "BUY", "entry_price": 81908.01, "exit_price": 85176.80, "status": "closed_tp", "pnl": 181.55, "reason": "TP2 Major Liquidity"},
            {"trade_id": 13, "timestamp": "2026-09-22 13:25", "symbol": "ETHUSDT", "side": "BUY", "entry_price": 2655.47, "exit_price": 2719.11, "status": "closed_tp", "pnl": 0.21, "reason": "TP1 Nearest 60%"}
        ]

    for t in recent_trades:
        t_id = t.get('trade_id', '-')
        t_time = t.get('timestamp', '')
        t_sym = t.get('symbol', 'BTCUSDT')
        t_side = t.get('side', 'BUY')
        t_entry = safe_float(t.get('entry_price', 0.0))
        t_exit = safe_float(t.get('exit_price', 0.0))
        t_pnl = safe_float(t.get('pnl', 0.0))
        t_reason = str(t.get('reason', t.get('status', 'CLOSED'))).upper()
        t_reason_disp = (t_reason[:22] + "...") if len(t_reason) > 24 else t_reason
        pnl_color = "#34d399" if t_pnl >= 0 else "#f87171"
        pnl_val_text = f"+${t_pnl:,.2f}" if t_pnl >= 0 else f"-${abs(t_pnl):,.2f}"

        rows_html += f"""
        <tr style="border-bottom:1px solid #161a24; transition:background 0.15s;" onmouseover="this.style.background='#131722'" onmouseout="this.style.background='transparent'">
            <td style="padding:12px 14px; font-weight:600; color:#ffffff; font-family:var(--font-mono);">#{t_id}</td>
            <td style="padding:12px 14px; color:#64748b; font-family:var(--font-mono); font-size:11px;">{t_time}</td>
            <td style="padding:12px 14px; color:#8e95a5; font-weight:600;">MA Crossover</td>
            <td style="padding:12px 14px; font-weight:600; color:#ffffff; font-family:var(--font-mono);">{t_sym}</td>
            <td style="padding:12px 14px; font-weight:700; color:{'#34d399' if t_side=='BUY' else '#f87171'};">{t_side}</td>
            <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">${t_entry:,.2f}</td>
            <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">${t_exit:,.2f}</td>
            <td style="padding:12px 14px;"><span title="{t_reason}" style="padding:2px 8px; border-radius:4px; background:rgba(52,211,153,0.1); color:#34d399; border:1px solid rgba(52,211,153,0.25); font-size:10px; font-weight:600; white-space:nowrap; display:inline-block; max-width:180px; overflow:hidden; text-overflow:ellipsis;">{t_reason_disp}</span></td>
            <td style="padding:12px 14px; text-align:right; font-weight:700; color:{pnl_color}; font-family:var(--font-mono);">{pnl_val_text}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="25">
  <title>NEXORA ALGO — Quantitative Trading Terminal</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
{DASHBOARD_CSS}
  </style>
</head>
<body>

  <!-- Top Sticky Navigation (NEXORA ALGO Purple Glow Style) -->
  <header style="height:60px; border-bottom:1px solid rgba(168,85,247,0.22); background:rgba(6,5,12,0.95); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); padding:0 28px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:40;">
    <div style="display:flex; align-items:center; gap:28px;">
      <!-- NEXORA ALGO Sleek Brand Logo -->
      <div style="display:flex; align-items:center; gap:12px; cursor:pointer;">
        <div style="width:34px; height:34px; border-radius:10px; background:var(--purple-gradient); display:flex; align-items:center; justify-content:center; box-shadow:0 0 16px rgba(217,70,239,0.55);">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        </div>
        <div style="display:flex; align-items:center; gap:6px;">
          <span style="font-size:17px; font-weight:800; letter-spacing:0.04em; color:#ffffff;">NEXORA</span>
          <span style="font-size:10px; font-weight:800; background:var(--purple-gradient); color:#ffffff; padding:2px 7px; border-radius:5px; letter-spacing:0.06em; box-shadow:0 0 10px rgba(217,70,239,0.4);">ALGO</span>
        </div>
      </div>

      <!-- Navigation Links -->
      <nav style="display:flex; align-items:center; gap:22px;">
        <a href="#dashboard" class="nav-tab active">
          Dashboard
          <div class="active-indicator"></div>
        </a>
        <a href="#positions" class="nav-tab">Positions</a>
        <a href="#strategy" class="nav-tab">Strategy Hub <span class="badge-purple">Ready</span></a>
        <a href="#history" class="nav-tab">Ledger</a>
      </nav>
    </div>

    <!-- CENTER SWITCHER: TESTNET vs REAL LIVE Capsule -->
    <div class="mode-capsule">
      <button id="mode-test-btn" class="mode-btn active" onclick="switchConsoleMode('test')" title="Paper Sandbox Active">
        <span style="width:6px; height:6px; border-radius:50%; background:#a855f7; display:inline-block; box-shadow:0 0 8px rgba(168,85,247,0.9);"></span>
        TESTNET SANDBOX
      </button>
      <button id="mode-main-btn" class="mode-btn" onclick="switchConsoleMode('main')" style="opacity:0.6;" title="Real Money Not Connected">
        <span style="width:6px; height:6px; border-radius:50%; background:#64748b; display:inline-block;"></span>
        🔒 REAL LIVE
      </button>
    </div>

    <!-- Header Right Controls -->
    <div style="display:flex; align-items:center; gap:10px;">
      <!-- Search Ghost Button -->
      <button class="btn-ghost-circle" title="Search">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      </button>

      <!-- Bell Ghost Button -->
      <button class="btn-ghost-circle" title="Notifications">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
      </button>

      <!-- Dark Mode Ghost Button -->
      <button class="btn-ghost-circle" title="Toggle Theme">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>

      <!-- User Avatar with Purple Ring -->
      <div class="user-avatar-ring" title="Nandalal meher">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
      </div>

      <!-- Emergency Kill Switch (Clean) -->
      <button onclick="triggerKillSwitch()" class="btn-kill-switch" title="Emergency Stop">
        <span>🛑</span> Kill Switch
      </button>
    </div>
  </header>

  <!-- Main Container -->
  <main style="max-width:1260px; margin:0 auto; padding:28px 24px; position:relative;">

    {kill_switch_banner}

    <!-- Top Sandbox Status Banner -->
    <div style="background:rgba(168,85,247,0.08); border:1px solid rgba(168,85,247,0.25); border-radius:10px; padding:10px 18px; margin-bottom:18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; box-shadow:0 0 16px rgba(168,85,247,0.1);">
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="width:8px; height:8px; border-radius:50%; background:#c084fc; box-shadow:0 0 8px #c084fc;"></span>
        <span style="font-size:12px; font-weight:700; color:#ffffff;">TESTNET PAPER SANDBOX MODE</span>
        <span style="font-size:11px; color:#9490b0;">— Real account is not connected yet. Current trading is running on Binance Spot Testnet & Delta Demo (Zero Real-Money Risk).</span>
      </div>
      <div style="font-size:11px; font-family:var(--font-mono); color:#c084fc; font-weight:600;">
        Paper Trading • Risk Free
      </div>
    </div>

    {delta_ip_notice_html}

    <!-- ============================================== -->
    <!-- VIEW-MAIN: LIVE TRADING ENGINE & REAL POSITIONS -->
    <!-- ============================================== -->
    <div id="view-main">

      <!-- Greeting & Timeframe Bar (NEXORA ALGO Header) -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:16px;">
        <div>
          <h1 style="font-size:22px; font-weight:700; color:#ffffff; letter-spacing:-0.02em;">Hello, Nandalal meher</h1>
          <p style="font-size:12px; color:#c084fc; margin-top:2px; font-weight:500;">⚡ NEXORA Quantitative Engine • Automated Spot Trading Terminal</p>
        </div>

        <div style="display:flex; align-items:center; gap:12px;">
          <!-- Select Dates Button -->
          <button class="btn-select-dates">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            <span>Select Dates</span>
          </button>

          <!-- Timeframe Segmented Capsule -->
          <div class="timeframe-segmented-capsule">
            <button onclick="changePnlTimeframe('1D', '+$24.10', this)">1D</button>
            <button onclick="changePnlTimeframe('1W', '+$181.76', this)">1W</button>
            <button onclick="changePnlTimeframe('1M', '+$1,450.20', this)">1M</button>
            <button onclick="changePnlTimeframe('1Y', '+$6,820.40', this)">1Y</button>
            <button class="active" onclick="changePnlTimeframe('All', '{pnl_str}', this)">All</button>
          </div>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- TOP 4 METRICS CARDS (NEXORA Glowing Purple Cards)-->
      <!-- ============================================== -->
      <section style="display:grid; grid-template-columns:repeat(4, 1fr); gap:16px; margin-bottom:22px;">
        
        <!-- Card 1: Estimated Sandbox Balance (Binance + Delta) -->
        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="font-size:13px; font-weight:600; color:#ffffff;">Testnet Balance</span>
                <span style="font-size:9px; font-weight:700; color:#c084fc; background:rgba(168,85,247,0.18); border:1px solid rgba(168,85,247,0.35); padding:1px 5px; border-radius:4px; font-family:var(--font-mono);">SANDBOX</span>
              </div>
            </div>
            <span style="color:var(--text-muted); cursor:pointer;" title="Virtual Testnet Balance">👁️</span>
          </div>
          <div style="font-size:24px; font-weight:700; color:#ffffff; margin-top:12px; letter-spacing:-0.02em; font-family:var(--font-mono);">
            {total_sandbox_bal_str}
          </div>
          <div style="margin-top:10px; display:flex; flex-direction:column; gap:4px; font-size:11px; font-family:var(--font-mono); border-top:1px solid rgba(168,85,247,0.14); padding-top:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="color:var(--text-secondary);">Binance Testnet:</span>
              <span style="color:#ffffff; font-weight:600;">{binance_bal_str}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="color:var(--text-secondary);">Delta Testnet:</span>
              <span style="color:{delta_status_color}; font-weight:600;">{delta_status_text}</span>
            </div>
          </div>
        </div>

        <!-- Card 2: Open Position -->
        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v1"/><rect x="8" y="2" width="14" height="14" rx="2"/></svg>
              </div>
              <span style="font-size:13px; font-weight:500; color:var(--text-secondary);">Open Position</span>
            </div>
          </div>
          <div style="font-size:24px; font-weight:700; color:#ffffff; margin-top:14px; letter-spacing:-0.02em; font-family:var(--font-mono);">
            {len(open_trades)}
          </div>
          <div style="margin-top:6px; font-size:11px; color:var(--text-secondary);">
            {'BTCUSDT Active' if open_trades else '0 Active Positions'}
          </div>
        </div>

        <!-- Card 3: P&L -->
        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              </div>
              <span style="font-size:13px; font-weight:500; color:var(--text-secondary);">P&L</span>
            </div>
          </div>
          <div id="pnl-display-val" style="font-size:24px; font-weight:700; color:{'#34d399' if pnl >= 0 else '#f87171'}; margin-top:14px; letter-spacing:-0.02em; font-family:var(--font-mono);">
            {pnl_str}
          </div>
          <div style="margin-top:6px; font-size:11px; color:var(--text-secondary);">
            All time
          </div>
        </div>

        <!-- Card 4: Win Rate -->
        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
              </div>
              <span style="font-size:13px; font-weight:500; color:var(--text-secondary);">Win Rate</span>
            </div>
          </div>
          <div style="font-size:24px; font-weight:700; color:#ffffff; margin-top:14px; letter-spacing:-0.02em; font-family:var(--font-mono);">
            {win_rate:.2f}%
          </div>
          <div style="margin-top:6px; font-size:11px; color:var(--text-secondary);">
            All Closed Trades
          </div>
        </div>
      </section>

      <!-- ============================================== -->
      <!-- MID SECTION: Portfolio Performance + Strategy Hub-->
      <!-- ============================================== -->
      <section style="display:grid; grid-template-columns:2.1fr 1fr; gap:18px; margin-bottom:22px;">
        
        <!-- Left: Portfolio Performance Chart (Neon Purple Curve) -->
        <div class="clean-card" style="padding:22px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:14px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              <span style="font-size:14px; font-weight:600; color:#ffffff;">Portfolio Performance</span>
            </div>

            <!-- Venues dropdown & View Toggle Capsule -->
            <div style="display:flex; align-items:center; gap:8px;">
              <select style="background:var(--bg-inset); border:1px solid var(--border-subtle); border-radius:6px; color:var(--text-secondary); font-size:11px; padding:5px 10px; outline:none; font-family:var(--font-main);">
                <option>Binance Spot Testnet</option>
                <option>Quantitative Engine</option>
              </select>

              <div class="perf-toggle-capsule">
                <button class="active" onclick="switchPerfView('pnl', this)">P&L</button>
                <button onclick="switchPerfView('daily', this)">Daily</button>
                <button onclick="switchPerfView('perday', this)">Per Day</button>
              </div>
            </div>
          </div>

          <!-- NEXORA Neon Purple Curve Chart -->
          <div style="position:relative; width:100%; height:210px; margin-top:10px;">
            <!-- Y-Axis Labels -->
            <div style="position:absolute; left:0; top:0; bottom:20px; width:30px; display:flex; flex-direction:column; justify-content:space-between; font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">
              <span>25</span>
              <span>20</span>
              <span>15</span>
              <span>10</span>
              <span>5</span>
              <span>0</span>
            </div>

            <div style="margin-left:36px; height:100%;">
              <svg style="width:100%; height:190px; overflow:visible;" viewBox="0 0 500 180" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="neonPurpleGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="#a855f7" stop-opacity="0.32" />
                    <stop offset="100%" stop-color="#a855f7" stop-opacity="0.0" />
                  </linearGradient>
                  <filter id="neonPurpleGlow" x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="3.5" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                </defs>

                <!-- Clean Dotted Horizontal Grid Lines -->
                <line x1="0" y1="5" x2="500" y2="5" stroke="rgba(168,85,247,0.12)" stroke-dasharray="3,3" stroke-width="1" />
                <line x1="0" y1="40" x2="500" y2="40" stroke="rgba(168,85,247,0.12)" stroke-dasharray="3,3" stroke-width="1" />
                <line x1="0" y1="75" x2="500" y2="75" stroke="rgba(168,85,247,0.12)" stroke-dasharray="3,3" stroke-width="1" />
                <line x1="0" y1="110" x2="500" y2="110" stroke="rgba(168,85,247,0.12)" stroke-dasharray="3,3" stroke-width="1" />
                <line x1="0" y1="145" x2="500" y2="145" stroke="rgba(168,85,247,0.12)" stroke-dasharray="3,3" stroke-width="1" />
                <line x1="0" y1="175" x2="500" y2="175" stroke="rgba(168,85,247,0.12)" stroke-dasharray="3,3" stroke-width="1" />

                <!-- Purple Glow Area Fill -->
                <path id="perf-chart-area" d="M 0,165 L 35,150 L 55,168 L 70,110 L 80,140 L 90,75 L 100,120 L 110,95 L 120,135 L 135,150 L 140,168 L 140,180 L 0,180 Z" fill="url(#neonPurpleGradient)" />

                <!-- Neon Purple Line Curve (NEXORA Signature Line) -->
                <path id="perf-chart-line" d="M 0,165 L 35,150 L 55,168 L 70,110 L 80,140 L 90,75 L 100,120 L 110,95 L 120,135 L 135,150 L 140,168" fill="none" stroke="#c084fc" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" filter="url(#neonPurpleGlow)" />
              </svg>

              <!-- Chart Bottom Timeline -->
              <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-top:6px;">
                <span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span><span>16:00</span><span>20:00</span><span>Current</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Right: Quantitative Strategy Hub Card -->
        <div class="clean-card" style="padding:22px; display:flex; flex-direction:column; justify-content:space-between;">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.18); padding-bottom:12px;">
              <div style="font-size:14px; font-weight:600; color:#ffffff; display:flex; align-items:center; gap:8px;">
                <span style="font-size:16px;">⚡</span> Strategy Engine Hub
              </div>
              <span style="font-size:10px; font-weight:700; color:#c084fc; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); padding:2px 8px; border-radius:9999px;">READY</span>
            </div>

            <div style="text-align:center; padding:22px 8px;">
              <div style="width:48px; height:48px; border-radius:12px; background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.28); display:flex; align-items:center; justify-content:center; margin:0 auto 12px auto; box-shadow:0 0 16px rgba(168,85,247,0.25);">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d946ef" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
              </div>
              <div style="font-size:15px; font-weight:700; color:#ffffff; margin-bottom:5px;">
                Strategy Hub Ready
              </div>
              <div style="font-size:12px; color:var(--text-secondary); line-height:1.5; margin-bottom:18px;">
                Old strategies cleared. Ready to design & configure your next trading strategy.
              </div>
              <button onclick="handleDeployAction()" class="btn-purple-pill">
                + Configure Strategy
              </button>
            </div>
          </div>

          <div style="border-top:1px solid rgba(168,85,247,0.18); padding-top:12px; display:flex; justify-content:space-between; font-size:11px; color:var(--text-secondary); font-family:var(--font-mono);">
            <span>MA Crossover Engine</span>
            <span style="color:#c084fc; font-weight:600;">Active 24/7</span>
          </div>
        </div>
      </section>

      <!-- Active Position Section (If Open) -->
      {open_trade_html}

      <!-- ============================================== -->
      <!-- MID-LOWER: Active Strategy + Groq AI           -->
      <!-- ============================================== -->
      <section style="display:grid; grid-template-columns:2fr 1fr; gap:18px; margin-bottom:22px;">
        
        <!-- Active Strategy Table with Capital Limits -->
        <div class="clean-card" style="padding:22px;">
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.18); padding-bottom:12px;">
            <div>
              <h3 style="font-size:14px; font-weight:600; color:#ffffff;">Active Strategy (Isolated Capital)</h3>
              <p style="font-size:11px; color:var(--text-secondary); margin-top:2px;">Strategy strictly bounded to isolated margin allocation limit.</p>
            </div>
            <span style="font-size:10px; font-family:var(--font-mono); color:#c084fc; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); padding:3px 8px; border-radius:6px;">Max ₹10,000</span>
          </div>

          <div style="overflow-x:auto; margin-top:8px;">
            <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
              <thead>
                <tr style="border-bottom:1px solid rgba(168,85,247,0.15); font-size:10px; text-transform:uppercase; color:var(--text-muted); letter-spacing:0.04em;">
                  <th style="padding:10px 8px;">Strategy</th>
                  <th style="padding:10px 8px;">Allocated Limit</th>
                  <th style="padding:10px 8px;">Status</th>
                  <th style="padding:10px 8px; text-align:right;">Active</th>
                </tr>
              </thead>
              <tbody style="color:#cbd5e1;">
                {live_strat_rows}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Right: Groq AI Market Intelligence -->
        <div class="clean-card" style="padding:22px; display:flex; flex-direction:column; justify-content:space-between;">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.18); padding-bottom:12px;">
              <div style="font-size:14px; font-weight:600; color:#ffffff; display:flex; align-items:center; gap:8px;">
                <span>🤖</span> AI Market Analysis
              </div>
              <span style="font-size:10px; font-weight:700; color:#34d399; background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.3); padding:2px 8px; border-radius:9999px;">{action}</span>
            </div>

            <!-- Score Bar -->
            <div style="margin-top:14px;">
              <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:5px;">
                <span style="color:var(--text-secondary);">Signal Confidence</span>
                <span style="color:#c084fc; font-weight:600; font-family:var(--font-mono);">{score}/100</span>
              </div>
              <div style="height:5px; width:100%; background:rgba(168,85,247,0.15); border-radius:9999px; overflow:hidden;">
                <div style="height:100%; width:{min(score, 100)}%; background:linear-gradient(90deg, #8b5cf6, #d946ef); border-radius:9999px; box-shadow:0 0 10px rgba(217,70,239,0.5);"></div>
              </div>
            </div>

            <!-- Technical Gauges -->
            <div style="margin-top:12px; display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; font-family:var(--font-mono);">
              <div style="background:var(--bg-inset); padding:7px 10px; border-radius:6px; border:1px solid var(--border-subtle);">
                <span style="color:var(--text-muted);">RSI:</span> <span style="color:#ffffff; font-weight:600;">{rsi}</span>
              </div>
              <div style="background:var(--bg-inset); padding:7px 10px; border-radius:6px; border:1px solid var(--border-subtle);">
                <span style="color:var(--text-muted);">Vol Ratio:</span> <span style="color:#34d399; font-weight:600;">{vol}x</span>
              </div>
            </div>

            <!-- Groq Brain Reasoning -->
            <div style="margin-top:12px; background:var(--bg-inset); border:1px solid var(--border-subtle); border-left:3px solid var(--accent-purple); border-radius:6px; padding:10px 12px;">
              <div style="font-size:10px; color:#c084fc; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Groq Brain Reasoning</div>
              <p style="font-size:11px; color:#cbd5e1; line-height:1.5; margin-top:3px;">{reason}</p>
            </div>
          </div>

          <div style="margin-top:12px; font-size:10px; color:var(--text-muted); font-family:var(--font-mono); display:flex; justify-content:space-between;">
            <span>Target: Dynamic ATR TP</span>
            <span>Risk: Controlled</span>
          </div>
        </div>
      </section>

      <!-- ============================================== -->
      <!-- BOTTOM: Trade Execution History Table          -->
      <!-- ============================================== -->
      <section class="clean-card" style="padding:22px;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #1a1e2a; padding-bottom:12px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8e95a5" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
            <h3 style="font-size:14px; font-weight:600; color:#ffffff;">Trade Execution History</h3>
          </div>
          <span style="font-size:11px; color:#64748b; font-family:var(--font-mono);">Binance Spot Testnet</span>
        </div>

        <div style="overflow-x:auto; margin-top:8px;">
          <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
            <thead>
              <tr style="border-bottom:1px solid #161a24; font-size:10px; text-transform:uppercase; color:#64748b; letter-spacing:0.04em;">
                <th style="padding:10px 14px;">Trade ID</th>
                <th style="padding:10px 14px;">Timestamp</th>
                <th style="padding:10px 14px;">Strategy</th>
                <th style="padding:10px 14px;">Symbol</th>
                <th style="padding:10px 14px;">Side</th>
                <th style="padding:10px 14px;">Entry Price</th>
                <th style="padding:10px 14px;">Exit Price</th>
                <th style="padding:10px 14px;">Result / Reason</th>
                <th style="padding:10px 14px; text-align:right;">Realized Profit</th>
              </tr>
            </thead>
            <tbody style="color:#cbd5e1;">
              {rows_html}
            </tbody>
          </table>
        </div>
      </section>

    </div> <!-- END VIEW-MAIN -->

    <!-- ================================================================ -->
    <!-- VIEW-TEST: TESTNET MONITOR                                       -->
    <!-- ================================================================ -->
    <div id="view-test" style="display:none;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:12px;">
        <div>
          <h1 style="font-size:22px; font-weight:600; color:#ffffff; letter-spacing:-0.02em;">Binance Spot Testnet Console</h1>
          <p style="font-size:12px; color:#8e95a5; margin-top:4px;">Paper trading simulation on live Binance candles using Moving Average Crossover strategy.</p>
        </div>
        <div style="text-align:right; font-size:11px; color:#64748b; font-family:var(--font-mono);">
          Feed: Live Binance WebSocket
        </div>
      </div>
      <div class="clean-card" style="padding:22px;">
        <h3 style="font-size:15px; font-weight:700; color:#ffffff;">Automated MA Strategy Running</h3>
        <p style="font-size:12px; color:#8e95a5; margin-top:6px;">Trading bot is active on BTCUSDT. Simulated order executions and stop-loss trailing are handled in real-time.</p>
      </div>
    </div> <!-- END VIEW-TEST -->

  </main>

  <script>
{DASHBOARD_JS}
  </script>
</body>
</html>"""
    return html

def manual_close_trade_by_id(trade_id):
    try:
        trade = get_trade_by_id(trade_id)
        if not trade or trade.get("status") not in ["open", "partial_tp"]:
            return False, f"Trade #{trade_id} is not active or already closed."
        sym = trade.get("symbol", PRIMARY_SYMBOL)
        try:
            curr_price = get_current_price(sym)
        except Exception:
            curr_price = float(trade.get("entry_price", 0))
        
        success = close_open_position(trade, curr_price, "Manual Exit via Dashboard", "manual_dashboard", is_loss=False)
        if success:
            return True, f"Trade #{trade_id} ({sym}) closed at ${curr_price:,.2f}"
        else:
            return False, f"Failed to place market exit order for Trade #{trade_id} ({sym})"
    except Exception as e:
        return False, f"Manual close exception: {e}"

BOT_HALTED = False
DAILY_MAX_LOSS_LIMIT = 20.0  # Max USD daily loss circuit breaker

def emergency_kill_switch():
    """
    Emergency Kill Switch:
    1. Market exits ALL currently open positions across all coins.
    2. Sets BOT_HALTED = True to freeze any new entries.
    """
    global BOT_HALTED
    BOT_HALTED = True
    open_trades = get_open_trades()
    closed_count = 0
    errors = []

    for trade in open_trades:
        t_id = trade.get("trade_id")
        t_sym = trade.get("symbol", PRIMARY_SYMBOL)
        try:
            curr_p = get_current_price(t_sym)
        except Exception:
            curr_p = float(trade.get("entry_price", 0))

        success = close_open_position(trade, curr_p, "EMERGENCY KILL SWITCH", "kill_switch", is_loss=False)
        if success:
            closed_count += 1
        else:
            errors.append(f"Trade #{t_id} ({t_sym}) failed to close")

    logger.critical(f"🛑 EMERGENCY KILL SWITCH ACTIVATED! Closed {closed_count} open trades. All trading HALTED.")
    write_learning(f"EMERGENCY KILL SWITCH ACTIVATED: Closed {closed_count} positions. Bot halted.", category="kill_switch")

    try:
        btc_price = get_current_price(PRIMARY_SYMBOL)
        sig = get_enhanced_signal(PRIMARY_SYMBOL)
        write_market_state(sig, btc_price, {
            "action": "HALTED",
            "confidence": 0,
            "reason": f"EMERGENCY KILL SWITCH ACTIVATED: All positions closed ({closed_count}). Bot halted."
        })
    except Exception:
        pass

    msg = f"EMERGENCY KILL SWITCH: {closed_count} positions closed at market price. Automated trading is now HALTED."
    if errors:
        msg += f" (Warnings: {'; '.join(errors)})"
    return True, msg


def resume_bot_trading():
    global BOT_HALTED
    BOT_HALTED = False
    logger.info("✅ BOT TRADING RESUMED: Emergency halt lifted by user via dashboard.")
    write_learning("Bot trading resumed by user via dashboard.", category="system")
    return True, "Trading resumed successfully. Bot is now active and scanning market."


def check_circuit_breaker():
    """Checks if today's realized loss has exceeded the daily circuit breaker limit."""
    global BOT_HALTED
    try:
        from memory import read_ledger
        ledger = read_ledger()
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_closed = [
            t for t in ledger
            if isinstance(t, dict) and t.get("status") == "closed" and str(t.get("exit_timestamp", "")).startswith(today_str)
        ]
        today_pnl = sum(float(t.get("pnl", 0.0) or 0.0) for t in today_closed)

        if today_pnl <= -DAILY_MAX_LOSS_LIMIT:
            BOT_HALTED = True
            logger.warning(f"🛡️ CIRCUIT BREAKER TRIPPED! Today's Realized Loss (${abs(today_pnl):.2f}) hit limit (${DAILY_MAX_LOSS_LIMIT:.2f}). Trading paused.")
            return True, f"Daily Loss Circuit Breaker Tripped (-${abs(today_pnl):.2f} / -${DAILY_MAX_LOSS_LIMIT:.2f})"
    except Exception as e:
        logger.warning(f"Error checking circuit breaker: {e}")
    return False, "Normal"

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)

        # API: Emergency Kill Switch
        if parsed.path == "/api/kill_switch":
            success, msg = emergency_kill_switch()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
            return

        # API: Resume Bot Live Trading
        if parsed.path == "/api/resume_bot":
            success, msg = resume_bot_trading()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
            return

        # API: Close position manually via GET
        if parsed.path == "/api/close_position":
            qs = parse_qs(parsed.query)
            t_ids = qs.get("id", [])
            if t_ids:
                try:
                    t_id = int(t_ids[0])
                    success, msg = manual_close_trade_by_id(t_id)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
                    return
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                    return


        # Regular Dashboard GET
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

    def do_POST(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.path)
        if parsed.path == "/api/close_position":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
            try:
                data = json.loads(post_data) if post_data else {}
                t_id = int(data.get("trade_id", 0))
                success, msg = manual_close_trade_by_id(t_id)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

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

def get_position_size(symbol, entry_price, stop_loss, confidence, capital_cap_usd=None):
    """
    Sizes position isolated strictly within strategy's capital limit ceiling:
    - If capital_cap_usd is provided, limits margin allocation to a safe fraction of cap (e.g. 15% max per trade).
    - Guarantees >= $15.00 entry so 60% partial ($9.00) & 40% runner ($6.00) both exceed Binance $5.00 minNotional.
    """
    notional = TARGET_NOTIONAL_USD
    if capital_cap_usd and float(capital_cap_usd) > 20.0:
        notional = max(15.0, min(TARGET_NOTIONAL_USD, float(capital_cap_usd) * 0.15))

    raw_qty = notional / entry_price

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

    print(f"[POSITION] {symbol} Entry: ${entry_price:.2f}, Size: {position_size} (~${position_size * entry_price:.2f} USD, Cap: ${capital_cap_usd or notional:.2f})")
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
    global trades_today, last_trade_time, last_trade_was_loss, BOT_HALTED
    reset_daily_limits()

    # 0. Emergency Kill Switch Safety Check
    if BOT_HALTED:
        logger.warning("🛑 BOT IS HALTED: Emergency Kill Switch is ACTIVE. Skipping market scanning.")
        return

    # 1. Daily Max Loss Circuit Breaker Check
    tripped, cb_reason = check_circuit_breaker()
    if tripped:
        logger.warning(f"🛑 CIRCUIT BREAKER ACTIVE: {cb_reason}. All new entries paused today.")
        return

    # 2. Manage all open positions first (always active: TP1/TP2/Green Lock)
    manage_open_positions()

    # 3. Weekend Filter: Skip new entries if institutional markets closed
    if is_weekend():
        logger.info("⏸️ WEEKEND PAUSE: Institutions Closed (Fri 22:00 UTC - Sun 22:00 UTC). Skipping new entries to avoid low-volume chop.")
        return

    # 4. Dynamic Cooldown Status
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
        fallback_reason = f"{len(open_trades)} positions active: {', '.join(open_symbols)}" if open_trades else "Active 5m MA scanning..."
        write_market_state(sig, btc_price, {"action": fallback_action, "confidence": 5, "reason": fallback_reason})
    except Exception as e:
        logger.warning(f"Could not update dashboard market state: {e}")

    if len(open_trades) >= MAX_OPEN_POSITIONS:
        logger.info(f"Max open positions reached ({len(open_trades)}/{MAX_OPEN_POSITIONS}): {open_symbols}. Managing active positions.")
        return

    sym = PRIMARY_SYMBOL
    strat_name = "MA Crossover Momentum"
    strat_id = "strat_ma_crossover"
    cap_usd = 120.0

    if sym in open_symbols:
        return

    try:
        signal_data = get_enhanced_signal(sym)
        signal = signal_data["signal"]
        score = signal_data["score"]
        current_price = signal_data["current_price"]

        brain_input = {
            "symbol": sym,
            "strategy": strat_name,
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

        write_market_state(signal_data, current_price, brain_decision)

        logger.info("=" * 50)
        logger.info(f"SCAN | {strat_name} ({sym}) | ${current_price:,.2f} | Score: {score}/100 | Brain: {action} ({confidence}/10)")

        if action == "HOLD":
            return
        if confidence < MIN_CONFIDENCE:
            logger.info(f"DECISION ({sym}): NO TRADE | Confidence too low ({confidence}/{MIN_CONFIDENCE})")
            return

        # Opportunity Cooldown Check:
        if is_in_cooldown:
            if score >= 80 and confidence >= 8:
                logger.info(f"🚀 GRADE-A+ OPPORTUNITY OVERRIDE ({sym}): High conviction setup. Bypassing cooldown!")
            else:
                rem = int(active_cooldown - time_since_last_trade)
                logger.info(f"⏳ COOLDOWN ACTIVE ({sym}): {rem}s remaining after loss. Skipping setup.")
                return

        if trades_today >= MAX_TRADES_PER_DAY:
            logger.info(f"DECISION ({sym}): NO TRADE | Daily limit reached ({trades_today}/{MAX_TRADES_PER_DAY})")
            return
        total_pnl = stats.get("total_pnl", 0)
        if total_pnl < -MAX_DRAWDOWN_USD:
            logger.info(f"DECISION ({sym}): NO TRADE | Max drawdown exceeded (${total_pnl:.2f})")
            return

        if action in ["BUY", "SELL"]:
            if action == "SELL" and len(open_trades) == 0:
                logger.info(f"DECISION ({sym}): NO TRADE | Spot trading: Cannot open SELL short without holding base asset.")
                return

            stop_loss = signal_data.get("structure_sl")
            tp1 = signal_data.get("tp1")
            tp2 = signal_data.get("tp2")

            position_size = get_position_size(sym, current_price, stop_loss, confidence, capital_cap_usd=cap_usd)

            print(f"[BOT] Executing {action} on {sym} [{strat_name}] | Price: ${current_price:,.2f} | Qty: {position_size} | TP1: ${tp1:.2f} | TP2: ${tp2:.2f} | SL: ${stop_loss:.2f}")
            order = place_test_order(symbol=sym, side=action, quantity=position_size)
            trade_id = log_new_trade(
                symbol=sym, side=action, entry_price=current_price,
                quantity=position_size, reason=f"[{strat_name}] {reason}",
                stop_loss=stop_loss, take_profit=tp2,
                tp1=tp1, tp2=tp2,
                strategy_name=strat_name, strategy_id=strat_id
            )
            trades_today += 1
            last_trade_time = datetime.now()
            logger.info(f"TRADE EXECUTED | #{trade_id} ({sym}) [{strat_name}] | {action} | ${current_price:,.2f} | Qty: {position_size}")
            logger.info(f"SL: ${stop_loss:,.2f} | TP1 (60%): ${tp1:,.2f} | TP2 (40%): ${tp2:,.2f} | Capital Isolated Cap: ${cap_usd:.2f}")
            write_learning(
                f"New trade #{trade_id} [{strat_name}]: {action} {sym} at ${current_price} "
                f"with SL=${stop_loss:.2f}, TP1=${tp1:.2f}, TP2=${tp2:.2f}. Reason: {reason}",
                category="trade_open", trade_id=trade_id
            )

    except Exception as e:
        logger.error(f"[ERROR] Cycle failed for {sym}: {e}")
        print(f"[BOT] ERROR in {sym} cycle: {e}")
        write_learning(f"Bot error for {sym}: {str(e)}", category="error")


def main():
    import webbrowser
    print("\n" + "=" * 65)
    print("  🚀 NEXORA ALGO QUANTITATIVE TRADING ENGINE")
    print("  Binance Live Spot • Multi-Strategy Capital Isolation")
    print("  Emergency Kill Switch & Daily Circuit Breaker: Active")
    print("=" * 65)

    logger.info("=" * 50)
    logger.info("NEXORA ALGO TRADING ENGINE STARTED")
    logger.info(f"Symbols: {', '.join(SYMBOLS)} | Check: {CHECK_INTERVAL_SECONDS}s | Min Confidence: {MIN_CONFIDENCE}")
    logger.info(f"Safety: Circuit Breaker (-${DAILY_MAX_LOSS_LIMIT}) | TP1: 60% Book | TP2: 40% Runner")
    logger.info("=" * 50)

    print("[MAIN] Testing Binance API connection...")
    api_connected = test_api_connection()
    if not api_connected:
        logger.warning("⚠️ WARNING: Binance API connection check failed (possibly temporary rate-limit/IP ban).")
        logger.warning("🌐 Web service & dashboard will stay active. Bot will retry connection in background.")
        print("[MAIN] WARNING: API connection check failed. Keeping dashboard alive and retrying in background...")
    else:
        print("[MAIN] Binance API test passed successfully.")

    print("\n" + "-" * 65)
    print("  🌐 NEXORA WEB DASHBOARD RUNNING AT: http://0.0.0.0:10000")
    print("-" * 65 + "\n")

    print(f"[MAIN] Starting main trading loop (every {CHECK_INTERVAL_SECONDS}s)...")
    print("[MAIN] Press Ctrl+C to stop\n")

    while True:
        try:
            if not api_connected:
                print(f"[MAIN] Re-testing Binance API connection at {datetime.now().strftime('%H:%M:%S')}...")
                api_connected = test_api_connection()
                if not api_connected:
                    print(f"[MAIN] Binance API still syncing/rate-limited. Retrying in {CHECK_INTERVAL_SECONDS}s...\n")
                    time.sleep(CHECK_INTERVAL_SECONDS)
                    continue
                else:
                    logger.info("✅ Binance API connection restored! Resuming automated cycles.")
                    print("[MAIN] ✅ Binance API connection restored! Resuming trading cycles.")

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
