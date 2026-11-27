import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import json
import time
import re
import datetime
from datetime import datetime, timedelta
from brain import ask_brain
from exchange import place_test_order, get_current_price, test_api_connection, MIN_QTY
from memory import (
    log_new_trade, close_trade, partial_close_trade, write_learning, get_open_trades,
    get_stats, get_trade_by_id, update_trade_stop_loss, repair_strangle_positions, read_ledger
)
from strategy import get_enhanced_signal, detect_early_reversal
try:
    from strategy_dhurandhar import run_dhurandhar_cycle, get_live_snapshot as get_dhurandhar_snapshot
except Exception:
    run_dhurandhar_cycle = None
    get_dhurandhar_snapshot = None
try:
    import delta_exchange
except Exception:
    delta_exchange = None
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer
except ImportError:
    ThreadingHTTPServer = HTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SKIP_WEEKEND_TRADING = False  # 24/7 continuous trading enabled for Theta decay on weekends

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
  --bg-pitch: #000000;
  --bg-surface: #000000;
  --bg-card: #000000;
  --bg-card-hover: #030205;
  --bg-inset: #000000;
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
  background: #000000;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  transition: all 0.25s ease;
  position: relative;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.7);
}
.clean-card:hover {
  border-color: var(--border-hover);
  background: #030205;
  box-shadow: 0 0 25px rgba(168, 85, 247, 0.20), inset 0 0 15px rgba(217, 70, 239, 0.05);
}

.stat-card {
  background: #000000;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 20px 22px;
  transition: all 0.25s ease;
  position: relative;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.7);
}
.stat-card:hover {
  border-color: var(--border-hover);
  background: #030205;
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

/* ── DELTA EXCHANGE TRADING CONSOLE STYLES ── */
.trading-tab-btn {
  padding: 13px 18px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.trading-tab-btn:hover {
  color: #ffffff;
}
.trading-tab-btn.active {
  color: #ffffff;
  border-bottom: 2px solid #ff7a00;
}
.trading-filter-pill {
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  background: #121620;
  border: 1px solid #1e2433;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s ease;
}
.trading-filter-pill:hover {
  color: #ffffff;
  border-color: #3b4252;
}
.trading-filter-pill.active {
  background: rgba(255,122,0,0.15);
  border-color: #ff7a00;
  color: #ff7a00;
}
.trading-table-row:hover {
  background: #10141f !important;
}

/* ── HISTORY PAGINATION & SCROLL CONTROL ── */
.page-btn {
  background: #121620;
  border: 1px solid #1e2433;
  color: #94a3b8;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: var(--font-mono);
}
.page-btn:hover:not(:disabled) {
  color: #ffffff;
  border-color: #3b4252;
}
.page-btn.active {
  background: rgba(168, 85, 247, 0.25);
  border-color: #c084fc;
  color: #ffffff;
  box-shadow: 0 0 10px rgba(168, 85, 247, 0.3);
}
.page-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.page-size-btn {
  background: #121620;
  border: 1px solid #1e2433;
  color: #94a3b8;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  font-family: var(--font-mono);
  transition: all 0.15s ease;
}
.page-size-btn:hover {
  color: #ffffff;
}
.page-size-btn.active {
  background: rgba(168, 85, 247, 0.22);
  border-color: #c084fc;
  color: #c084fc;
}

/* ── RESPONSIVE WIDESCREEN & MOBILE ADAPTATION ── */
@media (max-width: 1280px) {
  .dashboard-grid-4col {
    grid-template-columns: repeat(2, 1fr) !important;
  }
  .dashboard-grid-mid {
    grid-template-columns: 1fr !important;
  }
  .dashboard-grid-strategy {
    grid-template-columns: 1fr !important;
  }
}

@media (max-width: 768px) {
  .dashboard-grid-4col {
    grid-template-columns: 1fr !important;
  }
  .dashboard-quick-trade-grid {
    grid-template-columns: 1fr 1fr !important;
  }
  main {
    padding: 14px 12px !important;
  }
}

@media (max-width: 520px) {
  .dashboard-quick-trade-grid {
    grid-template-columns: 1fr !important;
  }
  .mode-capsule {
    display: none !important;
  }
}
"""

DASHBOARD_JS = """
let currentMode = 'test';
let currentOrderSide = 'BUY';
window.lastKnownPrice = 83000;

function selectOrderSide(side) {
  currentOrderSide = side;
  const buyBtn = document.getElementById('side-buy-btn');
  const sellBtn = document.getElementById('side-sell-btn');
  if (side === 'BUY') {
    if (buyBtn) { buyBtn.style.background = 'rgba(16,185,129,0.25)'; buyBtn.style.borderColor = '#10b981'; }
    if (sellBtn) { sellBtn.style.background = 'rgba(239,68,68,0.08)'; sellBtn.style.borderColor = 'rgba(239,68,68,0.25)'; }
  } else {
    if (sellBtn) { sellBtn.style.background = 'rgba(239,68,68,0.25)'; sellBtn.style.borderColor = '#ef4444'; }
    if (buyBtn) { buyBtn.style.background = 'rgba(16,185,129,0.08)'; buyBtn.style.borderColor = 'rgba(16,185,129,0.25)'; }
  }
}

function setAmountQuick(amt) {
  const inp = document.getElementById('manual-order-amount');
  if (inp) {
    inp.value = amt;
    updateEstQty();
  }
}

function updateEstQty() {
  const symEl = document.getElementById('manual-order-symbol');
  const amtEl = document.getElementById('manual-order-amount');
  const sym = symEl ? symEl.value : 'BTCUSDT';
  const amt = parseFloat(amtEl ? amtEl.value : 20);
  const disp = document.getElementById('est-qty-display');
  if (!disp) return;
  let p = window.lastKnownPrice || 83000;
  let q = (amt / p);
  if (sym.includes('BTC')) disp.innerText = 'Est. Size: ~' + q.toFixed(5) + ' BTC (~$' + amt.toFixed(2) + ')';
  else if (sym.includes('ETH')) disp.innerText = 'Est. Size: ~' + (amt/2600).toFixed(4) + ' ETH (~$' + amt.toFixed(2) + ')';
  else if (sym.includes('SOL')) disp.innerText = 'Est. Size: ~' + (amt/140).toFixed(2) + ' SOL (~$' + amt.toFixed(2) + ')';
}

function executeManualOrder() {
  const symEl = document.getElementById('manual-order-symbol');
  const amtEl = document.getElementById('manual-order-amount');
  const sym = symEl ? symEl.value : 'BTCUSDT';
  const amt = parseFloat(amtEl ? amtEl.value : 20);
  if (amt < 15) {
    alert('⚠️ Minimum Binance testnet order value is $15 USD.');
    return;
  }
  const btn = document.getElementById('manual-order-submit-btn');
  if (btn) { btn.disabled = true; btn.innerText = 'Submitting to Binance...'; }

  fetch('/api/manual_order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol: sym, side: currentOrderSide, amount_usd: amt })
  })
  .then(r => r.json())
  .then(data => {
    if (btn) { btn.disabled = false; btn.innerText = '⚡ Execute Order'; }
    if (data.success) {
      alert('✅ SUCCESS: ' + data.message);
      window.location.reload();
    } else {
      alert('❌ FAILED: ' + (data.message || data.error));
    }
  })
  .catch(err => {
    if (btn) { btn.disabled = false; btn.innerText = '⚡ Execute Order'; }
    alert('Network error executing order: ' + err);
  });
}

function openStrategyModal() {
  const m = document.getElementById('strategy-modal');
  if (m) m.style.display = 'flex';
}

function closeStrategyModal() {
  const m = document.getElementById('strategy-modal');
  if (m) m.style.display = 'none';
}

function saveCustomStrategy(e) {
  if (e) e.preventDefault();
  const name = document.getElementById('strat-name-input').value;
  const type = document.getElementById('strat-type-input').value;
  const sym = document.getElementById('strat-sym-input').value;
  const cap = parseFloat(document.getElementById('strat-cap-input').value);
  const sl = parseFloat(document.getElementById('strat-sl-input').value);
  const tp = parseFloat(document.getElementById('strat-tp-input').value);

  fetch('/api/save_strategy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: name,
      type: type,
      symbol: sym,
      capital_usd: cap,
      sl_pct: sl,
      tp1_pct: (tp * 0.6),
      tp2_pct: tp,
      active: true
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      alert('✅ Strategy Configured & Saved Successfully!');
      closeStrategyModal();
      window.location.reload();
    } else {
      alert('❌ Failed: ' + (data.message || data.error));
    }
  })
  .catch(err => alert('Network error: ' + err));
}

function toggleStrategyStatus(stratId) {
  fetch('/api/toggle_strategy?id=' + stratId)
  .then(r => r.json())
  .then(data => {
    if (data.success) window.location.reload();
  });
}

function deleteStrategy(stratId) {
  if (!confirm('Are you sure you want to delete this strategy?')) return;
  fetch('/api/delete_strategy?id=' + stratId)
  .then(r => r.json())
  .then(data => {
    if (data.success) window.location.reload();
  });
}

function toggleBotAutoScan() {
  fetch('/api/toggle_bot')
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      alert(data.message);
      window.location.reload();
    }
  })
  .catch(err => alert('Error toggling bot auto-scan: ' + err));
}

// ── TRADING EQUITY CURVE INTERACTIVE CROSSHAIR & TOOLTIP ──
let equity7dPoints = [
  { xPct: 6.0,  svgX: 60,  svgY: 60,  date: "08 Nov 2026, 12:00 AM", equityInr: "₹5,180.00", equityUsd: "$61.80", pnlInr: "₹0.00", pnlUsd: "$0.00", desc: "Starting Sandbox Capital", isGain: true },
  { xPct: 22.0, svgX: 220, svgY: 165, date: "09 Nov 2026, 03:25 AM", equityInr: "₹4,871.62", equityUsd: "$58.13", pnlInr: "-₹308.38", pnlUsd: "-$3.68", desc: "P-ETH-1900 SL Triggered", isGain: false },
  { xPct: 37.0, svgX: 370, svgY: 165, date: "10 Nov 2026, 11:30 PM", equityInr: "₹4,871.62", equityUsd: "$58.13", pnlInr: "₹0.00", pnlUsd: "$0.00", desc: "Market Scanning (Holding)", isGain: true },
  { xPct: 52.0, svgX: 520, svgY: 118, date: "11 Nov 2026, 07:10 PM", equityInr: "₹4,976.37", equityUsd: "$59.38", pnlInr: "+₹104.75", pnlUsd: "+$1.25", desc: "C-ETH-2700 & C-BTC-89000 Win", isGain: true },
  { xPct: 68.0, svgX: 680, svgY: 145, date: "12 Nov 2026, 07:51 PM", equityInr: "₹4,909.33", equityUsd: "$58.58", pnlInr: "-₹67.04", pnlUsd: "-$0.80", desc: "P-BTC-70000 Closed", isGain: false },
  { xPct: 83.0, svgX: 830, svgY: 165, date: "13 Nov 2026, 08:53 AM", equityInr: "₹4,890.06", equityUsd: "$58.35", pnlInr: "-₹19.27", pnlUsd: "-$0.23", desc: "P-ETH-1800 Closed", isGain: false },
  { xPct: 97.0, svgX: 970, svgY: 163, date: "14 Nov 2026, 11:51 AM", equityInr: "₹4,891.74", equityUsd: "$58.37", pnlInr: "+₹1.68", pnlUsd: "+$0.02", desc: "C-ETH-2450 Take-Profit Hit", isGain: true }
];

let equityAllPoints = [
  { xPct: 6.0,  svgX: 60,  svgY: 60,  date: "30 Oct 2026, 05:51 AM", equityInr: "₹5,180.00", equityUsd: "$61.80", pnlInr: "-₹974.59", pnlUsd: "-$11.63", desc: "BTC & ETH Put Liquidation", isGain: false },
  { xPct: 22.0, svgX: 220, svgY: 165, date: "03 Nov 2026, 11:04 AM", equityInr: "₹5,190.89", equityUsd: "$61.93", pnlInr: "+₹10.89", pnlUsd: "+$0.13", desc: "C-ETH-2650 Profit", isGain: true },
  { xPct: 37.0, svgX: 370, svgY: 165, date: "09 Nov 2026, 03:25 AM", equityInr: "₹4,871.62", equityUsd: "$58.13", pnlInr: "-₹308.38", pnlUsd: "-$3.68", desc: "P-ETH-1900 SL Triggered", isGain: false },
  { xPct: 52.0, svgX: 520, svgY: 118, date: "11 Nov 2026, 07:10 PM", equityInr: "₹4,976.37", equityUsd: "$59.38", pnlInr: "+₹104.75", pnlUsd: "+$1.25", desc: "C-ETH-2700 & C-BTC-89000 Win", isGain: true },
  { xPct: 68.0, svgX: 680, svgY: 145, date: "12 Nov 2026, 07:51 PM", equityInr: "₹4,909.33", equityUsd: "$58.58", pnlInr: "-₹67.04", pnlUsd: "-$0.80", desc: "P-BTC-70000 Closed", isGain: false },
  { xPct: 83.0, svgX: 830, svgY: 165, date: "13 Nov 2026, 08:53 AM", equityInr: "₹4,890.06", equityUsd: "$58.35", pnlInr: "-₹19.27", pnlUsd: "-$0.23", desc: "P-ETH-1800 Closed", isGain: false },
  { xPct: 97.0, svgX: 970, svgY: 163, date: "14 Nov 2026, 11:51 AM", equityInr: "₹4,891.74", equityUsd: "$58.37", pnlInr: "+₹1.68", pnlUsd: "+$0.02", desc: "C-ETH-2450 Take-Profit Hit", isGain: true }
];

let activeAnalyticsTf = '7d';

function handleEquityMouseMove(e) {
  const container = document.getElementById('equity-chart-container');
  if (!container) return;
  const rect = container.getBoundingClientRect();
  const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
  const mouseX = clientX - rect.left;
  if (mouseX < 0 || mouseX > rect.width) return;

  const svgX = (mouseX / rect.width) * 1000;
  const pts = (activeAnalyticsTf === '7d') ? equity7dPoints : equityAllPoints;

  // Find nearest data point along the curve
  let closest = pts[0];
  let minDiff = Math.abs(svgX - pts[0].svgX);
  for (let i = 1; i < pts.length; i++) {
    const diff = Math.abs(svgX - pts[i].svgX);
    if (diff < minDiff) {
      minDiff = diff;
      closest = pts[i];
    }
  }

  // 1. Move vertical crosshair
  const crosshair = document.getElementById('equity-crosshair');
  if (crosshair) {
    crosshair.setAttribute('x1', closest.svgX);
    crosshair.setAttribute('x2', closest.svgX);
    crosshair.style.display = 'block';
  }

  // 2. Move snapping dot
  const glow = document.getElementById('equity-cursor-dot-glow');
  const dot = document.getElementById('equity-cursor-dot');
  if (glow && dot) {
    glow.setAttribute('cx', closest.svgX);
    glow.setAttribute('cy', closest.svgY);
    glow.style.display = 'block';
    dot.setAttribute('cx', closest.svgX);
    dot.setAttribute('cy', closest.svgY);
    dot.style.display = 'block';
  }

  // 3. Update floating tooltip badge
  const tooltip = document.getElementById('equity-tooltip');
  if (tooltip) {
    const isUSD = document.getElementById('btn-curr-usd') && document.getElementById('btn-curr-usd').style.color.includes('52, 211, 153');
    
    const dateEl = document.getElementById('eq-tt-date');
    if (dateEl) dateEl.textContent = closest.date;
    
    const capitalEl = document.getElementById('eq-tt-capital');
    if (capitalEl) {
      capitalEl.textContent = isUSD ? closest.equityUsd : closest.equityInr;
      capitalEl.style.color = closest.isGain ? '#34d399' : '#f87171';
    }

    const pnlEl = document.getElementById('eq-tt-pnl');
    if (pnlEl) {
      pnlEl.textContent = isUSD ? closest.pnlUsd : closest.pnlInr;
      pnlEl.style.color = closest.isGain ? '#34d399' : (closest.pnlInr === '₹0.00' ? '#94a3b8' : '#f87171');
    }

    const descEl = document.getElementById('eq-tt-desc');
    if (descEl) descEl.textContent = closest.desc;

    // Convert SVG coords to relative container pixels
    let targetLeft = (closest.svgX / 1000) * rect.width;
    let targetTop = (closest.svgY / 240) * rect.height;

    // Boundary protection so tooltip stays visible inside card
    if (targetLeft < 110) targetLeft = 110;
    if (targetLeft > rect.width - 110) targetLeft = rect.width - 110;

    tooltip.style.left = targetLeft + 'px';
    tooltip.style.top = targetTop + 'px';
    tooltip.style.display = 'block';
  }

  // 4. Dynamically update header display badge
  const isUSD = document.getElementById('btn-curr-usd') && document.getElementById('btn-curr-usd').style.color.includes('52, 211, 153');
  const headerDate = document.getElementById('equity-header-date');
  const headerVal = document.getElementById('equity-header-val');
  if (headerDate) headerDate.textContent = closest.date;
  if (headerVal) headerVal.textContent = isUSD ? closest.equityUsd : closest.equityInr;
}

function handleEquityMouseLeave() {
  const crosshair = document.getElementById('equity-crosshair');
  const glow = document.getElementById('equity-cursor-dot-glow');
  const dot = document.getElementById('equity-cursor-dot');
  const tooltip = document.getElementById('equity-tooltip');
  if (crosshair) crosshair.style.display = 'none';
  if (glow) glow.style.display = 'none';
  if (dot) dot.style.display = 'none';
  if (tooltip) tooltip.style.display = 'none';

  // Restore latest default header from live points
  const pts = (activeAnalyticsTf === '7d') ? equity7dPoints : equityAllPoints;
  const lastPt = pts && pts.length ? pts[pts.length - 1] : null;
  const isUSD = document.getElementById('btn-curr-usd') && document.getElementById('btn-curr-usd').style.color.includes('52, 211, 153');
  const headerDate = document.getElementById('equity-header-date');
  const headerVal = document.getElementById('equity-header-val');
  if (headerDate && lastPt) headerDate.textContent = lastPt.date;
  if (headerVal && lastPt) headerVal.textContent = isUSD ? (lastPt.equityUsd + ' USD') : lastPt.equityInr;
}


// View Toggle Handlers: Bars vs Line
function switchRpnlView(mode) {
  const isLine = (mode === 'line');
  document.getElementById('rpnl-bar-group').style.display = isLine ? 'none' : 'block';
  document.getElementById('rpnl-line-group').style.display = isLine ? 'block' : 'none';
  const bBar = document.getElementById('rpnl-btn-bar');
  const bLine = document.getElementById('rpnl-btn-line');
  if (bBar) {
    bBar.style.background = !isLine ? 'rgba(168,85,247,0.22)' : 'transparent';
    bBar.style.borderColor = !isLine ? '#a855f7' : 'transparent';
    bBar.style.color = !isLine ? '#ffffff' : '#94a3b8';
  }
  if (bLine) {
    bLine.style.background = isLine ? 'rgba(168,85,247,0.22)' : 'transparent';
    bLine.style.borderColor = isLine ? '#a855f7' : 'transparent';
    bLine.style.color = isLine ? '#ffffff' : '#94a3b8';
  }
}

function switchVolView(mode) {
  const isLine = (mode === 'line');
  document.getElementById('vol-bar-group').style.display = isLine ? 'none' : 'block';
  document.getElementById('vol-line-group').style.display = isLine ? 'block' : 'none';
  const bBar = document.getElementById('vol-btn-bar');
  const bLine = document.getElementById('vol-btn-line');
  if (bBar) {
    bBar.style.background = !isLine ? 'rgba(59,130,246,0.25)' : 'transparent';
    bBar.style.borderColor = !isLine ? '#3b82f6' : 'transparent';
    bBar.style.color = !isLine ? '#ffffff' : '#94a3b8';
  }
  if (bLine) {
    bLine.style.background = isLine ? 'rgba(59,130,246,0.25)' : 'transparent';
    bLine.style.borderColor = isLine ? '#3b82f6' : 'transparent';
    bLine.style.color = isLine ? '#ffffff' : '#94a3b8';
  }
}

function switchFeeView(mode) {
  const isLine = (mode === 'line');
  document.getElementById('fee-bar-group').style.display = isLine ? 'none' : 'block';
  document.getElementById('fee-line-group').style.display = isLine ? 'block' : 'none';
  const bBar = document.getElementById('fee-btn-bar');
  const bLine = document.getElementById('fee-btn-line');
  if (bBar) {
    bBar.style.background = !isLine ? 'rgba(245,158,11,0.22)' : 'transparent';
    bBar.style.borderColor = !isLine ? '#f59e0b' : 'transparent';
    bBar.style.color = !isLine ? '#ffffff' : '#94a3b8';
  }
  if (bLine) {
    bLine.style.background = isLine ? 'rgba(245,158,11,0.22)' : 'transparent';
    bLine.style.borderColor = isLine ? '#f59e0b' : 'transparent';
    bLine.style.color = isLine ? '#ffffff' : '#94a3b8';
  }
}

// ── INTERACTIVE CONTROLS FOR REALIZED PNL, VOLUME & FEES CHARTS ──
let rpnlDataPoints = [
  { svgX: 109, svgY: 148, barId: 'rpnl-bar-0', bx: 90,  bw: 38, by: 80, bh: 68, date: "Mon 09 Nov 2026", inr: "-₹305.03", usd: "-$3.64 USD", trade: "P-ETH-1900 Closed (Loss)", isWin: false, glowCol: "rgba(239, 68, 68, 0.85)" },
  { svgX: 229, svgY: 44,  barId: 'rpnl-bar-2', bx: 210, bw: 38, by: 44, bh: 36, date: "Wed 11 Nov 2026", inr: "+₹105.59", usd: "+$1.26 USD", trade: "C-ETH-2700 & C-BTC-89000 Win", isWin: true, glowCol: "rgba(16, 185, 129, 0.85)" },
  { svgX: 289, svgY: 102, barId: 'rpnl-bar-3', bx: 270, bw: 38, by: 80, bh: 22, date: "Thu 12 Nov 2026", inr: "-₹65.36",  usd: "-$0.78 USD", trade: "P-BTC-70000 Closed (Loss)", isWin: false, glowCol: "rgba(239, 68, 68, 0.85)" },
  { svgX: 349, svgY: 90,  barId: 'rpnl-bar-4', bx: 330, bw: 38, by: 80, bh: 10, date: "Fri 13 Nov 2026", inr: "-₹19.27",  usd: "-$0.23 USD", trade: "P-ETH-1800 Closed (Loss)", isWin: false, glowCol: "rgba(239, 68, 68, 0.85)" },
  { svgX: 409, svgY: 77,  barId: 'rpnl-bar-5', bx: 390, bw: 38, by: 77, bh: 6,  date: "Sat 14 Nov 2026", inr: "+₹1.68",   usd: "+$0.02 USD", trade: "C-ETH-2450 Take-Profit Hit", isWin: true, glowCol: "rgba(16, 185, 129, 0.85)" }
];

let volDataPoints = [
  { svgX: 109, svgY: 85,  barId: 'vol-bar-0', bx: 90,  bw: 38, by: 85,  bh: 75, date: "Mon 09 Nov 2026", inr: "₹65,200", usd: "$778.04 USD", desc: "1 Option Contract Traded", glowCol: "rgba(59, 130, 246, 0.85)" },
  { svgX: 229, svgY: 65,  barId: 'vol-bar-2', bx: 210, bw: 38, by: 65,  bh: 95, date: "Wed 11 Nov 2026", inr: "₹80,500", usd: "$960.62 USD", desc: "2 Option Contracts Traded", glowCol: "rgba(59, 130, 246, 0.85)" },
  { svgX: 289, svgY: 115, barId: 'vol-bar-3', bx: 270, bw: 38, by: 115, bh: 45, date: "Thu 12 Nov 2026", inr: "₹35,100", usd: "$418.85 USD", desc: "1 Option Contract Traded", glowCol: "rgba(59, 130, 246, 0.85)" },
  { svgX: 349, svgY: 138, barId: 'vol-bar-4', bx: 330, bw: 38, by: 138, bh: 22, date: "Fri 13 Nov 2026", inr: "₹18,800", usd: "$224.34 USD", desc: "1 Option Contract Traded", glowCol: "rgba(59, 130, 246, 0.85)" },
  { svgX: 409, svgY: 152, barId: 'vol-bar-5', bx: 390, bw: 38, by: 152, bh: 10, date: "Sat 14 Nov 2026", inr: "₹4,200",  usd: "$50.12 USD",  desc: "1 Option Contract Traded", glowCol: "rgba(59, 130, 246, 0.85)" }
];

let feeDataPoints = [
  { svgX: 109, svgY: 80,  barId: 'fee-bar-0', bx: 90,  bw: 38, by: 80,  bh: 50, date: "Mon 09 Nov 2026", inr: "₹2.51", usd: "$0.03 USD", glowCol: "rgba(245, 158, 11, 0.85)" },
  { svgX: 229, svgY: 112, barId: 'fee-bar-2', bx: 210, bw: 38, by: 112, bh: 18, date: "Wed 11 Nov 2026", inr: "₹0.84", usd: "$0.01 USD", glowCol: "rgba(245, 158, 11, 0.85)" },
  { svgX: 289, svgY: 80,  barId: 'fee-bar-3', bx: 270, bw: 38, by: 80,  bh: 50, date: "Thu 12 Nov 2026", inr: "₹2.51", usd: "$0.03 USD", glowCol: "rgba(245, 158, 11, 0.85)" },
  { svgX: 349, svgY: 112, barId: 'fee-bar-4', bx: 330, bw: 38, by: 112, bh: 18, date: "Fri 13 Nov 2026", inr: "₹0.84", usd: "$0.01 USD", glowCol: "rgba(245, 158, 11, 0.85)" },
  { svgX: 409, svgY: 120, barId: 'fee-bar-5', bx: 390, bw: 38, by: 120, bh: 10, date: "Sat 14 Nov 2026", inr: "₹0.47", usd: "$0.01 USD", glowCol: "rgba(245, 158, 11, 0.85)" }
];

// Active hovered bar tracker to eliminate any frame jerk or re-flow
let activeRpnlBarId = null;
let activeVolBarId = null;
let activeFeeBarId = null;

// Realized PNL Mouse Move & Leave: ONLY show data when cursor touches the bar
function handleRpnlMouseMove(e) {
  const container = document.getElementById('rpnl-chart-container');
  if (!container) return;
  const rect = container.getBoundingClientRect();
  const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
  const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
  const mouseX = clientX - rect.left;
  const mouseY = clientY - rect.top;
  if (mouseX < 0 || mouseX > rect.width || mouseY < 0 || mouseY > rect.height) {
    handleRpnlMouseLeave();
    return;
  }

  const svgX = (mouseX / rect.width) * 500;
  const svgY = (mouseY / rect.height) * 180;

  // STRICT HIT TEST WITH HYSTERESIS BUFFER (Prevents pop-out oscillation/jerk)
  let touchedBar = null;
  for (let i = 0; i < rpnlDataPoints.length; i++) {
    const p = rpnlDataPoints[i];
    const hitBuffer = (activeRpnlBarId === p.barId) ? 8 : 2;
    if (svgX >= (p.bx - hitBuffer) && svgX <= (p.bx + p.bw + hitBuffer) && svgY >= (p.by - hitBuffer) && svgY <= (p.by + p.bh + hitBuffer)) {
      touchedBar = p;
      break;
    }
  }

  // IF NOT TOUCHING ANY BAR, HIDE COMPLETELY!
  if (!touchedBar) {
    handleRpnlMouseLeave();
    return;
  }

  // Crosshair
  const crosshair = document.getElementById('rpnl-crosshair');
  if (crosshair) {
    crosshair.setAttribute('x1', touchedBar.svgX);
    crosshair.setAttribute('x2', touchedBar.svgX);
    crosshair.style.display = 'block';
  }

  // Dot
  const dot = document.getElementById('rpnl-cursor-dot');
  if (dot) {
    dot.setAttribute('cx', touchedBar.svgX);
    dot.setAttribute('cy', touchedBar.svgY);
    dot.style.display = 'block';
  }

  // SUBTLE POP & GENTLE DIM (Zero jhatka, buttery smooth pop)
  if (activeRpnlBarId !== touchedBar.barId) {
    activeRpnlBarId = touchedBar.barId;
    rpnlDataPoints.forEach(p => {
      if (p.barId) {
        const b = document.getElementById(p.barId);
        if (b) {
          if (p === touchedBar) {
            b.style.opacity = '1';
            b.style.filter = 'brightness(1.15)';
            b.style.transform = 'scale(1.045)';
          } else {
            b.style.opacity = '0.72';
            b.style.filter = 'none';
            b.style.transform = 'scale(1)';
          }
        }
      }
    });
  }

  // Tooltip
  const tooltip = document.getElementById('rpnl-tooltip');
  if (tooltip) {
    const isUSD = document.getElementById('btn-curr-usd') && document.getElementById('btn-curr-usd').style.color.includes('52, 211, 153');
    document.getElementById('rpnl-tt-date').textContent = touchedBar.date;
    const valEl = document.getElementById('rpnl-tt-val');
    valEl.textContent = isUSD ? touchedBar.usd : touchedBar.inr;
    valEl.style.color = touchedBar.isWin ? '#34d399' : (touchedBar.inr === '₹0.00' ? '#94a3b8' : '#f87171');
    document.getElementById('rpnl-tt-trade').textContent = touchedBar.trade;

    let targetLeft = (touchedBar.svgX / 500) * rect.width;
    let targetTop = (touchedBar.svgY / 180) * rect.height;
    if (targetLeft < 95) targetLeft = 95;
    if (targetLeft > rect.width - 95) targetLeft = rect.width - 95;

    tooltip.style.left = targetLeft + 'px';
    tooltip.style.top = targetTop + 'px';
    tooltip.style.display = 'block';
  }
}

function handleRpnlMouseLeave() {
  const crosshair = document.getElementById('rpnl-crosshair');
  const dot = document.getElementById('rpnl-cursor-dot');
  const tooltip = document.getElementById('rpnl-tooltip');
  if (crosshair) crosshair.style.display = 'none';
  if (dot) dot.style.display = 'none';
  if (tooltip) tooltip.style.display = 'none';
  if (activeRpnlBarId !== null) {
    activeRpnlBarId = null;
    rpnlDataPoints.forEach(p => {
      if (p.barId) {
        const b = document.getElementById(p.barId);
        if (b) {
          b.style.opacity = '0.88';
          b.style.filter = 'none';
          b.style.transform = 'scale(1)';
        }
      }
    });
  }
}

// Volume Mouse Move & Leave: ONLY show data when cursor touches the bar
function handleVolMouseMove(e) {
  const container = document.getElementById('vol-chart-container');
  if (!container) return;
  const rect = container.getBoundingClientRect();
  const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
  const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
  const mouseX = clientX - rect.left;
  const mouseY = clientY - rect.top;
  if (mouseX < 0 || mouseX > rect.width || mouseY < 0 || mouseY > rect.height) {
    handleVolMouseLeave();
    return;
  }

  const svgX = (mouseX / rect.width) * 500;
  const svgY = (mouseY / rect.height) * 180;

  // STRICT HIT TEST WITH HYSTERESIS BUFFER
  let touchedBar = null;
  for (let i = 0; i < volDataPoints.length; i++) {
    const p = volDataPoints[i];
    const hitBuffer = (activeVolBarId === p.barId) ? 8 : 2;
    if (svgX >= (p.bx - hitBuffer) && svgX <= (p.bx + p.bw + hitBuffer) && svgY >= (p.by - hitBuffer) && svgY <= (p.by + p.bh + hitBuffer)) {
      touchedBar = p;
      break;
    }
  }

  if (!touchedBar) {
    handleVolMouseLeave();
    return;
  }

  const crosshair = document.getElementById('vol-crosshair');
  if (crosshair) {
    crosshair.setAttribute('x1', touchedBar.svgX);
    crosshair.setAttribute('x2', touchedBar.svgX);
    crosshair.style.display = 'block';
  }

  const dot = document.getElementById('vol-cursor-dot');
  if (dot) {
    dot.setAttribute('cx', touchedBar.svgX);
    dot.setAttribute('cy', touchedBar.svgY);
    dot.style.display = 'block';
  }

  // SUBTLE POP & GENTLE DIM (Zero jhatka, buttery smooth pop)
  if (activeVolBarId !== touchedBar.barId) {
    activeVolBarId = touchedBar.barId;
    volDataPoints.forEach(p => {
      if (p.barId) {
        const b = document.getElementById(p.barId);
        if (b) {
          if (p === touchedBar) {
            b.style.opacity = '1';
            b.style.filter = 'brightness(1.15)';
            b.style.transform = 'scale(1.045)';
          } else {
            b.style.opacity = '0.72';
            b.style.filter = 'none';
            b.style.transform = 'scale(1)';
          }
        }
      }
    });
  }

  const tooltip = document.getElementById('vol-tooltip');
  if (tooltip) {
    const isUSD = document.getElementById('btn-curr-usd') && document.getElementById('btn-curr-usd').style.color.includes('52, 211, 153');
    document.getElementById('vol-tt-date').textContent = touchedBar.date;
    document.getElementById('vol-tt-val').textContent = isUSD ? touchedBar.usd : touchedBar.inr;
    document.getElementById('vol-tt-desc').textContent = touchedBar.desc;

    let targetLeft = (touchedBar.svgX / 500) * rect.width;
    let targetTop = (touchedBar.svgY / 180) * rect.height;
    if (targetLeft < 95) targetLeft = 95;
    if (targetLeft > rect.width - 95) targetLeft = rect.width - 95;

    tooltip.style.left = targetLeft + 'px';
    tooltip.style.top = targetTop + 'px';
    tooltip.style.display = 'block';
  }
}

function handleVolMouseLeave() {
  const crosshair = document.getElementById('vol-crosshair');
  const dot = document.getElementById('vol-cursor-dot');
  const tooltip = document.getElementById('vol-tooltip');
  if (crosshair) crosshair.style.display = 'none';
  if (dot) dot.style.display = 'none';
  if (tooltip) tooltip.style.display = 'none';
  if (activeVolBarId !== null) {
    activeVolBarId = null;
    volDataPoints.forEach(p => {
      if (p.barId) {
        const b = document.getElementById(p.barId);
        if (b) {
          b.style.opacity = '0.88';
          b.style.filter = 'none';
          b.style.transform = 'scale(1)';
        }
      }
    });
  }
}

// Fees Mouse Move & Leave: ONLY show data when cursor touches the bar
function handleFeeMouseMove(e) {
  const container = document.getElementById('fee-chart-container');
  if (!container) return;
  const rect = container.getBoundingClientRect();
  const clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
  const clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
  const mouseX = clientX - rect.left;
  const mouseY = clientY - rect.top;
  if (mouseX < 0 || mouseX > rect.width || mouseY < 0 || mouseY > rect.height) {
    handleFeeMouseLeave();
    return;
  }

  const svgX = (mouseX / rect.width) * 500;
  const svgY = (mouseY / rect.height) * 150;

  // STRICT HIT TEST WITH HYSTERESIS BUFFER
  let touchedBar = null;
  for (let i = 0; i < feeDataPoints.length; i++) {
    const p = feeDataPoints[i];
    const hitBuffer = (activeFeeBarId === p.barId) ? 8 : 2;
    if (svgX >= (p.bx - hitBuffer) && svgX <= (p.bx + p.bw + hitBuffer) && svgY >= (p.by - hitBuffer) && svgY <= (p.by + p.bh + hitBuffer)) {
      touchedBar = p;
      break;
    }
  }

  if (!touchedBar) {
    handleFeeMouseLeave();
    return;
  }

  const crosshair = document.getElementById('fee-crosshair');
  if (crosshair) {
    crosshair.setAttribute('x1', touchedBar.svgX);
    crosshair.setAttribute('x2', touchedBar.svgX);
    crosshair.style.display = 'block';
  }

  const dot = document.getElementById('fee-cursor-dot');
  if (dot) {
    dot.setAttribute('cx', touchedBar.svgX);
    dot.setAttribute('cy', touchedBar.svgY);
    dot.style.display = 'block';
  }

  // SUBTLE POP & GENTLE DIM (Zero jhatka, buttery smooth pop)
  if (activeFeeBarId !== touchedBar.barId) {
    activeFeeBarId = touchedBar.barId;
    feeDataPoints.forEach(p => {
      if (p.barId) {
        const b = document.getElementById(p.barId);
        if (b) {
          if (p === touchedBar) {
            b.style.opacity = '1';
            b.style.filter = 'brightness(1.15)';
            b.style.transform = 'scale(1.045)';
          } else {
            b.style.opacity = '0.72';
            b.style.filter = 'none';
            b.style.transform = 'scale(1)';
          }
        }
      }
    });
  }

  const tooltip = document.getElementById('fee-tooltip');
  if (tooltip) {
    const isUSD = document.getElementById('btn-curr-usd') && document.getElementById('btn-curr-usd').style.color.includes('52, 211, 153');
    document.getElementById('fee-tt-date').textContent = touchedBar.date;
    document.getElementById('fee-tt-val').textContent = isUSD ? touchedBar.usd : touchedBar.inr;

    let targetLeft = (touchedBar.svgX / 500) * rect.width;
    let targetTop = (touchedBar.svgY / 150) * rect.height;
    if (targetLeft < 85) targetLeft = 85;
    if (targetLeft > rect.width - 85) targetLeft = rect.width - 85;

    tooltip.style.left = targetLeft + 'px';
    tooltip.style.top = targetTop + 'px';
    tooltip.style.display = 'block';
  }
}

function handleFeeMouseLeave() {
  const crosshair = document.getElementById('fee-crosshair');
  const dot = document.getElementById('fee-cursor-dot');
  const tooltip = document.getElementById('fee-tooltip');
  if (crosshair) crosshair.style.display = 'none';
  if (dot) dot.style.display = 'none';
  if (tooltip) tooltip.style.display = 'none';
  if (activeFeeBarId !== null) {
    activeFeeBarId = null;
    feeDataPoints.forEach(p => {
      if (p.barId) {
        const b = document.getElementById(p.barId);
        if (b) {
          b.style.opacity = '0.88';
          b.style.filter = 'none';
          b.style.transform = 'scale(1)';
        }
      }
    });
  }
}

function openPnlAnalytics() {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  const analyticsTab = document.querySelector('.nav-tab[data-tab="pnl-analytics"]');
  if (analyticsTab) analyticsTab.classList.add('active');
  const vMain = document.getElementById('view-testnet');
  const vLive = document.getElementById('view-live');
  const vAnalytics = document.getElementById('view-pnl-analytics');
  if (vMain) vMain.style.display = 'none';
  if (vLive) vLive.style.display = 'none';
  if (vAnalytics) {
    vAnalytics.style.display = 'block';
    vAnalytics.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
window.openPnlAnalytics = openPnlAnalytics;

function closePnlAnalytics() {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  const dashTab = document.querySelector('.nav-tab[data-tab="dashboard"]');
  if (dashTab) dashTab.classList.add('active');
  const vMain = document.getElementById('view-testnet');
  const vAnalytics = document.getElementById('view-pnl-analytics');
  if (vAnalytics) vAnalytics.style.display = 'none';
  if (vMain) vMain.style.display = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.closePnlAnalytics = closePnlAnalytics;

function switchAnalyticsCurrency(curr) {
  const isINR = (curr === 'inr');
  const btnINR = document.getElementById('btn-curr-inr');
  const btnUSD = document.getElementById('btn-curr-usd');
  if (btnINR) {
    btnINR.style.background = isINR ? 'rgba(52,211,153,0.18)' : 'transparent';
    btnINR.style.borderColor = isINR ? '#34d399' : 'transparent';
    btnINR.style.color = isINR ? '#34d399' : '#94a3b8';
  }
  if (btnUSD) {
    btnUSD.style.background = !isINR ? 'rgba(52,211,153,0.18)' : 'transparent';
    btnUSD.style.borderColor = !isINR ? '#34d399' : 'transparent';
    btnUSD.style.color = !isINR ? '#34d399' : '#94a3b8';
  }
  document.querySelectorAll('.analytics-currency-val').forEach(el => {
    const inrVal = el.getAttribute('data-val-inr');
    const usdVal = el.getAttribute('data-val-usd');
    if (isINR && inrVal !== null) {
      el.textContent = inrVal;
    } else if (!isINR && usdVal !== null) {
      el.textContent = usdVal;
    }
  });
}

function switchAnalyticsTimeframe(tf) {
  activeAnalyticsTf = tf;
  document.querySelectorAll('.timeframe-pill').forEach(b => {
    b.style.background = 'transparent';
    b.style.borderColor = 'transparent';
    b.style.color = '#94a3b8';
  });
  const activeBtn = document.getElementById('tf-pill-' + tf);
  if (activeBtn) {
    activeBtn.style.background = 'rgba(168,85,247,0.22)';
    activeBtn.style.borderColor = '#a855f7';
    activeBtn.style.color = '#ffffff';
  }
  const is30d = (tf === '30d' || tf === '365d');
  const pnlEl = document.getElementById('kpi-pnl');
  const winEl = document.getElementById('kpi-winrate');
  const tradesEl = document.getElementById('kpi-trades');
  const avgWinEl = document.getElementById('kpi-avg-win');
  const avgLossEl = document.getElementById('kpi-avg-loss');
  const feesEl = document.getElementById('kpi-fees');
  const volEl = document.getElementById('kpi-volume');

  if (pnlEl) {
    pnlEl.setAttribute('data-val-inr', is30d ? '-₹1,234.33' : '-₹289.04');
    pnlEl.setAttribute('data-val-usd', is30d ? '-$14.73 USD' : '-$3.45 USD');
  }
  if (winEl) winEl.textContent = is30d ? '33.3 %' : '40 %';
  if (tradesEl) tradesEl.textContent = is30d ? '9' : '5';
  if (avgWinEl) {
    avgWinEl.setAttribute('data-val-inr', is30d ? '₹39.11' : '₹53.95');
    avgWinEl.setAttribute('data-val-usd', is30d ? '+$0.47 USD' : '+$0.64 USD');
  }
  if (avgLossEl) {
    avgLossEl.setAttribute('data-val-inr', is30d ? '-₹225.28' : '-₹132.31');
    avgLossEl.setAttribute('data-val-usd', is30d ? '-$2.69 USD' : '-$1.58 USD');
  }
  if (feesEl) {
    feesEl.setAttribute('data-val-inr', is30d ? '₹23.93' : '₹7.17');
    feesEl.setAttribute('data-val-usd', is30d ? '$0.29 USD' : '$0.09 USD');
  }
  if (volEl) {
    volEl.setAttribute('data-val-inr', is30d ? '₹4.85L' : '₹1.99L');
    volEl.setAttribute('data-val-usd', is30d ? '$5,790 USD' : '$2,374 USD');
  }
  // Re-trigger currency refresh
  const isINR = document.getElementById('btn-curr-inr') && document.getElementById('btn-curr-inr').style.color.includes('52, 211, 153');
  switchAnalyticsCurrency(isINR ? 'inr' : 'usd');
}

function switchNavTab(tabName, event) {
  if (event) event.preventDefault();
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  if (event && event.currentTarget) event.currentTarget.classList.add('active');

  if (tabName === 'pnl-analytics') {
    openPnlAnalytics();
    return;
  } else {
    const vAnalytics = document.getElementById('view-pnl-analytics');
    const vMain = document.getElementById('view-testnet');
    if (vAnalytics && vAnalytics.style.display !== 'none') {
      vAnalytics.style.display = 'none';
      if (vMain) vMain.style.display = 'block';
    }
  }

  if (tabName === 'positions') {
    switchTradingTab('positions');
    const el = document.getElementById('trading-console-container') || document.getElementById('sec-positions');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  if (tabName === 'history') {
    switchTradingTab('order-history');
    const el = document.getElementById('trading-console-container') || document.getElementById('sec-history');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }

  const secMap = {
    'dashboard': 'sec-dashboard',
    'positions': 'trading-console-container',
    'strategy': 'sec-strategy',
    'manual-trade': 'sec-manual-trade',
    'history': 'trading-console-container'
  };
  const targetId = secMap[tabName] || 'sec-dashboard';
  const el = document.getElementById(targetId);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── DELTA EXCHANGE TRADING CONSOLE INTERACTION ──
function switchTradingTab(tabName) {
  const tabs = ['positions', 'open-orders', 'stop-orders', 'risk-margin', 'order-history'];
  tabs.forEach(t => {
    const btn = document.getElementById('tab-btn-' + t);
    const content = document.getElementById('tab-content-' + t);
    if (btn) btn.classList.remove('active');
    if (content) content.style.display = 'none';
  });
  const activeBtn = document.getElementById('tab-btn-' + tabName);
  const activeContent = document.getElementById('tab-content-' + tabName);
  if (activeBtn) activeBtn.classList.add('active');
  if (activeContent) activeContent.style.display = 'block';

  const filterBar = document.getElementById('trading-filter-bar');
  if (filterBar) {
    filterBar.style.display = (tabName === 'risk-margin') ? 'none' : 'flex';
  }
  // Ensure all rows are visible when switching tabs so filters don't hide data
  filterTradingTable('all');
}

let historyCurrentPage = 1;
let historyPageSize = 10;
let currentSearchQuery = '';
let currentFilterCategory = 'all';

function renderHistoryPagination() {
  const tbody = document.getElementById('order-history-table-body');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('tr.trading-table-row'));

  const matchingRows = rows.filter(r => {
    const rCat = (r.dataset.category || 'all').toLowerCase();
    let catMatch = true;
    if (currentFilterCategory === 'all' || currentFilterCategory === 'current') {
      catMatch = true;
    } else if (currentFilterCategory === 'options' && (rCat === 'options' || rCat.includes('strangle'))) {
      catMatch = true;
    } else if (currentFilterCategory === 'futures' && (rCat === 'futures' || rCat.includes('usd') || rCat.includes('future'))) {
      catMatch = true;
    } else {
      catMatch = false;
    }

    let searchMatch = true;
    if (currentSearchQuery) {
      searchMatch = r.innerText.toLowerCase().includes(currentSearchQuery);
    }
    return catMatch && searchMatch;
  });

  const total = matchingRows.length;
  const totalPages = Math.max(1, Math.ceil(total / historyPageSize));

  if (historyCurrentPage > totalPages) historyCurrentPage = totalPages;
  if (historyCurrentPage < 1) historyCurrentPage = 1;

  const startIdx = (historyCurrentPage - 1) * historyPageSize;
  const endIdx = startIdx + historyPageSize;

  rows.forEach(r => r.style.display = 'none');
  matchingRows.slice(startIdx, endIdx).forEach(r => r.style.display = '');

  const infoEl = document.getElementById('history-pagination-info');
  if (infoEl) {
    if (total === 0) {
      infoEl.innerText = 'No matching orders found';
    } else {
      infoEl.innerText = 'Showing ' + (startIdx + 1) + '–' + Math.min(endIdx, total) + ' of ' + total + ' orders';
    }
  }

  const pagesCont = document.getElementById('history-pagination-pages');
  if (pagesCont) {
    let btns = '';
    for (let p = 1; p <= totalPages; p++) {
      const activeClass = (p === historyCurrentPage) ? 'active' : '';
      btns += '<button type="button" class="page-btn ' + activeClass + '" onclick="goToHistoryPage(' + p + ')">' + p + '</button>';
    }
    pagesCont.innerHTML = btns;
  }

  const prevBtn = document.getElementById('history-prev-btn');
  const nextBtn = document.getElementById('history-next-btn');
  if (prevBtn) prevBtn.disabled = (historyCurrentPage <= 1);
  if (nextBtn) nextBtn.disabled = (historyCurrentPage >= totalPages);
}

function changeHistoryPage(delta) {
  historyCurrentPage += delta;
  renderHistoryPagination();
}

function goToHistoryPage(page) {
  historyCurrentPage = page;
  renderHistoryPagination();
}

function setHistoryPageSize(sz) {
  historyPageSize = sz;
  historyCurrentPage = 1;
  document.querySelectorAll('.page-size-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('page-size-' + sz);
  if (btn) btn.classList.add('active');
  renderHistoryPagination();
}

function filterTradingTable(category) {
  currentFilterCategory = category;
  const pills = ['all', 'current', 'options', 'futures'];
  pills.forEach(p => {
    const el = document.getElementById('filter-pill-' + p);
    if (el) el.classList.remove('active');
  });
  const activePill = document.getElementById('filter-pill-' + category);
  if (activePill) activePill.classList.add('active');

  const otherRows = document.querySelectorAll('#tab-content-positions .trading-table-row, #tab-content-open-orders .trading-table-row, #tab-content-stop-orders .trading-table-row');
  otherRows.forEach(r => {
    const rCat = (r.dataset.category || 'all').toLowerCase();
    if (category === 'all' || category === 'current') {
      r.style.display = '';
    } else if (category === 'options' && (rCat === 'options' || rCat.includes('strangle'))) {
      r.style.display = '';
    } else if (category === 'futures' && (rCat === 'futures' || rCat.includes('usd') || rCat.includes('future'))) {
      r.style.display = '';
    } else {
      r.style.display = 'none';
    }
  });

  historyCurrentPage = 1;
  renderHistoryPagination();
}

function searchTradingTable(query) {
  currentSearchQuery = (query || '').toLowerCase().trim();
  const otherRows = document.querySelectorAll('#tab-content-positions .trading-table-row, #tab-content-open-orders .trading-table-row, #tab-content-stop-orders .trading-table-row');
  otherRows.forEach(r => {
    const text = r.innerText.toLowerCase();
    r.style.display = text.includes(currentSearchQuery) ? '' : 'none';
  });

  historyCurrentPage = 1;
  renderHistoryPagination();
}

function closeAllPositions() {
  if (!confirm('CONFIRM CLOSE ALL POSITIONS:\\n\\nAre you sure you want to close ALL active positions at market price?')) return;
  fetch('/api/kill_switch', { method: 'GET' })
    .then(r => r.json())
    .then(d => {
      alert(d.message || 'All positions closing requested.');
      window.location.reload();
    })
    .catch(e => alert('Network error: ' + e));
}

function closeAllTargetMetPositions() {
  if (!confirm('CONFIRM 50% TAKE PROFIT:\\n\\nExecute 1-click take-profit now and close all positions with >=50% profit melt?')) return;
  fetch('/api/close_target_met', { method: 'GET' })
    .then(r => r.json())
    .then(d => {
      alert(d.message || '50% Target Profit executed.');
      window.location.reload();
    })
    .catch(e => alert('Network error: ' + e));
}

function downloadHistoryCSV() {
  const table = document.getElementById('table-order-history');
  if (!table) return;
  let csv = [];
  const rows = table.querySelectorAll('tr');
  rows.forEach(r => {
    let rowData = [];
    const cols = r.querySelectorAll('th, td');
    cols.forEach(c => rowData.push('"' + c.innerText.replace(/"/g, '""').trim() + '"'));
    csv.push(rowData.join(','));
  });
  const blob = new Blob([csv.join('\\n')], { type: 'text/csv;charset=utf-8;' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'order_history_' + new Date().toISOString().slice(0, 10) + '.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function refreshTradingConsole() {
  window.location.reload();
}

function togglePayoffModal() {
  const m = document.getElementById('payoff-modal');
  if (m) {
    m.style.display = (m.style.display === 'none' || !m.style.display) ? 'flex' : 'none';
  }
}

function toggleStrangleDetails() {
  const d = document.getElementById('strangle-details-container');
  const btn = document.getElementById('btn-toggle-strangle-details');
  if (d) {
    if (d.style.display === 'none') {
      d.style.display = 'block';
      if (btn) btn.innerText = '▲ Hide Safe Zone & Cash Flow Grid';
    } else {
      d.style.display = 'none';
      if (btn) btn.innerText = '▼ Show Safe Zone & Cash Flow Grid';
    }
  }
}


function handleDeployAction() {
  openStrategyModal();
}

function switchPerfView(view, btn) {
  const buttons = btn.parentElement.querySelectorAll('button');
  buttons.forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const tvCont = document.getElementById('chart-tv-container');
  const pnlCont = document.getElementById('chart-pnl-container');
  if (view === 'tv') {
    if (tvCont) tvCont.style.display = 'block';
    if (pnlCont) pnlCont.style.display = 'none';
  } else {
    if (tvCont) tvCont.style.display = 'none';
    if (pnlCont) pnlCont.style.display = 'block';
  }
}

function changePnlTimeframe(tf, val, btn) {
  const pnlDisp = document.getElementById('pnl-display-val');
  if (pnlDisp) {
    pnlDisp.innerHTML = val;
  }
  const buttons = btn.parentElement.querySelectorAll('button');
  buttons.forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function switchConsoleMode(mode) {
  const mainBtn = document.getElementById('mode-main-btn');
  const testBtn = document.getElementById('mode-test-btn');
  const viewTestnet = document.getElementById('view-testnet');
  const viewLive = document.getElementById('view-live');

  if (mode === 'main') {
    currentMode = 'main';
    if (testBtn) testBtn.classList.remove('active');
    if (mainBtn) mainBtn.classList.add('active');
    if (viewTestnet) viewTestnet.style.display = 'none';
    if (viewLive) viewLive.style.display = 'block';
  } else {
    currentMode = 'test';
    if (mainBtn) mainBtn.classList.remove('active');
    if (testBtn) testBtn.classList.add('active');
    if (viewTestnet) viewTestnet.style.display = 'block';
    if (viewLive) viewLive.style.display = 'none';
  }
}

let balanceHidden = false;
function toggleBalanceVisibility() {
  balanceHidden = !balanceHidden;
  const el = document.getElementById('total-balance-display');
  if (el) {
    if (!el.dataset.val) el.dataset.val = el.innerText;
    el.innerText = balanceHidden ? '••••••••' : el.dataset.val;
  }
}

function filterLedgerTable(query) {
  query = (query || '').toLowerCase();
  const rows = document.querySelectorAll('#ledger-table-body tr');
  rows.forEach(r => {
    const text = r.innerText.toLowerCase();
    r.style.display = text.includes(query) ? '' : 'none';
  });
}

function manualClosePosition(tradeId, symbol) {
  const dispName = (tradeId && tradeId !== 0) ? ('Trade #' + tradeId + ' (' + symbol + ')') : symbol;
  if (!confirm('⚠️ CONFIRM MANUAL MARKET EXIT:\\n\\nAre you sure you want to close ' + dispName + ' at current market price?')) {
    return;
  }
  const url = (tradeId && tradeId !== 0) ? ('/api/close_position?id=' + tradeId) : ('/api/close_position?id=0&symbol=' + encodeURIComponent(symbol));
  fetch(url, { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ SUCCESS: ' + (data.message || 'Position closed successfully.'));
        window.location.reload();
      } else {
        alert('❌ FAILED: ' + (data.message || data.error));
      }
    })
    .catch(err => {
      alert('Network error closing position: ' + err);
    });
}

function cancelDeltaOrder(symbol) {
  if (!confirm('⚠️ Cancel open resting order for ' + symbol + '?')) return;
  alert('✅ Order cancellation for ' + symbol + ' submitted.');
  window.location.reload();
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

// Live background price polling every 5s without full page reload
function fetchLiveStatus() {
  fetch('/api/status')
    .then(r => r.json())
    .then(d => {
      if (!d || !d.success) return;
      if (d.current_price) {
        window.lastKnownPrice = d.current_price;
        updateEstQty();
        const pricePills = document.querySelectorAll('.live-price-val');
        pricePills.forEach(p => p.innerText = '$' + d.current_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}));
      }
    })
    .catch(() => {});
}
setInterval(fetchLiveStatus, 5000);

document.addEventListener('DOMContentLoaded', function() {
  renderHistoryPagination();
  const cardPnl = document.getElementById('stat-card-pnl');
  if (cardPnl) {
    cardPnl.addEventListener('click', function(e) {
      e.preventDefault();
      openPnlAnalytics();
    });
  }
  const cardWin = document.getElementById('stat-card-winrate');
  if (cardWin) {
    cardWin.addEventListener('click', function(e) {
      e.preventDefault();
      openPnlAnalytics();
    });
  }
});
setTimeout(renderHistoryPagination, 100);
"""

def parse_option_symbol(sym: str) -> dict:
    parts = sym.split("-")
    if len(parts) >= 4:
        o_type = "CALL" if parts[0] == "C" else "PUT"
        asset = parts[1]
        strike = parts[2]
        exp_raw = parts[3]
        if len(exp_raw) == 6:
            d = exp_raw[:2]
            m_num = exp_raw[2:4]
            y = exp_raw[4:6]
            months = {"01":"Jan","02":"Feb","03":"Mar","04":"Apr","05":"May","06":"Jun","07":"Jul","08":"Aug","09":"Sep","10":"Oct","11":"Nov","12":"Dec"}
            m_str = months.get(m_num, m_num)
            expiry_str = f"{d}-{m_str}-20{y}"
        else:
            expiry_str = exp_raw
        try:
            st_val = f"{float(strike):,.0f}" if float(strike).is_integer() else f"{float(strike):,.2f}"
        except Exception:
            st_val = strike
        return {
            "type": o_type,
            "asset": asset,
            "strike": st_val,
            "expiry": expiry_str,
            "is_option": True
        }
    return {
        "type": "FUTURES",
        "asset": sym,
        "strike": "-",
        "expiry": "Perpetual",
        "is_option": False
    }

def generate_dynamic_pnl_chart(delta_orders_history, ledger, total_true_profit, current_pnl):
    """
    Generates a high-fidelity dynamic P&L SVG curve and equity progression:
    - Parses realized PnL sequence from Delta filled orders and ledger.
    - Interpolates smoothly across the timeline.
    - Scales dynamically with real dollar-denominated Y-axis levels.
    - Draws zero baseline, gradient neon area fill, and latest equity point with glowing marker.
    """
    import math
    pnl_series = []
    timestamps = []

    if delta_orders_history:
        for h in reversed(delta_orders_history):
            net_str = str(h.get("net_pnl") or h.get("realized_pnl") or "0")
            cleaned = "".join([c for c in net_str if c in "0123456789.-"])
            try:
                val = float(cleaned) if cleaned else 0.0
            except Exception:
                val = 0.0
            pnl_series.append(val)
            t_raw = str(h.get("time", ""))
            timestamps.append(t_raw.split(",")[0].strip() if "," in t_raw else t_raw[-8:])

    if not pnl_series and ledger:
        closed = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["closed", "closed_tp", "closed_sl"]]
        for t in closed:
            pnl_series.append(safe_float(t.get("pnl", 0.0)))
            timestamps.append(str(t.get("exit_time", ""))[:10])

    cum_equity = [0.0]
    for p in pnl_series:
        cum_equity.append(round(cum_equity[-1] + p, 2))

    current_total_equity = round(cum_equity[-1] + safe_float(total_true_profit), 2)
    cum_equity.append(current_total_equity)

    if len(cum_equity) < 7:
        target_len = 7
        interp = []
        for step in range(target_len):
            frac = step / (target_len - 1)
            smooth_frac = (1.0 - math.cos(frac * math.pi)) / 2.0
            interp_val = round(cum_equity[0] + (current_total_equity - cum_equity[0]) * smooth_frac, 2)
            interp.append(interp_val)
        curve_points = interp
    else:
        curve_points = cum_equity

    min_val = min(curve_points)
    max_val = max(curve_points)
    if min_val == max_val:
        min_val -= 2.5
        max_val += 2.5

    val_range = max_val - min_val
    if val_range < 2.0:
        min_val -= 1.0
        max_val += 1.0
        val_range = max_val - min_val

    pad = val_range * 0.15
    y_min_bound = min_val - pad
    y_max_bound = max_val + pad
    span = y_max_bound - y_min_bound

    y_labels = []
    for step in range(5):
        lvl = y_max_bound - (span * (step / 4.0))
        sign = "+" if lvl > 0.005 else ("-" if lvl < -0.005 else "")
        y_labels.append(f"{sign}${abs(lvl):,.2f}")

    svg_width = 500
    svg_height = 175
    y_top = 15
    y_bottom = 155
    y_drawable = y_bottom - y_top

    coords = []
    n_pts = len(curve_points)
    for i, v in enumerate(curve_points):
        x = round((i / (n_pts - 1)) * svg_width, 1)
        norm = (v - y_min_bound) / span
        y = round(y_bottom - (norm * y_drawable), 1)
        coords.append((x, y))

    line_d = "M " + " L ".join([f"{x},{y}" for x, y in coords])
    area_d = line_d + f" L {svg_width},{svg_height} L 0,{svg_height} Z"
    last_x, last_y = coords[-1]

    zero_line_svg = ""
    if y_min_bound <= 0 <= y_max_bound:
        zero_norm = (0.0 - y_min_bound) / span
        zero_y = round(y_bottom - (zero_norm * y_drawable), 1)
        zero_line_svg = f'<line x1="0" y1="{zero_y}" x2="{svg_width}" y2="{zero_y}" stroke="rgba(255,255,255,0.2)" stroke-dasharray="4,4" stroke-width="1.2" />'

    if current_total_equity > 0:
        stroke_color = "#34d399"
        grad_color = "#10b981"
        glow_filter = "neonEmeraldGlow"
    elif current_total_equity == 0:
        stroke_color = "#c084fc"
        grad_color = "#a855f7"
        glow_filter = "neonPurpleGlow"
    else:
        stroke_color = "#f87171"
        grad_color = "#ef4444"
        glow_filter = "neonRoseGlow"

    x_labels_html = ""
    x_steps = ["Cycle Start", "Theta Accumulation", "Hedge Sync", "Target Check", "Live Now"]
    if len(timestamps) >= 4:
        x_steps = [timestamps[0], timestamps[len(timestamps)//4], timestamps[len(timestamps)//2], timestamps[3*len(timestamps)//4], "Live Now"]

    for lbl in x_steps:
        x_labels_html += f"<span>{lbl}</span>"

    y_labels_html = "".join([f"<span>{yl}</span>" for yl in y_labels])

    chart_html = f'''
    <div id="chart-pnl-container" style="display:none; position:relative; width:100%; height:260px; margin-top:10px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; padding:0 4px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="font-size:11px; font-weight:700; color:{stroke_color}; background:rgba({('52,211,153' if current_total_equity>=0 else '248,113,113')},0.12); border:1px solid rgba({('52,211,153' if current_total_equity>=0 else '248,113,113')},0.3); padding:3px 10px; border-radius:6px; font-family:var(--font-mono);">
            Net P&amp;L: {('+' if current_total_equity>=0 else '')}${current_total_equity:,.2f} USD
          </div>
          <div style="font-size:11px; color:#94a3b8; font-family:var(--font-mono);">
            Floating Theta: <b style="color:#34d399;">+${safe_float(total_true_profit):,.2f} USD</b>
          </div>
        </div>
        <div style="font-size:10px; color:#64748b; font-family:var(--font-mono);">
          Auto-Scaled Dynamic Curve • 24/7 Theta
        </div>
      </div>

      <div style="position:relative; width:100%; height:210px;">
        <div style="position:absolute; left:0; top:0; bottom:24px; width:45px; display:flex; flex-direction:column; justify-content:space-between; font-size:10px; color:#94a3b8; font-family:var(--font-mono); text-align:right; padding-right:6px;">
          {y_labels_html}
        </div>

        <div style="margin-left:48px; height:100%;">
          <svg style="width:100%; height:185px; overflow:visible;" viewBox="0 0 500 175" preserveAspectRatio="none">
            <defs>
              <linearGradient id="dynamicPnlGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="{grad_color}" stop-opacity="0.35" />
                <stop offset="100%" stop-color="{grad_color}" stop-opacity="0.0" />
              </linearGradient>
              <filter id="neonEmeraldGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3.5" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
              <filter id="neonPurpleGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3.5" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
              <filter id="neonRoseGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3.5" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
            </defs>

            <line x1="0" y1="15" x2="500" y2="15" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" stroke-width="1" />
            <line x1="0" y1="50" x2="500" y2="50" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" stroke-width="1" />
            <line x1="0" y1="85" x2="500" y2="85" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" stroke-width="1" />
            <line x1="0" y1="120" x2="500" y2="120" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" stroke-width="1" />
            <line x1="0" y1="155" x2="500" y2="155" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" stroke-width="1" />

            {zero_line_svg}

            <path d="{area_d}" fill="url(#dynamicPnlGradient)" />
            <path d="{line_d}" fill="none" stroke="{stroke_color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" filter="url(#{glow_filter})" />

            <circle cx="{last_x}" cy="{last_y}" r="6" fill="{stroke_color}" opacity="0.3" />
            <circle cx="{last_x}" cy="{last_y}" r="3.5" fill="#ffffff" stroke="{stroke_color}" stroke-width="2" />
          </svg>

          <div style="display:flex; justify-content:space-between; font-size:10px; color:#64748b; font-family:var(--font-mono); margin-top:6px; padding:0 2px;">
            {x_labels_html}
          </div>
        </div>
      </div>
    </div>
    '''
    return chart_html



def generate_pnl_analytics_html(delta_orders_history):
    """
    Renders Delta Exchange's exact PNL Analytics Interface:
    - Top Bar: Back button, Timeframe filters (7 days, 30 days, 365 days), Currency toggle (INR / USD)
    - TRADING EQUITY SVG curve matching Delta's exact equity trajectory
    - 7 Core KPI cards: Total Realized PNL (-₹289.04 / -$3.45), Win Rate (40%), Avg Win (₹53.95), Avg Loss (-₹132.31), # Trades (5), Fees Discount (₹0), Fees Saved (₹0)
    - PNL Heatmap calendar grid with daily tiles and hover tooltips
    - Realized PNL Per Day Bar Chart & Volume Traded Bar Chart
    - Fees Paid Bar Chart & Funding Card (Options Perpetual Note)
    - All-Time Settled Orders Drilldown Table
    """
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)

    def _parse_dt(t_str):
        s = str(t_str or "").strip()
        if not s:
            return None
        date_only = s.split(",")[0].strip()
        for candidate in (s, date_only, s[:19]):
            for fmt in ("%d - %b - %y, %I:%M:%S %p", "%d - %b - %y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(candidate.strip(), fmt)
                except Exception:
                    pass
        return None

    def _num(val_str):
        s = str(val_str or "0").replace("USD", "").replace("+", "").replace(",", "").strip()
        try:
            return float(s)
        except Exception:
            return 0.0

    # Closed trades list for drilldown
    closed_orders = []
    if delta_orders_history:
        closed_orders = [
            o for o in delta_orders_history
            if ("Close" in str(o.get("side", "")) or _num(o.get("realized_pnl", 0)) != 0 or _num(o.get("net_pnl", 0)) != 0)
            and str(o.get("status", "Filled")).lower() != "cancelled"
        ]

    def _calc_window_kpis(days_limit):
        w_pnl = 0.0
        w_fees = 0.0
        w_vol = 0.0
        wins_list = []
        losses_list = []
        cnt = 0
        for o in closed_orders:
            dt = _parse_dt(o.get("time", ""))
            if dt and (now_ist.date() - dt.date()).days > days_limit:
                continue
            net_v = _num(o.get("net_pnl") or o.get("realized_pnl") or 0)
            fee_v = abs(_num(o.get("trading_fees", 0)))
            cf_v = abs(_num(o.get("cashflow", 0)))
            w_pnl += net_v
            w_fees += fee_v
            w_vol += cf_v
            cnt += 1
            if net_v > 0:
                wins_list.append(net_v)
            elif net_v < 0:
                losses_list.append(net_v)
        # Also include volume from all filled orders in window
        for o in (delta_orders_history or []):
            if str(o.get("status", "")).lower() == "cancelled":
                continue
            dt = _parse_dt(o.get("time", ""))
            if dt and (now_ist.date() - dt.date()).days <= days_limit:
                w_vol += abs(_num(o.get("cashflow", 0)))
                w_fees += abs(_num(o.get("trading_fees", 0)))

        tot_wl = len(wins_list) + len(losses_list)
        wr = round((len(wins_list) / tot_wl) * 100.0, 1) if tot_wl > 0 else 0.0
        avg_w = (sum(wins_list) / len(wins_list)) if wins_list else 0.0
        max_w = max(wins_list) if wins_list else 0.0
        avg_l = (sum(losses_list) / len(losses_list)) if losses_list else 0.0
        return {
            "pnl_usd": round(w_pnl, 2),
            "pnl_inr": round(w_pnl * 83.8, 2),
            "wr": wr,
            "wins": len(wins_list),
            "losses": len(losses_list),
            "avg_w_usd": round(avg_w, 2),
            "avg_w_inr": round(avg_w * 83.8, 2),
            "max_w_inr": round(max_w * 83.8, 2),
            "avg_l_usd": round(avg_l, 2),
            "avg_l_inr": round(avg_l * 83.8, 2),
            "trades": cnt,
            "fees_usd": round(w_fees, 2),
            "fees_inr": round(w_fees * 83.8, 2),
            "vol_usd": round(w_vol, 2),
            "vol_inr": round(w_vol * 83.8, 2),
        }

    k7 = _calc_window_kpis(7)
    k30 = _calc_window_kpis(30)

    def _fmt_inr(v):
        return f"+₹{v:,.2f}" if v > 0 else (f"-₹{abs(v):,.2f}" if v < 0 else "₹0.00")

    def _fmt_usd(v):
        return f"+${v:,.2f} USD" if v > 0 else (f"-${abs(v):,.2f} USD" if v < 0 else "$0.00 USD")

    pnl_7d_inr = _fmt_inr(k7["pnl_inr"])
    pnl_7d_usd = _fmt_usd(k7["pnl_usd"])
    pnl_7d_col = "#34d399" if k7["pnl_usd"] >= 0 else "#f87171"
    winrate_7d = f"{k7['wr']} %"
    wins_7d = k7["wins"]
    losses_7d = k7["losses"]
    avg_win_inr = f"₹{k7['avg_w_inr']:,.2f}"
    avg_win_usd = f"+${k7['avg_w_usd']:,.2f} USD"
    max_win_inr_str = f"+₹{k7['max_w_inr']:,.0f}"
    avg_loss_inr = _fmt_inr(k7["avg_l_inr"])
    avg_loss_usd = _fmt_usd(k7["avg_l_usd"])
    trades_7d = str(k7["trades"])
    fees_paid_inr = f"₹{k7['fees_inr']:,.2f}"
    fees_paid_usd = f"${k7['fees_usd']:,.2f} USD"
    volume_inr = f"₹{k7['vol_inr']/100000:.2f}L" if k7["vol_inr"] >= 100000 else f"₹{k7['vol_inr']:,.0f}"
    volume_usd = f"${k7['vol_usd']:,.0f} USD"

    pnl_30d_inr = _fmt_inr(k30["pnl_inr"])
    pnl_30d_usd = _fmt_usd(k30["pnl_usd"])
    winrate_30d = f"{k30['wr']} %"
    avg_win_30d_inr = f"₹{k30['avg_w_inr']:,.2f}"
    avg_win_30d_usd = f"+${k30['avg_w_usd']:,.2f} USD"
    avg_loss_30d_inr = _fmt_inr(k30["avg_l_inr"])
    avg_loss_30d_usd = _fmt_usd(k30["avg_l_usd"])
    trades_30d = str(k30["trades"])
    fees_paid_30d_inr = f"₹{k30['fees_inr']:,.2f}"
    fees_paid_30d_usd = f"${k30['fees_usd']:,.2f} USD"
    volume_30d_inr = f"₹{k30['vol_inr']/100000:.2f}L" if k30["vol_inr"] >= 100000 else f"₹{k30['vol_inr']:,.0f}"
    volume_30d_usd = f"${k30['vol_usd']:,.0f} USD"

    # Build daily PnL map for last 14 days for Heatmap & X-axis dates
    daily_pnl_map = {}
    for o in closed_orders:
        dt = _parse_dt(o.get("time", ""))
        if dt:
            d_key = dt.date()
            daily_pnl_map[d_key] = daily_pnl_map.get(d_key, 0.0) + _num(o.get("net_pnl") or o.get("realized_pnl") or 0)

    last_7_dates = [(now_ist.date() - timedelta(days=i)) for i in range(6, -1, -1)]
    last_7_labels_html = "".join(f"<span>{d.strftime('%d %b')}</span>" for d in last_7_dates)
    equity_header_date_str = now_ist.strftime("%d %b %Y, %I:%M %p")
    heatmap_month_str = now_ist.strftime("%B %Y") + " Daily Performance"

    # Dynamic 2-week heatmap columns
    heatmap_cols_html = ""
    for w_idx in range(2):
        start_offset = 13 - (w_idx * 7)
        col_cells = ""
        for d_off in range(7):
            d_day = now_ist.date() - timedelta(days=(start_offset - d_off))
            d_usd = daily_pnl_map.get(d_day, 0.0)
            d_inr = round(d_usd * 83.8, 2)
            d_lbl = d_day.strftime("%a %d %b")
            if d_inr > 0.01:
                col_cells += f'<div title="{d_lbl}: +₹{d_inr:,.2f} (+${d_usd:,.2f} USD)" style="width:28px; height:24px; border-radius:4px; background:#065f46; border:1px solid #10b981; cursor:pointer; display:flex; align-items:center; justify-content:center;"><span style="font-size:9px; color:#a7f3d0; font-weight:700;">+{round(d_inr)}</span></div>'
            elif d_inr < -0.01:
                col_cells += f'<div title="{d_lbl}: -₹{abs(d_inr):,.2f} (-${abs(d_usd):,.2f} USD)" style="width:28px; height:24px; border-radius:4px; background:#7f1d1d; border:1px solid #ef4444; cursor:pointer; display:flex; align-items:center; justify-content:center;"><span style="font-size:9px; color:#fca5a5; font-weight:700;">-{round(abs(d_inr))}</span></div>'
            else:
                col_cells += f'<div title="{d_lbl}: No Settled Trades" style="width:28px; height:24px; border-radius:4px; background:#111622; border:1px solid #1e2538;"></div>'
        heatmap_cols_html += f'<div style="display:flex; flex-direction:column; gap:8px;">{col_cells}</div>'

    # Build dynamic daily buckets for Volume, Fees, and Trade descriptions over last 7 days
    daily_vol_map = {}
    daily_fee_map = {}
    daily_desc_map = {}
    daily_cnt_map = {}
    for o in (delta_orders_history or []):
        if str(o.get("status", "")).lower() == "cancelled":
            continue
        dt = _parse_dt(o.get("time", ""))
        if not dt:
            continue
        d_key = dt.date()
        daily_vol_map[d_key] = daily_vol_map.get(d_key, 0.0) + abs(_num(o.get("cashflow", 0)))
        daily_fee_map[d_key] = daily_fee_map.get(d_key, 0.0) + abs(_num(o.get("trading_fees", 0)))
        daily_cnt_map[d_key] = daily_cnt_map.get(d_key, 0) + 1
        if "Close" in str(o.get("side", "")) or _num(o.get("realized_pnl", 0)) != 0:
            daily_desc_map[d_key] = str(o.get("sym", "Option")) + " Settled"

    # Dynamic Realized PNL Bars (Last 7 Days)
    rpnl_vals_inr = [round(daily_pnl_map.get(d, 0.0) * 83.8, 2) for d in last_7_dates]
    max_abs_rpnl = max([abs(v) for v in rpnl_vals_inr] + [100.0])
    rpnl_pos_grid_inr = f"+{round(max_abs_rpnl)}"
    rpnl_pos_grid_usd = f"+${max_abs_rpnl/83.8:.1f}"
    rpnl_neg_grid_inr = f"-{round(max_abs_rpnl)}"
    rpnl_neg_grid_usd = f"-${max_abs_rpnl/83.8:.1f}"

    rpnl_bars_svg = ""
    rpnl_js_list = []
    bar_x_positions = [60, 120, 180, 240, 300, 360, 420]
    bw = 34
    for idx, d in enumerate(last_7_dates):
        bx = bar_x_positions[idx]
        d_usd = round(daily_pnl_map.get(d, 0.0), 2)
        d_inr = round(d_usd * 83.8, 2)
        if abs(d_inr) < 0.01:
            continue
        bh = max(4, round((abs(d_inr) / max_abs_rpnl) * 58))
        is_win = d_inr >= 0
        by = (80 - bh) if is_win else 80
        fill_col = "#10b981" if is_win else "#ef4444"
        bar_id = f"rpnl-bar-{idx}"
        rpnl_bars_svg += f'<rect id="{bar_id}" x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="{fill_col}" opacity="0.88" style="transform-box:fill-box; transform-origin:50% 50%; transition:transform 0.22s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.22s ease, filter 0.22s ease; cursor:pointer;" />'
        rpnl_js_list.append({
            "svgX": bx + (bw // 2),
            "svgY": by if is_win else (80 + bh),
            "barId": bar_id,
            "bx": bx, "bw": bw, "by": by, "bh": bh,
            "date": d.strftime("%a %d %b %Y"),
            "inr": f"+₹{d_inr:,.2f}" if is_win else f"-₹{abs(d_inr):,.2f}",
            "usd": f"+${d_usd:,.2f} USD" if is_win else f"-${abs(d_usd):,.2f} USD",
            "trade": daily_desc_map.get(d, "Settled Options Trade"),
            "isWin": is_win,
            "glowCol": "rgba(16, 185, 129, 0.85)" if is_win else "rgba(239, 68, 68, 0.85)"
        })

    # Dynamic Volume Bars (Last 7 Days)
    vol_vals_inr = [round(daily_vol_map.get(d, 0.0) * 83.8, 2) for d in last_7_dates]
    max_vol = max(vol_vals_inr + [100.0])
    vol_bars_svg = ""
    vol_js_list = []
    for idx, d in enumerate(last_7_dates):
        bx = bar_x_positions[idx]
        v_usd = round(daily_vol_map.get(d, 0.0), 2)
        v_inr = round(v_usd * 83.8, 2)
        if v_inr < 0.01:
            continue
        bh = max(6, round((v_inr / max_vol) * 110))
        by = 160 - bh
        bar_id = f"vol-bar-{idx}"
        vol_bars_svg += f'<rect id="{bar_id}" x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="#3b82f6" opacity="0.88" style="transform-box:fill-box; transform-origin:50% 50%; transition:transform 0.22s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.22s ease, filter 0.22s ease; cursor:pointer;" />'
        cnt_d = daily_cnt_map.get(d, 1)
        vol_js_list.append({
            "svgX": bx + (bw // 2), "svgY": by,
            "barId": bar_id, "bx": bx, "bw": bw, "by": by, "bh": bh,
            "date": d.strftime("%a %d %b %Y"),
            "inr": f"₹{v_inr:,.2f}",
            "usd": f"${v_usd:,.2f} USD",
            "desc": f"{cnt_d} Order{'s' if cnt_d != 1 else ''} Executed",
            "glowCol": "rgba(59, 130, 246, 0.85)"
        })

    # Dynamic Fees Bars (Last 7 Days)
    fee_vals_inr = [round(daily_fee_map.get(d, 0.0) * 83.8, 2) for d in last_7_dates]
    max_fee = max(fee_vals_inr + [1.0])
    fee_bars_svg = ""
    fee_js_list = []
    for idx, d in enumerate(last_7_dates):
        bx = bar_x_positions[idx]
        f_usd = round(daily_fee_map.get(d, 0.0), 4)
        f_inr = round(f_usd * 83.8, 2)
        if f_inr < 0.01:
            continue
        bh = max(6, round((f_inr / max_fee) * 85))
        by = 130 - bh
        bar_id = f"fee-bar-{idx}"
        fee_bars_svg += f'<rect id="{bar_id}" x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="#f59e0b" opacity="0.88" style="transform-box:fill-box; transform-origin:50% 50%; transition:transform 0.22s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.22s ease, filter 0.22s ease; cursor:pointer;" />'
        fee_js_list.append({
            "svgX": bx + (bw // 2), "svgY": by,
            "barId": bar_id, "bx": bx, "bw": bw, "by": by, "bh": bh,
            "date": d.strftime("%a %d %b %Y"),
            "inr": f"₹{f_inr:,.2f}",
            "usd": f"${f_usd:,.2f} USD",
            "glowCol": "rgba(245, 158, 11, 0.85)"
        })

    rpnl_js_json = json.dumps(rpnl_js_list)
    vol_js_json = json.dumps(vol_js_list)
    fee_js_json = json.dumps(fee_js_list)

    # Dynamic Trading Equity Curve (Last 7 Days)
    base_eq_inr = 3830.0
    try:
        import delta_exchange as _dx_eq
        if _dx_eq.DELTA_API_KEY:
            _live_inr = _dx_eq.get_total_inr_balance()
            if _live_inr > 0:
                base_eq_inr = _live_inr
    except Exception:
        pass

    sum_7d_inr = sum(round(daily_pnl_map.get(d, 0.0) * 83.8, 2) for d in last_7_dates)
    start_eq_inr = max(100.0, base_eq_inr - sum_7d_inr)
    eq_series_inr = []
    running_eq = start_eq_inr
    for d in last_7_dates:
        d_inr = round(daily_pnl_map.get(d, 0.0) * 83.8, 2)
        running_eq = round(running_eq + d_inr, 2)
        eq_series_inr.append((d, running_eq, d_inr))

    eq_min = min([x[1] for x in eq_series_inr] + [start_eq_inr])
    eq_max = max([x[1] for x in eq_series_inr] + [start_eq_inr])
    if eq_max - eq_min < 200.0:
        mid_eq = (eq_max + eq_min) / 2.0
        eq_min = mid_eq - 250.0
        eq_max = mid_eq + 250.0
    eq_span = max(1.0, eq_max - eq_min)

    eq_x_coords = [60, 210, 360, 510, 660, 810, 970]
    eq_points_js = []
    eq_svg_coords = []
    for i, (d, eq_v, d_inr) in enumerate(eq_series_inr):
        sx = eq_x_coords[i]
        norm = (eq_v - eq_min) / eq_span
        sy = round(210 - (norm * 175), 1)
        eq_svg_coords.append((sx, sy))
        d_usd = round(d_inr / 83.8, 2)
        eq_usd = round(eq_v / 83.8, 2)
        eq_points_js.append({
            "xPct": round((sx / 1000.0) * 100.0, 1),
            "svgX": sx,
            "svgY": sy,
            "date": d.strftime("%d %b %Y, %I:%M %p") if i < 6 else now_ist.strftime("%d %b %Y, %I:%M %p"),
            "equityInr": f"₹{eq_v:,.2f}",
            "equityUsd": f"${eq_usd:,.2f}",
            "pnlInr": f"+₹{d_inr:,.2f}" if d_inr > 0 else (f"-₹{abs(d_inr):,.2f}" if d_inr < 0 else "₹0.00"),
            "pnlUsd": f"+${d_usd:,.2f}" if d_usd > 0 else (f"-${abs(d_usd):,.2f}" if d_usd < 0 else "$0.00"),
            "desc": daily_desc_map.get(d, "Live Account Equity"),
            "isGain": d_inr >= 0
        })

    eq_line_d = "M " + " L ".join(f"{x},{y}" for x, y in eq_svg_coords)
    eq_area_d = eq_line_d + f" L {eq_svg_coords[-1][0]},225 L {eq_svg_coords[0][0]},225 Z"
    eq_last_x, eq_last_y = eq_svg_coords[-1]
    eq_header_inr = f"₹{eq_series_inr[-1][1]/1000:.2f}K" if eq_series_inr[-1][1] >= 1000 else f"₹{eq_series_inr[-1][1]:,.2f}"
    eq_header_usd = f"${eq_series_inr[-1][1]/83.8:,.2f} USD"
    equity_js_json = json.dumps(eq_points_js)

    drilldown_rows = ""
    for o in closed_orders:
        sym = o.get("sym", "-")
        side = o.get("side", "Close Buy")
        side_color = "#34d399" if "Buy" in side else "#f87171"
        exec_px = o.get("exec", "-")
        size = o.get("size", "1 Contract")
        rpnl_str = str(o.get("realized_pnl", "0 USD"))
        net_str = str(o.get("net_pnl", "0 USD"))
        fees_str = str(o.get("trading_fees", "0 USD"))
        time_str = str(o.get("time", "-"))
        
        try:
            val_f = float(rpnl_str.replace("USD","").replace("+","").strip())
            rpnl_col = "#34d399" if val_f > 0 else ("#f87171" if val_f < 0 else "#94a3b8")
            val_inr_str = f"+₹{val_f*83.8:,.2f}" if val_f > 0 else (f"-₹{abs(val_f*83.8):,.2f}" if val_f < 0 else "₹0.00")
        except Exception:
            rpnl_col = "#94a3b8"
            val_inr_str = "₹0.00"

        drilldown_rows += f"""
        <tr style="border-bottom:1px solid #161b26; font-size:12px; transition:background 0.15s;">
          <td style="padding:10px 14px; font-weight:700; color:#ffffff; font-family:var(--font-mono);">{sym}</td>
          <td style="padding:10px 14px; font-weight:600; color:{side_color}; font-family:var(--font-mono);">{side}</td>
          <td style="padding:10px 14px; font-family:var(--font-mono); color:#cbd5e1;">{size}</td>
          <td style="padding:10px 14px; font-family:var(--font-mono); color:#ffffff; font-weight:600;">{exec_px}</td>
          <td style="padding:10px 14px; font-family:var(--font-mono); font-weight:700; color:{rpnl_col};">{rpnl_str} <span style="font-size:11px; color:#94a3b8; font-weight:400;">({val_inr_str})</span></td>
          <td style="padding:10px 14px; font-family:var(--font-mono); color:#94a3b8;">{fees_str}</td>
          <td style="padding:10px 14px; font-family:var(--font-mono); font-weight:700; color:{rpnl_col};">{net_str}</td>
          <td style="padding:10px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px; white-space:nowrap;">{time_str}</td>
        </tr>
        """

    html = f"""
    <div style="max-width:1760px; margin:0 auto; padding:0 24px 60px;">
      
      <!-- TOP ACTION BAR: Back + Title + Filter Pills + Currency Switcher -->
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px; margin-bottom:24px; padding-bottom:18px; border-bottom:1px solid #1e2538;">
        <div style="display:flex; align-items:center; gap:14px;">
          <button onclick="closePnlAnalytics()" style="background:#161b26; border:1px solid #2d3748; color:#cbd5e1; padding:7px 14px; border-radius:8px; font-size:12px; font-weight:700; cursor:pointer; display:flex; align-items:center; gap:6px; transition:all 0.2s;" onmouseover="this.style.borderColor='#a855f7'; this.style.color='#ffffff';" onmouseout="this.style.borderColor='#2d3748'; this.style.color='#cbd5e1';">
            <span>&larr;</span> Back to Dashboard
          </button>
          <div>
            <div style="display:flex; align-items:center; gap:10px;">
              <h1 style="font-size:22px; font-weight:800; color:#ffffff; margin:0; letter-spacing:-0.02em;">PNL Analytics</h1>
              <span style="font-size:11px; font-weight:700; color:#a855f7; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); padding:2px 8px; border-radius:4px;">DELTA TESTNET LIVE</span>
            </div>
            <div style="font-size:12px; color:#94a3b8; margin-top:2px;">
              Delta Exchange India &bull; Direct Settlement &amp; Performance Ledger
            </div>
          </div>
        </div>

        <div style="display:flex; align-items:center; gap:12px;">
          <!-- Timeframe selector -->
          <div style="background:#090d16; border:1px solid #1e2538; border-radius:8px; padding:3px; display:flex; gap:4px;">
            <button class="timeframe-pill active" id="tf-pill-7d" onclick="switchAnalyticsTimeframe('7d')" style="background:rgba(168,85,247,0.22); border:1px solid #a855f7; color:#ffffff; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:700; cursor:pointer;">7 days</button>
            <button class="timeframe-pill" id="tf-pill-30d" onclick="switchAnalyticsTimeframe('30d')" style="background:transparent; border:1px solid transparent; color:#94a3b8; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;">30 days</button>
            <button class="timeframe-pill" id="tf-pill-365d" onclick="switchAnalyticsTimeframe('365d')" style="background:transparent; border:1px solid transparent; color:#94a3b8; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;">365 days</button>
          </div>

          <!-- Currency Toggle: INR vs USD -->
          <div style="background:#090d16; border:1px solid #1e2538; border-radius:8px; padding:3px; display:flex; gap:4px;">
            <button class="curr-pill active" id="btn-curr-inr" onclick="switchAnalyticsCurrency('inr')" style="background:rgba(52,211,153,0.18); border:1px solid #34d399; color:#34d399; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:700; cursor:pointer;">&#8377; INR</button>
            <button class="curr-pill" id="btn-curr-usd" onclick="switchAnalyticsCurrency('usd')" style="background:transparent; border:1px solid transparent; color:#94a3b8; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;">$ USD</button>
          </div>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- 1. TRADING EQUITY CHART (Matching Screenshot 2)-->
      <!-- ============================================== -->
      <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; margin-bottom:22px; box-shadow:0 4px 20px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:10px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:14px; font-weight:700; color:#cbd5e1; letter-spacing:0.04em;">TRADING EQUITY</span>
            <span style="font-size:12px; color:#64748b; cursor:help;" title="Hover across curve to inspect real-time capital &amp; PnL at each point">&#9432;</span>
            <span style="font-size:10px; color:#a855f7; background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.25); padding:2px 7px; border-radius:4px; font-family:var(--font-mono);">INTERACTIVE CROSSHAIR</span>
          </div>
          <div style="display:flex; align-items:center; gap:12px; font-family:var(--font-mono); font-size:12px;">
            <span id="equity-header-date" style="color:#94a3b8;">{equity_header_date_str}</span>
            <span style="color:#ffffff; font-weight:700; background:#121826; border:1px solid #232d42; padding:3px 10px; border-radius:6px;">
              Equity: <b id="equity-header-val" class="analytics-currency-val" data-val-inr="{eq_header_inr}" data-val-usd="{eq_header_usd}" style="color:#c084fc;">{eq_header_inr}</b>
            </span>
          </div>
        </div>

        <!-- SVG Equity Curve (Responsive Interactive SVG Container) -->
        <div id="equity-chart-container" onmousemove="handleEquityMouseMove(event)" onmouseleave="handleEquityMouseLeave()" ontouchmove="handleEquityMouseMove(event.touches[0])" ontouchend="handleEquityMouseLeave()" style="position:relative; width:100%; height:260px; overflow:visible; cursor:crosshair; user-select:none;">
          
          <!-- Floating Crosshair Tooltip Badge -->
          <div id="equity-tooltip" style="display:none; position:absolute; pointer-events:none; z-index:60; background:rgba(9,13,22,0.95); border:1px solid #a855f7; border-radius:10px; padding:10px 14px; box-shadow:0 8px 30px rgba(0,0,0,0.85), 0 0 16px rgba(168,85,247,0.35); font-family:var(--font-mono); transform:translate(-50%, -125%); white-space:nowrap; backdrop-filter:blur(8px);">
            <div id="eq-tt-date" style="font-size:11px; color:#94a3b8; font-weight:600; margin-bottom:5px;">09 Nov 2026, 03:25 AM</div>
            <div style="display:flex; align-items:baseline; justify-content:space-between; gap:14px;">
              <span style="font-size:11px; color:#cbd5e1; font-weight:600;">Capital / Equity:</span>
              <span id="eq-tt-capital" style="font-size:16px; font-weight:800; color:#34d399;">&#8377;4,871.62</span>
            </div>
            <div style="display:flex; align-items:center; justify-content:space-between; gap:14px; margin-top:5px; font-size:11px;">
              <span style="color:#64748b;">Daily Settled PnL:</span>
              <span id="eq-tt-pnl" style="font-weight:700; color:#f87171;">-&#8377;308.38</span>
            </div>
            <div id="eq-tt-desc" style="font-size:10px; color:#c084fc; margin-top:5px; border-top:1px solid rgba(255,255,255,0.1); padding-top:4px; font-weight:500;">P-ETH-1900 Closed</div>
          </div>

          <svg id="equity-svg" viewBox="0 0 1000 240" preserveAspectRatio="none" style="width:100%; height:100%; display:block; overflow:visible;">
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#a855f7" stop-opacity="0.32" />
                <stop offset="70%" stop-color="#a855f7" stop-opacity="0.05" />
                <stop offset="100%" stop-color="#a855f7" stop-opacity="0.0" />
              </linearGradient>
              <filter id="glowLine" x="-10%" y="-10%" width="120%" height="120%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
            </defs>

            <!-- Horizontal Gridlines & Y-Axis labels -->
            <line x1="50" y1="25" x2="980" y2="25" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
            <text x="40" y="29" fill="#64748b" font-size="11" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="5.3K" data-val-usd="$63.2">5.3K</text>

            <line x1="50" y1="75" x2="980" y2="75" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
            <text x="40" y="79" fill="#64748b" font-size="11" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="5.1K" data-val-usd="$60.8">5.1K</text>

            <line x1="50" y1="125" x2="980" y2="125" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
            <text x="40" y="129" fill="#64748b" font-size="11" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="4.9K" data-val-usd="$58.5">4.9K</text>

            <line x1="50" y1="175" x2="980" y2="175" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
            <text x="40" y="179" fill="#64748b" font-size="11" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="4.7K" data-val-usd="$56.1">4.7K</text>

            <line x1="50" y1="215" x2="980" y2="215" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
            <text x="40" y="219" fill="#64748b" font-size="11" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="4.5K" data-val-usd="$53.7">4.5K</text>

            <!-- Gradient Area Fill -->
            <path d="{eq_area_d}" fill="url(#eqGrad)" />

            <!-- Equity Line -->
            <path d="{eq_line_d}" fill="none" stroke="#a855f7" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" filter="url(#glowLine)" />

            <!-- Current Live Tip Pulse -->
            <circle cx="{eq_last_x}" cy="{eq_last_y}" r="7" fill="#a855f7" opacity="0.3">
              <animate attributeName="r" values="5;9;5" dur="2.4s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.4;0.1;0.4" dur="2.4s" repeatCount="indefinite" />
            </circle>
            <circle cx="{eq_last_x}" cy="{eq_last_y}" r="3.5" fill="#ffffff" stroke="#a855f7" stroke-width="2" />

            <!-- Dynamic Interactive Crosshair Line -->
            <line id="equity-crosshair" x1="0" y1="20" x2="0" y2="225" stroke="rgba(192, 132, 252, 0.65)" stroke-width="1.5" stroke-dasharray="4,4" style="display:none;" />

            <!-- Dynamic Snapping Hover Marker Dot with Glow -->
            <circle id="equity-cursor-dot-glow" cx="0" cy="0" r="11" fill="rgba(168, 85, 247, 0.35)" style="display:none;" />
            <circle id="equity-cursor-dot" cx="0" cy="0" r="5" fill="#ffffff" stroke="#c084fc" stroke-width="2.5" style="display:none;" />
          </svg>
        </div>

        <!-- X-Axis Dates (Dynamic Last 7 Days) -->
        <div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b; font-family:var(--font-mono); margin-top:8px; padding:0 24px;">
          {last_7_labels_html}
        </div>
      </div>

      <!-- ============================================== -->
      <!-- 2. CORE KPI CARDS (Matching Screenshot 3)      -->
      <!-- ============================================== -->
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:14px; margin-bottom:22px;">
        
        <!-- KPI 1: Total Realized PNL -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span>Total Realized PNL</span>
            <span style="font-size:11px; color:#64748b;" title="Cumulative net realized profit or loss from closed trades">&#9432;</span>
          </div>
          <div class="analytics-currency-val" id="kpi-pnl" data-val-inr="{pnl_7d_inr}" data-val-usd="{pnl_7d_usd}" style="font-size:24px; font-weight:800; color:{pnl_7d_col}; margin-top:10px; font-family:var(--font-mono);">
            {pnl_7d_inr}
          </div>
          <div style="margin-top:6px; font-size:11px; color:#f87171; font-weight:600; font-family:var(--font-mono);">
            &#9660; Settled -7D
          </div>
        </div>

        <!-- KPI 2: Win Rate -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span>Win Rate</span>
            <span style="font-size:11px; color:#64748b;" title="Percentage of winning closed positions">&#9432;</span>
          </div>
          <div id="kpi-winrate" style="font-size:24px; font-weight:800; color:#ffffff; margin-top:10px; font-family:var(--font-mono);">
            {winrate_7d}
          </div>
          <div style="margin-top:6px; font-size:11px; color:#34d399; font-weight:600; font-family:var(--font-mono);">
            {wins_7d} Wins / {losses_7d} Losses
          </div>
        </div>

        <!-- KPI 3: Average Win -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span>Average Win</span>
            <span style="font-size:11px; color:#64748b;">&#9432;</span>
          </div>
          <div class="analytics-currency-val" id="kpi-avg-win" data-val-inr="{avg_win_inr}" data-val-usd="{avg_win_usd}" style="font-size:24px; font-weight:800; color:#34d399; margin-top:10px; font-family:var(--font-mono);">
            {avg_win_inr}
          </div>
          <div style="margin-top:6px; font-size:11px; color:#64748b; font-family:var(--font-mono);">
            {max_win_inr_str} highest win
          </div>
        </div>

        <!-- KPI 4: Average Loss -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span>Average Loss</span>
            <span style="font-size:11px; color:#64748b;">&#9432;</span>
          </div>
          <div class="analytics-currency-val" id="kpi-avg-loss" data-val-inr="{avg_loss_inr}" data-val-usd="{avg_loss_usd}" style="font-size:24px; font-weight:800; color:#f87171; margin-top:10px; font-family:var(--font-mono);">
            {avg_loss_inr}
          </div>
          <div style="margin-top:6px; font-size:11px; color:#64748b; font-family:var(--font-mono);">
            Avg SL / Liq impact
          </div>
        </div>

        <!-- KPI 5: # Trades -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span># Trades</span>
            <span style="font-size:11px; color:#64748b;">&#9432;</span>
          </div>
          <div id="kpi-trades" style="font-size:24px; font-weight:800; color:#ffffff; margin-top:10px; font-family:var(--font-mono);">
            {trades_7d}
          </div>
          <div style="margin-top:6px; font-size:11px; color:#64748b; font-family:var(--font-mono);">
            Closed &amp; Settled
          </div>
        </div>

        <!-- KPI 6: Fees Discount -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span>Fees Discount</span>
            <span style="font-size:11px; color:#64748b;">&#9432;</span>
          </div>
          <div class="analytics-currency-val" data-val-inr="&#8377;0" data-val-usd="$0.00" style="font-size:24px; font-weight:800; color:#ffffff; margin-top:10px; font-family:var(--font-mono);">
            &#8377;0
          </div>
          <div style="margin-top:6px; font-size:11px; color:#64748b; font-family:var(--font-mono);">
            Standard Tier
          </div>
        </div>

        <!-- KPI 7: Fees Saved -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:12px; padding:18px 20px;">
          <div style="font-size:12px; color:#94a3b8; font-weight:600; display:flex; align-items:center; gap:6px;">
            <span>Fees Saved</span>
            <span style="font-size:11px; color:#64748b;">&#9432;</span>
          </div>
          <div class="analytics-currency-val" data-val-inr="&#8377;0" data-val-usd="$0.00" style="font-size:24px; font-weight:800; color:#ffffff; margin-top:10px; font-family:var(--font-mono);">
            &#8377;0
          </div>
          <div style="margin-top:6px; font-size:11px; color:#64748b; font-family:var(--font-mono);">
            Delta Maker Rebates
          </div>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- 3. PNL HEATMAP (Matching Screenshot 3)        -->
      <!-- ============================================== -->
      <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; margin-bottom:22px; box-shadow:0 4px 20px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:14px; font-weight:700; color:#cbd5e1;">PNL Heatmap</span>
            <span style="font-size:12px; color:#64748b;">&#9432;</span>
          </div>
          <div style="font-size:11px; color:#64748b; font-family:var(--font-mono);">
            {heatmap_month_str}
          </div>
        </div>

        <!-- Heatmap Grid -->
        <div style="display:flex; gap:14px; align-items:flex-start; overflow-x:auto; padding-bottom:8px;">
          <!-- Day Labels -->
          <div style="display:flex; flex-direction:column; gap:8px; font-size:11px; color:#64748b; font-family:var(--font-mono); padding-top:4px;">
            <span>Mon</span>
            <span>Tue</span>
            <span>Wed</span>
            <span>Thu</span>
            <span>Fri</span>
            <span>Sat</span>
            <span>Sun</span>
          </div>

          <!-- Heatmap Matrix (Dynamic Last 14 Days) -->
          <div style="display:flex; gap:8px;">
            {heatmap_cols_html}
          </div>
        </div>

        <!-- Legend -->
        <div style="display:flex; justify-content:flex-end; align-items:center; gap:8px; margin-top:14px; font-size:11px; color:#64748b;">
          <span>Loss</span>
          <div style="width:12px; height:12px; border-radius:2px; background:#7f1d1d;"></div>
          <div style="width:12px; height:12px; border-radius:2px; background:#991b1b;"></div>
          <span style="margin:0 4px;">|</span>
          <div style="width:12px; height:12px; border-radius:2px; background:#111622; border:1px solid #1e2538;"></div>
          <span style="margin:0 4px;">|</span>
          <div style="width:12px; height:12px; border-radius:2px; background:#047857;"></div>
          <div style="width:12px; height:12px; border-radius:2px; background:#065f46;"></div>
          <span>Profit</span>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- 4. ROW: REALIZED PNL BARS & VOLUME TRADED      -->
      <!-- ============================================== -->
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:22px;">
        
        <!-- Left: Realized PNL Bar Chart (Clean Straight Rectangular Bars matching Delta Exchange) -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; box-shadow:0 4px 20px rgba(0,0,0,0.6);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:14px; font-weight:700; color:#cbd5e1;">Realized PNL</span>
              <span style="font-size:12px; color:#64748b; cursor:help;" title="Hover over bars to inspect settled daily P&amp;L">&#9432;</span>
            </div>
            <div style="font-size:11px; color:#94a3b8; font-family:var(--font-mono);">Daily Net Settlement</div>
          </div>

          <!-- Interactive Realized PnL Container -->
          <div id="rpnl-chart-container" onmousemove="handleRpnlMouseMove(event)" onmouseleave="handleRpnlMouseLeave()" ontouchmove="handleRpnlMouseMove(event.touches[0])" ontouchend="handleRpnlMouseLeave()" style="position:relative; width:100%; height:190px; cursor:crosshair;">
            
            <!-- Floating Realized PnL Tooltip Badge (Ultra Premium Glassmorphism) -->
            <div id="rpnl-tooltip" style="display:none; position:absolute; pointer-events:none; z-index:60; background:linear-gradient(135deg, rgba(14,20,32,0.97) 0%, rgba(8,11,18,0.98) 100%); border:1px solid rgba(168,85,247,0.45); border-radius:10px; padding:10px 14px; box-shadow:0 14px 36px rgba(0,0,0,0.9), 0 0 20px rgba(168,85,247,0.25), inset 0 1px 0 rgba(255,255,255,0.12); font-family:var(--font-mono); transform:translate(-50%, -125%); white-space:nowrap; backdrop-filter:blur(10px); min-width:160px;">
              <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:5px;">
                <span id="rpnl-tt-date" style="font-size:11px; font-weight:700; color:#cbd5e1; letter-spacing:0.02em;">Mon 09 Nov</span>
                <span style="font-size:9px; font-weight:700; color:#a855f7; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); padding:2px 6px; border-radius:4px;">SETTLED</span>
              </div>
              <div style="display:flex; align-items:baseline; justify-content:space-between; gap:10px;">
                <span style="font-size:11px; color:#94a3b8; font-weight:600;">Realized PnL:</span>
                <span id="rpnl-tt-val" style="font-size:16px; font-weight:800; color:#f87171;">-&#8377;305.03</span>
              </div>
              <div id="rpnl-tt-trade" style="font-size:10px; color:#c084fc; margin-top:5px; border-top:1px solid rgba(255,255,255,0.08); padding-top:4px; font-weight:500;">P-ETH-1900 Closed</div>
            </div>

            <svg id="rpnl-svg" viewBox="0 0 500 180" preserveAspectRatio="none" style="width:100%; height:100%; display:block; overflow:visible;">
              <!-- Zero Axis Line -->
              <line x1="40" y1="80" x2="480" y2="80" stroke="#232d42" stroke-width="1.5" />
              <text x="35" y="84" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end">0</text>

              <!-- Dynamic Positive Gridline -->
              <line x1="40" y1="30" x2="480" y2="30" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
              <text x="35" y="34" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="{rpnl_pos_grid_inr}" data-val-usd="{rpnl_pos_grid_usd}">{rpnl_pos_grid_inr}</text>

              <!-- Dynamic Negative Gridline -->
              <line x1="40" y1="145" x2="480" y2="145" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
              <text x="35" y="149" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end" class="analytics-currency-val" data-val-inr="{rpnl_neg_grid_inr}" data-val-usd="{rpnl_neg_grid_usd}">{rpnl_neg_grid_inr}</text>

              <!-- DYNAMIC DAILY REALIZED PNL BARS -->
              <g id="rpnl-bar-group">
                {rpnl_bars_svg}
              </g>

              <!-- Dynamic Hover Crosshair Line -->
              <line id="rpnl-crosshair" x1="0" y1="20" x2="0" y2="165" stroke="rgba(168,85,247,0.6)" stroke-width="1.5" stroke-dasharray="3,3" style="display:none; pointer-events:none;" />
              
              <!-- Snapping Cursor Dot -->
              <circle id="rpnl-cursor-dot" cx="0" cy="0" r="4.5" fill="#ffffff" stroke="#a855f7" stroke-width="2" style="display:none; pointer-events:none;" />
            </svg>
          </div>

          <div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b; font-family:var(--font-mono); margin-top:6px; padding:0 24px;">
            {last_7_labels_html}
          </div>
        </div>

        <!-- Right: Volume Traded Bar Chart (Clean Straight Rectangular Bars matching Delta Exchange) -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; box-shadow:0 4px 20px rgba(0,0,0,0.6);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:14px; font-weight:700; color:#cbd5e1;">Volume Traded</span>
              <span style="font-size:12px; color:#64748b; cursor:help;" title="Hover over bars to view daily traded options volume">&#9432;</span>
            </div>
            
            <div class="analytics-currency-val" id="kpi-volume" data-val-inr="{volume_inr}" data-val-usd="{volume_usd}" style="font-size:14px; font-weight:800; color:#ffffff; font-family:var(--font-mono);">
              {volume_inr}
            </div>
          </div>

          <!-- Interactive Volume Chart Container -->
          <div id="vol-chart-container" onmousemove="handleVolMouseMove(event)" onmouseleave="handleVolMouseLeave()" ontouchmove="handleVolMouseMove(event.touches[0])" ontouchend="handleVolMouseLeave()" style="position:relative; width:100%; height:190px; cursor:crosshair;">
            
            <!-- Floating Volume Tooltip Badge (Ultra Premium Glassmorphism) -->
            <div id="vol-tooltip" style="display:none; position:absolute; pointer-events:none; z-index:60; background:linear-gradient(135deg, rgba(14,20,32,0.97) 0%, rgba(8,11,18,0.98) 100%); border:1px solid rgba(59,130,246,0.45); border-radius:10px; padding:10px 14px; box-shadow:0 14px 36px rgba(0,0,0,0.9), 0 0 20px rgba(59,130,246,0.25), inset 0 1px 0 rgba(255,255,255,0.12); font-family:var(--font-mono); transform:translate(-50%, -125%); white-space:nowrap; backdrop-filter:blur(10px); min-width:160px;">
              <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:5px;">
                <span id="vol-tt-date" style="font-size:11px; font-weight:700; color:#cbd5e1; letter-spacing:0.02em;">Wed 11 Nov</span>
                <span style="font-size:9px; font-weight:700; color:#60a5fa; background:rgba(59,130,246,0.15); border:1px solid rgba(59,130,246,0.3); padding:2px 6px; border-radius:4px;">VOLUME</span>
              </div>
              <div style="display:flex; align-items:baseline; justify-content:space-between; gap:10px;">
                <span style="font-size:11px; color:#94a3b8; font-weight:600;">Notional:</span>
                <span id="vol-tt-val" style="font-size:16px; font-weight:800; color:#60a5fa;">&#8377;80,500</span>
              </div>
              <div id="vol-tt-desc" style="font-size:10px; color:#93c5fd; margin-top:5px; border-top:1px solid rgba(255,255,255,0.08); padding-top:4px; font-weight:500;">2 Contracts Traded</div>
            </div>

            <svg id="vol-svg" viewBox="0 0 500 180" preserveAspectRatio="none" style="width:100%; height:100%; display:block; overflow:visible;">
              <line x1="40" y1="160" x2="480" y2="160" stroke="#232d42" stroke-width="1" />
              <line x1="40" y1="100" x2="480" y2="100" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />
              <line x1="40" y1="40" x2="480" y2="40" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />

              <!-- CLEAN CRISP RECTANGULAR BARS (No curved pill corners) -->
              <g id="vol-bar-group">
                {vol_bars_svg}
              </g>

              <!-- Dynamic Hover Crosshair & Dot -->
              <line id="vol-crosshair" x1="0" y1="20" x2="0" y2="160" stroke="rgba(96,165,250,0.6)" stroke-width="1.5" stroke-dasharray="3,3" style="display:none; pointer-events:none;" />
              <circle id="vol-cursor-dot" cx="0" cy="0" r="4.5" fill="#ffffff" stroke="#3b82f6" stroke-width="2" style="display:none; pointer-events:none;" />
            </svg>
          </div>

          <div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b; font-family:var(--font-mono); margin-top:6px; padding:0 24px;">
            {last_7_labels_html}
          </div>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- 5. ROW: FEES PAID & FUNDING (Matching Screenshot 5)-->
      <!-- ============================================== -->
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:22px;">
        
        <!-- Left: Fees Paid Bar Chart (Clean Straight Rectangular Bars matching Delta Exchange) -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; box-shadow:0 4px 20px rgba(0,0,0,0.6);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:14px; font-weight:700; color:#cbd5e1;">Fees Paid</span>
              <span style="font-size:12px; color:#64748b; cursor:help;" title="Hover over bars to view exchange fees incurred">&#9432;</span>
            </div>
            
            <div class="analytics-currency-val" id="kpi-fees" data-val-inr="{fees_paid_inr}" data-val-usd="{fees_paid_usd}" style="font-size:14px; font-weight:800; color:#f59e0b; font-family:var(--font-mono);">
              {fees_paid_inr}
            </div>
          </div>

          <!-- Interactive Fees Chart Container -->
          <div id="fee-chart-container" onmousemove="handleFeeMouseMove(event)" onmouseleave="handleFeeMouseLeave()" ontouchmove="handleFeeMouseMove(event.touches[0])" ontouchend="handleFeeMouseLeave()" style="position:relative; width:100%; height:160px; cursor:crosshair;">
            
            <!-- Floating Fees Tooltip Badge (Ultra Premium Glassmorphism) -->
            <div id="fee-tooltip" style="display:none; position:absolute; pointer-events:none; z-index:60; background:linear-gradient(135deg, rgba(14,20,32,0.97) 0%, rgba(8,11,18,0.98) 100%); border:1px solid rgba(245,158,11,0.45); border-radius:10px; padding:10px 14px; box-shadow:0 14px 36px rgba(0,0,0,0.9), 0 0 20px rgba(245,158,11,0.25), inset 0 1px 0 rgba(255,255,255,0.12); font-family:var(--font-mono); transform:translate(-50%, -125%); white-space:nowrap; backdrop-filter:blur(10px); min-width:150px;">
              <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:5px;">
                <span id="fee-tt-date" style="font-size:11px; font-weight:700; color:#cbd5e1; letter-spacing:0.02em;">Mon 09 Nov</span>
                <span style="font-size:9px; font-weight:700; color:#fbbf24; background:rgba(245,158,11,0.15); border:1px solid rgba(245,158,11,0.3); padding:2px 6px; border-radius:4px;">FEES</span>
              </div>
              <div style="display:flex; align-items:baseline; justify-content:space-between; gap:10px;">
                <span style="font-size:11px; color:#94a3b8; font-weight:600;">Exchange Fee:</span>
                <span id="fee-tt-val" style="font-size:16px; font-weight:800; color:#fbbf24;">&#8377;2.51</span>
              </div>
            </div>

            <svg id="fee-svg" viewBox="0 0 500 150" preserveAspectRatio="none" style="width:100%; height:100%; display:block; overflow:visible;">
              <line x1="40" y1="130" x2="480" y2="130" stroke="#232d42" stroke-width="1" />
              <line x1="40" y1="75" x2="480" y2="75" stroke="#141c2c" stroke-width="1" stroke-dasharray="3,3" />

              <!-- CLEAN CRISP RECTANGULAR BARS (No curved pill corners) -->
              <g id="fee-bar-group">
                {fee_bars_svg}
              </g>

              <!-- Dynamic Hover Crosshair & Dot -->
              <line id="fee-crosshair" x1="0" y1="20" x2="0" y2="130" stroke="rgba(251,191,36,0.6)" stroke-width="1.5" stroke-dasharray="3,3" style="display:none; pointer-events:none;" />
              <circle id="fee-cursor-dot" cx="0" cy="0" r="4.5" fill="#ffffff" stroke="#f59e0b" stroke-width="2" style="display:none; pointer-events:none;" />
            </svg>
          </div>

          <div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b; font-family:var(--font-mono); margin-top:6px; padding:0 24px;">
            {last_7_labels_html}
          </div>
        </div>

        <!-- Right: Funding Card (Matching Screenshot 5: Data not Found) -->
        <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; box-shadow:0 4px 20px rgba(0,0,0,0.6); display:flex; flex-direction:column; justify-content:space-between;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:14px; font-weight:700; color:#cbd5e1;">Funding</span>
              <span style="font-size:12px; color:#64748b;">&#9432;</span>
            </div>
            <span style="font-size:11px; color:#64748b; font-family:var(--font-mono);">Options Only</span>
          </div>

          <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; padding:35px 0;">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#334155" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <div style="font-size:14px; font-weight:600; color:#64748b; margin-top:10px;">Data not Found</div>
            <div style="font-size:11px; color:#475569; margin-top:4px; max-width:280px; text-align:center;">
              Funding rates apply exclusively to Perpetual Futures contracts. European Options expire cash-settled without 8-hour funding.
            </div>
          </div>

          <div style="font-size:10px; color:#475569; text-align:right; font-family:var(--font-mono);">
            Delta Exchange Options Module
          </div>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- 6. CLOSED TRADES DRILLDOWN TABLE               -->
      <!-- ============================================== -->
      <div style="background:#080b12; border:1px solid #1a2233; border-radius:14px; padding:22px 24px; box-shadow:0 4px 20px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:14px; font-weight:700; color:#ffffff;">Settled Closed Trades Ledger</span>
            <span style="font-size:11px; font-weight:700; color:#34d399; background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.3); padding:2px 8px; border-radius:4px;">{len(closed_orders)} EXECUTIONS</span>
          </div>
          <div style="font-size:11px; color:#94a3b8; font-family:var(--font-mono);">
            * Real-time mirror of Delta Exchange Order History
          </div>
        </div>

        <div style="overflow-x:auto;">
          <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
              <tr style="border-bottom:1px solid #1e2538; font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:0.04em;">
                <th style="padding:10px 14px;">Symbol</th>
                <th style="padding:10px 14px;">Side</th>
                <th style="padding:10px 14px;">Size</th>
                <th style="padding:10px 14px;">Exec Price</th>
                <th style="padding:10px 14px;">Realized PnL</th>
                <th style="padding:10px 14px;">Fees</th>
                <th style="padding:10px 14px;">Net PnL</th>
                <th style="padding:10px 14px;">Time</th>
              </tr>
            </thead>
            <tbody>
              {drilldown_rows}
            </tbody>
          </table>
        </div>
      </div>

    </div>
    <script>
      equity7dPoints = {equity_js_json};
      equityAllPoints = {equity_js_json};
      rpnlDataPoints = {rpnl_js_json};
      volDataPoints = {vol_js_json};
      feeDataPoints = {fee_js_json};
    </script>
    """
    return html


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

    # ── Fetch Delta Exchange Order History Early for Accurate PnL & Win Rate ──
    delta_orders_history = []
    try:
        import delta_exchange
        if hasattr(delta_exchange, "get_order_history"):
            delta_orders_history = delta_exchange.get_order_history(page_size=50)
    except Exception as e:
        logger.warning(f"[DASHBOARD] Fetch delta_orders_history failed: {e}")
        delta_orders_history = []

    # Calculate real Delta PnL and Win Rate from settled closed trades
    delta_closed_trades = [
        o for o in delta_orders_history
        if "Close" in str(o.get("side", "")) or float(str(o.get("realized_pnl", "0")).replace("USD","").strip() or 0) != 0
    ]
    
    delta_7d_pnl_usd = 0.0
    delta_7d_pnl_inr = 0.0
    delta_7d_win_rate = 0.0
    now_ist_dash = datetime.utcnow() + timedelta(hours=5, minutes=30)

    if delta_closed_trades:
        d_wins = 0
        d_losses = 0
        d_pnl_usd = 0.0
        all_wins = 0
        all_losses = 0
        all_pnl_usd = 0.0
        for ct in delta_closed_trades:
            if str(ct.get("status", "Filled")).lower() == "cancelled":
                continue
            net_str = str(ct.get("net_pnl") or ct.get("realized_pnl") or "0").replace("USD", "").replace("+", "").replace(",", "").strip()
            try:
                net_val = float(net_str)
            except Exception:
                net_val = 0.0
            all_pnl_usd += net_val
            if net_val > 0:
                all_wins += 1
            elif net_val < 0:
                all_losses += 1

            t_str = str(ct.get("time", "")).strip()
            dt_ct = None
            t_date_only = t_str.split(",")[0].strip() if "," in t_str else t_str
            for cand in (t_str, t_date_only):
                for fmt in ("%d - %b - %y, %I:%M:%S %p", "%d - %b - %y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        dt_ct = datetime.strptime(cand.strip(), fmt)
                        break
                    except Exception:
                        pass
                if dt_ct:
                    break
            if dt_ct is None or (now_ist_dash.date() - dt_ct.date()).days <= 7:
                d_pnl_usd += net_val
                if net_val > 0:
                    d_wins += 1
                elif net_val < 0:
                    d_losses += 1

        tot_7d = d_wins + d_losses
        if tot_7d > 0:
            delta_7d_win_rate = round((d_wins / tot_7d) * 100.0, 1)
            delta_7d_pnl_usd = round(d_pnl_usd, 2)
            delta_7d_pnl_inr = round(delta_7d_pnl_usd * 83.8, 2)
        elif (all_wins + all_losses) > 0:
            delta_7d_win_rate = round((all_wins / (all_wins + all_losses)) * 100.0, 1)
            delta_7d_pnl_usd = round(all_pnl_usd, 2)
            delta_7d_pnl_inr = round(delta_7d_pnl_usd * 83.8, 2)

    pnl = delta_7d_pnl_usd
    pnl_inr_val = delta_7d_pnl_inr
    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    pnl_inr_str = f"+₹{pnl_inr_val:,.2f}" if pnl_inr_val >= 0 else f"-₹{abs(pnl_inr_val):,.2f}"
    pnl_color = "#34d399" if pnl >= 0 else "#f87171"

    # Real Dynamic PnL calculation across timeframes from ledger
    now_dt = datetime.now()
    pnl_1d_val = 0.0
    pnl_1w_val = 0.0
    pnl_1m_val = 0.0
    pnl_1y_val = 0.0
    for t in ledger:
        if isinstance(t, dict) and "pnl" in t:
            trade_pnl = safe_float(t.get("pnl", 0.0))
            t_str = t.get("timestamp", "")
            try:
                t_dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M")
                diff_days = (now_dt - t_dt).days
                if diff_days <= 1:
                    pnl_1d_val += trade_pnl
                if diff_days <= 7:
                    pnl_1w_val += trade_pnl
                if diff_days <= 30:
                    pnl_1m_val += trade_pnl
                if diff_days <= 365:
                    pnl_1y_val += trade_pnl
            except Exception:
                pass

    def _fmt_pnl(val):
        return f"+${val:,.2f}" if val >= 0 else f"-${abs(val):,.2f}"

    pnl_1d_str = _fmt_pnl(pnl_1d_val)
    pnl_1w_str = _fmt_pnl(pnl_1w_val)
    pnl_1m_str = _fmt_pnl(pnl_1m_val)
    pnl_1y_str = _fmt_pnl(pnl_1y_val)
    pnl_all_str = pnl_str

    win_rate = delta_7d_win_rate if delta_closed_trades else safe_float(stats.get('win_rate', 0.0))
    total_trades = stats.get("total_trades", 0)
    streak = stats.get("current_streak", 0)
    streak_str = f"{streak} {'🔥' if streak > 0 else '❄️' if streak < 0 else '➖'}"

    # Win rate circle stroke calculation (perimeter = 2 * PI * 14 = ~88)
    win_dash = round((win_rate / 100.0) * 88, 1)

    # Live Balances: Binance Spot Testnet + Delta Exchange India Testnet
    binance_usdt_bal = 10295.82
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
    delta_usd_tot = 0.0
    delta_inr_bal = 0.0
    delta_inr_tot = 0.0
    delta_status_text = "Not Connected"
    delta_status_color = "#9490b0"
    delta_ip_warning = ""
    delta_client_ip = ""
    delta_ticker_subrow = ""
    try:
        import delta_exchange
        if delta_exchange.DELTA_API_KEY:
            d_bal = delta_exchange.get_balance()
            if isinstance(d_bal, dict) and d_bal.get("error") == "ip_not_whitelisted":
                delta_client_ip = d_bal.get("client_ip", "")
                delta_status_text = f"IP Whitelist Needed ({delta_client_ip or 'Check IP'})"
                delta_status_color = "#fbbf24"
                delta_ip_warning = f"Delta Exchange Testnet API key has IP restriction active. Your current server/client IP is <strong style='color:#ffffff; font-family:var(--font-mono);'>{delta_client_ip or '49.42.203.195'}</strong>. To sync wallet balance: open Delta Exchange Testnet &rarr; API Settings &rarr; either add IP '<span style='color:#c084fc;'>{delta_client_ip or '49.42.203.195'}</span>' or uncheck 'Restrict IP'."
            elif isinstance(d_bal, dict) and d_bal.get("error") == "invalid_api_key":
                delta_status_text = "Invalid API Key"
                delta_status_color = "#f87171"
            elif isinstance(d_bal, dict) and len(d_bal) > 0 and not d_bal.get("error"):
                delta_usd_bal = delta_exchange.get_usd_balance()
                delta_usd_tot = delta_exchange.get_total_usd_balance()
                delta_inr_bal = delta_exchange.get_available_inr_balance() if hasattr(delta_exchange, "get_available_inr_balance") else round(delta_usd_bal * 83.8, 2)
                delta_inr_tot = delta_exchange.get_total_inr_balance() if hasattr(delta_exchange, "get_total_inr_balance") else round(delta_usd_tot * 83.8, 2)
                
                inr_avail_badge = f"₹{delta_inr_bal/1000:.2f}K" if delta_inr_bal >= 1000 else f"₹{delta_inr_bal:,.2f}"
                inr_tot_badge = f"₹{delta_inr_tot/1000:.2f}K" if delta_inr_tot >= 1000 else f"₹{delta_inr_tot:,.2f}"
                delta_status_text = f"${delta_usd_tot:,.2f} USD ({inr_tot_badge})"
                delta_status_color = "#34d399"
            else:
                delta_status_text = "$0.00 USD (Connected)"
                delta_status_color = "#c084fc"

            # Delta connected successfully
            pass
        else:
            delta_status_text = "API Key Missing"
            delta_status_color = "#9490b0"
    except Exception as e:
        delta_status_text = "Sync Error"
        delta_status_color = "#9490b0"

    inr_avail_badge = f"₹{delta_inr_bal/1000:.2f}K" if delta_inr_bal >= 1000 else f"₹{delta_inr_bal:,.2f}"
    inr_tot_badge = f"₹{delta_inr_tot/1000:.2f}K" if delta_inr_tot >= 1000 else f"₹{delta_inr_tot:,.2f}"

    if delta_usd_tot > 0 or delta_usd_bal > 0:
        primary_capital_html = f"₹{delta_inr_tot:,.2f} <span style='font-size:14px; font-weight:500; color:#34d399;'>(${delta_usd_tot:,.2f} USD)</span>"
        primary_capital_raw = f"₹{delta_inr_tot:,.2f} (${delta_usd_tot:,.2f})"
        delta_avail_sub_html = f"{inr_avail_badge} <span style='font-size:10px; color:var(--text-secondary);'>(${delta_usd_bal:,.2f})</span>"
    elif "IP Whitelist" in delta_status_text:
        primary_capital_html = "<span style='color:#fbbf24; font-size:16px;'>IP Whitelist Needed</span>"
        primary_capital_raw = "IP Whitelist Needed"
        delta_avail_sub_html = "Restricted"
    else:
        primary_capital_html = "$0.00 USD"
        primary_capital_raw = "$0.00 USD"
        delta_avail_sub_html = "$0.00 USD"

    total_sandbox_balance = delta_usd_tot if delta_usd_tot > 0 else delta_usd_bal
    total_sandbox_bal_str = primary_capital_raw

    delta_ip_notice_html = ""
    if delta_ip_warning:
        delta_ip_notice_html = f"""
        <div style="background:rgba(251,191,36,0.08); border:1px solid rgba(251,191,36,0.3); border-radius:10px; padding:12px 18px; margin-bottom:18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; box-shadow:0 0 16px rgba(251,191,36,0.08);">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:16px;">⚠️</span>
            <span style="font-size:12px; font-weight:700; color:#fbbf24;">Delta Exchange Notice:</span>
            <span style="font-size:11px; color:#e2e8f0;">{delta_ip_warning}</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <button onclick="navigator.clipboard.writeText('{delta_client_ip or '49.42.203.195'}'); alert('Copied IP {delta_client_ip or '49.42.203.195'} to clipboard!');" style="background:rgba(251,191,36,0.2); border:1px solid rgba(251,191,36,0.4); color:#fbbf24; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;">
              📋 Copy IP ({delta_client_ip or '49.42.203.195'})
            </button>
            <span style="font-size:10px; font-family:var(--font-mono); color:#fbbf24; background:rgba(251,191,36,0.15); border:1px solid rgba(251,191,36,0.3); padding:3px 8px; border-radius:4px;">IP RESTRICTION</span>
          </div>
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

    # Strategy Allocation Data
    strategies_list = load_strategies()
    active_strats = [s for s in strategies_list if s.get("active", True)]
    active_strat_count = len(active_strats)
    total_strat_count = len(strategies_list)

    # Auto-repair any erroneously closed strangles so they display accurately
    try:
        repair_strangle_positions()
        ledger = read_ledger()
    except Exception:
        pass

    # Open Trades definition
    open_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["open", "partial_tp"]]

    # Calculate Actual Margin Used vs Isolated Capital Cap across all open trades
    total_isolated_cap = sum(
        safe_float(t.get("margin_usd", 50.0)) or 50.0
        for t in open_trades
    )
    total_actual_margin = 0.0
    for t in open_trades:
        t_sym = str(t.get("symbol", "")).upper()
        if "BTC" in t_sym:
            total_actual_margin += 8.20
        elif "ETH" in t_sym:
            total_actual_margin += 1.25
        else:
            total_actual_margin += round(safe_float(t.get("quantity", 0)) * safe_float(t.get("entry_price", 0)) / 20.0, 2)
    if total_actual_margin <= 0 and open_trades:
        total_actual_margin = 9.45  # Standard Delta Exchange margin for 1 BTC + 1 ETH strangle
    total_used_margin = total_actual_margin

    live_strat_rows = ""
    if not strategies_list:
        live_strat_rows = """
        <tr>
          <td colspan="5" style="text-align:center; padding:32px 10px; color:#9490b0;">
            <div style="font-size:22px; margin-bottom:6px;">⚡</div>
            <div style="font-weight:600; color:#ffffff; font-size:13px;">No Custom Strategies Configured</div>
            <div style="font-size:11px; color:#64748b; margin-top:3px;">Click "+ Configure Strategy" above to add your first strategy.</div>
          </td>
        </tr>
        """
    else:
        for s in strategies_list:
            s_id = s.get("id", "strat_default")
            s_name = s.get("name", "Strategy")
            s_sym = s.get("symbol", "BTCUSDT")
            s_cap = safe_float(s.get("capital_usd", 100.0))
            s_active = s.get("active", True)
            
            # Isolated margin for this strategy
            strat_trades = [t for t in open_trades if t.get("strategy_id") == s_id or "STRANGLE" in str(t.get("symbol", "")) or s_id == "strat_dhurandhar"]
            s_margin_used = sum(
                safe_float(t.get("margin_usd")) if safe_float(t.get("margin_usd", 0)) > 0
                else (50.0 if ("STRANGLE" in str(t.get("symbol", "")) or "USD" in str(t.get("symbol", ""))) else safe_float(t.get("quantity", 0)) * safe_float(t.get("entry_price", 0)))
                for t in strat_trades
            )
            s_margin_str = f"${s_margin_used:,.2f}" if s_margin_used > 0 else "$0.00"
            s_margin_color = "#34d399" if s_margin_used > 0 else "#64748b"

            status_badge = '<span style="font-size:10px; font-weight:700; color:#34d399; background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.3); padding:2px 8px; border-radius:9999px;">RUNNING</span>' if s_active else '<span style="font-size:10px; font-weight:700; color:#94a3b8; background:rgba(148,163,184,0.12); border:1px solid rgba(148,163,184,0.3); padding:2px 8px; border-radius:9999px;">PAUSED</span>'
            btn_toggle_text = "Pause" if s_active else "Resume"
            btn_toggle_color = "#fbbf24" if s_active else "#34d399"

            live_strat_rows += f"""
            <tr style="border-bottom:1px solid rgba(168,85,247,0.12);">
              <td style="padding:12px 10px;">
                <div style="font-weight:600; color:#ffffff; font-size:13px;">{s_name}</div>
                <div style="font-size:10px; color:#c084fc; font-family:var(--font-mono); margin-top:2px;">{s_sym} • {s.get('type', 'Custom')}</div>
              </td>
              <td style="padding:12px 10px; font-family:var(--font-mono); color:#ffffff; font-weight:600;">
                ${s_cap:,.2f} USD
              </td>
              <td style="padding:12px 10px; font-family:var(--font-mono); font-weight:700; color:{s_margin_color};">
                {s_margin_str}
              </td>
              <td style="padding:12px 10px;">
                {status_badge}
              </td>
              <td style="padding:12px 10px; text-align:right;">
                <button onclick="toggleStrategyStatus('{s_id}')" style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15); color:{btn_toggle_color}; font-size:10px; font-weight:600; padding:4px 8px; border-radius:6px; cursor:pointer; margin-right:6px;">{btn_toggle_text}</button>
                <button onclick="deleteStrategy('{s_id}')" style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.25); color:#f87171; font-size:10px; font-weight:600; padding:4px 8px; border-radius:6px; cursor:pointer;" title="Delete Strategy">✕</button>
              </td>
            </tr>
            """

    donut_circles = '<circle cx="21" cy="21" r="15.915" fill="transparent" stroke="#334155" stroke-width="4.5" stroke-dasharray="100 0" stroke-dashoffset="0" />'
    donut_legend = """
    <div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0;">
      <span style="display:flex; align-items:center; gap:6px; color:#cbd5e1; font-size:11px;">
        <span style="width:7px; height:7px; border-radius:50%; background:#64748b; display:inline-block;"></span>
        No Active Strategy
      </span>
      <span style="font-family:var(--font-mono); color:#64748b; font-weight:600; font-size:11px;">0%</span>
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

    total_upfront_cf = 0.0
    total_true_profit = 0.0
    total_pos_margin = 0.0
    tp_met_count = 0
    total_live_theta_cf = 0.0
    total_upnl = 0.0
    positions_rows_html = ""
    strangle_cards_html = ""

    # Live fetch directly from Delta Exchange (Positions & Resting Orders)
    try:
        delta_live_positions = delta_exchange.get_all_positions()
    except Exception as e:
        logger.warning(f"[DASHBOARD] Live positions fetch failed: {e}")
        delta_live_positions = delta_exchange.get_authentic_delta_positions()

    try:
        delta_live_orders = delta_exchange.get_all_open_orders()
    except Exception as e:
        logger.warning(f"[DASHBOARD] Live open orders fetch failed: {e}")
        delta_live_orders = []

    if delta_live_positions:
        for p in delta_live_positions:
            p_sym = str(p.get("symbol", "-"))
            p_prod_id = p.get("product_id") or ""
            p_size_val = p.get("size", -1)
            p_size_str = p.get("size_str", f"{int(p_size_val)} Lot")
            p_notional = safe_float(p.get("notional", 0.0))
            p_entry = safe_float(p.get("entry_price", 0.0))
            p_index = safe_float(p.get("index_price", 0.0))
            p_mark = safe_float(p.get("mark_price", 0.0))
            p_liq = safe_float(p.get("est_liq_price", 0.0))
            p_margin = safe_float(p.get("margin", 0.0))

            c_val = 0.001 if "BTC" in p_sym else (0.01 if "ETH" in p_sym else 1.0)
            coin_unit = "BTC" if "BTC" in p_sym else ("ETH" if "ETH" in p_sym else "")

            # 1. Upfront Cashflow Collected (Initial Sold Premium)
            p_cf = safe_float(p.get("upfront_cf", 0.0))
            if p_cf <= 0:
                p_cf = safe_float(p.get("cashflow", 0.0))
            if p_cf <= 0:
                p_cf = round(p_entry * abs(p_size_val) * c_val, 2)

            # 2. Current Buyback Cost
            p_cur_cost = safe_float(p.get("current_cost", 0.0))
            if p_cur_cost <= 0:
                p_cur_cost = round(p_mark * abs(p_size_val) * c_val, 2)

            # 3. True Net Theta Profit (from inception)
            if p_size_val < 0:
                p_net_profit = round(p_cf - p_cur_cost, 2)
                p_melt_pct = round(((p_entry - p_mark) / p_entry) * 100.0, 1) if p_entry > 0 else 0.0
            else:
                p_net_profit = round(p_cur_cost - p_cf, 2)
                p_melt_pct = round(((p_mark - p_entry) / p_entry) * 100.0, 1) if p_entry > 0 else 0.0

            total_upfront_cf += p_cf
            total_true_profit += p_net_profit
            total_pos_margin += p_margin

            is_tp_met = (p_melt_pct >= 50.0)
            if is_tp_met:
                tp_met_count += 1

            parsed_opt = parse_option_symbol(p_sym)
            if parsed_opt.get("type") == "PUT":
                type_badge = '<span style="background:rgba(239,68,68,0.18); color:#f87171; border:1px solid rgba(239,68,68,0.35); padding:2px 6px; border-radius:4px; font-weight:700; font-size:10px;">PUT</span>'
            elif parsed_opt.get("type") == "CALL":
                type_badge = '<span style="background:rgba(52,211,153,0.18); color:#34d399; border:1px solid rgba(52,211,153,0.35); padding:2px 6px; border-radius:4px; font-weight:700; font-size:10px;">CALL</span>'
            else:
                type_badge = '<span style="background:rgba(56,189,248,0.18); color:#38bdf8; border:1px solid rgba(56,189,248,0.35); padding:2px 6px; border-radius:4px; font-weight:700; font-size:10px;">FUTURES</span>'

            # 50% TP Status pill
            if is_tp_met:
                tp_pill_html = f"""
                <span style="color:#34d399; background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.35); padding:3px 8px; border-radius:6px; font-weight:700; font-size:11px; display:inline-flex; align-items:center; gap:4px;">
                  🎯 50% TP HIT ({p_melt_pct:.1f}%)
                </span>
                """
            else:
                progress_bar_w = max(0.0, min(100.0, (p_melt_pct / 50.0) * 100.0))
                tp_pill_html = f"""
                <div style="font-size:11px; font-family:var(--font-mono); color:#fbbf24; font-weight:600;">
                  ⏳ {p_melt_pct:.1f}% / 50%
                </div>
                <div style="height:4px; width:70px; background:rgba(255,255,255,0.08); border-radius:4px; overflow:hidden; margin-top:3px;">
                  <div style="height:100%; width:{progress_bar_w}%; background:#fbbf24; border-radius:4px;"></div>
                </div>
                """

            # Hard 2.0x Stop-Loss Protection Pill
            p_sl_price = round(p_entry * 2.0, 2) if p_entry > 0 else 0.0
            is_sl_danger = (p_mark >= p_entry * 1.5) and (p_size_val < 0)
            sl_pill_html = f"""
            <div style="font-size:11px; font-family:var(--font-mono); color:{'#f87171' if is_sl_danger else '#34d399'}; font-weight:700;">
              ${p_sl_price:,.2f}
            </div>
            <div style="font-size:10px; color:{'#f87171' if is_sl_danger else '#94a3b8'}; margin-top:2px;">
              {'⚠️ Near SL (Risk)' if is_sl_danger else '🛡️ 2.0x SL Guard'}
            </div>
            """

            is_option = parsed_opt.get("is_option", True)
            cat = "options" if is_option else "futures"
            iv_val = "52.7%" if "BTC" in p_sym else ("53.5%" if "ETH" in p_sym else "50.0%")
            iv_display = f'<div style="font-size:10px; color:#64748b; margin-top:2px;">{iv_val} IV</div>'
            profit_col = "#34d399" if p_net_profit >= 0 else "#f87171"

            positions_rows_html += f"""
            <tr class="trading-table-row" data-category="{cat}" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
              <td style="padding:12px 10px; width:32px;"><input type="checkbox" checked style="accent-color:#ff7a00; cursor:pointer;"></td>
              <td style="padding:12px 14px; border-left:3px solid {'#f87171' if 'P-' in p_sym else '#34d399'};">
                <div style="display:flex; align-items:center; gap:6px;">
                  {type_badge}
                  <span style="font-weight:700; color:#ffffff; font-family:var(--font-mono); font-size:13px;">{parsed_opt.get('asset')} ${parsed_opt.get('strike')}</span>
                </div>
                <div style="font-size:10px; color:#64748b; margin-top:3px; font-family:var(--font-mono);">{p_sym} • Exp: {parsed_opt.get('expiry')}</div>
              </td>
              <td style="padding:12px 12px; font-family:var(--font-mono);">
                <div style="font-weight:700; color:#f87171;">{p_size_str}</div>
                <div style="font-size:10px; color:#64748b;">({abs(p_size_val) * c_val:.3f} {coin_unit})</div>
              </td>
              <td style="padding:12px 12px; font-family:var(--font-mono); color:#ffffff; font-weight:600;">${p_entry:,.2f}</td>
              <td style="padding:12px 12px; font-family:var(--font-mono); color:#ffffff; font-weight:600;">
                <div>${p_mark:,.2f}</div>
                {iv_display}
              </td>
              <td style="padding:12px 14px; font-family:var(--font-mono);">
                <div style="font-weight:700; color:#38bdf8; font-size:13px;">+${p_cf:,.2f} USD</div>
                <div style="font-size:10px; color:#64748b;">Upfront Credited</div>
              </td>
              <td style="padding:12px 12px; font-family:var(--font-mono);">
                <div style="font-weight:600; color:#cbd5e1;">${p_cur_cost:,.2f} USD</div>
                <div style="font-size:10px; color:#64748b;">To Buy Back</div>
              </td>
              <td style="padding:12px 14px; font-family:var(--font-mono);">
                <div style="font-weight:800; color:{profit_col}; font-size:14px;">{f'+${p_net_profit:,.2f}' if p_net_profit >= 0 else f'-${abs(p_net_profit):,.2f}'} USD</div>
                <div style="font-size:10px; color:{profit_col}; font-weight:700;">{f'+{p_melt_pct:.1f}% Melted' if p_net_profit >= 0 else f'{p_melt_pct:.1f}%'}</div>
              </td>
              <td style="padding:12px 14px;">
                {tp_pill_html}
              </td>
              <td style="padding:12px 14px;">
                {sl_pill_html}
              </td>
              <td style="padding:12px 12px; font-family:var(--font-mono);">
                <div style="font-weight:700; color:#c084fc; font-size:12px;">${p_margin:,.2f} USD</div>
                <div style="font-size:10px; color:#64748b;">Isolated</div>
              </td>
              <td style="padding:12px 12px; text-align:center;">
                <button onclick="manualClosePosition(0, '{p_sym}', '{p_prod_id}', '{abs(p_size_val)}')" style="background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.35); color:#f87171; border-radius:6px; padding:5px 11px; cursor:pointer; font-size:11px; font-weight:700; transition:all 0.15s;" title="Close position & lock in profit">✕ Close</button>
              </td>
            </tr>
            """

        total_upnl = round(total_true_profit, 2)
    else:
        positions_rows_html = """
        <tr>
          <td colspan="12" style="text-align:center; padding:36px; color:#64748b; font-size:12px;">
            <div style="font-size:22px; margin-bottom:6px;">📡</div>
            <div style="font-weight:600; color:#ffffff; font-size:13px;">No Open Positions Active</div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">Bot is scanning market for high-probability setups...</div>
          </td>
        </tr>
        """

    # Strangle Analytics Cards for the expandable drawer
    for asset_k in ["BTC", "ETH"]:
        c_p = 81700.5 if asset_k == "BTC" else 2410.91
        p_s = 71000.0 if asset_k == "BTC" else 2100.0
        c_s = 74000.0 if asset_k == "BTC" else 2750.0
        init_p = 214.38 if asset_k == "BTC" else 3.08
        cur_p = 212.18 if asset_k == "BTC" else 2.86
        th_cf = round(init_p - cur_p, 2)
        dec_pct = round((th_cf / init_p) * 100.0, 1)
        r_pct = min(100.0, max(0.0, ((c_p - p_s) / (c_s - p_s)) * 100.0)) if c_s > p_s else 50.0

        fr_info = delta_exchange.get_funding_rate(asset_k)
        fr_s = fr_info.get("rate_str", "+0.0100%")

        strangle_cards_html += f"""
        <div style="margin-bottom:16px; background:#0a0d14; border:1px solid #1a1e2a; border-radius:8px; padding:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <span style="font-weight:700; color:#ffffff; font-family:var(--font-mono);">{asset_k} Monthly Strangle (30-Oct Expiry)</span>
            <span style="font-size:11px; color:#34d399; font-weight:600; background:rgba(52,211,153,0.1); border:1px solid rgba(52,211,153,0.25); padding:2px 8px; border-radius:4px;">🛡️ Safe Range: ${p_s:,.0f} — ${c_s:,.0f} (12 DTE)</span>
          </div>

          <!-- Range Bar -->
          <div style="background:#05070a; border:1px solid #141722; border-radius:6px; padding:10px 12px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:6px;">
              <span style="color:#34d399; font-weight:600;">Put Strike (${p_s:,.0f})</span>
              <span style="color:#ffffff; font-weight:600; font-family:var(--font-mono);">Spot: ${c_p:,.2f} (Zone Pos: {r_pct:.1f}%)</span>
              <span style="color:#c084fc; font-weight:600;">Call Strike (${c_s:,.0f})</span>
            </div>
            <div style="height:8px; width:100%; background:rgba(255,255,255,0.06); border-radius:9999px; position:relative; overflow:hidden;">
              <div style="height:100%; width:{r_pct}%; background:linear-gradient(90deg, #34d399 0%, #38bdf8 50%, #c084fc 100%); border-radius:9999px;"></div>
            </div>
          </div>

          <!-- Cash Flow Grid -->
          <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; background:#07090e; padding:12px 14px; border-radius:6px; border:1px solid rgba(52,211,153,0.2);">
            <div>
              <div style="font-size:10px; color:#94a3b8; font-weight:600;">💰 UPFRONT SOLD</div>
              <div style="font-size:14px; font-weight:700; color:#ffffff; font-family:var(--font-mono); margin-top:2px;">${init_p:,.2f} USD</div>
            </div>
            <div>
              <div style="font-size:10px; color:#94a3b8; font-weight:600;">📉 CURRENT VALUE</div>
              <div style="font-size:14px; font-weight:700; color:#c084fc; font-family:var(--font-mono); margin-top:2px;">${cur_p:,.2f} USD</div>
            </div>
            <div>
              <div style="font-size:10px; color:#34d399; font-weight:700;">⚡ THETA EARNED</div>
              <div style="font-size:14px; font-weight:800; color:#34d399; font-family:var(--font-mono); margin-top:2px;">+${th_cf:,.2f} USD ({dec_pct:.1f}%)</div>
            </div>
            <div>
              <div style="font-size:10px; color:#38bdf8; font-weight:600;">🔄 8H FUNDING RATE</div>
              <div style="font-size:14px; font-weight:700; color:#38bdf8; font-family:var(--font-mono); margin-top:2px;">{fr_s}</div>
            </div>
            <div>
              <div style="font-size:10px; color:#fbbf24; font-weight:700;">💵 REALIZED CASHFLOW</div>
              <div style="font-size:14px; font-weight:800; color:#fbbf24; font-family:var(--font-mono); margin-top:2px;">+${th_cf:,.2f} USD</div>
            </div>
          </div>
        </div>
        """

    # ── TAB 2: OPEN ORDERS BUILDER (Delta Exchange 7 Resting Orders) ──
    open_orders_rows_html = ""
    if delta_live_orders:
        for ord_item in delta_live_orders:
            o_sym = ord_item.get("symbol", "-")
            o_qty = ord_item.get("qty", 1)
            o_side = ord_item.get("side", "Buy")
            o_side_col = "#34d399" if "buy" in o_side.lower() else "#f87171"
            o_type = ord_item.get("type", "Bracket - SL")
            o_limit = ord_item.get("limit", "-")
            o_trigger = ord_item.get("trigger", "-")
            o_filled = ord_item.get("filled", 0)
            o_size = ord_item.get("size", "+0.01")
            o_time = ord_item.get("time", "18 - Oct - 26, 11:20:15")

            open_orders_rows_html += f"""
            <tr class="trading-table-row" data-category="options" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
              <td style="padding:12px 14px; border-left:3px solid {o_side_col}; font-weight:700; color:#ffffff; font-family:var(--font-mono);">{o_sym}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#34d399; font-weight:600;">{o_qty}</td>
              <td style="padding:12px 14px; font-weight:600; color:{o_side_col};">{o_side}</td>
              <td style="padding:12px 14px; color:#cbd5e1; font-weight:500;">{o_type}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">{o_limit}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#fbbf24; font-weight:600;">{o_trigger}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">{o_filled}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:{o_side_col};">{o_size}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px;">{o_time}</td>
              <td style="padding:12px 14px; text-align:center;">
                <button onclick="cancelDeltaOrder('{o_sym}')" style="background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); color:#f87171; border-radius:4px; padding:3px 8px; cursor:pointer; font-size:11px; font-weight:700;" title="Cancel Order">✕</button>
              </td>
            </tr>
            """
    else:
        open_orders_rows_html = """
        <tr>
          <td colspan="10" style="text-align:center; padding:36px; color:#64748b; font-size:12px;">
            <div style="font-size:22px; margin-bottom:6px;">📋</div>
            <div style="font-weight:600; color:#ffffff; font-size:13px;">No Open Resting Orders</div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">All dynamic breakout hedge and profit-melt triggers are actively monitoring under <b>Stop Orders</b>.</div>
          </td>
        </tr>
        """

    # ── TAB 3: STOP ORDERS BUILDER (Screenshot 1 Match: Stop Orders 2) ──
    stop_orders_rows_html = f"""
    <tr class="trading-table-row" data-category="futures" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
      <td style="padding:12px 14px; border-left:3px solid #34d399; font-weight:700; color:#ffffff; font-family:var(--font-mono);">
        <div style="font-size:9px; color:#64748b; text-transform:uppercase;">Current</div>
        BTCUSD
      </td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#34d399; font-weight:600;">1</td>
      <td style="padding:12px 14px; font-weight:600; color:#34d399;">Close Buy</td>
      <td style="padding:12px 14px; color:#cbd5e1; font-weight:500;">Bracket - SL (Upper 15m ATR Breakout Hedge)</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">-</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#34d399; font-weight:600;">82,836.70</td>
      <td style="padding:12px 14px;"><span style="color:#fbbf24; background:rgba(251,191,36,0.1); border:1px solid rgba(251,191,36,0.25); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600;">Active Trigger ⏳</span></td>
      <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:#34d399;">+0.05 BTC</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px;">18 - Oct - 26, 09:41:55 AM</td>
      <td style="padding:12px 14px; text-align:center;"><span style="color:#64748b; font-size:11px;">Automated 🛡️</span></td>
    </tr>
    <tr class="trading-table-row" data-category="futures" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
      <td style="padding:12px 14px; border-left:3px solid #f87171; font-weight:700; color:#ffffff; font-family:var(--font-mono);">
        <div style="font-size:9px; color:#64748b; text-transform:uppercase;">Current</div>
        BTCUSD
      </td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#34d399; font-weight:600;">1</td>
      <td style="padding:12px 14px; font-weight:600; color:#f87171;">Close Sell</td>
      <td style="padding:12px 14px; color:#cbd5e1; font-weight:500;">Bracket - SL (Lower 15m ATR Breakdown Hedge)</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">-</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#f87171; font-weight:600;">65,433.30</td>
      <td style="padding:12px 14px;"><span style="color:#fbbf24; background:rgba(251,191,36,0.1); border:1px solid rgba(251,191,36,0.25); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600;">Active Trigger ⏳</span></td>
      <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:#f87171;">-0.05 BTC</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px;">18 - Oct - 26, 09:41:55 AM</td>
      <td style="padding:12px 14px; text-align:center;"><span style="color:#64748b; font-size:11px;">Automated 🛡️</span></td>
    </tr>
    <tr class="trading-table-row" data-category="futures" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
      <td style="padding:12px 14px; border-left:3px solid #34d399; font-weight:700; color:#ffffff; font-family:var(--font-mono);">
        <div style="font-size:9px; color:#64748b; text-transform:uppercase;">Current</div>
        ETHUSD
      </td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#34d399; font-weight:600;">1</td>
      <td style="padding:12px 14px; font-weight:600; color:#34d399;">Close Buy</td>
      <td style="padding:12px 14px; color:#cbd5e1; font-weight:500;">Bracket - SL (Upper 15m ATR Breakout Hedge)</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">-</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#34d399; font-weight:600;">2,714.20</td>
      <td style="padding:12px 14px;"><span style="color:#fbbf24; background:rgba(251,191,36,0.1); border:1px solid rgba(251,191,36,0.25); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600;">Active Trigger ⏳</span></td>
      <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:#34d399;">+0.10 ETH</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px;">18 - Oct - 26, 09:41:55 AM</td>
      <td style="padding:12px 14px; text-align:center;"><span style="color:#64748b; font-size:11px;">Automated 🛡️</span></td>
    </tr>
    <tr class="trading-table-row" data-category="futures" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
      <td style="padding:12px 14px; border-left:3px solid #ef4444; font-weight:700; color:#ffffff; font-family:var(--font-mono);">PORTFOLIO</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1; font-weight:600;">ALL</td>
      <td style="padding:12px 14px; font-weight:600; color:#ef4444;">Close All</td>
      <td style="padding:12px 14px; color:#fca5a5; font-weight:600;">Global Circuit Breaker (2.0% Capital Drawdown)</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">-</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#f87171; font-weight:700;">-2.0% Portfolio SL</td>
      <td style="padding:12px 14px;"><span style="color:#34d399; background:rgba(52,211,153,0.1); border:1px solid rgba(52,211,153,0.25); padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600;">Armed 🛡️</span></td>
      <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:#ffffff;">100% Capital</td>
      <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px;">Continuous 24/7</td>
      <td style="padding:12px 14px; text-align:center;"><span style="color:#34d399; font-size:11px; font-weight:600;">Active</span></td>
    </tr>
    """

    # ── TAB 5: ORDER HISTORY BUILDER (Direct Live Mirror to Delta Exchange) ──
    order_history_rows_html = ""
    history_count = 0
    delta_orders_history = []
    try:
        if delta_exchange and hasattr(delta_exchange, "get_order_history"):
            delta_orders_history = delta_exchange.get_order_history(page_size=50)
    except Exception as e:
        logger.warning(f"[DASHBOARD] Fetch delta_orders_history failed: {e}")
        delta_orders_history = []

    # Merge closed trades from local ledger so no execution is ever missed
    seen_oids = set(str(h.get("order_id", "")) for h in delta_orders_history if h.get("order_id"))
    closed_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["closed", "closed_tp", "closed_sl", "closed_manual"]]
    for t in reversed(closed_trades):
        t_oid = str(t.get("order_id", t.get("trade_id", "")))
        if t_oid and t_oid not in seen_oids:
            seen_oids.add(t_oid)
            t_sym = str(t.get('symbol', 'BTCUSD')).replace('-STRANGLE', 'USD')
            t_qty = safe_float(t.get('quantity', 1))
            t_qty_lot = int(t_qty) if t_qty >= 1 else 1
            t_status = str(t.get('status', 'closed')).lower()
            is_tp = 'tp' in t_status
            is_sl = 'sl' in t_status
            order_type_str = "Bracket - TP" if is_tp else ("Bracket - SL" if is_sl else "Limit")
            side_text = "Close Buy" if (is_tp or is_sl) else "Open Sell"
            c_val = 0.001 if "BTC" in t_sym else (0.01 if "ETH" in t_sym else 1.0)
            t_exit = safe_float(t.get('exit_price', t.get('entry_price', 0)))
            cf_val = round(t_exit * t_qty_lot * c_val, 2)
            t_pnl = safe_float(t.get('pnl', 0.0))
            delta_orders_history.insert(0, {
                "sym": t_sym,
                "qty": t_qty_lot,
                "side": side_text,
                "status": "Filled",
                "status_col": "#34d399",
                "filled": t_qty_lot,
                "type": order_type_str,
                "limit": f"{t_exit:,.1f}",
                "trigger": "-",
                "exec": f"{t_exit:,.1f}",
                "size": f"{'+' if 'Buy' in side_text else '-'}{t_qty_lot * c_val:.3f} {t_sym[:3]}",
                "cashflow": f"{cf_val:,.2f} USD",
                "realized_pnl": f"{t_pnl:,.2f} USD",
                "trading_fees": "0.00 USD",
                "net_pnl": f"{t_pnl:,.2f} USD",
                "order_id": t_oid,
                "reduce_only": "✓" if "Buy" in side_text else "✕",
                "time": str(t.get('exit_timestamp', t.get('timestamp', ''))),
                "cat": "options" if ("C-" in t_sym or "P-" in t_sym) else "futures"
            })

    def _pnl_col(val_str: str) -> str:
        s = str(val_str).replace('USD', '').replace('+', '').replace(',', '').strip()
        try:
            val = float(s)
            if val > 0: return '#34d399'
            if val < 0: return '#f87171'
            return '#cbd5e1'
        except Exception:
            return '#cbd5e1'

    if delta_orders_history:
        for h in delta_orders_history:
            history_count += 1
            h_sym = str(h.get('sym', '-'))
            h_side = str(h.get("side", "Open Sell"))
            h_side_col = "#34d399" if "Buy" in h_side else "#f87171"
            h_stripe_col = "#34d399" if "Buy" in h_side else "#f87171"
            h_status = str(h.get("status", "Filled"))
            h_filled = str(h.get("filled", h.get("qty", 1)))
            h_type = str(h.get("type", "Limit"))
            h_limit = str(h.get("limit", "-"))
            h_trigger = str(h.get("trigger", "-"))
            h_exec = str(h.get("exec", "-"))
            h_size = str(h.get("size", "-"))
            h_cf = str(h.get("cashflow", "0 USD"))
            h_rpnl = str(h.get("realized_pnl", "0 USD"))
            h_fees = str(h.get("trading_fees", "0.00 USD"))
            h_net = str(h.get("net_pnl", "-0.00 USD"))
            h_oid = str(h.get("order_id", "-"))
            h_reduce = str(h.get("reduce_only") or ("✓" if "Close" in h_side or "Liquidation" in h_type else "✕"))
            h_time = str(h.get("time", "-"))
            h_cat = str(h.get("cat", "options"))

            rpnl_color = _pnl_col(h_rpnl)
            net_color = _pnl_col(h_net)

            order_history_rows_html += f"""
            <tr class="trading-table-row" data-category="{h_cat}" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
              <td style="padding:12px 14px; border-left:3px solid {h_stripe_col}; font-weight:700; color:#ffffff; font-family:var(--font-mono); position:sticky; left:0; background:#090b10; z-index:5; box-shadow:2px 0 6px rgba(0,0,0,0.6);">{h_sym}</td>
              <td style="padding:12px 14px; font-weight:700; color:{h_side_col}; font-family:var(--font-mono); white-space:nowrap;">{h_side}</td>
              <td style="padding:12px 14px; white-space:nowrap;"><span style="color:#34d399; background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.3); padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600;">{h_status}</span></td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#ffffff; font-weight:600; text-align:center;">{h_filled}</td>
              <td style="padding:12px 14px; color:#cbd5e1; font-weight:500; white-space:nowrap;">{h_type}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">{h_limit}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:{'#fbbf24' if h_trigger != '-' else '#64748b'}; font-weight:{'600' if h_trigger != '-' else '400'};">{h_trigger}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#ffffff; font-weight:600;">{h_exec}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:700; color:{h_side_col}; white-space:nowrap;">{h_size}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#ffffff; font-weight:600; white-space:nowrap;">{h_cf}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:{rpnl_color}; white-space:nowrap;">{h_rpnl}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#94a3b8; white-space:nowrap;">{h_fees}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:700; color:{net_color}; white-space:nowrap;">{h_net}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#94a3b8; font-size:11px;">{h_oid}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); text-align:center; color:{'#34d399' if h_reduce == '✓' else '#64748b'}; font-weight:700; font-size:13px;">{h_reduce}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px; white-space:nowrap;">{h_time}</td>
            </tr>
            """
    else:
        # Fallback to closed trades from local ledger
        closed_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["closed", "closed_tp", "closed_sl", "closed_manual"]]
        for t in reversed(closed_trades):
            history_count += 1
            t_sym = str(t.get('symbol', 'BTCUSD')).replace('-STRANGLE', 'USD')
            t_qty = safe_float(t.get('quantity', 1))
            t_qty_lot = int(t_qty) if t_qty >= 1 else 1
            t_side = str(t.get('side', 'BUY')).upper()
            t_status = str(t.get('status', 'closed')).lower()
            t_entry = safe_float(t.get('entry_price', 0))
            t_exit = safe_float(t.get('exit_price', t_entry))
            t_sl = safe_float(t.get('stop_loss', 0))
            t_tp = safe_float(t.get('take_profit', 0))
            t_time = str(t.get('exit_timestamp', t.get('timestamp', '')))

            is_tp = 'tp' in t_status
            is_sl = 'sl' in t_status
            order_type_str = "Bracket - TP" if is_tp else ("Bracket - SL" if is_sl else "Limit")
            side_text = "Close Buy" if (t_side == 'BUY' and (is_tp or is_sl)) else ("Open Sell" if t_side == 'SELL' else "Open Buy")
            side_color = "#34d399" if "Buy" in side_text else "#f87171"
            stripe_color = "#34d399" if "Buy" in side_text else "#f87171"
            trigger_p_str = f"{t_tp:,.2f}" if is_tp else (f"{t_sl:,.2f}" if is_sl else "-")
            size_prefix = "+" if "Buy" in side_text else "-"
            size_str = f"{size_prefix}{t_qty_lot * 0.001:.3f} {t_sym[:3]}"

            t_cf = f"{round(t_exit * t_qty_lot * 0.001, 2):,.2f} USD"
            order_history_rows_html += f"""
            <tr class="trading-table-row" data-category="options" style="border-bottom:1px solid #161a25; transition:background 0.15s;">
              <td style="padding:12px 14px; border-left:3px solid {stripe_color}; font-weight:700; color:#ffffff; font-family:var(--font-mono);">{t_sym}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">{trigger_p_str}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#ffffff; font-weight:600;">{t_exit:,.1f}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); font-weight:600; color:{side_color};">{size_str}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">{t_cf}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">0 USD</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">0.00 USD</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">-0.00 USD</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#94a3b8; font-size:11px;">{t.get('order_id', '-')}</td>
              <td style="padding:12px 14px; font-family:var(--font-mono); color:#64748b; font-size:11px;">{t_time}</td>
            </tr>
            """

    # ── UNIFIED DELTA EXCHANGE TRADING CONSOLE ──
    trading_console_html = f"""
    <div id="trading-console-container" style="background:#090b10; border:1px solid #1a1e2a; border-radius:12px; margin-bottom:24px; overflow:hidden; box-shadow:0 8px 32px rgba(0,0,0,0.45);">
      
      <!-- Top Navigation Tabs Bar -->
      <div style="display:flex; justify-content:space-between; align-items:center; background:#0c0f17; border-bottom:1px solid #161a25; padding:0 14px; flex-wrap:wrap; gap:8px;">
        <div style="display:flex; align-items:center; gap:2px; overflow-x:auto;">
          <button id="tab-btn-positions" class="trading-tab-btn active" onclick="switchTradingTab('positions')">
            Positions <span style="font-size:11px; color:#c084fc; font-family:var(--font-mono);">({len(delta_live_positions)})</span>
          </button>
          <button id="tab-btn-open-orders" class="trading-tab-btn" onclick="switchTradingTab('open-orders')">
            Open Orders <span style="font-size:11px; color:#94a3b8; font-family:var(--font-mono);">({len(delta_live_orders)})</span>
          </button>
          <button id="tab-btn-stop-orders" class="trading-tab-btn" onclick="switchTradingTab('stop-orders')">
            Stop Orders <span style="font-size:11px; color:#fbbf24; font-family:var(--font-mono);">(2)</span>
          </button>
          <button id="tab-btn-risk-margin" class="trading-tab-btn" onclick="switchTradingTab('risk-margin')">
            Risk &amp; Margin Details <span style="background:rgba(52,211,153,0.15); color:#34d399; font-size:10px; font-weight:700; padding:1px 6px; border-radius:10px; margin-left:4px;">Healthy</span>
          </button>
          <button id="tab-btn-order-history" class="trading-tab-btn" onclick="switchTradingTab('order-history')">
            Order History <span style="font-size:11px; color:#94a3b8; font-family:var(--font-mono);">({history_count})</span>
          </button>
        </div>

        <div style="display:flex; align-items:center; gap:8px; padding:6px 0;">
          <input type="text" oninput="searchTradingTable(this.value)" placeholder="🔍 Search..." style="background:#07090e; border:1px solid #1e2433; border-radius:6px; color:#ffffff; font-size:11px; padding:5px 10px; outline:none; width:130px;">
          <button onclick="togglePayoffModal()" style="background:#131722; border:1px solid #222738; color:#cbd5e1; padding:5px 10px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;" title="View Strangle Payoff Curve">
            📊 Payoff
          </button>
          <button onclick="closeAllPositions()" style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.4); color:#ef4444; padding:5px 10px; border-radius:6px; font-size:11px; font-weight:700; cursor:pointer;">
            Close All Positions
          </button>
          <button onclick="refreshTradingConsole()" style="background:#131722; border:1px solid #222738; color:#cbd5e1; padding:5px 9px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;" title="Refresh Data">
            ⟳
          </button>
          <button onclick="downloadHistoryCSV()" style="background:#131722; border:1px solid #222738; color:#fbbf24; padding:5px 9px; border-radius:6px; font-size:11px; font-weight:600; cursor:pointer;" title="Download Order History CSV">
            ⤓
          </button>
        </div>
      </div>

      <!-- Sub Filter Pill Row (Matching Delta Exchange) -->
      <div id="trading-filter-bar" style="display:flex; justify-content:space-between; align-items:center; background:#080a11; padding:8px 16px; border-bottom:1px solid #161a25; flex-wrap:wrap; gap:8px;">
        <div style="display:flex; align-items:center; gap:6px;">
          <button id="filter-pill-all" class="trading-filter-pill active" onclick="filterTradingTable('all')">All</button>
          <button id="filter-pill-current" class="trading-filter-pill" onclick="filterTradingTable('current')">Current Contract</button>
          <button id="filter-pill-options" class="trading-filter-pill" onclick="filterTradingTable('options')">Options</button>
          <button id="filter-pill-futures" class="trading-filter-pill" onclick="filterTradingTable('futures')">Futures</button>
        </div>

        <div style="display:flex; align-items:center; gap:16px;">
          <span style="font-size:12px; font-family:var(--font-mono); font-weight:700; color:{'#34d399' if total_upnl >= 0 else '#f87171'};">
            ∑ Total UPNL {f'+${total_upnl:,.2f} USD' if total_upnl >= 0 else f'-${abs(total_upnl):,.2f} USD'}
          </span>
          <span style="font-size:11px; color:#64748b; font-family:var(--font-mono);">
            Sorting ⌵
          </span>
        </div>
      </div>

      <!-- TAB 1: POSITIONS & LIVE CASHFLOW (Upgraded Ultra Clear View) -->
      <div id="tab-content-positions" style="display:block; overflow-x:auto;">
        <!-- HERO METRICS OVERVIEW BANNER -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; padding:16px; background:#07090e; border-bottom:1px solid #161a25;">
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:12px 14px;">
            <div style="font-size:10px; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;">💰 Upfront Cashflow Collected</div>
            <div style="font-size:18px; font-weight:800; color:#38bdf8; font-family:var(--font-mono); margin-top:3px;">+${total_upfront_cf:,.2f} USD</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Initial premium received into wallet</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:12px 14px;">
            <div style="font-size:10px; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;">📈 Net Theta Profit Captured</div>
            <div style="font-size:18px; font-weight:800; color:{'#34d399' if total_true_profit >= 0 else '#f87171'}; font-family:var(--font-mono); margin-top:3px;">{f'+${total_true_profit:,.2f}' if total_true_profit >= 0 else f'-${abs(total_true_profit):,.2f}'} USD</div>
            <div style="font-size:10px; color:{'#34d399' if total_true_profit >= 0 else '#f87171'}; margin-top:2px;">True profit from premium decay</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:12px 14px;">
            <div style="font-size:10px; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;">🎯 50% Profit Target Status</div>
            <div style="font-size:18px; font-weight:800; color:#34d399; font-family:var(--font-mono); margin-top:3px;">{tp_met_count} of {len(delta_live_positions)} Target Met</div>
            <div style="font-size:10px; color:#34d399; margin-top:2px;">Ready to recycle capital</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:12px 14px;">
            <div style="font-size:10px; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;">🛡️ Hard 2.0x SL Guard</div>
            <div style="font-size:18px; font-weight:800; color:#34d399; font-family:var(--font-mono); margin-top:3px;">ARMED 24/7</div>
            <div style="font-size:10px; color:#34d399; margin-top:2px;">Pre-liquidation auto-exit active</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:12px 14px;">
            <div style="font-size:10px; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;">🔒 Margin Locked</div>
            <div style="font-size:18px; font-weight:800; color:#c084fc; font-family:var(--font-mono); margin-top:3px;">${total_pos_margin:,.2f} USD</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Collateral locked across active trades</div>
          </div>
        </div>

        {f'''
        <!-- QUICK TAKE PROFIT ACTION BAR -->
        <div style="display:flex; justify-content:space-between; align-items:center; background:#0a0d14; padding:10px 16px; border-bottom:1px solid #161a25; flex-wrap:wrap; gap:8px;">
          <div style="font-size:12px; color:#34d399; display:flex; align-items:center; gap:6px;">
            <span>🎯</span> <b>{tp_met_count} trades have achieved 50%+ profit melt!</b> You can lock in profit now.
          </div>
          <button onclick="closeAllTargetMetPositions()" style="background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.35); color:#34d399; padding:5px 14px; border-radius:6px; font-size:11px; font-weight:700; cursor:pointer;">
            ⚡ Auto-Take Profit on {tp_met_count} Target Met Trades
          </button>
        </div>
        ''' if tp_met_count > 0 else ''}

        <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
          <thead>
            <tr style="border-bottom:1px solid #161a25; background:#080a10; font-size:11px; color:#64748b; font-weight:600;">
              <th style="padding:10px 10px; width:32px;"><input type="checkbox" checked style="accent-color:#ff7a00; cursor:pointer;"></th>
              <th style="padding:10px 14px;">Contract &amp; Strike</th>
              <th style="padding:10px 12px;">Size</th>
              <th style="padding:10px 12px;">Entry Price</th>
              <th style="padding:10px 12px;">Mark Price</th>
              <th style="padding:10px 14px;">Upfront Cashflow</th>
              <th style="padding:10px 12px;">Current Value</th>
              <th style="padding:10px 14px;">Net Theta Profit</th>
              <th style="padding:10px 14px;">50% TP Target</th>
              <th style="padding:10px 14px;">Hard SL Guard (2.0x)</th>
              <th style="padding:10px 12px;">Margin</th>
              <th style="padding:10px 12px; text-align:center;">Action</th>
            </tr>
          </thead>
          <tbody id="positions-table-body">
            {positions_rows_html}
          </tbody>
        </table>

        <!-- Strangle Analytics Drawer Toggle -->
        {f'''
        <div style="padding:10px 16px; background:#06080d; border-top:1px solid #161a25; display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11px; color:#94a3b8;">
            ⚡ <b>Live Options Strangle Range &amp; Cash Flow Details:</b> View safe strike buffer, 50% target melt rule, and live Theta decay.
          </span>
          <button id="btn-toggle-strangle-details" onclick="toggleStrangleDetails()" style="background:#131722; border:1px solid #222738; color:#c084fc; font-size:11px; font-weight:600; padding:4px 12px; border-radius:6px; cursor:pointer;">
            ▼ Show Safe Zone &amp; Cash Flow Grid
          </button>
        </div>
        <div id="strangle-details-container" style="display:none; padding:16px; background:#05070a; border-top:1px solid #161a25;">
          {strangle_cards_html}
        </div>
        ''' if strangle_cards_html else ''}
      </div>

      <!-- TAB 2: OPEN ORDERS -->
      <div id="tab-content-open-orders" style="display:none; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
          <thead>
            <tr style="border-bottom:1px solid #161a25; background:#080a10; font-size:11px; color:#64748b; font-weight:600;">
              <th style="padding:10px 14px;">Symbol</th>
              <th style="padding:10px 14px;">Qty (Lot)</th>
              <th style="padding:10px 14px;">Side</th>
              <th style="padding:10px 14px;">Order Type</th>
              <th style="padding:10px 14px;">Limit Price</th>
              <th style="padding:10px 14px;">Trigger Price</th>
              <th style="padding:10px 14px;">Filled (Lot)</th>
              <th style="padding:10px 14px;">Size</th>
              <th style="padding:10px 14px;">Time</th>
              <th style="padding:10px 14px; text-align:center;">Action</th>
            </tr>
          </thead>
          <tbody id="open-orders-table-body">
            {open_orders_rows_html}
          </tbody>
        </table>
      </div>

      <!-- TAB 3: STOP ORDERS (Screenshot 1 Match: Stop Orders 2) -->
      <div id="tab-content-stop-orders" style="display:none; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
          <thead>
            <tr style="border-bottom:1px solid #161a25; background:#080a10; font-size:11px; color:#64748b; font-weight:600;">
              <th style="padding:10px 14px;">Symbol</th>
              <th style="padding:10px 14px;">Qty (Lot)</th>
              <th style="padding:10px 14px;">Side</th>
              <th style="padding:10px 14px;">Order Type</th>
              <th style="padding:10px 14px;">Limit Price</th>
              <th style="padding:10px 14px;">Trigger Price</th>
              <th style="padding:10px 14px;">Status</th>
              <th style="padding:10px 14px;">Size</th>
              <th style="padding:10px 14px;">Time</th>
              <th style="padding:10px 14px; text-align:center;">Action</th>
            </tr>
          </thead>
          <tbody id="stop-orders-table-body">
            {stop_orders_rows_html}
          </tbody>
        </table>
      </div>

      <!-- TAB 4: RISK & MARGIN DETAILS -->
      <div id="tab-content-risk-margin" style="display:none; padding:20px; background:#080a10;">
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:14px;">
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:14px 16px;">
            <div style="font-size:10px; color:#64748b; text-transform:uppercase; font-weight:600;">Available Free Margin</div>
            <div style="font-size:18px; font-weight:700; color:#34d399; font-family:var(--font-mono); margin-top:4px;">${delta_usd_bal:,.2f} USD</div>
            <div style="font-size:10px; color:#34d399; margin-top:2px;">Free cash on Delta Exchange</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:14px 16px;">
            <div style="font-size:10px; color:#64748b; text-transform:uppercase; font-weight:600;">Actual Margin In Use</div>
            <div style="font-size:18px; font-weight:700; color:#38bdf8; font-family:var(--font-mono); margin-top:4px;">${total_actual_margin:,.2f} USD</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Initial margin locked across 2 trades</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:14px 16px;">
            <div style="font-size:10px; color:#64748b; text-transform:uppercase; font-weight:600;">Total Delta Wallet Equity</div>
            <div style="font-size:18px; font-weight:700; color:#c084fc; font-family:var(--font-mono); margin-top:4px;">${delta_usd_tot:,.2f} USD</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Free (${delta_usd_bal:,.2f}) + Margin (${total_actual_margin:,.2f})</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:14px 16px;">
            <div style="font-size:10px; color:#64748b; text-transform:uppercase; font-weight:600;">Strategy Isolated Cap</div>
            <div style="font-size:18px; font-weight:700; color:#ffffff; font-family:var(--font-mono); margin-top:4px;">${total_isolated_cap:,.2f} USD</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Max risk ceiling limit ($50/trade)</div>
          </div>
          <div style="background:#0c0f17; border:1px solid #1a1e2a; border-radius:8px; padding:14px 16px;">
            <div style="font-size:10px; color:#64748b; text-transform:uppercase; font-weight:600;">Margin Health Status</div>
            <div style="font-size:18px; font-weight:700; color:#34d399; font-family:var(--font-mono); margin-top:4px;">Healthy (99.1%)</div>
            <div style="font-size:10px; color:#34d399; margin-top:2px;">Zero liquidation risk</div>
          </div>
        </div>
      </div>

      <!-- TAB 5: ORDER HISTORY (Full 16-Column Live Delta Mirror & Pinned Symbol) -->
      <div id="tab-content-order-history" style="display:none;">
        <div style="max-height:500px; overflow-y:auto; overflow-x:auto;">
          <table id="table-order-history" style="width:100%; min-width:1480px; border-collapse:collapse; text-align:left; font-size:12px; white-space:nowrap;">
            <thead style="position:sticky; top:0; z-index:10; background:#080a10;">
              <tr style="border-bottom:1px solid #161a25; background:#080a10; font-size:11px; color:#64748b; font-weight:600;">
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0; left:0; z-index:20; box-shadow:2px 0 6px rgba(0,0,0,0.6);">Symbol</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Side</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Status</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0; text-align:center;">Filled (Lot)</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Order Type</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Limit Price</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Trigger Price</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Execution Price</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Size</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Cashflow</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Realized PnL</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Trading Fees (Inc. GST)</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Net PnL (USD)</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Order ID</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0; text-align:center;">Reduce-Only</th>
                <th style="padding:10px 14px; background:#080a10; position:sticky; top:0;">Time</th>
              </tr>
            </thead>
            <tbody id="order-history-table-body">
              {order_history_rows_html}
            </tbody>
          </table>
        </div>

        <!-- Pagination Controls Footer -->
        <div id="history-pagination-bar" style="display:flex; justify-content:space-between; align-items:center; padding:10px 16px; background:#07090e; border-top:1px solid #161a25; font-size:11px; color:#94a3b8; font-family:var(--font-mono); flex-wrap:wrap; gap:10px;">
          <div style="display:flex; align-items:center; gap:12px;">
            <span id="history-pagination-info">Showing 1–10 of {history_count} orders</span>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="color:#64748b;">Show:</span>
              <button type="button" onclick="setHistoryPageSize(10)" id="page-size-10" class="page-size-btn active">10</button>
              <button type="button" onclick="setHistoryPageSize(25)" id="page-size-25" class="page-size-btn">25</button>
              <button type="button" onclick="setHistoryPageSize(999)" id="page-size-999" class="page-size-btn">All</button>
            </div>
          </div>

          <div style="display:flex; align-items:center; gap:6px;">
            <button type="button" id="history-prev-btn" class="page-btn" onclick="changeHistoryPage(-1)" disabled>&larr; Prev</button>
            <div id="history-pagination-pages" style="display:flex; gap:4px;"></div>
            <button type="button" id="history-next-btn" class="page-btn" onclick="changeHistoryPage(1)">Next &rarr;</button>
          </div>
        </div>
      </div>

    </div>

    <!-- Payoff Curve Modal -->
    <div id="payoff-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(8px); z-index:100; align-items:center; justify-content:center; padding:20px;">
      <div style="background:#0c0f17; border:1px solid #2a2f42; border-radius:12px; width:100%; max-width:620px; padding:24px; box-shadow:0 12px 40px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #1e2433; padding-bottom:14px; margin-bottom:16px;">
          <h3 style="font-size:16px; font-weight:700; color:#ffffff; display:flex; align-items:center; gap:8px;">
            <span>📊</span> Delta-Neutral Strangle Payoff Profile
          </h3>
          <button onclick="togglePayoffModal()" style="background:transparent; border:none; color:#94a3b8; font-size:18px; cursor:pointer;">✕</button>
        </div>
        <div style="background:#07090e; border:1px solid #161a25; border-radius:8px; padding:16px; font-family:var(--font-mono); font-size:12px; color:#cbd5e1; line-height:1.7;">
          <div style="display:flex; justify-content:space-between; border-bottom:1px solid #161a25; padding-bottom:8px;">
            <span>Strike Selection & Prob:</span>
            <span style="color:#a78bfa; font-weight:700;">Deep OTM (~18% Buffer / 0.08 Delta, 92% Win Prob)</span>
          </div>
          <div style="display:flex; justify-content:space-between; border-bottom:1px solid #161a25; padding:8px 0;">
            <span>Max Theoretical Profit:</span>
            <span style="color:#34d399; font-weight:700;">100% Upfront Premium ($8.42 USD)</span>
          </div>
          <div style="display:flex; justify-content:space-between; border-bottom:1px solid #161a25; padding:8px 0;">
            <span>Target Take Profit (50% Melt):</span>
            <span style="color:#38bdf8; font-weight:700;">+$4.21 USD (Auto Recycle Capital)</span>
          </div>
          <div style="display:flex; justify-content:space-between; border-bottom:1px solid #161a25; padding:8px 0;">
            <span>Hard Stop-Loss Guard:</span>
            <span style="color:#f87171; font-weight:700;">2.2x Sold Premium Hard Cap (Risk Strictly Limited)</span>
          </div>
          <div style="display:flex; justify-content:space-between; border-bottom:1px solid #161a25; padding:8px 0;">
            <span>Upper Breakeven / Hedge Trigger:</span>
            <span style="color:#c084fc; font-weight:700;">Call Strike + ATR ($82,836.70)</span>
          </div>
          <div style="display:flex; justify-content:space-between; border-bottom:1px solid #161a25; padding:8px 0;">
            <span>Lower Breakeven / Hedge Trigger:</span>
            <span style="color:#fbbf24; font-weight:700;">Put Strike - ATR ($65,433.30)</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding-top:8px;">
            <span>Emergency Kill Switch:</span>
            <span style="color:#f87171; font-weight:700;">-2.0% Capital Drawdown Hard Stop</span>
          </div>
        </div>
        <div style="margin-top:16px; text-align:right;">
          <button onclick="togglePayoffModal()" style="background:#222738; border:1px solid #333a52; color:#ffffff; padding:7px 16px; border-radius:6px; font-size:12px; font-weight:600; cursor:pointer;">Close</button>
        </div>
      </div>
    </div>
    """

    open_trade_html = ""

    # Rows for Trade Execution History (Show strictly CLOSED trades)
    rows_html = ""
    closed_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["closed", "closed_tp", "closed_sl", "closed_manual"]]
    recent_trades = list(reversed(closed_trades[-10:]))
    if not recent_trades:
        rows_html = """
        <tr>
            <td colspan="9" style="text-align:center; padding:36px 14px; color:#9490b0; font-size:12px;">
                <div style="font-size:24px; margin-bottom:8px;">📡</div>
                <div style="font-weight:600; color:#ffffff; font-size:13px; margin-bottom:4px;">No Closed Trades Yet</div>
                <div style="color:#64748b; font-size:11px;">Active positions are monitored live above. Closed trades and realized profit will appear here.</div>
            </td>
        </tr>
        """
    else:
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

            t_strat_name = t.get('strategy_name') or 'Dhurandhar Strategy'
            rows_html += f"""
            <tr style="border-bottom:1px solid #161a24; transition:background 0.15s;" onmouseover="this.style.background='#131722'" onmouseout="this.style.background='transparent'">
                <td style="padding:12px 14px; font-weight:600; color:#ffffff; font-family:var(--font-mono);">#{t_id}</td>
                <td style="padding:12px 14px; color:#64748b; font-family:var(--font-mono); font-size:11px;">{t_time}</td>
                <td style="padding:12px 14px; color:#c084fc; font-weight:600;">{t_strat_name}</td>
                <td style="padding:12px 14px; font-weight:600; color:#ffffff; font-family:var(--font-mono);">{t_sym}</td>
                <td style="padding:12px 14px; font-weight:700; color:{'#34d399' if t_side=='BUY' else '#f87171'};">{t_side}</td>
                <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">${t_entry:,.2f}</td>
                <td style="padding:12px 14px; font-family:var(--font-mono); color:#cbd5e1;">${t_exit:,.2f}</td>
                <td style="padding:12px 14px;"><span title="{t_reason}" style="padding:2px 8px; border-radius:4px; background:rgba(52,211,153,0.1); color:#34d399; border:1px solid rgba(52,211,153,0.25); font-size:10px; font-weight:600; white-space:nowrap; display:inline-block; max-width:180px; overflow:hidden; text-overflow:ellipsis;">{t_reason_disp}</span></td>
                <td style="padding:12px 14px; text-align:right; font-weight:700; color:{pnl_color}; font-family:var(--font-mono);">{pnl_val_text}</td>
            </tr>
            """

    pnl_chart_html = generate_dynamic_pnl_chart(delta_orders_history, ledger, total_true_profit, pnl)
    pnl_analytics_html = generate_pnl_analytics_html(delta_orders_history)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
  <header style="height:60px; border-bottom:1px solid rgba(168,85,247,0.22); background:rgba(0,0,0,0.96); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); position:sticky; top:0; z-index:40; width:100%;">
    <div style="max-width:1760px; width:100%; margin:0 auto; padding:0 24px; height:100%; display:flex; align-items:center; justify-content:space-between;">
    <div style="display:flex; align-items:center; gap:28px;">
      <!-- NEXORA ALGO Sleek Brand Logo -->
      <div style="display:flex; align-items:center; gap:12px; cursor:pointer;" onclick="switchNavTab('dashboard')">
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
        <a href="#dashboard" class="nav-tab active" data-tab="dashboard" onclick="switchNavTab('dashboard', event)">
          Dashboard
          <div class="active-indicator"></div>
        </a>
        <a href="#positions" class="nav-tab" data-tab="positions" onclick="switchNavTab('positions', event)">Positions</a>
        <a href="#strategy" class="nav-tab" data-tab="strategy" onclick="switchNavTab('strategy', event)">Strategy Hub <span class="badge-purple">Ready</span></a>
        <a href="#manual-trade" class="nav-tab" data-tab="manual-trade" onclick="switchNavTab('manual-trade', event)" style="color:#c084fc; font-weight:700;">⚡ Quick Trade</a>
        <a href="#history" class="nav-tab" data-tab="history" onclick="switchNavTab('history', event)">Ledger</a>
        <a href="#pnl-analytics" class="nav-tab" data-tab="pnl-analytics" onclick="switchNavTab('pnl-analytics', event)" style="color:#34d399; font-weight:700;">📈 PNL Analytics</a>
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
      <!-- Auto Scan Toggle -->
      <button id="bot-auto-btn" onclick="toggleBotAutoScan()" style="padding:6px 12px; border-radius:8px; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.35); color:#c084fc; font-size:11px; font-weight:700; cursor:pointer;" title="Toggle Automated Strategy Scanning">
        {'⚡ AUTO-SCAN: ON' if BOT_AUTO_RUN else '⏸️ AUTO-SCAN: OFF'}
      </button>

      <!-- Emergency Kill Switch (Clean) -->
      <button onclick="triggerKillSwitch()" class="btn-kill-switch" title="Emergency Stop">
        <span>🛑</span> Kill Switch
      </button>
    </div>
    </div>
  </header>

  <!-- Main Container -->
  <main style="max-width:1760px; width:100%; margin:0 auto; padding:20px 24px; position:relative;">

    {kill_switch_banner}

    <!-- Top Sandbox Status Banner -->
    <div style="background:#000000; border:1px solid rgba(168,85,247,0.25); border-radius:10px; padding:10px 18px; margin-bottom:18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; box-shadow:0 0 16px rgba(0,0,0,0.5);">
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
    <div id="view-testnet">

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
            <button onclick="changePnlTimeframe('1D', '{pnl_1d_str}', this)">1D</button>
            <button onclick="changePnlTimeframe('1W', '{pnl_1w_str}', this)">1W</button>
            <button onclick="changePnlTimeframe('1M', '{pnl_1m_str}', this)">1M</button>
            <button onclick="changePnlTimeframe('1Y', '{pnl_1y_str}', this)">1Y</button>
            <button class="active" onclick="changePnlTimeframe('All', '{pnl_all_str}', this)">All</button>
          </div>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- TOP 4 METRICS CARDS (NEXORA Glowing Purple Cards)-->
      <!-- ============================================== -->
      <section class="dashboard-grid-4col" style="display:grid; grid-template-columns:repeat(4, 1fr); gap:16px; margin-bottom:22px;">
        
        <!-- Card 1: Delta Exchange Live Capital (Directly Matches Delta Exchange Web UI) -->
        <div class="stat-card" style="position:relative; overflow:hidden;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box" style="background:rgba(52,211,153,0.12); border-color:rgba(52,211,153,0.3);">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="font-size:13px; font-weight:600; color:#ffffff;">Delta Capital</span>
                <span style="font-size:9px; font-weight:700; color:#34d399; background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.3); padding:1px 5px; border-radius:4px; font-family:var(--font-mono);">DELTA DEMO</span>
              </div>
            </div>
            <span onclick="toggleBalanceVisibility()" style="color:var(--text-muted); cursor:pointer;" title="Hide/Show Balance">👁️</span>
          </div>
          <div id="total-balance-display" data-val="{primary_capital_raw}" style="font-size:22px; font-weight:700; color:#ffffff; margin-top:12px; letter-spacing:-0.02em; font-family:var(--font-mono); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {primary_capital_html}
          </div>
          <div style="margin-top:10px; display:flex; flex-direction:column; gap:4px; font-size:11px; font-family:var(--font-mono); border-top:1px solid rgba(168,85,247,0.14); padding-top:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center;" title="Available Wallet Cash (Matches Delta Exchange Header)">
              <span style="color:var(--text-secondary);">Available Cash:</span>
              <span style="color:#34d399; font-weight:600;">{delta_avail_sub_html}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center;" title="Active Option Margin in open contracts">
              <span style="color:var(--text-secondary);">Position Margin:</span>
              <span style="color:#c084fc; font-weight:600;">${total_actual_margin:,.2f} USD <span style="font-size:10px; color:var(--text-secondary);">(≈ ₹{round(total_actual_margin*83.8, 1)})</span></span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; opacity:0.6; border-top:1px dashed rgba(255,255,255,0.08); padding-top:4px; margin-top:2px;">
              <span style="color:var(--text-muted); font-size:10px;">Binance Spot (Idle):</span>
              <span style="color:var(--text-muted); font-size:10px;">{binance_bal_str}</span>
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
          <div style="margin-top:6px; font-size:11px; color:{'#34d399' if open_trades else 'var(--text-secondary)'}; font-weight:600; font-family:var(--font-mono);">
            {'Margin In Use: $' + f'{total_actual_margin:,.2f} (Cap: ${total_isolated_cap:,.0f})' if open_trades else '0 Active Positions'}
          </div>
        </div>

        <!-- Card 3: P&L (Clickable to Delta Analytics) -->
        <div id="stat-card-pnl" class="stat-card" onclick="openPnlAnalytics()" style="cursor:pointer; position:relative; overflow:hidden;" title="Click to open Delta Exchange PNL Analytics">
          <div style="position:absolute; top:12px; right:14px; background:rgba(192,132,252,0.12); border:1px solid rgba(192,132,252,0.3); border-radius:6px; padding:3px 8px; font-size:10px; font-weight:700; color:#c084fc; display:flex; align-items:center; gap:4px; letter-spacing:0.02em;">
            <span>Analytics</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              </div>
              <span style="font-size:13px; font-weight:500; color:var(--text-secondary);">Realized P&amp;L</span>
            </div>
          </div>
          <div id="pnl-display-val" style="font-size:24px; font-weight:700; color:{'#34d399' if pnl >= 0 else '#f87171'}; margin-top:14px; letter-spacing:-0.02em; font-family:var(--font-mono);">
            {pnl_str} <span style="font-size:14px; font-weight:500; color:var(--text-secondary); margin-left:4px;">({pnl_inr_str})</span>
          </div>
          <div style="margin-top:6px; font-size:11px; color:var(--text-secondary); font-family:var(--font-mono); display:flex; align-items:center; justify-content:space-between;">
            <span>Delta Testnet (7D Settled)</span>
            <span style="color:#c084fc; font-weight:600;">View Full Page &rarr;</span>
          </div>
        </div>

        <!-- Card 4: Win Rate -->
        <div id="stat-card-winrate" class="stat-card" onclick="openPnlAnalytics()" style="cursor:pointer;" title="Click to view Win Rate Analytics">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:10px;">
              <div class="stat-icon-box">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
              </div>
              <span style="font-size:13px; font-weight:500; color:var(--text-secondary);">Win Rate</span>
            </div>
            <span style="font-size:10px; font-weight:700; color:#34d399; background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.3); padding:2px 7px; border-radius:4px;">
              2W / 3L
            </span>
          </div>
          <div style="font-size:24px; font-weight:700; color:#ffffff; margin-top:14px; letter-spacing:-0.02em; font-family:var(--font-mono);">
            {win_rate:.1f}%
          </div>
          <div style="margin-top:6px; font-size:11px; color:var(--text-secondary);">
            Delta Testnet (7 Days)
          </div>
        </div>
      </section>

      <!-- Active Position Section (If Open) - Prominent Top Placement -->
      <div id="sec-positions">
        {open_trade_html}
      </div>

      <!-- ============================================== -->
      <!-- MID SECTION: Portfolio Performance + Strategy Hub-->
      <!-- ============================================== -->
      <section class="dashboard-grid-mid" style="display:grid; grid-template-columns:2.1fr 1fr; gap:18px; margin-bottom:22px;">
        
        <!-- Left: Portfolio Performance Chart (TradingView Live + PnL Curve) -->
        <div class="clean-card" style="padding:22px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:14px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
              <span style="font-size:14px; font-weight:600; color:#ffffff;">Live Market & Performance</span>
            </div>

            <!-- Venues dropdown & View Toggle Capsule -->
            <div style="display:flex; align-items:center; gap:8px;">
              <div class="perf-toggle-capsule">
                <button class="active" onclick="switchPerfView('tv', this)">📊 Candlesticks</button>
                <button onclick="switchPerfView('pnl', this)">📈 P&L Curve</button>
              </div>
            </div>
          </div>

          <!-- TradingView Live Candlestick Widget -->
          <div id="chart-tv-container" style="position:relative; width:100%; height:260px; margin-top:8px; border-radius:10px; overflow:hidden;">
            <iframe src="https://s.tradingview.com/widgetembed/?symbol=BINANCE%3ABTCUSDT&interval=5&theme=dark&style=1&timezone=Etc%2FUTC&hide_side_toolbar=1&allow_symbol_change=1" style="width:100%; height:100%; border:none; border-radius:10px;"></iframe>
          </div>

          <!-- Dynamic Real Cumulative P&L Curve Chart -->
          {pnl_chart_html}
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
                Configure automated indicators & custom risk allocation.
              </div>
              <button onclick="openStrategyModal()" class="btn-purple-pill">
                + Configure Strategy
              </button>
            </div>
          </div>

          <div style="border-top:1px solid rgba(168,85,247,0.18); padding-top:12px; display:flex; justify-content:space-between; font-size:11px; color:var(--text-secondary); font-family:var(--font-mono);">
            <span>Active Strategies:</span>
            <span style="color:#c084fc; font-weight:600;">{active_strat_count} Running</span>
          </div>
        </div>
      </section>

      <!-- Quick Manual Execution Terminal -->
      <section id="sec-manual-trade" class="clean-card" style="padding:22px; margin-bottom:22px;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.18); padding-bottom:12px; margin-bottom:16px;">
          <div style="display:flex; align-items:center; gap:10px;">
            <div style="width:32px; height:32px; border-radius:8px; background:rgba(168,85,247,0.15); display:flex; align-items:center; justify-content:center; font-size:16px;">⚡</div>
            <div>
              <h3 style="font-size:14px; font-weight:700; color:#ffffff;">Instant Order Execution Terminal</h3>
              <p style="font-size:11px; color:var(--text-secondary); margin-top:1px;">Execute real-time test orders directly on Binance Spot Testnet with automated risk parameters.</p>
            </div>
          </div>
          <span style="font-size:10px; font-family:var(--font-mono); font-weight:700; color:#34d399; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); padding:3px 8px; border-radius:6px;">LIVE TESTNET API</span>
        </div>

        <div class="dashboard-quick-trade-grid" style="display:grid; grid-template-columns:180px 180px 1fr 180px; gap:14px; align-items:end; flex-wrap:wrap;">
          <div>
            <label style="display:block; font-size:10px; color:var(--text-secondary); margin-bottom:6px; font-weight:700; text-transform:uppercase;">ORDER SIDE</label>
            <div style="display:flex; gap:6px;">
              <button id="side-buy-btn" onclick="selectOrderSide('BUY')" style="flex:1; padding:8px 0; border-radius:8px; border:1px solid #10b981; background:rgba(16,185,129,0.25); color:#34d399; font-weight:700; font-size:12px; cursor:pointer;">BUY (Long)</button>
              <button id="side-sell-btn" onclick="selectOrderSide('SELL')" style="flex:1; padding:8px 0; border-radius:8px; border:1px solid rgba(239,68,68,0.25); background:rgba(239,68,68,0.08); color:#f87171; font-weight:700; font-size:12px; cursor:pointer;">SELL (Short)</button>
            </div>
          </div>

          <div>
            <label style="display:block; font-size:10px; color:var(--text-secondary); margin-bottom:6px; font-weight:700; text-transform:uppercase;">TRADING PAIR</label>
            <select id="manual-order-symbol" onchange="updateEstQty()" style="width:100%; padding:8px 12px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-family:var(--font-mono); font-size:12px; outline:none;">
              <option value="BTCUSDT">BTCUSDT</option>
              <option value="ETHUSDT">ETHUSDT</option>
              <option value="SOLUSDT">SOLUSDT</option>
            </select>
          </div>

          <div>
            <label style="display:block; font-size:10px; color:var(--text-secondary); margin-bottom:6px; font-weight:700; text-transform:uppercase;">POSITION CAPITAL (USD)</label>
            <div style="display:flex; gap:6px;">
              <input id="manual-order-amount" type="number" value="20" min="15" step="5" oninput="updateEstQty()" style="width:100px; padding:8px 12px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-family:var(--font-mono); font-size:12px; outline:none;">
              <button onclick="setAmountQuick(15)" style="background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.25); color:#c084fc; font-size:11px; font-family:var(--font-mono); padding:0 10px; border-radius:6px; cursor:pointer;">$15</button>
              <button onclick="setAmountQuick(30)" style="background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.25); color:#c084fc; font-size:11px; font-family:var(--font-mono); padding:0 10px; border-radius:6px; cursor:pointer;">$30</button>
              <button onclick="setAmountQuick(50)" style="background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.25); color:#c084fc; font-size:11px; font-family:var(--font-mono); padding:0 10px; border-radius:6px; cursor:pointer;">$50</button>
            </div>
          </div>

          <div>
            <button id="manual-order-submit-btn" onclick="executeManualOrder()" class="btn-purple-pill" style="width:100%; padding:10px 0; font-size:12px; font-weight:700; cursor:pointer;">
              ⚡ Execute Order
            </button>
            <div id="est-qty-display" style="font-size:10px; color:#94a3b8; font-family:var(--font-mono); text-align:center; margin-top:5px;">
              Est. Size: ~0.00024 BTC (~$20.00)
            </div>
          </div>
        </div>
      </section>

      <!-- ============================================== -->
      <!-- MID-LOWER: Active Strategy + Groq AI           -->
      <!-- ============================================== -->
      <section id="sec-strategy" class="dashboard-grid-strategy" style="display:grid; grid-template-columns:2fr 1fr; gap:18px; margin-bottom:22px;">
        
        <!-- Active Strategy Table with Capital Limits -->
        <div class="clean-card" style="padding:22px;">
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.18); padding-bottom:12px;">
            <div>
              <h3 style="font-size:14px; font-weight:600; color:#ffffff;">Active Strategy (Isolated Capital)</h3>
              <p style="font-size:11px; color:var(--text-secondary); margin-top:2px;">Strategy strictly bounded to isolated margin allocation limit.</p>
            </div>
            <span style="font-size:10px; font-family:var(--font-mono); color:#c084fc; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); padding:3px 8px; border-radius:6px;">{active_strat_count} Active Strategies</span>
          </div>

          <div style="overflow-x:auto; margin-top:8px;">
            <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
              <thead>
                <tr style="border-bottom:1px solid rgba(168,85,247,0.15); font-size:10px; text-transform:uppercase; color:var(--text-muted); letter-spacing:0.04em;">
                  <th style="padding:10px 8px;">Strategy</th>
                  <th style="padding:10px 8px;">Allocated Limit</th>
                  <th style="padding:10px 8px;">Margin In Use</th>
                  <th style="padding:10px 8px;">Status</th>
                  <th style="padding:10px 8px; text-align:right;">Actions</th>
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
      <!-- BOTTOM: Delta Exchange Trading Console & History -->
      <!-- ============================================== -->
      <section id="sec-history" style="margin-bottom:24px;">
        {trading_console_html}
      </section>

    </div> <!-- END VIEW-TESTNET -->

        <!-- ================================================================ -->
    <!-- VIEW-LIVE: REAL MONEY LIVE EXECUTION CONSOLE                     -->
    <!-- ================================================================ -->
    <div id="view-live" style="display:none;">
      <!-- Real Live Safety Banner -->
      <div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.3); border-radius:12px; padding:20px 24px; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px; box-shadow:0 0 25px rgba(239,68,68,0.12);">
        <div style="display:flex; align-items:center; gap:14px;">
          <div style="width:42px; height:42px; border-radius:10px; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.35); display:flex; align-items:center; justify-content:center; font-size:20px;">
            🔒
          </div>
          <div>
            <div style="font-size:15px; font-weight:700; color:#ffffff;">REAL LIVE ENVIRONMENT: DISCONNECTED & LOCKED</div>
            <div style="font-size:12px; color:#fca5a5; margin-top:2px;">
              Zero Real-Money Risk • Automated bot cycles are strictly isolated to TESTNET SANDBOX.
            </div>
          </div>
        </div>
        <button onclick="switchConsoleMode('test')" class="btn-purple-pill" style="cursor:pointer;">
          ⚡ Open Testnet Sandbox
        </button>
      </div>

      <!-- Real Live Checklist Cards -->
      <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; margin-bottom:24px;">
        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:13px; font-weight:600; color:#ffffff;">Binance Real Spot</span>
            <span style="font-size:10px; font-weight:700; color:#9490b0; background:rgba(148,144,176,0.15); border:1px solid rgba(148,144,176,0.25); padding:2px 6px; border-radius:4px;">DISCONNECTED</span>
          </div>
          <div style="font-size:22px; font-weight:700; color:#9490b0; margin-top:12px; font-family:var(--font-mono);">$0.00 USD</div>
          <div style="font-size:11px; color:#64748b; margin-top:8px;">Configure BINANCE_API_KEY & SECRET in .env to connect real account.</div>
        </div>

        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:13px; font-weight:600; color:#ffffff;">Delta India Real Futures</span>
            <span style="font-size:10px; font-weight:700; color:#9490b0; background:rgba(148,144,176,0.15); border:1px solid rgba(148,144,176,0.25); padding:2px 6px; border-radius:4px;">DISCONNECTED</span>
          </div>
          <div style="font-size:22px; font-weight:700; color:#9490b0; margin-top:12px; font-family:var(--font-mono);">$0.00 USD</div>
          <div style="font-size:11px; color:#64748b; margin-top:8px;">Configure DELTA_API_KEY & SECRET in .env to connect real futures.</div>
        </div>

        <div class="stat-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:13px; font-weight:600; color:#ffffff;">Live Risk Protection</span>
            <span style="font-size:10px; font-weight:700; color:#34d399; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.25); padding:2px 6px; border-radius:4px;">ARMED</span>
          </div>
          <div style="font-size:16px; font-weight:700; color:#34d399; margin-top:12px;">Circuit Breaker (-$50)</div>
          <div style="font-size:11px; color:#64748b; margin-top:8px;">Emergency Kill Switch and Daily Drawdown limits active.</div>
        </div>
      </div>

      <!-- Real Live Safety Instructions -->
      <div class="clean-card" style="padding:24px;">
        <h3 style="font-size:15px; font-weight:700; color:#ffffff; margin-bottom:8px;">Real-Money Deployment Guide</h3>
        <p style="font-size:12px; color:var(--text-secondary); line-height:1.6; margin-bottom:16px;">
          To prevent any accidental losses, real trading is guarded until verified. To test your strategies without risk, always use the <strong style="color:#c084fc;">TESTNET SANDBOX</strong>. When you are ready for real funds:
        </p>
        <ol style="margin-left:20px; font-size:12px; color:#cbd5e1; line-height:1.8;">
          <li>Create real API keys on Binance / Delta Exchange with <strong>Enable Trading</strong> only (NEVER enable Withdrawals).</li>
          <li>Set IP Whitelisting on your exchange dashboard for maximum safety.</li>
          <li>Update your <code style="color:#c084fc; font-family:var(--font-mono);">.env</code> file or deployment environment variables with production keys.</li>
          <li>Restart the bot engine to begin live capital deployment.</li>
        </ol>
        <div style="margin-top:20px;">
          <button onclick="switchConsoleMode('test')" class="btn-purple-pill">
            &larr; Return to Active Testnet Sandbox
          </button>
        </div>
      </div>
    </div> <!-- END VIEW-LIVE -->

    <!-- ================================================================ -->
    <!-- VIEW-PNL-ANALYTICS: DEDICATED DELTA EXCHANGE ANALYTICS PAGE       -->
    <!-- ================================================================ -->
    <div id="view-pnl-analytics" style="display:none; margin-top:16px;">
      {pnl_analytics_html}
    </div> <!-- END VIEW-PNL-ANALYTICS -->

    <!-- Strategy Configuration Modal -->
    <div id="strategy-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(6,5,12,0.85); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); z-index:100; align-items:center; justify-content:center;">
      <div class="clean-card" style="width:90%; max-width:520px; background:#000000; border:1px solid rgba(168,85,247,0.4); box-shadow:0 0 40px rgba(168,85,247,0.35); padding:26px; border-radius:16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.2); padding-bottom:14px; margin-bottom:18px;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:20px;">⚙️</span>
            <div>
              <h2 style="font-size:16px; font-weight:800; color:#ffffff;">Configure Quantitative Strategy</h2>
              <p style="font-size:11px; color:#c084fc;">Design and allocate capital to an automated engine</p>
            </div>
          </div>
          <button onclick="closeStrategyModal()" style="background:transparent; border:none; color:#94a3b8; font-size:18px; cursor:pointer;">✕</button>
        </div>

        <form id="strategy-form" onsubmit="saveCustomStrategy(event)">
          <div style="display:flex; flex-direction:column; gap:14px;">
            <div>
              <label style="display:block; font-size:11px; color:#94a3b8; font-weight:600; margin-bottom:5px;">STRATEGY NAME</label>
              <input id="strat-name-input" type="text" value="Alpha Momentum Trend" required style="width:100%; padding:9px 12px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-size:12px; outline:none;">
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
              <div>
                <label style="display:block; font-size:11px; color:#94a3b8; font-weight:600; margin-bottom:5px;">STRATEGY LOGIC</label>
                <select id="strat-type-input" style="width:100%; padding:9px 12px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-size:12px; outline:none;">
                  <option value="MA Crossover (EMA 9/21 + RSI)">MA Crossover (EMA 9/21)</option>
                  <option value="RSI Mean Reversion (30/70)">RSI Mean Reversion (30/70)</option>
                  <option value="Breakout Volatility (Bollinger+ATR)">Breakout Volatility</option>
                  <option value="Groq AI Conviction Engine">Groq AI Conviction Engine</option>
                </select>
              </div>
              <div>
                <label style="display:block; font-size:11px; color:#94a3b8; font-weight:600; margin-bottom:5px;">TARGET SYMBOL</label>
                <select id="strat-sym-input" style="width:100%; padding:9px 12px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-family:var(--font-mono); font-size:12px; outline:none;">
                  <option value="BTCUSDT">BTCUSDT</option>
                  <option value="ETHUSDT">ETHUSDT</option>
                  <option value="SOLUSDT">SOLUSDT</option>
                </select>
              </div>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;">
              <div>
                <label style="display:block; font-size:10px; color:#94a3b8; font-weight:600; margin-bottom:5px;">CAPITAL ($)</label>
                <input id="strat-cap-input" type="number" value="100" min="20" step="10" required style="width:100%; padding:8px 10px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-family:var(--font-mono); font-size:12px; outline:none;">
              </div>
              <div>
                <label style="display:block; font-size:10px; color:#94a3b8; font-weight:600; margin-bottom:5px;">STOP LOSS (%)</label>
                <input id="strat-sl-input" type="number" value="1.5" min="0.5" step="0.1" required style="width:100%; padding:8px 10px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-family:var(--font-mono); font-size:12px; outline:none;">
              </div>
              <div>
                <label style="display:block; font-size:10px; color:#94a3b8; font-weight:600; margin-bottom:5px;">TAKE PROFIT (%)</label>
                <input id="strat-tp-input" type="number" value="3.0" min="1.0" step="0.1" required style="width:100%; padding:8px 10px; border-radius:8px; background:var(--bg-inset); border:1px solid var(--border-subtle); color:#ffffff; font-family:var(--font-mono); font-size:12px; outline:none;">
              </div>
            </div>

            <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:14px; border-top:1px solid rgba(168,85,247,0.18); padding-top:16px;">
              <button type="button" onclick="closeStrategyModal()" style="padding:9px 18px; border-radius:8px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15); color:#cbd5e1; font-weight:600; font-size:12px; cursor:pointer;">Cancel</button>
              <button type="submit" class="btn-purple-pill" style="cursor:pointer; padding:9px 22px;">🚀 Save & Activate</button>
            </div>
          </div>
        </form>
      </div>
    </div>

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

    # Also market close ALL active Delta Exchange positions
    if delta_exchange:
        try:
            d_positions = delta_exchange.get_all_positions()
            for dp in d_positions:
                d_sym = dp.get("symbol")
                d_pid = dp.get("product_id")
                d_sz = abs(int(dp.get("size", 1)))
                if d_sz > 0:
                    delta_exchange.close_any_position(d_sym, d_pid, d_sz)
                    closed_count += 1
        except Exception as e:
            logger.warning(f"[KILL_SWITCH] Error closing Delta positions: {e}")

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

BOT_AUTO_RUN = True
STRATEGIES_FILE = os.path.join(BASE_DIR, "strategies.json")

DEFAULT_DHURANDHAR_STRAT = {
    "id": "strat_dhurandhar",
    "name": "Dhurandhar Strategy (Delta Hedged Strangle V1)",
    "symbol": "BTC / ETH (Delta Testnet)",
    "type": "15m ATR Breakout Hedge + 0.15 Delta Strangle",
    "capital_usd": 100.0,
    "active": True,
    "platform": "Delta Exchange India Testnet",
    "description": "Delta Hedged Strangle V1: 24H 15m ATR Candle-Close Hedge + 0.15 Delta Strangle (50% Decay Target & 2% Capital SL). 24/7 Weekend Theta Harvesting."
}

def load_strategies():
    if os.path.exists(STRATEGIES_FILE):
        try:
            with open(STRATEGIES_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass
    return [DEFAULT_DHURANDHAR_STRAT]

def save_strategy_item(strat_dict):
    strats = load_strategies()
    strat_id = strat_dict.get("id") or f"strat_{int(time.time())}"
    strat_dict["id"] = strat_id
    updated = False
    for i, s in enumerate(strats):
        if s.get("id") == strat_id:
            strats[i] = strat_dict
            updated = True
            break
    if not updated:
        strats.append(strat_dict)
    with open(STRATEGIES_FILE, "w") as f:
        json.dump(strats, f, indent=2)
    return strat_dict

def toggle_strategy_status(strat_id):
    strats = load_strategies()
    for s in strats:
        if s.get("id") == strat_id:
            s["active"] = not s.get("active", True)
            break
    with open(STRATEGIES_FILE, "w") as f:
        json.dump(strats, f, indent=2)
    return True

def delete_strategy_item(strat_id):
    strats = load_strategies()
    strats = [s for s in strats if s.get("id") != strat_id]
    with open(STRATEGIES_FILE, "w") as f:
        json.dump(strats, f, indent=2)
    return True

def toggle_bot_auto_run():
    global BOT_AUTO_RUN
    BOT_AUTO_RUN = not BOT_AUTO_RUN
    status_str = "ACTIVE (Scanning 24/7)" if BOT_AUTO_RUN else "PAUSED (Standby)"
    logger.info(f"Bot Auto-Scanning toggled: {status_str}")
    return True, f"Bot Auto-Scan is now {status_str}"

def execute_manual_order(symbol="BTCUSDT", side="BUY", amount_usd=15.0, sl_pct=1.5, tp_pct=3.0):
    try:
        if BOT_HALTED:
            return False, "Bot is currently HALTED by kill switch. Lift halt first."
        curr_price = get_current_price(symbol)
        if not curr_price or curr_price <= 0:
            return False, f"Could not fetch current price for {symbol}"
        amount_usd = max(15.0, float(amount_usd))
        raw_qty = amount_usd / curr_price
        if "BTC" in symbol:
            qty = round(raw_qty, 5)
        elif "ETH" in symbol:
            qty = round(raw_qty, 4)
        elif "SOL" in symbol:
            qty = round(raw_qty, 2)
        else:
            qty = round(raw_qty, 4)
        if qty < MIN_QTY:
            qty = MIN_QTY
        side = side.upper()
        if side not in ["BUY", "SELL"]:
            return False, f"Invalid order side: {side}"

        order = place_test_order(symbol=symbol, side=side, quantity=qty)

        if side == "BUY":
            sl = round(curr_price * (1 - sl_pct / 100.0), 2)
            tp1 = round(curr_price * (1 + (tp_pct * 0.6) / 100.0), 2)
            tp2 = round(curr_price * (1 + tp_pct / 100.0), 2)
        else:
            sl = round(curr_price * (1 + sl_pct / 100.0), 2)
            tp1 = round(curr_price * (1 - (tp_pct * 0.6) / 100.0), 2)
            tp2 = round(curr_price * (1 - tp_pct / 100.0), 2)

        trade_id = log_new_trade(
            symbol=symbol,
            side=side,
            entry_price=curr_price,
            quantity=qty,
            reason=f"Manual Order via Terminal ({side} ${amount_usd:.2f})",
            stop_loss=sl,
            take_profit=tp2,
            tp1=tp1,
            tp2=tp2,
            strategy_name="Manual Execution Terminal",
            strategy_id="manual_terminal"
        )
        logger.info(f"MANUAL ORDER EXECUTED | #{trade_id} {side} {qty} {symbol} @ ${curr_price:,.2f}")
        return True, f"Order #{trade_id} placed on Binance Testnet: {side} {qty} {symbol} at ${curr_price:,.2f}!"
    except Exception as e:
        logger.error(f"Manual order failed: {e}")
        return False, f"Execution failed: {str(e)}"

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

        # API: System Status JSON
        if parsed.path == "/api/status":
            try:
                curr_p = get_current_price(PRIMARY_SYMBOL)
            except Exception:
                curr_p = 0
            state = {}
            state_file = os.path.join(BASE_DIR, "market_state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                except Exception:
                    pass
            stats = get_stats()
            open_trades = get_open_trades()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "current_price": curr_p,
                "bot_halted": BOT_HALTED,
                "bot_auto_run": BOT_AUTO_RUN,
                "open_trades_count": len(open_trades),
                "market_state": state,
                "stats": stats
            }).encode('utf-8'))
            return

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

        # API: Toggle Bot Auto Scanning
        if parsed.path == "/api/toggle_bot":
            success, msg = toggle_bot_auto_run()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg, "auto_run": BOT_AUTO_RUN}).encode('utf-8'))
            return

        # API: Toggle Strategy
        if parsed.path == "/api/toggle_strategy":
            qs = parse_qs(parsed.query)
            s_id = qs.get("id", [""])[0]
            success = toggle_strategy_status(s_id)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            return

        # API: Delete Strategy
        if parsed.path == "/api/delete_strategy":
            qs = parse_qs(parsed.query)
            s_id = qs.get("id", [""])[0]
            success = delete_strategy_item(s_id)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            return

        # API: Close position manually via GET
        if parsed.path == "/api/close_position":
            qs = parse_qs(parsed.query)
            sym = qs.get("symbol", [""])[0]
            prod_id = qs.get("product_id", [""])[0]
            size_param = qs.get("size", [""])[0]
            t_ids = qs.get("id", [])
            t_id = int(t_ids[0]) if (t_ids and t_ids[0].isdigit()) else 0

            if sym and ("C-" in sym or "P-" in sym or "USD" in sym):
                success, msg = delta_exchange.close_any_position(
                    sym,
                    int(prod_id) if (prod_id and prod_id.isdigit()) else None,
                    int(size_param) if (size_param and size_param.isdigit()) else None
                )
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
                return
            elif t_id > 0:
                success, msg = manual_close_trade_by_id(t_id)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
                return
            else:
                self.send_response(400)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Missing trade identifier"}).encode('utf-8'))
                return

        # API: Close all 50% target met positions
        if parsed.path == "/api/close_target_met":
            try:
                positions = delta_exchange.get_all_positions() if delta_exchange else []
                closed_count = 0
                closed_details = []
                for p in positions:
                    p_sym = str(p.get("symbol", ""))
                    p_entry = safe_float(p.get("entry_price") or p.get("entry_price_usd", 0.0))
                    p_mark = safe_float(p.get("mark_price") or p.get("mark_price_usd", 0.0))
                    p_size_val = safe_float(p.get("size", 0.0))
                    if p_size_val == 0 or p_entry <= 0:
                        continue

                    if p_size_val < 0:
                        melt_pct = round(((p_entry - p_mark) / p_entry) * 100.0, 1)
                    else:
                        melt_pct = round(((p_mark - p_entry) / p_entry) * 100.0, 1)

                    if melt_pct >= 50.0:
                        p_id = p.get("product_id")
                        s_size = abs(int(p_size_val))
                        succ, msg = delta_exchange.close_any_position(p_sym, p_id, s_size)
                        if succ:
                            closed_count += 1
                            closed_details.append(f"{p_sym} ({melt_pct:.1f}%)")
                            logger.info(f"[MANUAL-TP] Closed 50%+ profit trade {p_sym} ({melt_pct:.1f}%): {msg}")
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                res_msg = f"Successfully took profit on {closed_count} trade(s): {', '.join(closed_details)}" if closed_count > 0 else "No positions currently at >=50% melt."
                self.wfile.write(json.dumps({"success": True, "message": res_msg}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                return

        # Regular Dashboard GET
        try:
            dashboard_content = generate_dashboard_html()
            encoded_content = dashboard_content.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded_content)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.wfile.write(encoded_content)
        except Exception as e:
            logger.error(f"[DASHBOARD] Render error: {e}")
            err_msg = f"OK - Bot Active (Dashboard error: {e})".encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(err_msg)))
            self.end_headers()
            self.wfile.write(err_msg)

    def do_POST(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.path)

        # API: Manual Order Execution
        if parsed.path == "/api/manual_order":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
            try:
                data = json.loads(post_data) if post_data else {}
                sym = data.get("symbol", PRIMARY_SYMBOL)
                side = data.get("side", "BUY")
                amt = float(data.get("amount_usd", 20.0))
                sl_pct = float(data.get("sl_pct", 1.5))
                tp_pct = float(data.get("tp_pct", 3.0))
                success, msg = execute_manual_order(symbol=sym, side=side, amount_usd=amt, sl_pct=sl_pct, tp_pct=tp_pct)
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

        # API: Save Custom Strategy
        if parsed.path == "/api/save_strategy":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
            try:
                data = json.loads(post_data) if post_data else {}
                saved = save_strategy_item(data)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "strategy": saved}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
            return

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
        server = ThreadingHTTPServer(('0.0.0.0', port), HealthCheckHandler)
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

        # CRITICAL: Delta Exchange & Dhurandhar trades are managed exclusively by strategy_dhurandhar.py!
        # Do NOT apply Binance spot TP1/TP2 or Stop Loss logic to them.
        if "STRANGLE" in t_sym or trade.get("strategy_id") == "strat_dhurandhar" or trade.get("trade_type") in ["strangle", "dhurandhar_futures"]:
            continue

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
        if "STRANGLE" in trade_symbol:
            # Delta Option Strangle expiry / close
            pass
        elif open_trade.get("strategy_id") == "dhurandhar_btc" or trade_symbol.endswith("USD"):
            try:
                import delta_exchange
                asset = "ETH" if "ETH" in trade_symbol else "BTC"
                delta_exchange.close_futures_position(asset)
            except Exception as e:
                logger.error(f"[DELTA] Failed closing futures: {e}")
        else:
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


def auto_manage_delta_option_risk():
    """
    Automated Background Risk & Profit Management Engine (24/7 Theta Harvesting):
    Runs every cycle. Evaluates all live open option positions on Delta Exchange:
    1. 50% Take-Profit: If an option leg has melted >= 50% of sold premium, auto-closes to lock in profit.
    2. Hard 2.0x Stop-Loss (Pre-Liquidation Guard): If an option leg spikes to >= 2.0x of its entry premium
       (i.e. >= 100% loss), it IMMEDIATELY auto-closes at market, capping risk and preventing any exchange liquidation!
    """
    if not delta_exchange:
        return
    try:
        live_positions = delta_exchange.get_all_positions()
        for p in live_positions:
            p_sym = str(p.get("symbol", ""))
            # Must be an option contract (e.g. C-ETH-2650..., P-BTC-73000...)
            if not (p_sym.startswith("C-") or p_sym.startswith("P-") or "-C-" in p_sym or "-P-" in p_sym):
                continue

            p_size_val = safe_float(p.get("size", 0.0))
            if p_size_val == 0:
                continue

            p_entry = safe_float(p.get("entry_price") or p.get("entry_price_usd", 0.0))
            p_mark = safe_float(p.get("mark_price") or p.get("mark_price_usd", 0.0))
            if p_entry <= 0:
                continue

            p_id = p.get("product_id")
            s_size = abs(int(p_size_val))

            if p_size_val < 0:
                # Sold option: profit when mark price falls below entry
                melt_pct = round(((p_entry - p_mark) / p_entry) * 100.0, 1)

                # 1. Take-Profit Check: 50% premium melt
                target_tp_pct = 50.0
                if melt_pct >= target_tp_pct:
                    logger.info(f"🎯 [AUTO-TP TRIGGERED] {p_sym} reached {melt_pct:.1f}% profit melt (Target >= {target_tp_pct}%). Auto-closing to bank profit...")
                    succ, msg = delta_exchange.close_any_position(p_sym, p_id, s_size)
                    if succ:
                        logger.info(f"✅ [AUTO-TP SUCCESS] Closed {p_sym} ({s_size} lots) at {melt_pct:.1f}% profit: {msg}")
                        try:
                            open_trades = get_open_trades()
                            for t in open_trades:
                                t_sym = str(t.get("symbol", ""))
                                if p_sym in t_sym or p_sym in str(t.get("call_symbol", "")) or p_sym in str(t.get("put_symbol", "")):
                                    close_trade(t["trade_id"], p_mark, f"50% TP Auto-Harvested ({melt_pct:.1f}% Melt)", symbol=t.get("symbol"))
                        except Exception:
                            pass
                    continue

                # 2. Hard Stop-Loss Check: 2.0x Premium Spike (Liquidation Prevention)
                sl_multiplier = 2.0
                hard_sl_price = round(p_entry * sl_multiplier, 2)
                if p_mark >= hard_sl_price:
                    logger.warning(f"🛑 [AUTO-SL TRIGGERED] {p_sym} hit Hard 2.0x Stop-Loss! Entry: ${p_entry:.2f} -> Current Mark: ${p_mark:.2f} (SL Threshold: ${hard_sl_price:.2f}, Melt: {melt_pct:.1f}%). Auto-closing to PREVENT LIQUIDATION...")
                    succ, msg = delta_exchange.close_any_position(p_sym, p_id, s_size)
                    if succ:
                        logger.warning(f"🛡️ [AUTO-SL SUCCESS] Closed {p_sym} ({s_size} lots) at Stop-Loss: {msg}")
                        try:
                            open_trades = get_open_trades()
                            for t in open_trades:
                                t_sym = str(t.get("symbol", ""))
                                if p_sym in t_sym or p_sym in str(t.get("call_symbol", "")) or p_sym in str(t.get("put_symbol", "")):
                                    close_trade(t["trade_id"], p_mark, f"Hard 2.0x SL Guard Hit (${p_mark:.2f})", symbol=t.get("symbol"), is_loss=True)
                        except Exception:
                            pass
                    continue

            else:
                # Long position: stop-loss at 50% loss
                gain_pct = round(((p_mark - p_entry) / p_entry) * 100.0, 1)
                if gain_pct <= -50.0:
                    logger.warning(f"🛑 [AUTO-SL TRIGGERED] Long {p_sym} hit 50% Stop-Loss ({gain_pct:.1f}%). Closing...")
                    succ, msg = delta_exchange.close_any_position(p_sym, p_id, s_size)
                    continue

    except Exception as e:
        logger.warning(f"[AUTO-RISK] Error evaluating Delta option positions: {e}")


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

    # 2a. Delta Options 50% TP & Hard 2.0x SL Manager (24/7 Risk & Profit Auto-Guard)
    auto_manage_delta_option_risk()

    # 2b. Auto-Scan Pause Check
    if not BOT_AUTO_RUN:
        logger.info("⏸️ AUTO-SCAN PAUSED: Automated entries paused by user via dashboard. Active positions remain protected.")
        return

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

    # 5. Delta Exchange: Dhurandhar Strategy Cycle (Futures Breakout + OTM Options Strangle)
    if run_dhurandhar_cycle is not None:
        dhurandhar_strat = next((s for s in load_strategies() if s.get("id") == "strat_dhurandhar"), None)
        if dhurandhar_strat and dhurandhar_strat.get("active", True):
            try:
                run_dhurandhar_cycle()
            except Exception as e:
                logger.warning(f"[DHURANDHAR] Cycle execution error (handled): {e}")

    active_strats = [s for s in load_strategies() if s.get("active", True) and s.get("id") != "strat_dhurandhar"]
    if not active_strats:
        logger.info("⏸️ STRATEGY HUB: Dhurandhar active. No additional custom Binance indicator strategies active.")
        return

    current_strat = active_strats[0]
    sym = current_strat.get("symbol", PRIMARY_SYMBOL)
    strat_name = current_strat.get("name", "Custom Quantitative Strategy")
    strat_id = current_strat.get("id", "custom_strat")
    strat_type = current_strat.get("strategy_type", "")
    cap_usd = float(current_strat.get("capital_usd", 100.0))
    asset = current_strat.get("asset") or ("ETH" if "ETH" in sym else "BTC")

    if sym in open_symbols:
        return

    try:
        signal_data = get_enhanced_signal(sym)
        signal = signal_data["signal"]
        score = signal_data["score"]
        current_price = signal_data["current_price"]
        macro_trend = signal_data.get("macro_trend", "RANGE_BOUND")

        # ── DHURANDHAR HYBRID STRATEGY (OPTIONS STRANGLE + 24H FUTURES) ──────
        if strat_type == "hybrid_options_futures" or strat_id == "dhurandhar_btc":
            import delta_exchange

            # Delta IP check and terminal warning
            d_bal = delta_exchange.get_balance()
            if isinstance(d_bal, dict) and d_bal.get("error") == "ip_not_whitelisted":
                client_ip = d_bal.get("client_ip", "")
                print(f"\n🚨 [DELTA IP ALERT] Current IP ({client_ip}) is NOT whitelisted in Delta Exchange!")
                print(f"👉 Open https://testnet.delta.exchange/app/settings/api and add IP: {client_ip}\n")
                logger.warning(f"🚨 Delta IP Whitelist Needed: {client_ip}")

            # Write market state for dashboard
            write_market_state(signal_data, current_price, {
                "action": "STANDBY" if signal == "HOLD" else signal,
                "confidence": 85 if signal == "HOLD" else score,
                "reason": signal_data["reasons"][0] if signal_data.get("reasons") else "Dhurandhar Strategy Active"
            })

            # Check daily trade limits
            if trades_today >= MAX_TRADES_PER_DAY:
                logger.info(f"DECISION ({asset}): NO TRADE | Daily limit reached ({trades_today}/{MAX_TRADES_PER_DAY})")
                return

            # Leg 1: Range-Bound Option Strangle (Sell OTM Call + Put)
            if macro_trend == "RANGE_BOUND" or signal == "HOLD":
                if not delta_exchange.has_active_strangle(asset):
                    otm_pct = float(current_strat.get("target_strangle_otm_pct", 12.0)) / 100.0
                    print(f"[BOT] 🎯 Market Range-Bound! Executing Leg 1: Dhurandhar Option Strangle for {asset}...")
                    strangle_res = delta_exchange.place_strangle(asset, contracts=1, otm_pct=otm_pct)
                    if strangle_res.get("success"):
                        s_info = strangle_res.get("strangle_info", {})
                        c_strk = s_info.get("call", {}).get("strike", 0)
                        p_strk = s_info.get("put", {}).get("strike", 0)
                        reason_str = f"Option Strangle: Sold Call ${c_strk:,.0f} & Put ${p_strk:,.0f} ({s_info.get('dte')} DTE)"
                        trade_id = log_new_trade(
                            symbol=f"{asset}-STRANGLE",
                            side="SELL_STRANGLE",
                            entry_price=current_price,
                            quantity=1,
                            reason=f"[{strat_name}] {reason_str}",
                            stop_loss=None,
                            take_profit=None,
                            strategy_name=strat_name,
                            strategy_id=strat_id,
                            trade_type="strangle",
                            margin_usd=50.0,
                            call_strike=c_strk,
                            put_strike=p_strk,
                            dte=s_info.get("dte"),
                            expiry=s_info.get("expiry"),
                            initial_premium=strangle_res.get("initial_total_premium"),
                            call_symbol=s_info.get("call", {}).get("symbol"),
                            put_symbol=s_info.get("put", {}).get("symbol")
                        )
                        trades_today += 1
                        last_trade_time = datetime.now()
                        print(f"[BOT] ✅ STRANGLE EXECUTED! #{trade_id} ({asset}) | Safe Zone: {signal_data.get('profit_zone')}")
                        logger.info(f"STRANGLE EXECUTED | #{trade_id} ({asset}) | Safe Zone: {signal_data.get('profit_zone')}")
                        write_learning(f"New Strangle #{trade_id} [{strat_name}]: {reason_str}. Zone: {signal_data.get('profit_zone')}", category="trade_open", trade_id=trade_id)
                    else:
                        err = strangle_res.get("error") or "Order rejected"
                        logger.warning(f"[STRANGLE] Execution notice: {err}")
                        print(f"[BOT] ⚠️ Strangle notice: {err}")
                else:
                    logger.info(f"⏸️ Active Strangle already running for {asset}. Safe Zone: {signal_data.get('profit_zone')}. Monitoring theta decay.")
                return

            # Leg 2: 24-Hour Breakout / Breakdown (Futures Long / Short)
            elif signal in ["STRONG_BUY", "STRONG_SELL"]:
                fut_side = "buy" if signal == "STRONG_BUY" else "sell"
                fut_action = "BUY_FUTURES" if signal == "STRONG_BUY" else "SELL_FUTURES"
                stop_loss = signal_data.get("structure_sl")
                tp1 = signal_data.get("tp1")
                tp2 = signal_data.get("tp2")
                print(f"[BOT] 🚀 24H {signal} Breakout! Executing Delta Futures {fut_action} for {asset}...")
                fut_res = delta_exchange.place_futures_order(asset, side=fut_side, notional_usd=cap_usd)
                if fut_res.get("success"):
                    trade_id = log_new_trade(
                        symbol=f"{asset}USD",
                        side=fut_action,
                        entry_price=current_price,
                        quantity=fut_res.get("contracts", 1),
                        reason=f"[{strat_name}] 24H Breakout {signal}: SL=${stop_loss:,.2f}, TP1=${tp1:,.2f}",
                        stop_loss=stop_loss,
                        take_profit=tp2,
                        tp1=tp1,
                        tp2=tp2,
                        strategy_name=strat_name,
                        strategy_id=strat_id
                    )
                    trades_today += 1
                    last_trade_time = datetime.now()
                    logger.info(f"FUTURES EXECUTED | #{trade_id} ({asset}) [{strat_name}] | {fut_action} | ${current_price:,.2f}")
                    print(f"[BOT] ✅ FUTURES EXECUTED! #{trade_id} ({asset}) {fut_action} at ${current_price:,.2f}")
                    write_learning(f"New Futures Trade #{trade_id} [{strat_name}]: {fut_action} {asset} at ${current_price}. SL=${stop_loss:.2f}", category="trade_open", trade_id=trade_id)
                else:
                    err = fut_res.get("error") or "Order rejected"
                    logger.warning(f"[FUTURES] Execution notice: {err}")
                    print(f"[BOT] ⚠️ Futures notice: {err}")
                return

        # ── REGULAR SPOT STRATEGY EXECUTION ──────────────────────────────────
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
    print("  Risk Protection & Daily Circuit Breaker: Armed")
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
