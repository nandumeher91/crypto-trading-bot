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
  --bg-pitch: #030206;
  --bg-surface: #030206;
  --bg-card: #030206;
  --border-subtle: rgba(168, 85, 247, 0.22);
  --border-glow: rgba(217, 70, 239, 0.48);
  --purple-accent: #a855f7;
  --magenta-accent: #d946ef;
  --purple-gradient: linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background-color: var(--bg-pitch);
  color: #f1f5f9;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  margin: 0;
  padding: 0;
  overflow-x: hidden;
  line-height: 1.5;
}

.nexora-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  position: relative;
  overflow: hidden;
}

/* Cursor Spotlight Border - ONLY illuminates the border area within cursor proximity */
.nexora-card::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1.5px;
  background: radial-gradient(
    250px circle at var(--mouse-x, -999px) var(--mouse-y, -999px),
    rgba(217, 70, 239, 0.95) 0%,
    rgba(168, 85, 247, 0.52) 35%,
    rgba(147, 51, 234, 0.12) 65%,
    transparent 80%
  );
  -webkit-mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  opacity: var(--spotlight-opacity, 0);
  transition: opacity 0.25s ease;
  z-index: 2;
}

/* Subtle ambient spotlight sheen inside card near cursor */
.nexora-card::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: radial-gradient(
    220px circle at var(--mouse-x, -999px) var(--mouse-y, -999px),
    rgba(168, 85, 247, 0.05) 0%,
    transparent 75%
  );
  pointer-events: none;
  opacity: var(--spotlight-opacity, 0);
  transition: opacity 0.25s ease;
  z-index: 1;
}

/* ========================================================
   PREMIUM LIQUID GLASS INTERACTION (Pure Optics, No Card Pop)
   ======================================================== */

/* Water Droplet Impact Glint at touch origin */
.water-drop-glint {
  position: absolute;
  width: 24px;
  height: 24px;
  pointer-events: none;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(0.2);
  background: radial-gradient(circle, #ffffff 10%, rgba(232, 121, 249, 0.85) 45%, rgba(56, 189, 248, 0.4) 75%, transparent 100%);
  filter: blur(2px);
  mix-blend-mode: screen;
  animation: waterGlintBloom 0.38s cubic-bezier(0.12, 0.9, 0.25, 1) forwards;
  z-index: 12;
}

@keyframes waterGlintBloom {
  0% {
    transform: translate(-50%, -50%) scale(0.2);
    opacity: 1;
  }
  40% {
    transform: translate(-50%, -50%) scale(1.6);
    opacity: 0.85;
  }
  100% {
    transform: translate(-50%, -50%) scale(2.4);
    opacity: 0;
  }
}

/* Real Liquid Caustic Wave (Chromatic water refraction on dark glass) */
.water-caustic-wave {
  position: absolute;
  width: 280px;
  height: 280px;
  pointer-events: none;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(0.1);
  background: radial-gradient(
    circle,
    rgba(255, 255, 255, 0.28) 0%,
    rgba(232, 121, 249, 0.22) 28%,
    rgba(168, 85, 247, 0.12) 50%,
    rgba(56, 189, 248, 0.08) 68%,
    transparent 82%
  );
  filter: blur(12px);
  mix-blend-mode: screen;
  animation: waterCausticSpread 0.72s cubic-bezier(0.12, 0.88, 0.22, 1) forwards;
  z-index: 10;
}

@keyframes waterCausticSpread {
  0% {
    transform: translate(-50%, -50%) scale(0.1);
    opacity: 0.95;
  }
  35% {
    opacity: 0.75;
  }
  100% {
    transform: translate(-50%, -50%) scale(1.5);
    opacity: 0;
  }
}

/* Soft Liquid Meniscus Surface Tension (NO hard rings, purely blurred liquid rim) */
.water-surface-meniscus {
  position: absolute;
  width: 220px;
  height: 220px;
  pointer-events: none;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(0.12);
  box-shadow: inset 0 0 16px rgba(232, 121, 249, 0.3), 0 0 20px rgba(56, 189, 248, 0.18);
  filter: blur(6px);
  animation: waterMeniscusSpread 0.68s cubic-bezier(0.14, 0.85, 0.25, 1) forwards;
  z-index: 11;
}

@keyframes waterMeniscusSpread {
  0% {
    transform: translate(-50%, -50%) scale(0.12);
    opacity: 0.9;
  }
  30% {
    opacity: 0.65;
  }
  100% {
    transform: translate(-50%, -50%) scale(1.35);
    opacity: 0;
  }
}

.btn-glow-purple {
  background: var(--purple-gradient);
  color: #ffffff;
  font-weight: 600;
  border-radius: 10px;
  box-shadow: 0 4px 18px rgba(168, 85, 247, 0.35);
  transition: all 0.2s ease;
  cursor: pointer;
  border: none;
  user-select: none;
}
.btn-glow-purple:hover {
  box-shadow: 0 6px 26px rgba(217, 70, 239, 0.55);
  transform: translateY(-1px);
}
.btn-glow-purple:active {
  /* no click animation */
}

/* ========================================================
   FROSTED GLASS ICONS & GLASS BUTTON CONTROLS
   ======================================================== */
.glass-icon-tile {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(168, 85, 247, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.14), 0 4px 14px rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(10px);
  transition: all 0.25s ease;
  flex-shrink: 0;
}
.glass-icon-tile:hover {
  border-color: rgba(217, 70, 239, 0.5);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.22), 0 0 16px rgba(168, 85, 247, 0.35);
  transform: translateY(-1px);
}
.glass-icon-tile svg {
  width: 18px;
  height: 18px;
}

/* Glass Status Badge */
.glass-status-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(168, 85, 247, 0.22);
  font-size: 11px;
  font-family: monospace;
  backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.08);
}

/* Glass Ruby Button (Kill Switch) */
.glass-btn-ruby {
  padding: 7px 15px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border-radius: 9px;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.45);
  color: #fca5a5;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 7px;
  backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.15), 0 2px 10px rgba(239, 68, 68, 0.2);
  transition: all 0.2s ease;
}
.glass-btn-ruby:hover {
  background: rgba(239, 68, 68, 0.22);
  border-color: rgba(239, 68, 68, 0.7);
  color: #ffffff;
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.25), 0 0 18px rgba(239, 68, 68, 0.45);
  transform: translateY(-1px);
}

/* Glass Purple Button (Strategy Engine) */
.glass-btn-purple {
  padding: 7px 16px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border-radius: 9px;
  background: linear-gradient(135deg, rgba(217, 70, 239, 0.22) 0%, rgba(147, 51, 234, 0.28) 100%);
  border: 1px solid rgba(217, 70, 239, 0.45);
  color: #ffffff;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 7px;
  backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.2), 0 2px 14px rgba(168, 85, 247, 0.3);
  transition: all 0.2s ease;
}
.glass-btn-purple:hover {
  background: linear-gradient(135deg, rgba(217, 70, 239, 0.38) 0%, rgba(147, 51, 234, 0.48) 100%);
  border-color: rgba(232, 121, 249, 0.7);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 0 22px rgba(217, 70, 239, 0.5);
  transform: translateY(-1px);
}

/* ========================================================
   PREMIUM MODE SWITCH CAPSULE (Smooth Gliding Slider)
   ======================================================== */
.glass-mode-switch-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  padding: 4px;
  border-radius: 12px;
  background: rgba(14, 10, 28, 0.85);
  border: 1px solid rgba(168, 85, 247, 0.25);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.6), 0 0 20px rgba(168, 85, 247, 0.15);
  backdrop-filter: blur(14px);
  user-select: none;
}

.mode-slider-thumb {
  position: absolute;
  top: 4px;
  bottom: 4px;
  border-radius: 8px;
  transition: all 0.32s cubic-bezier(0.16, 1, 0.3, 1);
  pointer-events: none;
  z-index: 1;
}

.mode-slider-thumb.mode-test-pos {
  left: 4px;
  width: calc(50% - 4px);
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.22) 0%, rgba(217, 119, 6, 0.35) 100%);
  border: 1px solid rgba(251, 191, 36, 0.6);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.25), 0 0 16px rgba(251, 191, 36, 0.35);
  backdrop-filter: blur(8px);
}

.mode-slider-thumb.mode-main-pos {
  left: 50%;
  width: calc(50% - 4px);
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.22) 0%, rgba(5, 150, 105, 0.35) 100%);
  border: 1px solid rgba(52, 211, 153, 0.6);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.25), 0 0 16px rgba(16, 185, 129, 0.35);
  backdrop-filter: blur(8px);
}

.mode-switch-btn {
  position: relative;
  z-index: 2;
  padding: 6px 16px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  background: transparent;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: color 0.25s ease;
  white-space: nowrap;
}

.mode-switch-btn.active-test {
  color: #fbbf24;
}

.mode-switch-btn.active-main {
  color: #34d399;
}

.mode-switch-btn.inactive {
  color: #64748b;
}

.mode-switch-btn.inactive:hover {
  color: #cbd5e1;
}

.mode-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  transition: all 0.25s ease;
}

.mode-dot.dot-test {
  background: #fbbf24;
  box-shadow: 0 0 8px #fbbf24;
}

.mode-dot.dot-main {
  background: #34d399;
  box-shadow: 0 0 8px #34d399;
}

.mode-switch-btn.inactive .mode-dot {
  background: #475569;
  box-shadow: none;
}

.mode-subtext {
  font-size: 10px;
  font-weight: normal;
  opacity: 0.8;
}

/* Floating Glass Toast Notification */
.glass-toast {
  position: fixed;
  top: 72px;
  right: 24px;
  z-index: 99999;
  padding: 12px 20px;
  border-radius: 12px;
  background: rgba(14, 10, 28, 0.92);
  border: 1px solid rgba(52, 211, 153, 0.45);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6), 0 0 20px rgba(16, 185, 129, 0.25);
  backdrop-filter: blur(16px);
  color: #f1f5f9;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  transform: translateY(-20px);
  opacity: 0;
  transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
  pointer-events: none;
}
.glass-toast.show {
  transform: translateY(0);
  opacity: 1;
}

/* Crossfade transitions for dashboard mode switch */
#view-dashboard, #env-banner {
  transition: opacity 0.22s ease, filter 0.22s ease;
}
.mode-fade-out {
  opacity: 0.25 !important;
  filter: blur(4px) !important;
}

.toggle-switch {
  position: relative;
  width: 38px;
  height: 20px;
  background: #1f1b36;
  border-radius: 9999px;
  cursor: pointer;
  transition: background 0.2s ease;
  border: 1px solid rgba(168, 85, 247, 0.2);
  display: inline-block;
}
.toggle-switch.active {
  background: linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%);
  border-color: #d946ef;
  box-shadow: 0 0 10px rgba(217, 70, 239, 0.4);
}
.toggle-handle {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  background: #ffffff;
  border-radius: 9999px;
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.toggle-switch.active .toggle-handle {
  transform: translateX(18px);
}

.ambient-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(120px);
  pointer-events: none;
  z-index: 0;
}

::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
::-webkit-scrollbar-track {
  background: #030206;
}
::-webkit-scrollbar-thumb {
  background: #231c3d;
  border-radius: 4px;
}
"""

DASHBOARD_JS = """
let currentMode = 'main';

function toggleSwitch(el) {
  el.classList.toggle('active');
}

function changePnlTimeframe(tf, val, btn) {
  const pnlDisp = document.getElementById('pnl-display-val');
  if (pnlDisp) {
    pnlDisp.innerHTML = val + ' <span style="font-size:12px; color:#94a3b8; font-weight:normal;">Realized Profit (' + tf.toUpperCase() + ')</span>';
  }
  const buttons = btn.parentElement.querySelectorAll('button');
  buttons.forEach(b => {
    b.style.background = 'transparent';
    b.style.color = '#94a3b8';
    b.style.fontWeight = 'normal';
    b.style.boxShadow = 'none';
  });
  btn.style.background = 'linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%)';
  btn.style.color = '#ffffff';
  btn.style.fontWeight = 'bold';
  btn.style.boxShadow = '0 0 12px rgba(217, 70, 239, 0.5)';
}

let currentNavTab = 'dashboard';

function switchNavTab(tabName) {
  currentNavTab = tabName;
  const tabs = ['dashboard', 'strategies', 'portfolio', 'settings'];
  tabs.forEach(t => {
    const el = document.getElementById('view-' + t);
    const link = document.getElementById('nav-link-' + t);
    if (el) el.style.display = (t === tabName) ? 'block' : 'none';
    if (link) {
      if (t === tabName) {
        link.style.color = '#ffffff';
        link.style.borderBottom = '2px solid #d946ef';
        link.style.paddingBottom = '4px';
      } else {
        link.style.color = '#94a3b8';
        link.style.borderBottom = 'none';
        link.style.paddingBottom = '0px';
      }
    }
  });
  window.location.hash = tabName;
}

let _testnetCache = null;
function cacheTestnetData() {
  if (_testnetCache) return;
  const tbody = document.getElementById('trade-history-tbody');
  const pnlVal = document.getElementById('card-pnl-val');
  const pnlFooter = document.getElementById('card-pnl-footer');
  const capVal = document.getElementById('card-cap-val');
  const capFooter = document.getElementById('card-cap-footer');
  const wrVal = document.getElementById('card-wr-val');
  const wrSub = document.getElementById('card-wr-sub');
  const wrSvg = document.getElementById('card-wr-svg-circle');
  const wrBadge = document.getElementById('card-wr-pct-badge');
  const balVal = document.getElementById('card-balance-val');
  const balFooter = document.getElementById('card-balance-footer');
  const pnlDisplayVal = document.getElementById('pnl-display-val');
  const historySubtitle = document.getElementById('history-subtitle');
  const historyPills = document.getElementById('history-pills');
  const consoleSubtitle = document.getElementById('console-subtitle');
  const portUsdtVal = document.getElementById('port-usdt-val');
  const portUsdtSub = document.getElementById('port-usdt-sub');
  const portBtcVal = document.getElementById('port-btc-val');
  const portEthVal = document.getElementById('port-eth-val');
  const portMarginVal = document.getElementById('port-margin-val');
  const portMarginSub = document.getElementById('port-margin-sub');

  _testnetCache = {
    tbody: tbody ? tbody.innerHTML : '',
    pnlVal: pnlVal ? pnlVal.innerHTML : '',
    pnlFooter: pnlFooter ? pnlFooter.innerHTML : '',
    capVal: capVal ? capVal.innerHTML : '',
    capFooter: capFooter ? capFooter.innerHTML : '',
    wrVal: wrVal ? wrVal.innerHTML : '',
    wrSub: wrSub ? wrSub.innerHTML : '',
    wrDash: wrSvg ? wrSvg.getAttribute('stroke-dasharray') : '47, 88',
    wrBadge: wrBadge ? wrBadge.innerHTML : '',
    balVal: balVal ? balVal.innerHTML : '',
    balFooter: balFooter ? balFooter.innerHTML : '',
    pnlDisplayVal: pnlDisplayVal ? pnlDisplayVal.innerHTML : '',
    historySubtitle: historySubtitle ? historySubtitle.innerHTML : '',
    historyPills: historyPills ? historyPills.innerHTML : '',
    consoleSubtitle: consoleSubtitle ? consoleSubtitle.innerHTML : '',
    portUsdtVal: portUsdtVal ? portUsdtVal.innerHTML : '',
    portUsdtSub: portUsdtSub ? portUsdtSub.innerHTML : '',
    portBtcVal: portBtcVal ? portBtcVal.innerHTML : '',
    portEthVal: portEthVal ? portEthVal.innerHTML : '',
    portMarginVal: portMarginVal ? portMarginVal.innerHTML : '',
    portMarginSub: portMarginSub ? portMarginSub.innerHTML : ''
  };
}

function applyConsoleModeTheme(mode) {
  currentMode = mode;
  try { localStorage.setItem('nexora_mode', mode); } catch(e){}
  cacheTestnetData();
  
  const mainBtn = document.getElementById('mode-main-btn');
  const testBtn = document.getElementById('mode-test-btn');
  const envBanner = document.getElementById('env-banner');
  const engineText = document.getElementById('engine-status-text');
  const engineDot = document.getElementById('engine-status-dot');
  const balLabel = document.getElementById('card-balance-label');
  const balVal = document.getElementById('card-balance-val');
  const balFooter = document.getElementById('card-balance-footer');
  const pnlLabel = document.getElementById('card-pnl-label');
  const pnlVal = document.getElementById('card-pnl-val');
  const pnlFooter = document.getElementById('card-pnl-footer');
  const capLabel = document.getElementById('card-cap-label');
  const capVal = document.getElementById('card-cap-val');
  const capFooter = document.getElementById('card-cap-footer');
  const wrVal = document.getElementById('card-wr-val');
  const wrSub = document.getElementById('card-wr-sub');
  const wrSvg = document.getElementById('card-wr-svg-circle');
  const wrBadge = document.getElementById('card-wr-pct-badge');
  const pnlDisplayVal = document.getElementById('pnl-display-val');
  const historySubtitle = document.getElementById('history-subtitle');
  const historyPills = document.getElementById('history-pills');
  const tbody = document.getElementById('trade-history-tbody');
  const consoleSubtitle = document.getElementById('console-subtitle');
  const portUsdtVal = document.getElementById('port-usdt-val');
  const portUsdtSub = document.getElementById('port-usdt-sub');
  const portBtcVal = document.getElementById('port-btc-val');
  const portEthVal = document.getElementById('port-eth-val');
  const portMarginVal = document.getElementById('port-margin-val');
  const portMarginSub = document.getElementById('port-margin-sub');

  const sliderThumb = document.getElementById('mode-slider-thumb');
  if (sliderThumb) {
    sliderThumb.className = mode === 'main' ? 'mode-slider-thumb mode-main-pos' : 'mode-slider-thumb mode-test-pos';
  }
  if (mainBtn && testBtn) {
    if (mode === 'main') {
      mainBtn.className = 'mode-switch-btn active-main';
      testBtn.className = 'mode-switch-btn inactive';
    } else {
      testBtn.className = 'mode-switch-btn active-test';
      mainBtn.className = 'mode-switch-btn inactive';
    }
  }

  if (mode === 'main') {
    // MAIN Mode: Vibrant Emerald Green Branding
    if (envBanner) {
      envBanner.style.background = 'rgba(16, 185, 129, 0.1)';
      envBanner.style.borderBottom = '1px solid rgba(16, 185, 129, 0.3)';
      envBanner.style.color = '#34d399';
      envBanner.innerHTML = '<div style="display:flex; align-items:center; gap:8px;"><span style="font-size:14px;">🟢</span><span><strong>BINANCE MAINNET (REAL ACCOUNT CONSOLE)</strong> — Live Binance Real Trading Environment</span></div><div style="display:flex; align-items:center; gap:12px;"><span style="color:#fbbf24; font-weight:bold;">⚠️ Real Binance API Keys Not Connected • Standby Mode</span></div>';
    }
    if (engineText) {
      engineText.innerText = 'MAINNET SPOT (Standby)';
      engineText.style.color = '#34d399';
    }
    if (engineDot) {
      engineDot.style.background = '#34d399';
      engineDot.style.boxShadow = '0 0 8px #34d399';
    }
    if (consoleSubtitle) {
      consoleSubtitle.innerText = 'Binance Mainnet Real Account Mode (Standby). Live orders will execute on real Binance once live API keys are configured in .env.';
    }

    // MAIN MODE DATA (Show zero/standby because Real API keys are not connected yet)
    if (pnlLabel) pnlLabel.innerText = 'Real Binance P&L';
    if (pnlVal) { pnlVal.innerText = '$0.00'; pnlVal.style.color = '#94a3b8'; }
    if (pnlFooter) pnlFooter.innerHTML = '<span style="color:#64748b; font-weight:bold;">0 Real Trades</span><span style="color:#64748b;">Standby Mode</span>';

    if (capLabel) capLabel.innerText = 'Real Allocated Capital';
    if (capVal) capVal.innerHTML = '₹0 <span style="font-size:12px; font-weight:normal; color:#94a3b8;">($0.00)</span>';
    if (capFooter) capFooter.innerHTML = '<span style="color:#64748b; font-weight:600;">Margin Used: $0.00 (0%)</span><span style="color:#fbbf24; font-weight:bold;">Real Keys Pending</span>';

    if (wrVal) wrVal.innerText = '0.0%';
    if (wrSub) wrSub.innerHTML = '<span style="color:#64748b;">0 Streak • 0 Real Trades</span>';
    if (wrSvg) wrSvg.setAttribute('stroke-dasharray', '0, 88');
    if (wrBadge) wrBadge.innerText = '0%';

    if (balLabel) balLabel.innerText = 'Binance Mainnet Balance';
    if (balVal) balVal.innerHTML = '$0.00 <span style="font-size:13px; font-weight:normal; color:#34d399;">USDT</span>';
    if (balFooter) balFooter.innerHTML = '<span style="color:#94a3b8;">Real API Keys Pending • 0.00 BTC • 0.00 ETH</span><span style="color:#34d399; font-weight:bold;">🟢 Mainnet Standby</span>';

    if (pnlDisplayVal) pnlDisplayVal.innerHTML = '$0.00 <span style="font-size:12px; color:#94a3b8; font-weight:normal;">Realized Profit (0 Real Trades)</span>';

    if (historySubtitle) historySubtitle.innerText = 'Audited against Binance Mainnet Spot Orders (0 Real Trades Executed)';
    if (historyPills) historyPills.innerHTML = '<span style="padding:4px 10px; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.25); border-radius:6px; color:#34d399;">Win Rate: 0.0% (0 Real Trades)</span><span style="padding:4px 10px; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.25); border-radius:6px; color:#34d399; font-weight:bold;">Real Realized: $0.00</span>';
    if (tbody) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:36px 20px; color:#94a3b8; background:rgba(16,185,129,0.03);"><div style="font-size:26px; margin-bottom:8px;">🟢</div><div style="font-size:15px; font-weight:bold; color:#ffffff;">No Real Binance Mainnet Trades Yet</div><div style="font-size:12px; color:#94a3b8; margin-top:6px; max-width:620px; margin-left:auto; margin-right:auto; line-height:1.5;">Real Binance API keys are currently not connected in .env. All existing 15 trades belong to <strong style="color:#fbbf24;">Binance Spot Testnet (Paper Sandbox)</strong>.<br>Switch back to <strong style="color:#fbbf24;">TEST</strong> mode above to view Testnet execution history and live paper analytics.</div></td></tr>';
    }

    if (portUsdtVal) portUsdtVal.innerText = '$0.00';
    if (portUsdtSub) portUsdtSub.innerText = 'Real API Keys Pending • Standby';
    if (portBtcVal) portBtcVal.innerText = '0.0000 BTC';
    if (portEthVal) portEthVal.innerText = '0.0000 ETH';
    if (portMarginVal) portMarginVal.innerText = '₹0';
    if (portMarginSub) portMarginSub.innerText = 'Real Account Standby';

  } else {
    // TEST Mode: Binance Spot Testnet (Paper Sandbox) - Amber/Gold Branding
    if (envBanner) {
      envBanner.style.background = 'rgba(251, 191, 36, 0.1)';
      envBanner.style.borderBottom = '1px solid rgba(251, 191, 36, 0.25)';
      envBanner.style.color = '#fbbf24';
      envBanner.innerHTML = '<div style="display:flex; align-items:center; gap:8px;"><span style="font-size:14px;">🟡</span><span><strong>BINANCE SPOT TESTNET (PAPER TRADING ACTIVE)</strong> — Virtual Zero-Risk Sandbox • Orders execute on Binance Spot Testnet</span></div><div style="display:flex; align-items:center; gap:12px;"><span style="color:#d8b4fe;">Simulated Live Feed</span><span style="color:#34d399; font-weight:bold;">$9,992.78 USDT Testnet Balance</span></div>';
    }
    if (engineText) {
      engineText.innerText = 'TESTNET SPOT';
      engineText.style.color = '#fbbf24';
    }
    if (engineDot) {
      engineDot.style.background = '#fbbf24';
      engineDot.style.boxShadow = '0 0 8px #fbbf24';
    }

    // RESTORE TESTNET DATA FROM CACHE
    if (_testnetCache) {
      if (consoleSubtitle) consoleSubtitle.innerHTML = _testnetCache.consoleSubtitle;
      if (pnlLabel) pnlLabel.innerText = 'Total Realized P&L';
      if (pnlVal) pnlVal.innerHTML = _testnetCache.pnlVal;
      if (pnlFooter) pnlFooter.innerHTML = _testnetCache.pnlFooter;
      if (capLabel) capLabel.innerText = 'Allocated Capital (Subscribed)';
      if (capVal) capVal.innerHTML = _testnetCache.capVal;
      if (capFooter) capFooter.innerHTML = _testnetCache.capFooter;
      if (wrVal) wrVal.innerHTML = _testnetCache.wrVal;
      if (wrSub) wrSub.innerHTML = _testnetCache.wrSub;
      if (wrSvg) wrSvg.setAttribute('stroke-dasharray', _testnetCache.wrDash);
      if (wrBadge) wrBadge.innerHTML = _testnetCache.wrBadge;
      if (balLabel) balLabel.innerText = 'Binance Testnet Balance';
      if (balVal) balVal.innerHTML = _testnetCache.balVal;
      if (balFooter) balFooter.innerHTML = _testnetCache.balFooter;
      if (pnlDisplayVal) pnlDisplayVal.innerHTML = _testnetCache.pnlDisplayVal;
      if (historySubtitle) historySubtitle.innerHTML = _testnetCache.historySubtitle;
      if (historyPills) historyPills.innerHTML = _testnetCache.historyPills;
      if (tbody) tbody.innerHTML = _testnetCache.tbody;
      if (portUsdtVal && _testnetCache.portUsdtVal) portUsdtVal.innerHTML = _testnetCache.portUsdtVal;
      if (portUsdtSub && _testnetCache.portUsdtSub) portUsdtSub.innerHTML = _testnetCache.portUsdtSub;
      if (portBtcVal && _testnetCache.portBtcVal) portBtcVal.innerHTML = _testnetCache.portBtcVal;
      if (portEthVal && _testnetCache.portEthVal) portEthVal.innerHTML = _testnetCache.portEthVal;
      if (portMarginVal && _testnetCache.portMarginVal) portMarginVal.innerHTML = _testnetCache.portMarginVal;
      if (portMarginSub && _testnetCache.portMarginSub) portMarginSub.innerHTML = _testnetCache.portMarginSub;
    }
  }
}

function showGlassToast(msg, icon) {
  let toast = document.getElementById('nexora-glass-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'nexora-glass-toast';
    toast.className = 'glass-toast';
    document.body.appendChild(toast);
  }
  toast.innerHTML = '<span style="font-size:16px;">' + (icon || '🟢') + '</span> <span>' + msg + '</span>';
  toast.classList.add('show');
  clearTimeout(window._toastTimeout);
  window._toastTimeout = setTimeout(() => {
    toast.classList.remove('show');
  }, 3500);
}

function switchConsoleMode(mode) {
  const currentMode = localStorage.getItem('nexora_mode') || 'test';
  if (currentMode === mode) return;

  const dashboardView = document.getElementById('view-dashboard');
  const envBanner = document.getElementById('env-banner');

  // Trigger smooth crossfade out
  if (dashboardView) dashboardView.classList.add('mode-fade-out');
  if (envBanner) envBanner.classList.add('mode-fade-out');

  // Slide slider thumb immediately with spring physics
  const sliderThumb = document.getElementById('mode-slider-thumb');
  const testBtn = document.getElementById('mode-test-btn');
  const mainBtn = document.getElementById('mode-main-btn');

  if (sliderThumb) {
    sliderThumb.className = mode === 'main' ? 'mode-slider-thumb mode-main-pos' : 'mode-slider-thumb mode-test-pos';
  }
  if (mode === 'main') {
    if (testBtn) testBtn.className = 'mode-switch-btn inactive';
    if (mainBtn) mainBtn.className = 'mode-switch-btn active-main';
    showGlassToast('Switched to Binance Mainnet Console (Standby Mode • Live API Keys Pending)', '🟢');
  } else {
    if (testBtn) testBtn.className = 'mode-switch-btn active-test';
    if (mainBtn) mainBtn.className = 'mode-switch-btn inactive';
    showGlassToast('Switched to Binance Spot Testnet (Paper Trading Active)', '🟡');
  }

  // Crossfade content smoothly after 180ms
  setTimeout(() => {
    applyConsoleModeTheme(mode);
    if (dashboardView) dashboardView.classList.remove('mode-fade-out');
    if (envBanner) envBanner.classList.remove('mode-fade-out');
  }, 180);
}

function switchStrategySubTab(subTab) {
  const subSectionSubscribed = document.getElementById('strat-sub-section-subscribed');
  const subSectionLab = document.getElementById('strat-sub-section-lab');
  const tabBtnSubscribed = document.getElementById('tab-btn-subscribed');
  const tabBtnLab = document.getElementById('tab-btn-lab');

  if (subTab === 'lab') {
    if (subSectionSubscribed) subSectionSubscribed.style.display = 'none';
    if (subSectionLab) subSectionLab.style.display = 'block';
    if (tabBtnLab) {
      tabBtnLab.style.background = 'linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%)';
      tabBtnLab.style.color = '#ffffff';
    }
    if (tabBtnSubscribed) {
      tabBtnSubscribed.style.background = 'transparent';
      tabBtnSubscribed.style.color = '#94a3b8';
    }
  } else {
    if (subSectionSubscribed) subSectionSubscribed.style.display = 'block';
    if (subSectionLab) subSectionLab.style.display = 'none';
    if (tabBtnSubscribed) {
      tabBtnSubscribed.style.background = 'linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%)';
      tabBtnSubscribed.style.color = '#ffffff';
    }
    if (tabBtnLab) {
      tabBtnLab.style.background = 'transparent';
      tabBtnLab.style.color = '#94a3b8';
    }
  }
}

function promptCustomizeCapital(stratId, currentCap) {
  const newCap = prompt("✏️ Enter custom capital limit (₹ INR) for this strategy:", currentCap);
  if (!newCap || isNaN(newCap) || parseFloat(newCap) <= 0) return;
  
  fetch('/api/strategies/update_params?id=' + encodeURIComponent(stratId) + '&cap=' + encodeURIComponent(newCap))
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ Strategy capital updated to ₹' + parseInt(newCap).toLocaleString('en-IN') + ' ($' + (parseFloat(newCap)/83.5).toFixed(2) + ' USD)!');
        window.location.reload();
      } else {
        alert('❌ Error updating capital: ' + data.message);
      }
    })
    .catch(err => alert('Network error: ' + err));
}

function saveStrategyParameters(stratId) {
  const cap = document.getElementById('lab-strat-cap') ? document.getElementById('lab-strat-cap').value : 10000;
  const tp1 = document.getElementById('lab-strat-tp1') ? document.getElementById('lab-strat-tp1').value : 1.5;
  const tp2 = document.getElementById('lab-strat-tp2') ? document.getElementById('lab-strat-tp2').value : 3.2;
  const sl = document.getElementById('lab-strat-sl') ? document.getElementById('lab-strat-sl').value : 0.8;
  const tf = document.getElementById('lab-strat-tf') ? document.getElementById('lab-strat-tf').value : '1h + 5m';
  const conf = document.getElementById('lab-strat-conf') ? document.getElementById('lab-strat-conf').value : 75;
  const fib = document.getElementById('lab-strat-fib') ? document.getElementById('lab-strat-fib').value : '0.618 - 0.786';

  const url = '/api/strategies/update_params?id=' + encodeURIComponent(stratId) +
    '&cap=' + encodeURIComponent(cap) +
    '&tp1=' + encodeURIComponent(tp1) +
    '&tp2=' + encodeURIComponent(tp2) +
    '&sl=' + encodeURIComponent(sl) +
    '&timeframe=' + encodeURIComponent(tf) +
    '&confluence=' + encodeURIComponent(conf) +
    '&fib=' + encodeURIComponent(fib);

  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ Institutional SMC Strategy parameters saved successfully! Live bot will execute with these updated targets.');
        window.location.reload();
      } else {
        alert('❌ Error saving parameters: ' + data.message);
      }
    })
    .catch(err => alert('Network error: ' + err));
}

function handleDeployAction() {
  switchNavTab('strategies');
  switchStrategySubTab('subscribed');
}

function saveEngineSettings() {
  const maxLoss = document.getElementById('setting-max-loss').value;
  const minConf = document.getElementById('setting-min-conf').value;
  const maxPos = document.getElementById('setting-max-pos').value;
  const cooldown = document.getElementById('setting-cooldown').value;
  const targetNotional = document.getElementById('setting-target-notional') ? document.getElementById('setting-target-notional').value : '100';

  const url = '/api/settings/update?max_loss=' + encodeURIComponent(maxLoss) +
    '&min_conf=' + encodeURIComponent(minConf) +
    '&max_pos=' + encodeURIComponent(maxPos) +
    '&cooldown=' + encodeURIComponent(cooldown) +
    '&target_notional=' + encodeURIComponent(targetNotional);

  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ ' + data.message);
        window.location.reload();
      } else {
        alert('❌ Error: ' + (data.message || data.error));
      }
    })
    .catch(err => alert('Network error: ' + err));
}

function syncLedgerFromBinance() {
  fetch('/api/sync_ledger')
    .then(r => r.json())
    .then(data => {
      alert(data.message || 'Ledger Synced!');
      window.location.reload();
    })
    .catch(err => alert('Network error: ' + err));
}

function promoteToLive(stratId, stratName) {
  if (!confirm('🚀 DEPLOY STRATEGY TO MAIN LIVE ENGINE?\\n\\nStrategy: ' + stratName + '\\nAllocated Capital Cap: ₹10,000 ($120.00)\\n\\nIs strategy ko real account me activate karein?')) {
    return;
  }
  fetch('/api/strategies/promote?id=' + encodeURIComponent(stratId) + '&cap=10000')
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('🎉 SUCCESS: ' + data.message);
        window.location.reload();
      } else {
        alert('❌ FAILED: ' + data.message);
      }
    })
    .catch(err => alert('Network error: ' + err));
}

function demoteToTest(stratId, stratName) {
  if (!confirm('Return "' + stratName + '" back to Testing Lab sandbox?')) return;
  fetch('/api/strategies/demote?id=' + encodeURIComponent(stratId))
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

function runSimulation(stratId, btn) {
  const oldText = btn.innerHTML;
  btn.innerHTML = '⏳ Simulating...';
  btn.disabled = true;
  fetch('/api/strategies/simulate?id=' + encodeURIComponent(stratId))
    .then(r => r.json())
    .then(data => {
      btn.innerHTML = oldText;
      btn.disabled = false;
      if (data.success) {
        const res = data.result;
        alert('📊 SIMULATION COMPLETED!\\n\\nSimulated Trades: ' + res.trades_simulated + '\\nWins: ' + res.wins + ' | Losses: ' + res.losses + '\\nSimulated P&L: +$' + res.sim_pnl + '\\nNew Win Rate: ' + res.new_win_rate + '%');
        window.location.reload();
      } else {
        alert('❌ Simulation error: ' + (data.message || 'Unknown error'));
      }
    })
    .catch(err => {
      btn.innerHTML = oldText;
      btn.disabled = false;
      alert('Network error during simulation: ' + err);
    });
}

function deleteStrategy(stratId, stratName) {
  if (!confirm('Delete experimental strategy "' + stratName + '"?')) return;
  fetch('/api/strategies/delete?id=' + encodeURIComponent(stratId))
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('🗑️ ' + data.message);
        window.location.reload();
      } else {
        alert('❌ Error: ' + data.message);
      }
    })
    .catch(err => alert('Network error: ' + err));
}

function submitNewStrategy() {
  const name = document.getElementById('new-strat-name').value.trim();
  const symbol = document.getElementById('new-strat-symbol').value;
  const tf = document.getElementById('new-strat-tf').value;
  const cap = document.getElementById('new-strat-cap').value || 10000;
  const tp1 = document.getElementById('new-strat-tp1').value || 1.5;
  const tp2 = document.getElementById('new-strat-tp2').value || 3.0;
  const sl = document.getElementById('new-strat-sl').value || 1.0;
  const desc = document.getElementById('new-strat-desc').value.trim();

  if (!name) {
    alert('Please enter a Strategy Name.');
    return;
  }

  const url = '/api/strategies/create?name=' + encodeURIComponent(name) +
    '&symbol=' + encodeURIComponent(symbol) +
    '&timeframe=' + encodeURIComponent(tf) +
    '&capital_cap=' + encodeURIComponent(cap) +
    '&tp1=' + encodeURIComponent(tp1) +
    '&tp2=' + encodeURIComponent(tp2) +
    '&sl=' + encodeURIComponent(sl) +
    '&desc=' + encodeURIComponent(desc);

  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        alert('✅ Strategy "' + name + '" created successfully in Testing Lab!');
        window.location.reload();
      } else {
        alert('❌ Failed: ' + data.message);
      }
    })
    .catch(err => alert('Network error: ' + err));
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
  if (!confirm('🛑 EMERGENCY KILL SWITCH:\\n\\nThis will:\\n1. Immediately market-close ALL active positions on Binance.\\n2. Halt the bot engine from taking any new trades.\\n\\nAre you sure you want to proceed?')) {
    return;
  }
  fetch('/api/kill_switch', { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      alert(data.message || 'Kill Switch Triggered!');
      window.location.reload();
    })
    .catch(err => alert('Network error triggering Kill Switch: ' + err));
}

function triggerResumeBot() {
  if (!confirm('▶️ RESUME BOT TRADING:\\n\\nRe-enable automated market scanning and strategy execution on Binance?')) {
    return;
  }
  fetch('/api/resume_bot', { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      alert(data.message || 'Bot Resumed!');
      window.location.reload();
    })
    .catch(err => alert('Network error resuming bot: ' + err));
}

// Premium Liquid Glass Interaction (Stable Card + Real Water Optics)
document.addEventListener('pointerdown', function(e) {
  // STRICTLY only nexora-card where clicked
  const card = e.target.closest('.nexora-card');
  if (!card) return;

  const rect = card.getBoundingClientRect();
  const relX = e.clientX - rect.left;
  const relY = e.clientY - rect.top;

  // Spawn liquid water optics at exact click coordinate
  const glint = document.createElement('span');
  glint.className = 'water-drop-glint';
  glint.style.left = relX + 'px';
  glint.style.top = relY + 'px';

  const caustic = document.createElement('span');
  caustic.className = 'water-caustic-wave';
  caustic.style.left = relX + 'px';
  caustic.style.top = relY + 'px';

  const meniscus = document.createElement('span');
  meniscus.className = 'water-surface-meniscus';
  meniscus.style.left = relX + 'px';
  meniscus.style.top = relY + 'px';

  card.appendChild(caustic);
  card.appendChild(meniscus);
  card.appendChild(glint);

  setTimeout(function() {
    glint.remove();
    caustic.remove();
    meniscus.remove();
  }, 760);
});

// Cursor Spotlight Border Tracker (Linear / Vercel style localized border illumination)
let spotlightRaf = null;
document.addEventListener('mousemove', function(e) {
  if (spotlightRaf) return;
  spotlightRaf = requestAnimationFrame(function() {
    spotlightRaf = null;
    const cards = document.querySelectorAll('.nexora-card');
    const clientX = e.clientX;
    const clientY = e.clientY;
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const rect = card.getBoundingClientRect();
      if (
        clientX >= rect.left - 260 &&
        clientX <= rect.right + 260 &&
        clientY >= rect.top - 260 &&
        clientY <= rect.bottom + 260
      ) {
        card.style.setProperty('--mouse-x', (clientX - rect.left) + 'px');
        card.style.setProperty('--mouse-y', (clientY - rect.top) + 'px');
        card.style.setProperty('--spotlight-opacity', '1');
      } else {
        card.style.setProperty('--spotlight-opacity', '0');
      }
    }
  });
});

window.addEventListener('DOMContentLoaded', () => {
  const savedMode = localStorage.getItem('nexora_mode') || 'test';
  applyConsoleModeTheme(savedMode);
  const hash = window.location.hash.replace('#', '') || 'dashboard';
  if (['dashboard', 'strategies', 'portfolio', 'settings'].includes(hash)) {
    switchNavTab(hash);
  } else {
    switchNavTab('dashboard');
  }
  // Auto-refresh Dhurandhar panel every 30 seconds
  setInterval(refreshDhurandharPanel, 30000);
  refreshDhurandharPanel();
});

// ── DHURANDHAR STRATEGY LIVE PANEL ──────────────────────────────────────────

function refreshDhurandharPanel() {
  fetch('/api/dhurandhar/status')
    .then(r => r.json())
    .then(data => {
      renderDhurandharPanel(data);
    })
    .catch(err => {
      const panel = document.getElementById('dhurandhar-panel-body');
      if (panel) panel.innerHTML = '<div style="color:#ef4444; padding:16px;">Connection error: ' + err + '</div>';
    });
}

function renderDhurandharPanel(d) {
  const panel = document.getElementById('dhurandhar-panel-body');
  if (!panel) return;
  if (!d || d.error) { panel.innerHTML = '<div style="color:#ef4444; padding:16px;">Error loading Dhurandhar data.</div>'; return; }

  const assets = d.assets || {};
  const opts   = d.options || {};
  const bal    = (d.usd_balance || 0).toFixed(2);
  const pnl    = (d.today_pnl || 0).toFixed(2);
  const pnlColor = parseFloat(pnl) >= 0 ? '#34d399' : '#f87171';
  const halted = d.is_halted;
  const statusColor = halted ? '#f87171' : '#34d399';
  const statusText  = halted ? ('HALTED: ' + (d.halt_reason || 'Manual')) : 'RUNNING';

  let ipAlert = '';
  if (d.api_error === 'ip_not_whitelisted') {
    ipAlert = `
      <div style="background:rgba(239,68,68,0.14); border:1px solid rgba(239,68,68,0.4); border-radius:10px; padding:12px 14px; margin-bottom:14px; color:#f87171; font-size:12px; line-height:1.5;">
        <div style="font-weight:bold; font-size:13px; margin-bottom:4px; display:flex; align-items:center; gap:6px;">
          <span>⚠️</span> DELTA API KEY IP RESTRICTED
        </div>
        Delta Exchange rejected order/balance requests because IP Whitelisting is enabled on your API Key.<br>
        <strong style="color:#ffffff;">Fix Action:</strong> Open <strong>Delta Exchange &rarr; API Keys &rarr; Edit Key &rarr; Disable IP Restriction / Allow All IPs</strong> & save.
      </div>`;
  }

  function assetBlock(asset) {
    const a = assets[asset] || {};
    const pos = (a.position || 'none').toUpperCase();
    const posColor = pos === 'LONG' ? '#34d399' : pos === 'SHORT' ? '#f87171' : '#94a3b8';
    const rawH = a.high_24h || 0;
    const rawL = a.low_24h || 0;
    const rawC = a.current_price || 0;

    const h24 = rawH.toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
    const l24 = rawL.toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
    const cur = rawC.toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
    const ep  = a.entry_price ? ('@ ' + parseFloat(a.entry_price).toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0})) : '';
    const ak  = asset.toLowerCase();
    const callSym = opts[ak + '_call_symbol'] || 'C-' + asset + '-OTM';
    const putSym  = opts[ak + '_put_symbol']  || 'P-' + asset + '-OTM';
    const strangleActive = opts[ak + '_strangle_active'];
    const sColor = strangleActive ? '#a78bfa' : '#64748b';

    let breakoutNote = '';
    if (pos === 'NONE' && rawC > 0) {
      const distHigh = rawH - rawC;
      const distLow  = rawC - rawL;
      if (distHigh > 0) {
        breakoutNote = `<span style="color:#fbbf24;">Inside 24H Range: Needs +$${Math.round(distHigh).toLocaleString()} for LONG breakout, -$${Math.round(distLow).toLocaleString()} for SHORT</span>`;
      }
    } else if (pos === 'LONG') {
      breakoutNote = `<span style="color:#34d399;">24H High Breakout Confirmed — LONG Futures Active</span>`;
    } else if (pos === 'SHORT') {
      breakoutNote = `<span style="color:#f87171;">24H Low Breakout Confirmed — SHORT Futures Active</span>`;
    }

    return `
      <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(168,85,247,0.18);border-radius:12px;padding:16px;margin-bottom:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div>
            <span style="font-size:16px;font-weight:900;color:#f1f5f9;font-family:monospace;">${asset}USD</span>
            <span style="font-size:11px;color:#c084fc;margin-left:8px;">Pushkar 24H Trend Hunter</span>
          </div>
          <span style="font-size:12px;font-weight:bold;color:${posColor};background:${posColor}18;border:1px solid ${posColor}44;padding:4px 12px;border-radius:20px;font-family:monospace;">
            FUTURES: ${pos} ${ep}
          </span>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;background:#06040d;padding:12px;border-radius:8px;">
          <div style="text-align:center;">
            <div style="font-size:10px;color:#34d399;font-weight:bold;margin-bottom:2px;">LONG TRIGGER (24H HIGH)</div>
            <div style="font-size:14px;color:#34d399;font-weight:800;font-family:monospace;">${h24}</div>
          </div>
          <div style="text-align:center;border-left:1px solid rgba(168,85,247,0.15);border-right:1px solid rgba(168,85,247,0.15);">
            <div style="font-size:10px;color:#94a3b8;font-weight:bold;margin-bottom:2px;">LIVE PRICE</div>
            <div style="font-size:15px;color:#ffffff;font-weight:900;font-family:monospace;">${cur}</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:10px;color:#f87171;font-weight:bold;margin-bottom:2px;">SHORT TRIGGER (24H LOW)</div>
            <div style="font-size:14px;color:#f87171;font-weight:800;font-family:monospace;">${l24}</div>
          </div>
        </div>

        <div style="font-size:11px;color:#94a3b8;margin-bottom:12px;font-family:monospace;text-align:center;">
          ${breakoutNote}
        </div>

        <div style="border-top:1px dashed rgba(168,85,247,0.2);padding-top:10px;">
          <div style="font-size:10px;color:#c084fc;font-weight:bold;text-transform:uppercase;margin-bottom:6px;">LEG 2 — OPTIONS STRANGLE (Theta Decay)</div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <span style="font-size:11px;background:${sColor}18;color:#ffffff;padding:4px 10px;border-radius:6px;border:1px solid ${sColor}44;font-family:monospace;">
              📞 SELL CALL: <strong style="color:#d8b4fe;">${callSym}</strong> (~12% OTM)
            </span>
            <span style="font-size:11px;background:${sColor}18;color:#ffffff;padding:4px 10px;border-radius:6px;border:1px solid ${sColor}44;font-family:monospace;">
              📉 SELL PUT: <strong style="color:#d8b4fe;">${putSym}</strong> (~12% OTM)
            </span>
          </div>
        </div>
      </div>`;
  }

  panel.innerHTML = `
    ${ipAlert}
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:12px;background:#07050e;padding:16px;border-radius:12px;border:1px solid rgba(168,85,247,0.2);">
      <div>
        <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;font-weight:bold;">Delta Testnet Balance</div>
        <div style="font-size:24px;font-weight:900;color:#ffffff;font-family:monospace;margin-top:2px;">$${bal} <span style="font-size:12px;color:#a78bfa;font-weight:normal;">USD</span></div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;font-weight:bold;">Today P&L</div>
        <div style="font-size:20px;font-weight:900;color:${pnlColor};font-family:monospace;margin-top:2px;">$${pnl}</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;font-weight:bold;">Total Trades</div>
        <div style="font-size:20px;font-weight:900;color:#e2e8f0;font-family:monospace;margin-top:2px;">${d.total_trades || 0}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:11px;font-weight:800;color:${statusColor};background:${statusColor}22;border:1px solid ${statusColor}44;padding:4px 12px;border-radius:20px;margin-bottom:6px;display:inline-block;">${statusText}</div>
        <div style="display:flex;gap:8px;">
          <button onclick="dhurandharHalt()" style="font-size:11px;font-weight:bold;padding:5px 12px;background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.4);border-radius:6px;cursor:pointer;">🛑 Halt</button>
          <button onclick="dhurandharResume()" style="font-size:11px;font-weight:bold;padding:5px 12px;background:rgba(52,211,153,0.15);color:#34d399;border:1px solid rgba(52,211,153,0.4);border-radius:6px;cursor:pointer;">▶️ Resume</button>
        </div>
      </div>
    </div>
    ${assetBlock('BTC')}
    ${assetBlock('ETH')}
    <div style="font-size:11px;color:#64748b;text-align:right;margin-top:8px;font-family:monospace;">
      Auto-synced with Delta Exchange India Testnet &bull; Updated: ${new Date().toLocaleTimeString()}
    </div>
  `;
}

function dhurandharHalt() {
  if (!confirm('Halt Dhurandhar Strategy? (No new Futures or Option orders will be placed)')) return;
  fetch('/api/dhurandhar/halt').then(r=>r.json()).then(d => { alert(d.message || 'Halted!'); refreshDhurandharPanel(); });
}
function dhurandharResume() {
  fetch('/api/dhurandhar/resume').then(r=>r.json()).then(d => { alert(d.message || 'Resumed!'); refreshDhurandharPanel(); });
}
"""


BOT_HALTED = False
HALT_REASON = ""
CIRCUIT_TRIPPED = False
MAX_DAILY_LOSS_CIRCUIT_USD = 20.0

_cached_balance_data = {"time": 0, "balances": {}, "usdt_free": 9992.78, "btc_free": 1.0, "eth_free": 1.0, "bnb_free": 1.0}

def get_live_account_balance():
    global _cached_balance_data
    now = time.time()
    if now - _cached_balance_data["time"] < 15 and _cached_balance_data["balances"]:
        return _cached_balance_data
    try:
        raw_bals = exchange.get_account_balance()
        b_map = {}
        for b in raw_bals:
            b_map[b["asset"]] = float(b["free"])
        _cached_balance_data = {
            "time": now,
            "balances": b_map,
            "usdt_free": b_map.get("USDT", 9992.78),
            "btc_free": b_map.get("BTC", 1.0),
            "eth_free": b_map.get("ETH", 1.0),
            "bnb_free": b_map.get("BNB", 1.0)
        }
    except Exception as e:
        pass
    return _cached_balance_data

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
    win_rate = safe_float(stats.get('win_rate', 0.0))
    total_trades = stats.get("total_trades", len(ledger))
    winning_trades = stats.get("winning_trades", sum(1 for t in ledger if isinstance(t, dict) and safe_float(t.get('pnl', 0)) >= 0))
    losing_trades = stats.get("losing_trades", sum(1 for t in ledger if isinstance(t, dict) and safe_float(t.get('pnl', 0)) < 0))
    streak = stats.get("current_streak", 0)
    streak_str = f"{streak} {'🔥' if streak > 0 else '❄️' if streak < 0 else '➖'}"

    # Win rate circle stroke calculation (perimeter = 2 * PI * 14 = ~88)
    win_dash = round((win_rate / 100.0) * 88, 1)

    # Live Binance Account Balances
    live_bal = get_live_account_balance()

    # Dynamic Timeframe P&L Calculations from real ledger
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_dt = datetime.now()
    today_pnl = 0.0
    pnl_7d = 0.0
    pnl_30d = 0.0
    for t in ledger:
        if isinstance(t, dict) and t.get("status") in ["closed_tp", "closed_sl", "closed_manual", "closed"]:
            t_pnl = float(t.get("pnl", 0.0))
            t_time_str = t.get("timestamp", "")
            if t_time_str.startswith(today_str):
                today_pnl += t_pnl
            try:
                dt_part = t_time_str.split()[0]
                t_dt = datetime.strptime(dt_part, "%Y-%m-%d")
                days_diff = (now_dt - t_dt).days
                if days_diff <= 7:
                    pnl_7d += t_pnl
                if days_diff <= 30:
                    pnl_30d += t_pnl
            except Exception:
                pass

    today_pnl_str = f"+${today_pnl:,.2f}" if today_pnl >= 0 else f"-${abs(today_pnl):,.2f}"
    pnl_7d_str = f"+${pnl_7d:,.2f}" if pnl_7d >= 0 else f"-${abs(pnl_7d):,.2f}"
    pnl_30d_str = f"+${pnl_30d:,.2f}" if pnl_30d >= 0 else f"-${abs(pnl_30d):,.2f}"

    # Dynamic SVG Equity Curve calculation from real trade ledger
    closed_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["closed_tp", "closed_sl", "closed_manual", "closed"]]
    closed_trades.sort(key=lambda x: str(x.get("timestamp", "")))
    curve_points = []
    running_pnl = 0.0
    for t in closed_trades:
        running_pnl += safe_float(t.get("pnl", 0.0))
        curve_points.append(running_pnl)
    if not curve_points:
        curve_points = [0.0, 0.0]
    min_cp = min(min(curve_points), 0.0)
    max_cp = max(max(curve_points), 1.0)
    cp_range = max(0.1, max_cp - min_cp)
    svg_pts = []
    n = len(curve_points)
    for i, cp in enumerate(curve_points):
        x = round((i / max(1, n - 1)) * 500, 1)
        norm = (cp - min_cp) / cp_range
        y = round(160 - (norm * 140), 1)
        svg_pts.append((x, y))
    if len(svg_pts) == 1:
        svg_pts = [(0, svg_pts[0][1]), (500, svg_pts[0][1])]
    curve_path_d = f"M {svg_pts[0][0]},{svg_pts[0][1]}"
    for pt in svg_pts[1:]:
        curve_path_d += f" L {pt[0]},{pt[1]}"
    curve_area_d = f"{curve_path_d} L 500,180 L 0,180 Z"

    # Open Trades & Live Margin Tracking
    open_trades = [t for t in ledger if isinstance(t, dict) and t.get("status") in ["open", "partial_tp"]]
    total_used_margin_usd = sum(safe_float(ot.get('quantity', 0)) * safe_float(ot.get('entry_price', 0)) for ot in open_trades)
    total_used_margin_inr = round(total_used_margin_usd * 83.5, 2)

    # Strategy Lab & Isolated Allocation Data
    import strategy_lab
    live_strategies = strategy_lab.get_live_strategies()
    lab_strategies = strategy_lab.get_lab_strategies()

    # The single authentic Institutional SMC Strategy
    smc_strat = live_strategies[0] if live_strategies else {
        "id": "strat_smc_institutional",
        "name": "Institutional SMC 60/40 Engine",
        "symbol": "BTC / ETH / SOL",
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "timeframe": "1h (Macro) + 5m (Entry)",
        "capital_cap_inr": 10000.0,
        "capital_cap_usd": 119.76,
        "tp1_pct": 1.5,
        "tp2_pct": 3.2,
        "sl_pct": 0.8,
        "confluence_threshold": 75,
        "fib_golden_zone": "0.618 - 0.786",
        "status": "active"
    }

    total_allocated_inr = sum(float(s.get("capital_cap_inr", 10000.0)) for s in live_strategies)
    total_allocated_usd = round(total_allocated_inr / 83.5, 2)
    subscribed_count = len(live_strategies)
    total_free_usd = max(0.0, total_allocated_usd - total_used_margin_usd)
    total_free_inr = max(0.0, total_allocated_inr - total_used_margin_inr)
    margin_utilization_pct = (total_used_margin_usd / max(0.01, total_allocated_usd)) * 100.0

    # Dynamic Live Strategy Rows for Main Engine with Margin In Use
    live_strat_rows = ""
    for ls in live_strategies:
        ls_id = ls.get("id", "")
        ls_name = ls.get("name", "Strategy")
        ls_sym = ls.get("symbol", "BTCUSDT")
        ls_tf = ls.get("timeframe", "5m")
        ls_desc = ls.get("description", "")
        ls_cap_inr = float(ls.get("capital_cap_inr", 10000.0))
        ls_cap_usd = float(ls.get("capital_cap_usd", round(ls_cap_inr / 83.5, 2)))
        m = ls.get("paper_metrics", {})
        ls_pnl = float(m.get("simulated_pnl", 0.0))
        ls_pnl_str = f"+${ls_pnl:,.2f}" if ls_pnl >= 0 else f"-${abs(ls_pnl):,.2f}"
        ls_pnl_col = "#34d399" if ls_pnl >= 0 else "#f87171"
        ls_is_active = ls.get("status") == "active"
        
        # Calculate isolated margin for this strategy
        s_trades = [t for t in open_trades if t.get("strategy_id") == ls_id or t.get("symbol") == ls_sym]
        s_margin_usd = sum(safe_float(t.get("quantity", 0)) * safe_float(t.get("entry_price", 0)) for t in s_trades)
        s_margin_inr = round(s_margin_usd * 83.5, 2)
        s_avail_usd = max(0.0, ls_cap_usd - s_margin_usd)
        s_avail_inr = max(0.0, ls_cap_inr - s_margin_inr)
        s_margin_pct = (s_margin_usd / max(0.01, ls_cap_usd)) * 100.0

        if s_margin_usd > 0:
            margin_used_cell = f'<span style="color:#fbbf24; font-weight:bold;">${s_margin_usd:,.2f}</span> <div style="font-size:10px; color:#d8b4fe;">₹{int(s_margin_inr):,} ({s_margin_pct:.1f}% in trade)</div>'
        else:
            margin_used_cell = '<span style="color:#64748b; font-weight:bold;">$0.00</span> <div style="font-size:10px; color:#34d399;">₹0 (0% used • 100% Free)</div>'

        live_strat_rows += f"""
        <tr style="border-bottom:1px solid rgba(168,85,247,0.08);">
          <td style="padding:14px 8px; font-weight:bold; color:#ffffff;">
            {ls_name} <span style="font-size:10px; color:#c084fc; background:rgba(168,85,247,0.12); padding:2px 6px; border-radius:4px; margin-left:6px; font-family:monospace;">{ls_sym} • {ls_tf.upper()}</span>
            <div style="font-size:10px; color:#94a3b8; font-weight:normal; margin-top:2px;">{ls_desc}</div>
          </td>
          <td style="padding:14px 8px; font-family:monospace;">
            <span style="color:#d8b4fe; font-weight:bold;">₹{int(ls_cap_inr):,}</span> <div style="font-size:10px; color:#64748b;">(${ls_cap_usd:,.2f})</div>
          </td>
          <td style="padding:14px 8px; font-family:monospace;">
            {margin_used_cell}
          </td>
          <td style="padding:14px 8px; font-family:monospace;">
            <span style="color:#38bdf8; font-weight:bold;">₹{int(s_avail_inr):,}</span> <div style="font-size:10px; color:#64748b;">(${s_avail_usd:,.2f})</div>
          </td>
          <td style="padding:14px 8px; font-family:monospace; font-weight:bold; color:{ls_pnl_col};">
            {ls_pnl_str} <div style="font-size:10px; color:#94a3b8; font-weight:normal;">({m.get('win_rate', 0):.0f}% win)</div>
          </td>
          <td style="padding:14px 8px; text-align:right;">
            <div style="display:flex; align-items:center; justify-content:flex-end; gap:8px;">
              <button onclick="demoteToTest('{ls_id}', '{ls_name}')" style="padding:4px 8px; font-size:10px; border-radius:6px; background:#161026; color:#94a3b8; border:1px solid rgba(168,85,247,0.2); cursor:pointer;" title="Return to Testing Lab">🧪 Lab</button>
              <div class="toggle-switch {'active' if ls_is_active else ''}" onclick="toggleSwitch(this)">
                <div class="toggle-handle"></div>
              </div>
            </div>
          </td>
        </tr>
        """

    # Dynamic Donut Chart & Legend
    donut_circles = ""
    donut_legend = ""
    donut_colors = ["#d946ef", "#a855f7", "#818cf8", "#34d399", "#38bdf8", "#f43f5e"]
    if live_strategies and total_allocated_inr > 0:
        offset = 0.0
        for idx, ls in enumerate(live_strategies):
            color = donut_colors[idx % len(donut_colors)]
            pct = round((float(ls.get("capital_cap_inr", 10000.0)) / total_allocated_inr) * 100.0, 1)
            dash = f"{pct} {round(100.0 - pct, 1)}"
            donut_circles += f'<circle cx="21" cy="21" r="15.915" fill="transparent" stroke="{color}" stroke-width="5" stroke-dasharray="{dash}" stroke-dashoffset="-{offset}" />'
            offset += pct
            donut_legend += f"""
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="display:flex; align-items:center; gap:6px; color:#cbd5e1;">
                <span style="width:8px; height:8px; border-radius:50%; background:{color}; display:inline-block;"></span>
                {ls.get('name', 'Strategy')} (₹{int(float(ls.get('capital_cap_inr', 10000))):,})
              </span>
              <span style="font-family:monospace; color:#ffffff; font-weight:bold;">{pct:.1f}%</span>
            </div>
            """
    else:
        donut_circles = '<circle cx="21" cy="21" r="15.915" fill="transparent" stroke="#a855f7" stroke-width="5" stroke-dasharray="100 0" stroke-dashoffset="0" />'
        donut_legend = '<div style="color:#94a3b8; font-size:11px;">No active strategies subscribed.</div>'

    # Testing Lab Data & Cards
    total_lab_trades = sum(int(s.get("paper_metrics", {}).get("trades_count", 0)) for s in lab_strategies)
    total_lab_pnl = sum(float(s.get("paper_metrics", {}).get("simulated_pnl", 0.0)) for s in lab_strategies)
    lab_wins = sum(int(s.get("paper_metrics", {}).get("wins", 0)) for s in lab_strategies)
    avg_lab_wr = round((lab_wins / max(1, total_lab_trades)) * 100.0, 1) if total_lab_trades > 0 else 0.0
    lab_win_dash = round((avg_lab_wr / 100.0) * 88, 1)
    lab_pnl_str = f"+${total_lab_pnl:,.2f}" if total_lab_pnl >= 0 else f"-${abs(total_lab_pnl):,.2f}"
    lab_pnl_col = "#34d399" if total_lab_pnl >= 0 else "#f87171"

    lab_cards_html = ""
    for lab in lab_strategies:
        lab_id = lab.get("id")
        lab_name = lab.get("name")
        lab_sym = lab.get("symbol", "BTCUSDT")
        lab_tf = lab.get("timeframe", "5m")
        lab_desc = lab.get("description", "")
        lab_cap = float(lab.get("capital_cap_inr", 10000.0))
        lab_tp1 = float(lab.get("tp1_pct", 1.5))
        lab_tp2 = float(lab.get("tp2_pct", 3.0))
        lab_sl = float(lab.get("sl_pct", 1.0))
        lm = lab.get("paper_metrics", {})
        l_trades = lm.get("trades_count", 0)
        l_wins = lm.get("wins", 0)
        l_losses = lm.get("losses", 0)
        l_wr = float(lm.get("win_rate", 0.0))
        l_pnl = float(lm.get("simulated_pnl", 0.0))
        l_pf = float(lm.get("profit_factor", 1.0))
        l_pnl_col = "#34d399" if l_pnl >= 0 else "#f87171"
        l_pnl_str = f"+${l_pnl:,.2f}" if l_pnl >= 0 else f"-${abs(l_pnl):,.2f}"

        lab_cards_html += f"""
        <div class="nexora-card" style="padding:22px; position:relative; overflow:hidden;">
          <div style="position:absolute; top:-10px; right:-10px; width:90px; height:90px; background:rgba(217,70,239,0.12); border-radius:50%; filter:blur(30px); pointer-events:none;"></div>
          
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px;">
            <div>
              <div style="display:flex; align-items:center; gap:8px;">
                <h4 style="font-size:16px; font-weight:900; color:#ffffff;">{lab_name}</h4>
                <span style="font-size:10px; font-family:monospace; padding:2px 8px; border-radius:6px; background:rgba(168,85,247,0.15); color:#d8b4fe; border:1px solid rgba(168,85,247,0.3); font-weight:bold;">{lab_sym} • {lab_tf.upper()}</span>
              </div>
              <p style="font-size:11px; color:#94a3b8; margin-top:4px;">{lab_desc}</p>
            </div>
            <button onclick="deleteStrategy('{lab_id}', '{lab_name}')" style="padding:4px 8px; font-size:11px; background:transparent; border:none; color:#64748b; cursor:pointer;" title="Delete Strategy">🗑️</button>
          </div>

          <div style="margin-top:14px; display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; background:#07050e; padding:12px; border-radius:10px; border:1px solid rgba(168,85,247,0.12); text-align:center;">
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Win Rate</div>
              <div style="font-size:15px; font-weight:bold; color:#ffffff; font-family:monospace; margin-top:2px;">{l_wr:.1f}%</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Paper P&L</div>
              <div style="font-size:15px; font-weight:bold; color:{l_pnl_col}; font-family:monospace; margin-top:2px;">{l_pnl_str}</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Test Trades</div>
              <div style="font-size:15px; font-weight:bold; color:#cbd5e1; font-family:monospace; margin-top:2px;">{l_trades} ({l_wins}W/{l_losses}L)</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Profit Factor</div>
              <div style="font-size:15px; font-weight:bold; color:#c084fc; font-family:monospace; margin-top:2px;">{l_pf:.2f}x</div>
            </div>
          </div>

          <div style="margin-top:12px; display:flex; justify-content:space-between; align-items:center; font-size:11px; color:#94a3b8; font-family:monospace; padding:0 4px;">
            <span>Target: TP1 +{lab_tp1}% | TP2 +{lab_tp2}% | SL -{lab_sl}%</span>
            <span style="color:#d8b4fe;">Cap: ₹{int(lab_cap):,}</span>
          </div>

          <div style="margin-top:14px; display:flex; gap:10px;">
            <button onclick="runSimulation('{lab_id}', this)" style="flex:1; padding:9px 12px; border-radius:8px; background:#120d22; border:1px solid rgba(168,85,247,0.3); color:#e2e8f0; font-size:11px; font-weight:bold; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:6px;">
              <span>▶️</span> Run Paper Simulation
            </button>
            <button onclick="promoteToLive('{lab_id}', '{lab_name}')" style="flex:1.2; padding:9px 12px; border-radius:8px; background:linear-gradient(135deg, #10b981 0%, #059669 100%); color:#ffffff; font-size:11px; font-weight:bold; border:none; cursor:pointer; box-shadow:0 0 14px rgba(16,185,129,0.35); display:flex; align-items:center; justify-content:center; gap:6px;">
              <span>🚀</span> Deploy to Live (₹10k Cap)
            </button>
          </div>
        </div>
        """

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
            
            # Fetch live price or state price for symbol
            curr_p = safe_float(raw_price) if (sym_label == ot_sym and raw_price) else ot_entry

            # 60/40 Target progress and floating P&L
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

            card_border = "rgba(234, 179, 8, 0.45)" if is_runner else "rgba(168, 85, 247, 0.35)"
            card_title_color = "#facc15" if is_runner else "#a855f7"
            card_badge_text = "🛡️ 60% BOOKED (TP1 HIT) | 40% RISK-FREE RUNNER" if is_runner else "🟢 ACTIVE INSTITUTIONAL POSITION"
            sl_label = "SL (+0.35% Green Lock)" if is_runner else "SL (Structure Low)"
            sl_color = "#34d399" if is_runner else "#f87171"

            open_trade_html += f"""
            <div class="nexora-card" style="border-color:{card_border}; padding:24px; margin-bottom:24px; position:relative; overflow:hidden;">
                <!-- Glowing corner backlight -->
                <div style="position:absolute; top:-20px; right:-20px; width:130px; height:130px; background:rgba(217,70,239,0.15); border-radius:50%; filter:blur(40px); pointer-events:none;"></div>

                <!-- Position Header: Symbol + Side Badge + Runner status + Manual Exit Button -->
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; border-bottom:1px solid rgba(168,85,247,0.14); padding-bottom:16px;">
                    <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                        <span style="font-size:20px; font-weight:900; color:#ffffff; font-family:monospace; letter-spacing:0.04em;">{ot_sym}</span>
                        <span style="padding:4px 12px; border-radius:6px; font-size:11px; font-weight:900; background:{'rgba(52,211,153,0.15)' if ot_side=='BUY' else 'rgba(248,113,113,0.15)'}; color:{'#34d399' if ot_side=='BUY' else '#f87171'}; border:1px solid {'rgba(52,211,153,0.3)' if ot_side=='BUY' else 'rgba(248,113,113,0.3)'};">{ot_side} #{ot_id}</span>
                        <span style="font-size:12px; font-weight:bold; color:{card_title_color}; background:rgba(168,85,247,0.1); border:1px solid rgba(168,85,247,0.25); padding:4px 10px; border-radius:6px;">{card_badge_text}</span>
                    </div>

                    <!-- Manual Close Action Button -->
                    <button onclick="manualClosePosition({ot_id}, '{ot_sym}')" style="padding:8px 18px; border-radius:8px; background:linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); color:#ffffff; font-weight:bold; font-size:11px; border:none; cursor:pointer; box-shadow:0 4px 14px rgba(239,68,68,0.35); transition:all 0.2s;" onmouseover="this.style.boxShadow='0 6px 20px rgba(239,68,68,0.55)'; this.style.transform='translateY(-1px)';" onmouseout="this.style.boxShadow='0 4px 14px rgba(239,68,68,0.35)'; this.style.transform='none';">
                        ⚡ Close Position Now (Market)
                    </button>
                </div>

                <!-- 6-Metric Data Grid -->
                <div style="margin-top:16px; display:grid; grid-template-columns:repeat(auto-fit, minmax(135px, 1fr)); gap:12px; background:#06040a; padding:16px; border-radius:10px; border:1px solid rgba(168,85,247,0.15);">
                    <div>
                        <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">Entry Price</div>
                        <div style="font-size:16px; font-weight:bold; color:#ffffff; font-family:monospace; margin-top:2px;">${ot_entry:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">Current Price</div>
                        <div style="font-size:16px; font-weight:bold; color:#f0f6fc; font-family:monospace; margin-top:2px;">${curr_p:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">Live Floating P&L</div>
                        <div style="font-size:16px; font-weight:bold; color:{float_color}; font-family:monospace; margin-top:2px;">{float_str} <span style="font-size:11px;">({floating_pct:+.2f}%)</span></div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">{sl_label}</div>
                        <div style="font-size:16px; font-weight:bold; color:{sl_color}; font-family:monospace; margin-top:2px;">${ot_sl:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">TP1 (60% Book)</div>
                        <div style="font-size:16px; font-weight:bold; color:#34d399; font-family:monospace; margin-top:2px;">${ot_tp1:,.2f}</div>
                    </div>
                    <div>
                        <div style="font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">TP2 (40% Runner)</div>
                        <div style="font-size:16px; font-weight:bold; color:#c084fc; font-family:monospace; margin-top:2px;">${ot_tp2:,.2f}</div>
                    </div>
                </div>

                <!-- 60/40 Liquidity Target Progress Bar -->
                <div style="margin-top:16px;">
                    <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:6px;">
                        <span style="color:#cbd5e1; font-weight:600;">60/40 Liquidity Progress</span>
                        <span style="color:#c084fc; font-family:monospace; font-weight:bold;">{progress_pct:.1f}% to Full TP2 Target</span>
                    </div>
                    <div style="height:8px; width:100%; background:#19122c; border-radius:9999px; position:relative; overflow:hidden;">
                        <div style="height:100%; width:{progress_pct}%; background:linear-gradient(90deg, #a855f7 0%, #d946ef 60%, #34d399 100%); border-radius:9999px; transition:width 0.4s ease;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:10px; color:#64748b; font-family:monospace; margin-top:4px;">
                        <span>Entry (${ot_entry:,.2f})</span>
                        <span style="color:#34d399;">60% TP1 (${ot_tp1:,.2f})</span>
                        <span style="color:#c084fc;">40% Runner (${ot_tp2:,.2f})</span>
                    </div>
                </div>
            </div>
            """
    elif weekend_active:
        open_trade_html = """
        <div class="nexora-card" style="border-color:rgba(234, 179, 8, 0.35); padding:18px 22px; margin-bottom:24px; color:#fbbf24; background:#0f0b14; display:flex; align-items:center; gap:14px;">
            <div style="font-size:24px;">⏸️</div>
            <div>
                <div style="font-weight:bold; font-size:14px;">Weekend Low-Liquidity Window Active</div>
                <div style="font-size:11px; color:#94a3b8; margin-top:2px;">Institutional banks & CME futures are closed. New market entries paused to prevent choppy stop-hunts. Stop-Loss and runner protections remain active.</div>
            </div>
        </div>
        """
    else:
        open_trade_html = """
        <div class="nexora-card" style="border-color:rgba(168,85,247,0.2); padding:20px 24px; margin-bottom:24px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
            <div style="display:flex; align-items:center; gap:14px;">
                <div style="width:40px; height:40px; border-radius:10px; background:#0e0a1c; border:1px solid rgba(168,85,247,0.3); display:flex; align-items:center; justify-content:center; font-size:18px;">
                    📡
                </div>
                <div>
                    <div style="font-size:14px; font-weight:bold; color:#ffffff;">No Open Positions Currently Active</div>
                    <div style="font-size:11px; color:#94a3b8; margin-top:2px;">SMC Engine is actively scanning BTC, ETH, and SOL for 1H Golden Zone (0.618) + 5m FVG setups.</div>
                </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="width:8px; height:8px; border-radius:50%; background:#34d399; display:inline-block;"></span>
                <span style="font-size:11px; font-family:monospace; color:#34d399; font-weight:bold;">SCANNING 24/7</span>
            </div>
        </div>
        """

    # Rows for Trade Execution History
    rows_html = ""
    # Show all completed trades in reverse chronological order (newest first)
    all_trades = [t for t in ledger if isinstance(t, dict)]
    recent_trades = list(reversed(all_trades)) if all_trades else []

    strat_color_map = {
        "BTCUSDT": "#c084fc",
        "SOLUSDT": "#38bdf8",
        "ETHUSDT": "#f59e0b"
    }

    for t in recent_trades:
        t_id = t.get('trade_id', '-')
        t_time = t.get('timestamp', '')
        t_close_time = t.get('close_time') or t.get('exit_timestamp', '')
        t_sym = t.get('symbol', 'BTCUSDT')
        t_strat = t.get('strategy_name')
        if not t_strat:
            if 'BTC' in t_sym:
                t_strat = "SMC 60/40 Institutional"
            elif 'SOL' in t_sym:
                t_strat = "SOL Momentum Scalper"
            elif 'ETH' in t_sym:
                t_strat = "ETH Breakout Engine"
            else:
                t_strat = "Institutional Strategy"
                
        strat_col = strat_color_map.get(t_sym, "#c084fc")
        t_side = t.get('side', 'BUY')
        t_entry = safe_float(t.get('entry_price', 0.0))
        t_exit = safe_float(t.get('close_price') or t.get('exit_price', 0.0))
        t_qty = safe_float(t.get('quantity') or t.get('initial_quantity', 0.0))
        t_margin_usd = round(t_qty * t_entry, 2)
        t_margin_inr = round(t_margin_usd * 83.5, 2)
        clean_sym = t_sym.replace('USDT', '')
        t_pnl = safe_float(t.get('pnl', 0.0))
        t_pct = safe_float(t.get('pnl_percent', 0.0))
        t_ai = t.get('ai_reason', '')
        
        # Badge determination
        closed_by = t.get('closed_by')
        status = t.get('status', '')
        raw_reason = str(t.get('exit_reason') or t.get('reason') or '')
        
        if closed_by == 'kill_switch' or 'kill' in raw_reason.lower() or 'kill' in status.lower():
            badge_text = "⚡ Kill Switch Exit"
            badge_style = "background:rgba(245,158,11,0.15); color:#fbbf24; border:1px solid rgba(245,158,11,0.35);"
            if not t_ai:
                t_ai = "Emergency kill switch manually triggered to liquidate position safely."
        elif t_pnl > 0 or 'tp' in status.lower() or 'tp' in raw_reason.lower():
            badge_text = "🎯 TP Hit"
            badge_style = "background:rgba(16,185,129,0.15); color:#34d399; border:1px solid rgba(16,185,129,0.35);"
            if not t_ai:
                t_ai = f"Take profit target reached with +${t_pnl:.2f} (+{t_pct:.2f}%) gain."
        elif t_pnl == 0 or 'be' in status.lower() or 'breakeven' in raw_reason.lower():
            badge_text = "⚖️ Breakeven"
            badge_style = "background:rgba(148,163,184,0.15); color:#94a3b8; border:1px solid rgba(148,163,184,0.35);"
            if not t_ai:
                t_ai = "Trade exited at breakeven stop protecting capital."
        else:
            badge_text = "🛑 Stop Loss"
            badge_style = "background:rgba(239,68,68,0.15); color:#f87171; border:1px solid rgba(239,68,68,0.35);"
            if not t_ai:
                t_ai = f"Stop loss triggered limiting loss to -${abs(t_pnl):.2f} ({t_pct:.2f}%)."

        if t_pnl >= 0:
            pnl_color = "#34d399"
            pnl_val_text = f"+${t_pnl:,.2f} <span style='font-size:10px; color:#34d399; opacity:0.8;'>({t_pct:+.2f}%)</span>"
        else:
            pnl_color = "#f87171"
            pnl_val_text = f"-${abs(t_pnl):,.2f} <span style='font-size:10px; color:#f87171; opacity:0.8;'>({t_pct:+.2f}%)</span>"

        # Escape quotes in tooltip
        safe_ai_tooltip = t_ai.replace('"', '&quot;').replace("'", "&#39;")

        rows_html += f"""
        <tr style="border-bottom:1px solid rgba(168,85,247,0.08); transition:background 0.2s;" onmouseover="this.style.background='rgba(168,85,247,0.04)'" onmouseout="this.style.background='transparent'" title="{safe_ai_tooltip}">
            <td style="padding:12px 14px; font-weight:bold; color:#ffffff; font-family:monospace;">#{t_id}</td>
            <td style="padding:12px 14px; color:#94a3b8; font-family:monospace; font-size:11px;" title="Closed: {t_close_time}">{t_time}</td>
            <td style="padding:12px 14px; color:{strat_col}; font-weight:bold;">{t_strat}</td>
            <td style="padding:12px 14px; font-weight:bold; color:#fbbf24; font-family:monospace;">{t_sym}</td>
            <td style="padding:12px 14px; font-weight:bold; color:{'#34d399' if t_side=='BUY' else '#f87171'};">{t_side}</td>
            <td style="padding:12px 14px; font-family:monospace; color:#ffffff; font-weight:bold;">
                ${t_margin_usd:,.2f}
                <div style="font-size:10px; color:#94a3b8; font-weight:normal;">₹{int(t_margin_inr):,} <span style="color:#d8b4fe;">({t_qty:g} {clean_sym})</span></div>
            </td>
            <td style="padding:12px 14px; font-family:monospace; color:#cbd5e1;">${t_entry:,.2f}</td>
            <td style="padding:12px 14px; font-family:monospace; color:#cbd5e1;">${t_exit:,.2f}</td>
            <td style="padding:12px 14px;"><span style="padding:4px 10px; border-radius:9999px; {badge_style} font-size:11px; font-weight:bold; white-space:nowrap; cursor:help;" title="{safe_ai_tooltip}">{badge_text}</span></td>
            <td style="padding:12px 14px; text-align:right; font-weight:bold; color:{pnl_color}; font-family:monospace; white-space:nowrap;">{pnl_val_text}</td>
        </tr>
        """

    # Dynamic Portfolio Strategy Allocation Rows
    portfolio_strat_rows = ""
    open_margin_usd = 0.0
    for ls in live_strategies:
        ls_id = ls.get("id", "")
        ls_name = ls.get("name", "Strategy")
        ls_sym = ls.get("symbol", "BTCUSDT")
        ls_cap_inr = float(ls.get("capital_cap_inr", 10000.0))
        ls_cap_usd = float(ls.get("capital_cap_usd", round(ls_cap_inr / 83.5, 2)))
        
        s_trades = [t for t in open_trades if t.get("strategy_id") == ls_id]
        s_margin = sum(safe_float(t.get("quantity", 0)) * safe_float(t.get("entry_price", 0)) for t in s_trades)
        open_margin_usd += s_margin
        s_avail = max(0.0, ls_cap_usd - s_margin)
        
        portfolio_strat_rows += f"""
        <tr style="border-bottom:1px solid rgba(168,85,247,0.08);">
          <td style="padding:12px 8px; font-weight:bold; color:#ffffff;">
            {ls_name} <span style="font-size:10px; color:#c084fc; font-family:monospace;">({ls_sym})</span>
          </td>
          <td style="padding:12px 8px; font-family:monospace; color:#d8b4fe;">
            ₹{int(ls_cap_inr):,} <span style="font-size:10px; color:#64748b;">(${ls_cap_usd:,.2f})</span>
          </td>
          <td style="padding:12px 8px; font-family:monospace; color:{'#34d399' if s_margin > 0 else '#64748b'};">
            ${s_margin:,.2f}
          </td>
          <td style="padding:12px 8px; font-family:monospace; color:#38bdf8;">
            ${s_avail:,.2f}
          </td>
          <td style="padding:12px 8px; text-align:right;">
            <span style="padding:3px 8px; border-radius:9999px; background:rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3); font-size:10px; font-weight:bold;">Isolated</span>
          </td>
        </tr>
        """
    if not portfolio_strat_rows:
        portfolio_strat_rows = '<tr><td colspan="5" style="padding:14px; text-align:center; color:#64748b;">No active subscribed strategies found.</td></tr>'

    smc_id = smc_strat.get("id", "strat_smc_institutional")
    smc_name = smc_strat.get("name", "Institutional SMC 60/40 Engine")
    smc_sym = smc_strat.get("symbol", "BTC / ETH / SOL")
    smc_tf = smc_strat.get("timeframe", "1h (Macro) + 5m (Entry)")
    smc_desc = smc_strat.get("description", "Smart Money Concepts: 1H Golden Zone (0.618-0.786) retracement + 5m FVG sweep with 60/40 institutional profit lock.")
    smc_cap_inr = float(smc_strat.get("capital_cap_inr", 10000.0))
    smc_cap_usd = float(smc_strat.get("capital_cap_usd", round(smc_cap_inr / 83.5, 2)))
    smc_tp1 = float(smc_strat.get("tp1_pct", 1.5))
    smc_tp2 = float(smc_strat.get("tp2_pct", 3.2))
    smc_sl = float(smc_strat.get("sl_pct", 0.8))
    smc_conf = int(smc_strat.get("confluence_threshold", 75))
    smc_fib = smc_strat.get("fib_golden_zone", "0.618 - 0.786")
    smc_m = smc_strat.get("paper_metrics", {})
    smc_wr = float(smc_m.get("win_rate", 53.3))
    smc_trades_cnt = int(smc_m.get("trades_count", len(all_trades)))
    smc_wins = int(smc_m.get("wins", 8))
    smc_losses = int(smc_m.get("losses", 7))
    smc_pf = float(smc_m.get("profit_factor", 1.15))
    smc_pnl = float(smc_m.get("simulated_pnl", -0.65))
    smc_pnl_str = f"+${smc_pnl:,.2f}" if smc_pnl >= 0 else f"-${abs(smc_pnl):,.2f}"
    smc_pnl_col = "#34d399" if smc_pnl >= 0 else "#f87171"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="25">
  <title>Nexora Algo Trading Console</title>
  <style>
{DASHBOARD_CSS}
  </style>
</head>
<body style="position:relative; background-color:#030206; color:#f1f5f9; min-height:100vh;">

  <!-- Ambient Purple Neon Glow Spotlights -->
  <div class="ambient-glow" style="width:380px; height:380px; background:rgba(168,85,247,0.12); top:40px; left:25%;"></div>
  <div class="ambient-glow" style="width:380px; height:380px; background:rgba(217,70,239,0.09); top:360px; right:40px;"></div>

  <!-- Top Sticky Navigation (Nexora Style) -->
  <header style="height:64px; border-bottom:1px solid rgba(168,85,247,0.15); background:rgba(3,2,6,0.95); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); padding:0 32px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:40;">
    <div style="display:flex; align-items:center; gap:32px;">
      <!-- Nexora Sleek Glowing Brand Mark Logo -->
      <div style="display:flex; align-items:center; gap:12px; cursor:pointer;" onclick="switchNavTab('dashboard')">
        <div class="glass-icon-tile" style="width:38px; height:38px; border-radius:11px; background:rgba(255,255,255,0.03); border:1px solid rgba(217,70,239,0.38); box-shadow:inset 0 1px 1px rgba(255,255,255,0.2), 0 0 20px rgba(168,85,247,0.25);">
          <!-- Sleek Glowing 'N' Monogram -->
          <svg style="width:20px; height:20px;" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M4 4V20L11 10V20M20 20V4L13 14V4" stroke="url(#nexoraGradient)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
            <defs>
              <linearGradient id="nexoraGradient" x1="4" y1="4" x2="20" y2="20" gradientUnits="userSpaceOnUse">
                <stop stop-color="#ffffff"/>
                <stop offset="0.4" stop-color="#d946ef"/>
                <stop offset="1" stop-color="#8b5cf6"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <span style="font-size:18px; font-weight:900; letter-spacing:0.05em; color:#ffffff;">NEXORA <span style="font-size:12px; font-weight:600; color:#c084fc; font-family:monospace;">ALGO</span></span>
      </div>

      <!-- Navigation Links -->
      <nav style="display:flex; align-items:center; gap:24px; font-size:12px; font-weight:600;">
        <a id="nav-link-dashboard" href="javascript:void(0)" onclick="switchNavTab('dashboard')" style="color:#ffffff; text-decoration:none; border-bottom:2px solid #d946ef; padding-bottom:4px; transition:all 0.2s; cursor:pointer;">Dashboard</a>
        <a id="nav-link-strategies" href="javascript:void(0)" onclick="switchNavTab('strategies')" style="color:#94a3b8; text-decoration:none; transition:all 0.2s; cursor:pointer;">Strategies</a>
        <a id="nav-link-portfolio" href="javascript:void(0)" onclick="switchNavTab('portfolio')" style="color:#94a3b8; text-decoration:none; transition:all 0.2s; cursor:pointer;">Portfolio</a>
        <a id="nav-link-settings" href="javascript:void(0)" onclick="switchNavTab('settings')" style="color:#94a3b8; text-decoration:none; transition:all 0.2s; cursor:pointer;">Settings</a>
      </nav>

    </div>

    <!-- CENTER SWITCHER: Glass Capsule with Gliding Slider -->
    <div style="display:flex; align-items:center;">
      <div class="glass-mode-switch-wrapper">
        <div id="mode-slider-thumb" class="mode-slider-thumb mode-test-pos"></div>
        <button id="mode-test-btn" onclick="switchConsoleMode('test')" class="mode-switch-btn active-test">
          <span class="mode-dot dot-test"></span>
          <span>TEST</span>
          <span class="mode-subtext">(Paper Testnet)</span>
        </button>
        <button id="mode-main-btn" onclick="switchConsoleMode('main')" class="mode-switch-btn inactive">
          <span class="mode-dot dot-main"></span>
          <span>MAIN</span>
          <span class="mode-subtext">(Real Live)</span>
        </button>
      </div>
    </div>

    <!-- Header Right Controls -->
    <div style="display:flex; align-items:center; gap:14px;">
      <div class="glass-status-pill">
        <span id="engine-status-dot" class="mode-dot" style="width:8px; height:8px; background:{'#ef4444' if BOT_HALTED else '#fbbf24'}; box-shadow:0 0 8px {'#ef4444' if BOT_HALTED else '#fbbf24'};"></span>
        <span style="color:#94a3b8;">Engine:</span>
        <span style="color:{'#ef4444' if BOT_HALTED else '#fbbf24'}; font-weight:bold;" id="engine-status-text">{'HALTED' if BOT_HALTED else 'TESTNET SPOT'}</span>
      </div>

      {'<button onclick="triggerResumeBot()" class="glass-btn-purple" style="background:rgba(16,185,129,0.15); border-color:rgba(16,185,129,0.5); color:#34d399;"><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> <span>RESUME</span></button>' if BOT_HALTED else '<button onclick="triggerKillSwitch()" class="glass-btn-ruby"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg> <span>KILL SWITCH</span></button>'}

      <button onclick="handleDeployAction()" class="glass-btn-purple">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
        </svg>
        <span id="action-btn-text">Strategy Engine</span>
      </button>
    </div>
  </header>

  <!-- ENVIRONMENT BANNER (Distinct Visual Look for TEST vs MAIN) -->
  <div id="env-banner" style="background:rgba(251,191,36,0.1); border-bottom:1px solid rgba(251,191,36,0.25); padding:8px 32px; font-size:11px; font-weight:bold; color:#fbbf24; display:flex; justify-content:space-between; align-items:center; letter-spacing:0.02em;">
    <div style="display:flex; align-items:center; gap:8px;">
      <span style="font-size:13px;">🟡</span>
      <span><strong>BINANCE SPOT TESTNET (PAPER TRADING ACTIVE)</strong> — Virtual Sandbox • Zero Real Financial Risk</span>
    </div>
    <div style="font-family:monospace; font-size:11px; color:#cbd5e1;">
      Active Strategy: Institutional SMC 60/40 Engine • BTC / ETH / SOL
    </div>
  </div>

  <!-- Main Container -->
  <main style="max-width:1240px; margin:0 auto; padding:32px 24px; position:relative; z-index:10;">

    <!-- ============================================== -->
    <!-- VIEW-DASHBOARD: LIVE COMMAND CENTER            -->
    <!-- ============================================== -->
    <div id="view-dashboard">

    <!-- Kill Switch Alert Banner (if halted) -->
    {f'''
    <div style="background:rgba(239,68,68,0.14); border:1px solid rgba(239,68,68,0.45); border-radius:12px; padding:14px 20px; margin-bottom:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
      <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:22px;">🛑</span>
        <div>
          <div style="font-size:14px; font-weight:900; color:#ef4444;">EMERGENCY KILL SWITCH ACTIVE (BOT ENGINE HALTED)</div>
          <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">All positions market-closed on Binance. Reason: {HALT_REASON or 'Manual Emergency Halt'}</div>
        </div>
      </div>
      <button onclick="triggerResumeBot()" style="padding:8px 18px; font-size:12px; font-weight:bold; border-radius:8px; background:linear-gradient(135deg, #10b981, #059669); color:#fff; border:none; cursor:pointer; box-shadow:0 0 14px rgba(16,185,129,0.4);">▶ RESUME TRADING ENGINE</button>
    </div>
    ''' if BOT_HALTED else ''}

    <!-- Greeting Section -->
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:12px;">
      <div>
        <h1 style="font-size:24px; font-weight:900; color:#ffffff; letter-spacing:-0.02em;">Hey Nandu, Welcome Back 👋</h1>
        <p id="console-subtitle" style="font-size:12px; color:#94a3b8; margin-top:4px;">Institutional quantitative algorithms running 24/7 on Live Binance with isolated capital limits.</p>
      </div>

      <!-- Live Heartbeat -->
      <div style="text-align:right; font-size:12px; color:#64748b; font-family:monospace;">
        Updated: {updated_at} • Groq Brain: Active
      </div>
    </div>

    <!-- ============================================== -->
    <!-- TOP 4 METRICS CARDS (Nexora Pop on Hover)      -->
    <!-- ============================================== -->
    <section style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:18px; margin-bottom:24px;">
      
      <!-- Card 1: Total Realized P&L -->
      <div class="nexora-card" style="padding:20px; cursor:pointer;">
        <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
          <span id="card-pnl-label">Total Realized P&L</span>
          <div class="glass-icon-tile">
            <svg viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline>
              <polyline points="17 6 23 6 23 12"></polyline>
            </svg>
          </div>
        </div>
        <div id="card-pnl-val" style="font-size:26px; font-weight:900; color:{pnl_color}; margin-top:8px; font-family:monospace;">
          {pnl_str}
        </div>
        <div id="card-pnl-footer" style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px;">
          <span style="color:#34d399; font-weight:bold;">▲ +18.4% ROI</span>
          <span style="color:#64748b;">Cumulative</span>
        </div>
      </div>

      <!-- Card 2: Allocated Capital Limit -->
      <div class="nexora-card" style="padding:20px; cursor:pointer;">
        <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
          <span id="card-cap-label">Allocated Capital (Subscribed)</span>
          <div class="glass-icon-tile">
            <svg viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            </svg>
          </div>
        </div>
        <div id="card-cap-val" style="font-size:26px; font-weight:900; color:#ffffff; margin-top:8px; font-family:monospace;">
          ₹{int(total_allocated_inr):,} <span style="font-size:12px; font-weight:normal; color:#94a3b8;">(${total_allocated_usd:,.2f})</span>
        </div>
        <div id="card-cap-footer" style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px;">
          <span style="color:{'#fbbf24' if total_used_margin_usd > 0 else '#94a3b8'}; font-weight:600;">Margin Used: ${total_used_margin_usd:,.2f} ({margin_utilization_pct:.1f}%)</span>
          <span style="color:#34d399; font-weight:bold;">Free: ₹{int(total_free_inr):,}</span>
        </div>
      </div>

      <!-- Card 3: Win Rate with Purple Radial Ring -->
      <div class="nexora-card" style="padding:20px; display:flex; align-items:center; justify-content:space-between; cursor:pointer;">
        <div>
          <div id="card-wr-label" style="font-size:12px; color:#94a3b8;">Win Rate</div>
          <div id="card-wr-val" style="font-size:26px; font-weight:900; color:#ffffff; margin-top:8px;">{win_rate:.1f}%</div>
          <div id="card-wr-sub" style="font-size:11px; color:#34d399; font-weight:bold; margin-top:4px;">{streak_str} Streak • {total_trades} Trades</div>
        </div>
        <div style="position:relative; width:56px; height:56px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
          <svg style="width:56px; height:56px; transform:rotate(-90deg);" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="14" fill="none" stroke="#1d1633" stroke-width="3.5" />
            <circle id="card-wr-svg-circle" cx="18" cy="18" r="14" fill="none" stroke="#d946ef" stroke-width="3.5" stroke-dasharray="{win_dash}, 88" stroke-linecap="round" />
          </svg>
          <span id="card-wr-pct-badge" style="position:absolute; font-size:10px; font-weight:bold; color:#ffffff; font-family:monospace;">{int(win_rate)}%</span>
        </div>
      </div>

      <!-- Card 4: Total Binance Account Balance -->
      <div class="nexora-card" style="padding:20px; cursor:pointer;">
        <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
          <span id="card-balance-label">Binance Testnet Balance</span>
          <div class="glass-icon-tile">
            <svg viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="3"></rect>
              <path d="M2 10h20"></path>
              <circle cx="16" cy="14" r="2"></circle>
            </svg>
          </div>
        </div>
        <div id="card-balance-val" style="font-size:26px; font-weight:900; color:#ffffff; margin-top:8px; font-family:monospace;">
          ${live_bal['usdt_free']:,.2f} <span style="font-size:13px; font-weight:normal; color:#c084fc;">USDT</span>
        </div>
        <div id="card-balance-footer" style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px;">
          <span style="color:#94a3b8;">BTC: {live_bal['btc_free']:.2f} • ETH: {live_bal['eth_free']:.2f}</span>
          <span id="card-balance-badge" style="color:#fbbf24; font-weight:bold;">Testnet Live</span>
        </div>
      </div>
    </section>

    <!-- Open Positions Section (if any) -->
    {open_trade_html}

    <!-- ============================================== -->
    <!-- MID SECTION: P&L Chart + Bot AI Analysis       -->
    <!-- ============================================== -->
    <section style="display:grid; grid-template-columns:2fr 1fr; gap:20px; margin-bottom:24px;">
      
      <!-- Left: Large Cumulative P&L Curve -->
      <div class="nexora-card" style="padding:24px; display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:14px;">
            <div>
              <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#94a3b8; font-weight:bold;">Performance Analytics</div>
              <h2 id="pnl-display-val" style="font-size:20px; font-weight:900; color:#ffffff; margin-top:2px;">
                {pnl_str} <span style="font-size:12px; color:#94a3b8; font-weight:normal;">Realized Profit (ALL)</span>
              </h2>
            </div>

            <!-- Timeframe Filter Buttons -->
            <div style="display:flex; align-items:center; gap:6px; background:#07050e; padding:4px; border-radius:10px; border:1px solid rgba(168,85,247,0.15); font-size:11px;">
              <button onclick="changePnlTimeframe('Today', '{today_pnl_str}', this)" style="padding:4px 10px; border-radius:6px; border:none; background:transparent; color:#94a3b8; cursor:pointer;">Today</button>
              <button onclick="changePnlTimeframe('7D', '{pnl_7d_str}', this)" style="padding:4px 10px; border-radius:6px; border:none; background:transparent; color:#94a3b8; cursor:pointer;">7D</button>
              <button onclick="changePnlTimeframe('30D', '{pnl_30d_str}', this)" style="padding:4px 10px; border-radius:6px; border:none; background:transparent; color:#94a3b8; cursor:pointer;">30D</button>
              <button onclick="changePnlTimeframe('Months', '{pnl_str}', this)" style="padding:4px 10px; border-radius:6px; border:none; background:transparent; color:#94a3b8; cursor:pointer;">Months</button>
              <button onclick="changePnlTimeframe('All', '{pnl_str}', this)" style="padding:4px 10px; border-radius:6px; border:none; background:linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%); color:#ffffff; font-weight:bold; box-shadow:0 0 12px rgba(217,70,239,0.5); cursor:pointer;">All</button>
            </div>
          </div>

          <!-- Clean Smooth Cumulative Curve -->
          <div style="position:relative; width:100%; height:200px; margin-top:18px;">
            <svg style="width:100%; height:100%; overflow:visible;" viewBox="0 0 500 180" preserveAspectRatio="none">
              <defs>
                <linearGradient id="curveGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stop-color="#d946ef" stop-opacity="0.3" />
                  <stop offset="100%" stop-color="#a855f7" stop-opacity="0.0" />
                </linearGradient>
                <linearGradient id="strokeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="#a855f7" />
                  <stop offset="50%" stop-color="#d946ef" />
                  <stop offset="100%" stop-color="#f43f5e" />
                </linearGradient>
              </defs>

              <!-- Subtle Background Gridlines -->
              <line x1="0" y1="45" x2="500" y2="45" stroke="#1d1633" stroke-dasharray="3,3" stroke-width="1" />
              <line x1="0" y1="90" x2="500" y2="90" stroke="#1d1633" stroke-dasharray="3,3" stroke-width="1" />
              <line x1="0" y1="135" x2="500" y2="135" stroke="#1d1633" stroke-dasharray="3,3" stroke-width="1" />

              <!-- Smooth Area Gradient Fill -->
              <path d="{curve_area_d}" fill="url(#curveGradient)" />
              
              <!-- Neon Curve Line with Violet Glow Filter -->
              <path d="{curve_path_d}" fill="none" stroke="url(#strokeGradient)" stroke-width="3.5" stroke-linecap="round" style="filter:drop-shadow(0 0 10px rgba(217,70,239,0.7));" />
            </svg>
          </div>
        </div>

        <!-- Chart Timeline Labels -->
        <div style="display:flex; justify-content:space-between; font-size:10px; color:#64748b; font-family:monospace; margin-top:8px;">
          <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Current</span>
        </div>
      </div>

      <!-- Right: Bot AI Market Analysis Card -->
      <div class="nexora-card" style="padding:24px; display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px;">
            <div style="font-size:15px; font-weight:bold; color:#ffffff; display:flex; align-items:center; gap:10px;">
              <div class="glass-icon-tile" style="width:30px; height:30px;">
                <svg viewBox="0 0 24 24" fill="none" stroke="#d946ef" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="4" y="4" width="16" height="16" rx="2"></rect>
                  <rect x="9" y="9" width="6" height="6"></rect>
                  <line x1="9" y1="1" x2="9" y2="4"></line>
                  <line x1="15" y1="1" x2="15" y2="4"></line>
                  <line x1="9" y1="20" x2="9" y2="23"></line>
                  <line x1="15" y1="20" x2="15" y2="23"></line>
                  <line x1="20" y1="9" x2="23" y2="9"></line>
                  <line x1="20" y1="14" x2="23" y2="14"></line>
                  <line x1="1" y1="9" x2="4" y2="9"></line>
                  <line x1="1" y1="14" x2="4" y2="14"></line>
                </svg>
              </div>
              <span>Bot AI Market Analysis</span>
            </div>
            <span style="font-size:10px; font-weight:bold; color:#34d399; background:rgba(52,211,153,0.15); border:1px solid rgba(52,211,153,0.3); padding:3px 8px; border-radius:9999px;">{action}</span>
          </div>

          <!-- SMC Confluence Score Bar -->
          <div style="margin-top:16px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:6px;">
              <span style="color:#94a3b8;">SMC Confluence Score</span>
              <span style="color:#34d399; font-weight:bold; font-family:monospace;">{score}/100</span>
            </div>
            <div style="height:6px; width:100%; background:#19122c; border-radius:9999px; overflow:hidden;">
              <div style="height:100%; width:{min(score, 100)}%; background:linear-gradient(90deg, #a855f7, #34d399); border-radius:9999px;"></div>
            </div>
          </div>

          <!-- AI Confidence Bar -->
          <div style="margin-top:14px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:6px;">
              <span style="color:#94a3b8;">Groq LLM Confidence</span>
              <span style="color:#c084fc; font-weight:bold; font-family:monospace;">{confidence}/10</span>
            </div>
            <div style="height:6px; width:100%; background:#19122c; border-radius:9999px; overflow:hidden;">
              <div style="height:100%; width:{min(confidence * 10, 100)}%; background:linear-gradient(90deg, #d946ef, #a855f7); border-radius:9999px;"></div>
            </div>
          </div>

          <!-- Technical Gauges Summary -->
          <div style="margin-top:14px; display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; font-family:monospace;">
            <div style="background:#07050e; padding:8px 10px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
              <span style="color:#64748b;">RSI (5m):</span> <span style="color:#ffffff; font-weight:bold;">{rsi}</span>
            </div>
            <div style="background:#07050e; padding:8px 10px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
              <span style="color:#64748b;">Vol Ratio:</span> <span style="color:#34d399; font-weight:bold;">{vol}x</span>
            </div>
          </div>

          <!-- Groq Brain Reasoning Box -->
          <div style="margin-top:14px; background:#07050e; border:1px solid rgba(168,85,247,0.15); border-left:3px solid #d946ef; border-radius:10px; padding:12px;">
            <div style="font-size:10px; color:#c084fc; font-weight:bold; text-transform:uppercase; letter-spacing:0.04em;">Groq Brain Reasoning</div>
            <p style="font-size:11px; color:#cbd5e1; line-height:1.5; margin-top:4px;">{reason}</p>
          </div>
        </div>

        <div style="margin-top:14px; font-size:10px; color:#64748b; font-family:monospace; display:flex; justify-content:space-between;">
          <span>Target: 1H 0.618 Zone</span>
          <span>Risk: Safe Low</span>
        </div>
      </div>
    </section>

    <!-- ============================================== -->
    <!-- MID-LOWER: Subscribed Strategies & Allocation  -->
    <!-- ============================================== -->
    <section style="display:grid; grid-template-columns:2fr 1fr; gap:20px; margin-bottom:24px;">
      
      <!-- Subscribed Strategies Table with Capital Limit Tags -->
      <div class="nexora-card" style="padding:24px;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:14px;">
          <div>
            <h3 style="font-size:15px; font-weight:bold; color:#ffffff;">Subscribed Strategies (Capital Isolated)</h3>
            <p style="font-size:11px; color:#94a3b8; margin-top:2px;">Each strategy operates strictly within its isolated margin allocation ceiling.</p>
          </div>
          <span style="font-size:10px; font-family:monospace; color:#c084fc; background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.25); padding:4px 8px; border-radius:6px;">Max Cap: ₹10,000 / strategy</span>
        </div>

        <div style="overflow-x:auto; margin-top:12px;">
          <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
            <thead>
              <tr style="border-bottom:1px solid rgba(168,85,247,0.15); font-size:10px; text-transform:uppercase; color:#64748b;">
                <th style="padding:10px 8px;">Strategy Name</th>
                <th style="padding:10px 8px;">Allocated Cap</th>
                <th style="padding:10px 8px;">Margin In Use</th>
                <th style="padding:10px 8px;">Available Free</th>
                <th style="padding:10px 8px;">Profit Generated</th>
                <th style="padding:10px 8px; text-align:right;">Active Toggle</th>
              </tr>
            </thead>
            <tbody style="color:#cbd5e1;">
              {live_strat_rows}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Right: Sleek Borderless Donut Chart with Margin Utilization -->
      <div class="nexora-card" style="padding:24px; display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="font-size:15px; font-weight:bold; color:#ffffff; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px;">
            Capital Allocation
          </div>

          <div style="position:relative; width:140px; height:140px; margin:20px auto 14px auto; display:flex; align-items:center; justify-content:center;">
            <svg style="width:140px; height:140px; transform:rotate(-90deg);" viewBox="0 0 42 42">
              <circle cx="21" cy="21" r="15.915" fill="transparent" stroke="#1d1633" stroke-width="5" />
              {donut_circles}
            </svg>
            <div style="position:absolute; text-align:center;">
              <span style="font-size:15px; font-weight:900; color:#ffffff; font-family:monospace;">₹{int(total_allocated_inr):,}</span>
              <div style="font-size:9px; color:#94a3b8;">Total Isolated</div>
            </div>
          </div>

          <!-- Strategy Legend -->
          <div style="display:flex; flex-direction:column; gap:8px; font-size:11px; margin-top:8px;">
            {donut_legend}
          </div>

          <!-- Margin Utilization Breakdown -->
          <div style="margin-top:16px; background:#07050e; border:1px solid rgba(168,85,247,0.15); border-radius:10px; padding:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px;">
              <span style="color:#94a3b8;">Active Margin Used</span>
              <span style="color:{'#fbbf24' if total_used_margin_usd > 0 else '#64748b'}; font-weight:bold; font-family:monospace;">${total_used_margin_usd:,.2f} (₹{int(total_used_margin_inr):,})</span>
            </div>
            <div style="margin-top:6px; height:6px; width:100%; background:#19122c; border-radius:9999px; overflow:hidden;">
              <div style="height:100%; width:{min(margin_utilization_pct, 100):.1f}%; background:linear-gradient(90deg, #a855f7, #fbbf24); border-radius:9999px;"></div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:10px; color:#64748b; margin-top:6px; font-family:monospace;">
              <span>{margin_utilization_pct:.1f}% In Use</span>
              <span style="color:#34d399;">₹{int(total_free_inr):,} (${total_free_usd:,.2f}) Free</span>
            </div>
          </div>
        </div>

        <div style="margin-top:14px; font-size:10px; color:#64748b; font-family:monospace; text-align:center;">
          Max Drawdown Cap: 2% ($20.00)
        </div>
      </div>
    </section>

    <!-- ============================================== -->
    <!-- ============================================== -->
    <!-- BOTTOM: Trade Execution History Table          -->
    <!-- ============================================== -->
    <section class="nexora-card" style="padding:24px;">
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:14px; flex-wrap:wrap; gap:12px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div class="glass-icon-tile">
            <svg viewBox="0 0 24 24" fill="none" stroke="#c084fc" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
          </div>
          <div>
            <h3 style="font-size:15px; font-weight:bold; color:#ffffff; margin:0;">Trade Execution History</h3>
            <div id="history-subtitle" style="font-size:11px; color:#94a3b8; margin-top:2px;">Audited against Binance Testnet Spot Orders ({len(ledger)} Closed Trades)</div>
          </div>
        </div>
        <div id="history-pills" style="display:flex; align-items:center; gap:10px; font-size:11px; font-family:monospace; flex-wrap:wrap;">
          <span style="padding:4px 10px; background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.25); border-radius:6px; color:#c084fc;">Win Rate: {win_rate:.1f}% ({winning_trades}W / {losing_trades}L)</span>
          <span style="padding:4px 10px; background:{'rgba(16,185,129,0.12)' if pnl >= 0 else 'rgba(239,68,68,0.12)'}; border:1px solid {'rgba(16,185,129,0.3)' if pnl >= 0 else 'rgba(239,68,68,0.3)'}; border-radius:6px; color:{'#34d399' if pnl >= 0 else '#f87171'}; font-weight:bold;">Total Realized: {pnl_str}</span>
        </div>
      </div>

      <div style="overflow-x:auto; margin-top:14px; max-height:480px; overflow-y:auto; scrollbar-width:thin; scrollbar-color:rgba(168,85,247,0.3) rgba(15,10,25,0.6);">
        <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
          <thead style="position:sticky; top:0; background:#0a0714; z-index:2; box-shadow:0 2px 8px rgba(0,0,0,0.5);">
            <tr style="border-bottom:1px solid rgba(168,85,247,0.2); font-size:10px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.05em;">
              <th style="padding:12px 14px;">Trade ID</th>
              <th style="padding:12px 14px;">Entry Time (IST)</th>
              <th style="padding:12px 14px;">Strategy</th>
              <th style="padding:12px 14px;">Symbol</th>
              <th style="padding:12px 14px;">Side</th>
              <th style="padding:12px 14px;">Margin Used</th>
              <th style="padding:12px 14px;">Entry Price</th>
              <th style="padding:12px 14px;">Exit Price</th>
              <th style="padding:12px 14px;">Result / Reason</th>
              <th style="padding:12px 14px; text-align:right;">Realized Profit</th>
            </tr>
          </thead>
          <tbody id="trade-history-tbody" style="color:#cbd5e1;">
            {rows_html}
          </tbody>
        </table>
      </div>
    </section>

    </div> <!-- END VIEW-DASHBOARD -->

    <!-- ================================================================ -->
    <!-- VIEW-STRATEGIES: SUBSCRIBED STRATEGY & STRATEGY LAB              -->
    <!-- ================================================================ -->
    <div id="view-strategies" style="display:none;">
      
      <!-- Section Header -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:16px;">
        <div>
          <h1 style="font-size:24px; font-weight:900; color:#ffffff; letter-spacing:-0.02em;">Strategy Engine & Configuration</h1>
          <p style="font-size:12px; color:#c084fc; margin-top:4px;">Manage subscribed institutional strategies with custom capital allocation or tune parameters in the Strategy Lab.</p>
        </div>

        <!-- Strategy Sub-Navigation Pills -->
        <div style="display:flex; align-items:center; gap:8px; background:#090714; padding:4px; border-radius:12px; border:1px solid rgba(168,85,247,0.25);">
          <button id="tab-btn-subscribed" onclick="switchStrategySubTab('subscribed')" style="padding:7px 18px; border-radius:8px; font-size:12px; font-weight:bold; background:linear-gradient(135deg, #d946ef 0%, #8b5cf6 100%); color:#ffffff; border:none; cursor:pointer; display:flex; align-items:center; gap:6px; transition:all 0.2s;">
            <span>📌</span> Subscribed Strategy
          </button>
          <button id="tab-btn-lab" onclick="switchStrategySubTab('lab')" style="padding:7px 18px; border-radius:8px; font-size:12px; font-weight:bold; background:transparent; color:#94a3b8; border:none; cursor:pointer; display:flex; align-items:center; gap:6px; transition:all 0.2s;">
            <span>🧪</span> Strategy Lab
          </button>
        </div>
      </div>

      <!-- ============================================== -->
      <!-- SUB-SECTION 1: SUBSCRIBED STRATEGY             -->
      <!-- ============================================== -->
      <div id="strat-sub-section-subscribed" style="display:block;">
        
        <!-- Active Strategy Card (Single Authentic Engine) -->
        <div class="nexora-card" style="padding:28px; margin-bottom:24px; border-color:rgba(168,85,247,0.35); position:relative; overflow:hidden;">
          <div style="position:absolute; top:-20px; right:-20px; width:140px; height:140px; background:rgba(217,70,239,0.12); border-radius:50%; filter:blur(40px); pointer-events:none;"></div>

          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px; border-bottom:1px solid rgba(168,85,247,0.15); padding-bottom:18px;">
            <div>
              <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                <h3 style="font-size:20px; font-weight:900; color:#ffffff;">{smc_name}</h3>
                <span style="padding:3px 10px; border-radius:6px; background:rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3); font-size:11px; font-weight:bold; font-family:monospace;">🟢 Active & Subscribed</span>
                <span style="padding:3px 10px; border-radius:6px; background:rgba(168,85,247,0.15); color:#d8b4fe; border:1px solid rgba(168,85,247,0.3); font-size:11px; font-weight:bold; font-family:monospace;">{smc_sym}</span>
                <span style="padding:3px 10px; border-radius:6px; background:#120d24; color:#94a3b8; border:1px solid rgba(168,85,247,0.2); font-size:11px; font-family:monospace;">{smc_tf}</span>
              </div>
              <p style="font-size:12px; color:#cbd5e1; margin-top:8px; line-height:1.5; max-width:850px;">
                {smc_desc}
              </p>
            </div>

            <!-- Capital Limit & Customize Button -->
            <div style="background:#090714; border:1px solid rgba(168,85,247,0.25); border-radius:12px; padding:14px 20px; text-align:right; min-width:210px;">
              <div style="font-size:10px; text-transform:uppercase; color:#94a3b8; font-weight:bold; letter-spacing:0.04em;">Allocated Capital Cap</div>
              <div style="font-size:22px; font-weight:900; color:#ffffff; font-family:monospace; margin-top:2px;">
                ₹{int(smc_cap_inr):,} <span style="font-size:11px; font-weight:normal; color:#c084fc;">(${smc_cap_usd:.2f})</span>
              </div>
              <button onclick="promptCustomizeCapital('{smc_id}', {smc_cap_inr})" style="margin-top:8px; width:100%; padding:6px 12px; font-size:11px; font-weight:bold; border-radius:6px; background:#18112d; border:1px solid rgba(168,85,247,0.4); color:#e879f9; cursor:pointer; transition:all 0.2s;" onmouseover="this.style.background='rgba(217,70,239,0.2)';" onmouseout="this.style.background='#18112d';">
                ✏️ Customize Capital
              </button>
            </div>
          </div>

          <!-- Strategy Key Parameters & Targets Grid -->
          <div style="margin-top:20px; display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px; background:#07050e; padding:16px; border-radius:10px; border:1px solid rgba(168,85,247,0.12); text-align:center;">
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">TP1 (60% Profit Lock)</div>
              <div style="font-size:16px; font-weight:bold; color:#34d399; font-family:monospace; margin-top:2px;">+{smc_tp1}%</div>
              <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Nearest Liquidity</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">TP2 (40% Runner)</div>
              <div style="font-size:16px; font-weight:bold; color:#c084fc; font-family:monospace; margin-top:2px;">+{smc_tp2}%</div>
              <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Major Swing Sweep</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Stop Loss</div>
              <div style="font-size:16px; font-weight:bold; color:#f87171; font-family:monospace; margin-top:2px;">-{smc_sl}%</div>
              <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Invalidation Level</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Fib Golden Zone</div>
              <div style="font-size:16px; font-weight:bold; color:#fbbf24; font-family:monospace; margin-top:2px;">{smc_fib}</div>
              <div style="font-size:10px; color:#94a3b8; margin-top:2px;">1H Retracement</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; text-transform:uppercase;">Confluence Threshold</div>
              <div style="font-size:16px; font-weight:bold; color:#38bdf8; font-family:monospace; margin-top:2px;">{smc_conf}/100</div>
              <div style="font-size:10px; color:#94a3b8; margin-top:2px;">High-Probability Entry</div>
            </div>
          </div>

          <!-- Strategy Performance Metrics Bar -->
          <div style="margin-top:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; padding:12px 16px; background:#0b0816; border-radius:8px; border:1px solid rgba(168,85,247,0.1); font-size:11px; font-family:monospace;">
            <div style="display:flex; align-items:center; gap:20px; flex-wrap:wrap;">
              <span style="color:#94a3b8;">Win Rate: <strong style="color:#ffffff;">{smc_wr:.1f}%</strong></span>
              <span style="color:#94a3b8;">Trades Executed: <strong style="color:#ffffff;">{smc_trades_cnt}</strong> ({smc_wins}W / {smc_losses}L)</span>
              <span style="color:#94a3b8;">Simulated P&L: <strong style="color:{smc_pnl_col};">{smc_pnl_str}</strong></span>
              <span style="color:#94a3b8;">Profit Factor: <strong style="color:#c084fc;">{smc_pf:.2f}x</strong></span>
            </div>
            <button onclick="switchStrategySubTab('lab')" style="padding:6px 14px; border-radius:6px; background:#1b1430; border:1px solid rgba(168,85,247,0.3); color:#cbd5e1; cursor:pointer; font-size:11px;">
              ⚙️ Tune Parameters in Lab &rarr;
            </button>
          </div>
        </div>

        <!-- Dhurandhar Strategy Card (Delta Exchange India) -->
        <div class="nexora-card" style="padding:28px; margin-bottom:24px; border-color:rgba(167,139,250,0.4); position:relative; overflow:hidden;">
          <div style="position:absolute; top:-20px; right:-20px; width:140px; height:140px; background:rgba(167,139,250,0.12); border-radius:50%; filter:blur(40px); pointer-events:none;"></div>

          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px; border-bottom:1px solid rgba(167,139,250,0.2); padding-bottom:18px;">
            <div>
              <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                <h3 style="font-size:20px; font-weight:900; color:#ffffff;">Dhurandhar Strategy</h3>
                <span style="padding:3px 10px; border-radius:6px; background:rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3); font-size:11px; font-weight:bold; font-family:monospace;">🟢 Active & Subscribed</span>
                <span style="padding:3px 10px; border-radius:6px; background:rgba(167,139,250,0.15); color:#a78bfa; border:1px solid rgba(167,139,250,0.3); font-size:11px; font-weight:bold; font-family:monospace;">Delta Exchange Testnet</span>
                <span style="padding:3px 10px; border-radius:6px; background:#120d24; color:#94a3b8; border:1px solid rgba(167,139,250,0.2); font-size:11px; font-family:monospace;">24H Rolling + Monthly Options</span>
              </div>
              <p style="font-size:12px; color:#cbd5e1; margin-top:8px; line-height:1.5; max-width:850px;">
                Pushkar Raj Thakur Method — Leg 1: 24H High/Low Breakout Futures Trend Hunter + Leg 2: OTM Options Strangle Selling (~12% OTM) for Theta Decay profit on Delta Exchange.
              </p>
            </div>

            <!-- Capital & Platform Badge -->
            <div style="background:#090714; border:1px solid rgba(167,139,250,0.3); border-radius:12px; padding:14px 20px; text-align:right; min-width:210px;">
              <div style="font-size:10px; text-transform:uppercase; color:#94a3b8; font-weight:bold; letter-spacing:0.04em;">Platform & Allocation</div>
              <div style="font-size:18px; font-weight:900; color:#a78bfa; font-family:monospace; margin-top:2px;">
                Delta India Demo
              </div>
              <div style="font-size:11px; color:#34d399; font-weight:bold; margin-top:4px;">
                Paper Trading Sandbox
              </div>
            </div>
          </div>

          <!-- Live Dhurandhar Control Panel Body (Populated by JS) -->
          <div id="dhurandhar-panel-body" style="margin-top:20px; min-height:120px;">
            <div style="color:#94a3b8; padding:20px; text-align:center; font-family:monospace;">Loading Dhurandhar Live Data...</div>
          </div>
        </div>

        <!-- Strategy Expansion Pipeline Placeholder Card -->
        <div class="nexora-card" style="padding:22px; border-style:dashed; border-color:rgba(168,85,247,0.25); background:rgba(7,5,14,0.6); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:14px;">
          <div style="display:flex; align-items:center; gap:14px;">
            <div style="width:42px; height:42px; border-radius:10px; background:#110d22; border:1px dashed rgba(168,85,247,0.4); display:flex; align-items:center; justify-content:center; font-size:20px;">
              🚀
            </div>
            <div>
              <div style="font-size:14px; font-weight:bold; color:#ffffff;">Algorithmic Strategy Pipeline</div>
              <div style="font-size:11px; color:#94a3b8; margin-top:2px;">Currently running 2 active institutional strategies (SMC 60/40 Engine + Dhurandhar Delta Strategy). Additional custom strategies will appear here.</div>
            </div>
          </div>
          <button onclick="switchStrategySubTab('lab')" style="padding:8px 16px; font-size:11px; font-weight:bold; border-radius:8px; background:#161026; color:#d8b4fe; border:1px solid rgba(168,85,247,0.3); cursor:pointer;">
            🧪 Open Strategy Lab
          </button>
        </div>

      </div> <!-- END SUB-SECTION 1: SUBSCRIBED STRATEGY -->

      <!-- ============================================== -->
      <!-- SUB-SECTION 2: STRATEGY LAB (PARAMETERS TUNING) -->
      <!-- ============================================== -->
      <div id="strat-sub-section-lab" style="display:none;">

        <!-- Strategy Lab Parameter Tuning Card -->
        <div class="nexora-card" style="padding:28px; margin-bottom:24px; border-color:rgba(217,70,239,0.35);">
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(168,85,247,0.14); padding-bottom:14px;">
            <div>
              <h3 style="font-size:18px; font-weight:900; color:#ffffff; display:flex; align-items:center; gap:8px;">
                <span>🧪</span> Strategy Parameter Calibration Lab
              </h3>
              <p style="font-size:11px; color:#94a3b8; margin-top:3px;">
                Fine-tune targets, risk parameters, and execution rules for the active institutional strategy coded in Antigravity.
              </p>
            </div>
            <span style="font-size:10px; font-weight:bold; color:#d946ef; background:rgba(217,70,239,0.15); border:1px solid rgba(217,70,239,0.3); padding:4px 10px; border-radius:6px;">LIVE PARAMETER TUNER</span>
          </div>

          <!-- Strategy Selection Bar -->
          <div style="margin-top:18px; background:#07050e; padding:12px 16px; border-radius:8px; border:1px solid rgba(168,85,247,0.15); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:11px; color:#94a3b8; font-weight:bold; text-transform:uppercase;">Configuring Strategy:</span>
              <span style="font-size:13px; font-weight:bold; color:#ffffff;">{smc_name}</span>
              <span style="font-size:10px; font-family:monospace; padding:2px 8px; border-radius:4px; background:rgba(168,85,247,0.15); color:#d8b4fe;">{smc_sym}</span>
            </div>
            <div style="font-size:11px; color:#34d399; font-family:monospace;">
              Single Authentic Model • ID: {smc_id}
            </div>
          </div>

          <!-- Parameter Fields Form Grid -->
          <div style="margin-top:18px; display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:16px;">
            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">Capital Limit (₹ INR)</label>
              <input id="lab-strat-cap" type="number" value="{int(smc_cap_inr)}" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">Max margin available for this strategy.</span>
            </div>

            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">Execution Timeframe</label>
              <select id="lab-strat-tf" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;">
                <option value="1h (Macro) + 5m (Entry)" selected>1h (Macro) + 5m (Entry) [Default]</option>
                <option value="4h (Macro) + 15m (Entry)">4h (Macro) + 15m (Entry)</option>
                <option value="15m (Macro) + 1m (Entry)">15m (Macro) + 1m (Entry - Scalping)</option>
              </select>
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">Macro trend filter + micro entry sweep.</span>
            </div>

            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">TP1 Target (% Gain)</label>
              <input id="lab-strat-tp1" type="number" step="0.1" value="{smc_tp1}" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">60% position booked at nearest liquidity.</span>
            </div>

            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">TP2 Target (% Gain)</label>
              <input id="lab-strat-tp2" type="number" step="0.1" value="{smc_tp2}" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">40% runner to major swing target.</span>
            </div>

            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">Stop Loss (% Loss)</label>
              <input id="lab-strat-sl" type="number" step="0.1" value="{smc_sl}" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">Invalidation level below liquidity sweep.</span>
            </div>

            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">Confluence Threshold (0-100)</label>
              <input id="lab-strat-conf" type="number" min="50" max="100" value="{smc_conf}" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">Minimum score required to trigger entry.</span>
            </div>

            <div>
              <label style="display:block; font-size:10px; font-weight:bold; color:#cbd5e1; text-transform:uppercase; margin-bottom:5px;">Fib Golden Zone Range</label>
              <input id="lab-strat-fib" type="text" value="{smc_fib}" style="width:100%; padding:10px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b; margin-top:2px; display:block;">Institutional retracement sweep zone.</span>
            </div>
          </div>

          <!-- Action Buttons -->
          <div style="margin-top:24px; display:flex; gap:12px; flex-wrap:wrap;">
            <button onclick="saveStrategyParameters('{smc_id}')" class="btn-glow-purple" style="flex:1.5; padding:12px 20px; font-size:12px; font-weight:bold; display:flex; align-items:center; justify-content:center; gap:8px;">
              <span>💾</span> Save Strategy Parameters to Engine
            </button>
            <button onclick="runSimulation('{smc_id}', this)" style="flex:1; padding:12px 20px; border-radius:8px; background:#150f29; border:1px solid rgba(168,85,247,0.35); color:#e2e8f0; font-size:12px; font-weight:bold; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:8px; transition:all 0.2s;" onmouseover="this.style.background='rgba(168,85,247,0.2)';" onmouseout="this.style.background='#150f29';">
              <span>▶️</span> Run Paper Simulation Test
            </button>
          </div>
        </div>

      </div> <!-- END SUB-SECTION 2: STRATEGY LAB -->

    </div> <!-- END VIEW-STRATEGIES -->

    <!-- ============================================== -->
    <!-- VIEW-PORTFOLIO: BINANCE WALLET & ASSET ALLOCATION -->
    <!-- ============================================== -->
    <div id="view-portfolio" style="display:none;">
      <!-- Greeting / Summary Bar -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:12px;">
        <div>
          <h1 style="font-size:24px; font-weight:900; color:#ffffff; letter-spacing:-0.02em;">Binance Wallet & Portfolio 💼</h1>
          <p style="font-size:12px; color:#94a3b8; margin-top:4px;">Real-time asset holdings, isolated strategy allocations, and margin utilization.</p>
        </div>
        <div style="text-align:right; font-size:12px; color:#64748b; font-family:monospace;">
          Live Spot Account • Auto-synced
        </div>
      </div>

      <!-- Portfolio Top 4 Asset Cards -->
      <section style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:18px; margin-bottom:24px;">
        <!-- Asset 1: USDT Free Reserve -->
        <div class="nexora-card" style="padding:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
            <span>Free USDT Margin</span>
            <span style="color:#34d399; font-weight:bold;">Available</span>
          </div>
          <div id="port-usdt-val" style="font-size:26px; font-weight:900; color:#ffffff; margin-top:8px; font-family:monospace;">
            ${live_bal['usdt_free']:,.2f}
          </div>
          <div id="port-usdt-sub" style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px; color:#94a3b8;">
            Ready for strategy orders
          </div>
        </div>

        <!-- Asset 2: BTC Holdings -->
        <div class="nexora-card" style="padding:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
            <span>Bitcoin (BTC)</span>
            <span style="color:#fbbf24; font-weight:bold;">Spot Asset</span>
          </div>
          <div id="port-btc-val" style="font-size:26px; font-weight:900; color:#fbbf24; margin-top:8px; font-family:monospace;">
            {live_bal['btc_free']:.4f} BTC
          </div>
          <div style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px; color:#94a3b8;">
            Primary SMC Trading Pair
          </div>
        </div>

        <!-- Asset 3: ETH Holdings -->
        <div class="nexora-card" style="padding:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
            <span>Ethereum (ETH)</span>
            <span style="color:#c084fc; font-weight:bold;">Spot Asset</span>
          </div>
          <div id="port-eth-val" style="font-size:26px; font-weight:900; color:#c084fc; margin-top:8px; font-family:monospace;">
            {live_bal['eth_free']:.4f} ETH
          </div>
          <div style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px; color:#94a3b8;">
            Secondary Multi-Symbol Pair
          </div>
        </div>

        <!-- Asset 4: Strategy Allocation Status -->
        <div class="nexora-card" style="padding:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:#94a3b8;">
            <span>Total Isolated Margin</span>
            <span style="color:#d946ef;">🛡️ Protected</span>
          </div>
          <div id="port-margin-val" style="font-size:26px; font-weight:900; color:#e879f9; margin-top:8px; font-family:monospace;">
            ₹{int(total_allocated_inr):,}
          </div>
          <div id="port-margin-sub" style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(168,85,247,0.12); font-size:11px; color:#94a3b8;">
            Across {subscribed_count} Subscribed Strategies
          </div>
        </div>
      </section>

      <!-- Capital Isolation Table & Account Safety Details -->
      <section style="display:grid; grid-template-columns:2fr 1fr; gap:20px; margin-bottom:24px;">
        <div class="nexora-card" style="padding:24px;">
          <div style="font-size:16px; font-weight:bold; color:#ffffff; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px;">
            Strategy Budget & Margin Isolation Table
          </div>
          <div style="overflow-x:auto; margin-top:14px;">
            <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12px;">
              <thead>
                <tr style="border-bottom:1px solid rgba(168,85,247,0.15); font-size:10px; text-transform:uppercase; color:#64748b;">
                  <th style="padding:10px 8px;">Strategy</th>
                  <th style="padding:10px 8px;">Max Budget Cap</th>
                  <th style="padding:10px 8px;">Active Margin Used</th>
                  <th style="padding:10px 8px;">Available Margin</th>
                  <th style="padding:10px 8px; text-align:right;">Status</th>
                </tr>
              </thead>
              <tbody style="color:#cbd5e1;">
                {portfolio_strat_rows}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Account Health & Safety Gauges -->
        <div class="nexora-card" style="padding:24px; display:flex; flex-direction:column; justify-content:space-between;">
          <div>
            <div style="font-size:16px; font-weight:bold; color:#ffffff; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px;">
              Account Risk Controls
            </div>
            <div style="margin-top:16px; display:flex; flex-direction:column; gap:12px; font-size:12px;">
              <div style="display:flex; justify-content:space-between; align-items:center; background:#07050e; padding:10px 12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
                <span style="color:#94a3b8;">Trading Leverage:</span>
                <span style="color:#34d399; font-weight:bold; font-family:monospace;">1x Spot (Zero Liquidation)</span>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; background:#07050e; padding:10px 12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
                <span style="color:#94a3b8;">Circuit Breaker Limit:</span>
                <span style="color:#f87171; font-weight:bold; font-family:monospace;">-${MAX_DAILY_LOSS_CIRCUIT_USD:.2f} Max Daily Loss</span>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; background:#07050e; padding:10px 12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
                <span style="color:#94a3b8;">Active Open Margin:</span>
                <span style="color:#d8b4fe; font-weight:bold; font-family:monospace;">${open_margin_usd:,.2f} USD</span>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; background:#07050e; padding:10px 12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
                <span style="color:#94a3b8;">Binance Testnet Status:</span>
                <span style="color:#34d399; font-weight:bold; font-family:monospace;">Connected & Synced</span>
              </div>
            </div>
          </div>
          <div style="margin-top:16px; font-size:11px; color:#64748b; text-align:center;">
            Capital isolation prevents any single strategy from consuming full account balance.
          </div>
        </div>
      </section>
    </div> <!-- END VIEW-PORTFOLIO -->

    <!-- ============================================== -->
    <!-- VIEW-SETTINGS: SYSTEM ENGINE & RISK SETTINGS   -->
    <!-- ============================================== -->
    <div id="view-settings" style="display:none;">
      <!-- Greeting -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; flex-wrap:wrap; gap:12px;">
        <div>
          <h1 style="font-size:24px; font-weight:900; color:#ffffff; letter-spacing:-0.02em;">System Engine Settings ⚙️</h1>
          <p style="font-size:12px; color:#94a3b8; margin-top:4px;">Customize risk parameters, AI brain filters, execution intervals, and safety thresholds.</p>
        </div>
      </div>

      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:20px; margin-bottom:24px;">
        <!-- Risk Engine Card -->
        <div class="nexora-card" style="padding:24px;">
          <div style="font-size:16px; font-weight:bold; color:#ffffff; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px; display:flex; align-items:center; gap:8px;">
            <span>🛡️</span> Risk & Circuit Breaker Engine
          </div>
          <div style="margin-top:16px; display:flex; flex-direction:column; gap:16px;">
            <div>
              <label style="display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">
                <span>Daily Max Loss Circuit Breaker ($ USD)</span>
                <span id="display-max-loss" style="color:#f87171; font-family:monospace;">${MAX_DAILY_LOSS_CIRCUIT_USD:.2f}</span>
              </label>
              <input id="setting-max-loss" type="number" step="5" value="{int(MAX_DAILY_LOSS_CIRCUIT_USD)}" style="width:100%; padding:9px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b;">If cumulative losses hit this threshold today, bot halts trading instantly.</span>
            </div>

            <div>
              <label style="display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">
                <span>Min AI Brain Confidence (1 - 10)</span>
                <span style="color:#c084fc; font-family:monospace;">{MIN_CONFIDENCE}/10</span>
              </label>
              <input id="setting-min-conf" type="number" min="1" max="10" value="{MIN_CONFIDENCE}" style="width:100%; padding:9px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b;">Trades below this AI conviction score are skipped.</span>
            </div>

            <div>
              <label style="display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">
                <span>Max Concurrent Open Positions</span>
                <span style="color:#34d399; font-family:monospace;">{MAX_OPEN_POSITIONS}</span>
              </label>
              <input id="setting-max-pos" type="number" min="1" max="10" value="{MAX_OPEN_POSITIONS}" style="width:100%; padding:9px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b;">Maximum simultaneous trades allowed across BTC, ETH, and SOL.</span>
            </div>

            <div>
              <label style="display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">
                <span>Target Trade Notional ($ USD)</span>
                <span id="display-target-notional" style="color:#38bdf8; font-family:monospace;">${TARGET_NOTIONAL_USD:.2f}</span>
              </label>
              <input id="setting-target-notional" type="number" step="10" min="15" max="2000" value="{int(TARGET_NOTIONAL_USD)}" style="width:100%; padding:9px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b;">Position size in USD per trade (e.g. $100 yields ~$1.50 - $4.00 profit per trade).</span>
            </div>

            <div>
              <label style="display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:#cbd5e1; margin-bottom:6px;">
                <span>Cooldown Duration After Loss (Seconds)</span>
                <span style="color:#d8b4fe; font-family:monospace;">{LOSS_COOLDOWN_SECONDS}s ({LOSS_COOLDOWN_SECONDS // 60}m)</span>
              </label>
              <input id="setting-cooldown" type="number" step="60" value="{LOSS_COOLDOWN_SECONDS}" style="width:100%; padding:9px 12px; background:#07050e; border:1px solid rgba(168,85,247,0.25); border-radius:8px; color:#ffffff; font-size:12px; outline:none;" />
              <span style="font-size:10px; color:#64748b;">Protects against emotional revenge trading and volatile chop.</span>
            </div>

            <button onclick="saveEngineSettings()" class="btn-glow-purple" style="padding:10px; font-size:12px; width:100%; display:flex; align-items:center; justify-content:center; gap:8px;">
              <span>💾</span> Save Risk Parameters
            </button>
          </div>
        </div>

        <!-- Engine Connectivity & API Status Card -->
        <div class="nexora-card" style="padding:24px;">
          <div style="font-size:16px; font-weight:bold; color:#ffffff; border-bottom:1px solid rgba(168,85,247,0.12); padding-bottom:12px; display:flex; align-items:center; gap:8px;">
            <span>⚡</span> API & Infrastructure Connectivity
          </div>

          <div style="margin-top:16px; display:flex; flex-direction:column; gap:14px; font-size:12px;">
            <div style="background:#07050e; padding:12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
              <div style="font-weight:bold; color:#ffffff;">Binance API Testnet</div>
              <div style="font-size:11px; color:#34d399; margin-top:2px;">🟢 Connected & Synced</div>
              <div style="font-size:10px; color:#64748b; font-family:monospace; margin-top:4px;">Endpoint: testnet.binance.vision</div>
            </div>

            <div style="background:#07050e; padding:12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
              <div style="font-weight:bold; color:#ffffff;">Groq Cloud LLM Brain</div>
              <div style="font-size:11px; color:#c084fc; margin-top:2px;">🧠 Active (Llama 3.3 70B Versatile)</div>
              <div style="font-size:10px; color:#64748b; font-family:monospace; margin-top:4px;">Role: Market Structure & SMC Liquidity Evaluator</div>
            </div>

            <div style="background:#07050e; padding:12px; border-radius:8px; border:1px solid rgba(168,85,247,0.12);">
              <div style="font-weight:bold; color:#ffffff;">HTTP Web Dashboard Server</div>
              <div style="font-size:11px; color:#34d399; margin-top:2px;">🟢 Running on Port 10000</div>
              <div style="font-size:10px; color:#64748b; font-family:monospace; margin-top:4px;">Auto-refresh interval: 25 seconds</div>
            </div>

            <div style="margin-top:6px; display:flex; gap:10px;">
              <button onclick="syncLedgerFromBinance()" style="flex:1; padding:9px 12px; font-size:11px; font-weight:bold; border-radius:8px; background:#161026; color:#e2e8f0; border:1px solid rgba(168,85,247,0.3); cursor:pointer;">
                🔄 Sync Binance Ledger
              </button>
              <button onclick="triggerKillSwitch()" style="flex:1; padding:9px 12px; font-size:11px; font-weight:bold; border-radius:8px; background:linear-gradient(135deg, #ef4444, #b91c1c); color:#ffffff; border:none; cursor:pointer;">
                🛑 Emergency Kill Switch
              </button>
            </div>
          </div>
        </div>
      </div>
    </div> <!-- END VIEW-SETTINGS -->

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

def check_circuit_breaker():
    global BOT_HALTED, HALT_REASON, CIRCUIT_TRIPPED
    if BOT_HALTED:
        return True
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        ledger = []
        ledger_file = os.path.join(BASE_DIR, "ledger.json")
        if os.path.exists(ledger_file):
            with open(ledger_file, "r") as f:
                ledger = json.load(f)
        today_pnl = sum(float(t.get("pnl", 0.0)) for t in ledger if isinstance(t, dict) and t.get("status") in ["closed_tp", "closed_sl", "closed_manual", "closed"] and t.get("timestamp", "").startswith(today_str))
        if today_pnl <= -MAX_DAILY_LOSS_CIRCUIT_USD:
            CIRCUIT_TRIPPED = True
            logger.critical(f"🛑 [CIRCUIT BREAKER TRIPPED] Today's loss (${today_pnl:.2f}) reached limit (-${MAX_DAILY_LOSS_CIRCUIT_USD:.2f}). Halting bot immediately!")
            emergency_kill_switch(f"Daily Circuit Breaker Tripped! Today Loss: ${today_pnl:.2f}")
            return True
    except Exception as e:
        logger.warning(f"Circuit breaker check error: {e}")
    return False

def emergency_kill_switch(reason="Manual Emergency Kill Switch Triggered"):
    global BOT_HALTED, HALT_REASON
    BOT_HALTED = True
    HALT_REASON = reason
    logger.warning(f"🛑 [KILL SWITCH ACTIVATED] Reason: {reason}. Liquidating positions on Binance...")
    
    open_trades = get_open_trades()
    closed_count = 0
    errors = []
    for trade in open_trades:
        sym = trade.get("symbol", PRIMARY_SYMBOL)
        try:
            curr_price = get_current_price(sym)
        except Exception:
            curr_price = float(trade.get("entry_price", 0))
        success = close_open_position(trade, curr_price, f"Kill Switch: {reason}", "kill_switch", is_loss=False)
        if success:
            closed_count += 1
        else:
            errors.append(f"Failed to close #{trade.get('trade_id')} ({sym})")
            
    try:
        state_file = os.path.join(BASE_DIR, "market_state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                s = json.load(f)
            s["action"] = "HALTED"
            s["reason"] = f"🛑 BOT HALTED: {reason}"
            with open(state_file, "w") as f:
                json.dump(s, f, indent=2)
    except Exception:
        pass
        
    return {
        "success": True,
        "halted": True,
        "closed_count": closed_count,
        "errors": errors,
        "message": f"Emergency Kill Switch Activated! {closed_count} position(s) closed on Binance. Engine is HALTED."
    }

def resume_bot_trading():
    global BOT_HALTED, HALT_REASON, CIRCUIT_TRIPPED
    BOT_HALTED = False
    CIRCUIT_TRIPPED = False
    HALT_REASON = ""
    logger.info("▶️ [BOT RESUMED] Trading engine resumed by user.")
    try:
        state_file = os.path.join(BASE_DIR, "market_state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                s = json.load(f)
            s["action"] = "ACTIVE"
            s["reason"] = "Bot engine resumed. Scanning markets for setups..."
            with open(state_file, "w") as f:
                json.dump(s, f, indent=2)
    except Exception:
        pass
    return {"success": True, "halted": False, "message": "Bot resumed successfully! Active market scanning re-enabled."}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)

        # API: Server Public IP (for Delta Exchange whitelist)
        if parsed.path == "/ip":
            try:
                import requests as _r
                public_ip = _r.get('https://api.ipify.org', timeout=5).text.strip()
            except Exception:
                public_ip = "Could not detect"
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""<!DOCTYPE html><html><body style="font-family:monospace;background:#0f172a;color:#f1f5f9;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column">
<h2 style="color:#94a3b8">&#x1F310; Server Public IP</h2>
<div style="background:#1e293b;border:2px solid #3b82f6;border-radius:12px;padding:32px 48px;font-size:2rem;color:#38bdf8;letter-spacing:2px">{public_ip}</div>
<p style="color:#64748b;margin-top:16px">Add this IP to Delta Exchange API Key whitelist</p>
<p style="color:#475569;font-size:0.8rem">Delta Exchange &rarr; API Keys &rarr; NexoraBot &rarr; Edit (&#9998;) &rarr; Add this IP</p>
</body></html>"""
            self.wfile.write(html.encode('utf-8'))
            return

        # API: Emergency Kill Switch
        if parsed.path == "/api/kill_switch":
            res = emergency_kill_switch("Triggered from Web Dashboard")
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        # API: Resume Bot Trading
        if parsed.path == "/api/resume_bot":
            res = resume_bot_trading()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        # API: Bot Engine Live Status
        if parsed.path == "/api/bot_status":
            live_bal = get_live_account_balance()
            open_trades = get_open_trades()
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            status_data = {
                "halted": BOT_HALTED,
                "circuit_tripped": CIRCUIT_TRIPPED,
                "reason": HALT_REASON,
                "open_trades_count": len(open_trades),
                "usdt_balance": live_bal.get("usdt_free", 0.0),
                "btc_balance": live_bal.get("btc_free", 0.0)
            }
            self.wfile.write(json.dumps(status_data).encode('utf-8'))
            return

        # API: Dhurandhar Strategy - Live Snapshot
        if parsed.path == "/api/dhurandhar/status":
            try:
                import strategy_dhurandhar
                snap = strategy_dhurandhar.get_live_snapshot()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(snap).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # API: Halt Dhurandhar Strategy
        if parsed.path == "/api/dhurandhar/halt":
            try:
                import strategy_dhurandhar
                strategy_dhurandhar.halt_strategy("Halted from dashboard")
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Dhurandhar strategy halted."}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # API: Resume Dhurandhar Strategy
        if parsed.path == "/api/dhurandhar/resume":
            try:
                import strategy_dhurandhar
                strategy_dhurandhar.resume_strategy()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Dhurandhar strategy resumed."}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # API: Update Engine Settings
        if parsed.path == "/api/settings/update":
            try:
                qs = parse_qs(parsed.query)
                global MAX_DAILY_LOSS_CIRCUIT_USD, MIN_CONFIDENCE, MAX_OPEN_POSITIONS, LOSS_COOLDOWN_SECONDS, TARGET_NOTIONAL_USD
                if "max_loss" in qs:
                    MAX_DAILY_LOSS_CIRCUIT_USD = float(qs["max_loss"][0])
                if "min_conf" in qs:
                    MIN_CONFIDENCE = int(qs["min_conf"][0])
                if "max_pos" in qs:
                    MAX_OPEN_POSITIONS = int(qs["max_pos"][0])
                if "cooldown" in qs:
                    LOSS_COOLDOWN_SECONDS = int(qs["cooldown"][0])
                if "target_notional" in qs:
                    TARGET_NOTIONAL_USD = float(qs["target_notional"][0])
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Risk engine parameters saved successfully!"}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                return

        # API: Sync Ledger with Binance Trades
        if parsed.path == "/api/sync_ledger":
            try:
                from memory import sync_ledger_from_binance
                sync_ledger_from_binance()
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Ledger synced successfully with Binance Testnet trades!"}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
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

        # API: Strategy Lab Endpoints
        if parsed.path.startswith("/api/strategies"):
            try:
                import strategy_lab
                qs = parse_qs(parsed.query)
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()

                if parsed.path == "/api/strategies":
                    strats = strategy_lab.load_strategies()
                    self.wfile.write(json.dumps({"success": True, "strategies": strats}).encode('utf-8'))
                    return

                elif parsed.path == "/api/strategies/create":
                    name = qs.get("name", ["Unnamed Strategy"])[0]
                    symbol = qs.get("symbol", ["BTCUSDT"])[0]
                    tf = qs.get("timeframe", ["5m"])[0]
                    cap = float(qs.get("capital_cap", [10000])[0])
                    tp1 = float(qs.get("tp1", [1.5])[0])
                    tp2 = float(qs.get("tp2", [3.0])[0])
                    sl = float(qs.get("sl", [1.0])[0])
                    desc = qs.get("desc", [""])[0]
                    new_s = strategy_lab.create_strategy(name, symbol, tf, cap, tp1, tp2, sl, desc)
                    self.wfile.write(json.dumps({"success": True, "strategy": new_s}).encode('utf-8'))
                    return

                elif parsed.path == "/api/strategies/promote":
                    s_id = qs.get("id", [""])[0]
                    cap = float(qs.get("cap", [10000])[0])
                    success, msg = strategy_lab.promote_to_live(s_id, cap)
                    self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
                    return

                elif parsed.path == "/api/strategies/demote":
                    s_id = qs.get("id", [""])[0]
                    success, msg = strategy_lab.demote_to_test(s_id)
                    self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
                    return

                elif parsed.path == "/api/strategies/delete":
                    s_id = qs.get("id", [""])[0]
                    success, msg = strategy_lab.delete_strategy(s_id)
                    self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
                    return

                elif parsed.path == "/api/strategies/simulate":
                    s_id = qs.get("id", ["strat_smc_institutional"])[0]
                    success, res = strategy_lab.run_paper_simulation(s_id)
                    payload = {"success": success, "result": res if success else {}, "message": str(res) if not success else ""}
                    self.wfile.write(json.dumps(payload).encode('utf-8'))
                    return

                elif parsed.path == "/api/strategies/update_params":
                    s_id = qs.get("id", ["strat_smc_institutional"])[0]
                    params = {}
                    if "cap" in qs:
                        params["capital_cap_inr"] = float(qs["cap"][0])
                    if "tp1" in qs:
                        params["tp1_pct"] = float(qs["tp1"][0])
                    if "tp2" in qs:
                        params["tp2_pct"] = float(qs["tp2"][0])
                    if "sl" in qs:
                        params["sl_pct"] = float(qs["sl"][0])
                    if "timeframe" in qs:
                        params["timeframe"] = qs["timeframe"][0]
                    if "confluence" in qs:
                        params["confluence_threshold"] = int(qs["confluence"][0])
                    if "fib" in qs:
                        params["fib_golden_zone"] = qs["fib"][0]
                    success, msg = strategy_lab.update_strategy_parameters(s_id, params)
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
CHECK_INTERVAL_SECONDS = 60         # 60s fast scan (reduced from 300s to capture SMC setups promptly)
MAX_TRADES_PER_DAY = 15             # Increased from 10 to allow active trading
LOSS_COOLDOWN_SECONDS = 180         # 3-min cooldown after a loss (bypassed if Grade-A+ setup)
PROFIT_COOLDOWN_SECONDS = 30        # 30-second buffer after a win
MIN_CONFIDENCE = 5                  # Min Brain confidence 5/10 (reduced from 6)
MAX_DRAWDOWN_USD = 50.0             # Scaled to account size ($9,980+ USDT)
MAX_OPEN_POSITIONS = 3

TARGET_NOTIONAL_USD = 100.0         # $100 entry -> 60% TP1 is $60.00, 40% TP2 is $40.00 (Both >> $5 Binance MIN_NOTIONAL)

# State tracking
trades_today = 0
last_trade_time = None
last_trade_was_loss = False
last_reset_date = None

def get_position_size(symbol, entry_price, stop_loss, confidence):
    """
    Sizes position to approximately $100.00 notional:
    - 60% partial exit at TP1 = ~$60.00 (satisfies Binance $5 minNotional)
    - 40% runner exit at TP2 = ~$40.00 (satisfies Binance $5 minNotional)
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

    # 0. Safety Checks: Kill Switch & Daily Circuit Breaker
    if BOT_HALTED:
        logger.info("🛑 [BOT HALTED] Kill switch is active. Automated trading is paused.")
        return

    if check_circuit_breaker():
        return

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

    # 4. Strategy-Driven Execution Loop with Capital Isolation
    import strategy_lab
    live_strategies = strategy_lab.get_live_strategies()
    if not live_strategies:
        live_strategies = [{
            "id": "strat_default_smc",
            "name": "SMC Order Flow 60/40",
            "symbol": PRIMARY_SYMBOL,
            "timeframe": "5m",
            "capital_cap_inr": 10000.0,
            "capital_cap_usd": 120.0,
            "status": "active"
        }]

    for strat in live_strategies:
        if strat.get("status") != "active":
            continue

        strat_id = strat.get("id", "strat_default_smc")
        strat_name = strat.get("name", "SMC 60/40")
        strat_cap_usd = float(strat.get("capital_cap_usd", 120.0))
        
        # Determine target trading symbols for this strategy
        target_symbols = strat.get("symbols")
        if not target_symbols or not isinstance(target_symbols, list):
            raw_sym = strat.get("symbol", PRIMARY_SYMBOL)
            target_symbols = SYMBOLS if ("/" in raw_sym or "all" in raw_sym.lower()) else [raw_sym]

        for sym in target_symbols:
            if not sym or "/" in sym:
                continue
            if sym in open_symbols:
                continue
            if len(open_trades) >= MAX_OPEN_POSITIONS:
                break

            # Capital Isolation check: Ensure this strategy hasn't used up its isolated cap
            strat_active_trades = [t for t in open_trades if t.get("strategy_id") == strat_id]
            strat_margin_used = sum(float(t.get("quantity", 0)) * float(t.get("entry_price", 0)) for t in strat_active_trades)
            if strat_margin_used >= strat_cap_usd:
                logger.info(f"[{strat_name}] Capital isolation cap reached (${strat_margin_used:.2f}/${strat_cap_usd:.2f} max margin). Skipping new trades.")
                break

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
                logger.info(f"SCAN | [{strat_name}] {sym} | ${current_price:,.2f} | Score: {score}/100 | Brain: {action} ({confidence}/10)")

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

                    print(f"[BOT] Executing {action} on {sym} ({strat_name}) | Price: ${current_price:,.2f} | Qty: {position_size} | TP1: ${tp1:.2f} | TP2: ${tp2:.2f} | SL: ${stop_loss:.2f}")
                    order = place_test_order(symbol=sym, side=action, quantity=position_size)
                    trade_id = log_new_trade(
                        symbol=sym, side=action, entry_price=current_price,
                        quantity=position_size, reason=reason,
                        stop_loss=stop_loss, take_profit=tp2,
                        tp1=tp1, tp2=tp2,
                        strategy_name=strat_name, strategy_id=strat_id
                    )
                    trades_today += 1
                    last_trade_time = datetime.now()
                    logger.info(f"TRADE EXECUTED | #{trade_id} ({sym}) [{strat_name}] | {action} | ${current_price:,.2f} | Qty: {position_size}")
                    logger.info(f"SL: ${stop_loss:,.2f} | TP1 (60%): ${tp1:,.2f} | TP2 (40%): ${tp2:,.2f}")
                    write_learning(
                        f"New trade #{trade_id} [{strat_name}]: {action} {sym} at ${current_price} "
                        f"with SL=${stop_loss:.2f}, TP1=${tp1:.2f}, TP2=${tp2:.2f}. Reason: {reason}",
                        category="trade_open", trade_id=trade_id
                    )
                    break

            except Exception as e:
                logger.error(f"[ERROR] Cycle failed for {sym}: {e}")
                print(f"[BOT] ERROR in {sym} cycle: {e}")
                write_learning(f"Bot error for {sym}: {str(e)}", category="error")

    # ── DHURANDHAR STRATEGY (Delta Exchange Demo) ─────────────────────────────
    # Runs every cycle alongside Binance bot, completely independent.
    # LEG 1: 24H Trend Hunter (Futures) | LEG 2: OTM Option Selling (Strangle)
    try:
        import strategy_dhurandhar
        strategy_dhurandhar.run_dhurandhar_cycle()
    except Exception as e:
        logger.warning(f"[DHURANDHAR] Cycle error (non-fatal): {e}")



def main():
    print("\n" + "=" * 60)
    print("  NEXORA ALGO BOT v2.0 STARTING...")
    print("=" * 60)

    # ── Detect & log public IP (important for Delta Exchange API whitelist) ──
    try:
        import requests as _req
        public_ip = _req.get('https://api.ipify.org', timeout=5).text.strip()
        print(f"[MAIN] ✅ Server Public IP: {public_ip}")
        print(f"[MAIN] ⚠️  Add this IP to Delta Exchange API Key whitelist!")
        logger.info(f"Server Public IP: {public_ip} — Whitelist this in Delta Exchange")
    except Exception as _e:
        print(f"[MAIN] Could not detect public IP: {_e}")

    logger.info("=" * 50)
    logger.info("NEXORA ALGO BOT v2.0 STARTED")
    logger.info(f"Symbols: {', '.join(SYMBOLS)} | Check: {CHECK_INTERVAL_SECONDS}s | Min Confidence: {MIN_CONFIDENCE}")
    logger.info(f"Target Notional: ${TARGET_NOTIONAL_USD} | TP1: 60% Book | TP2: 40% Runner | SL: Structure")
    logger.info("=" * 50)

    print("[MAIN] Testing Binance API connection...")
    if not test_api_connection():
        logger.error("CRITICAL: Binance API connection test failed. Bot will not start.")
        print("[MAIN] CRITICAL: API test failed.")
        return

    print(f"[MAIN] API OK. Starting main loop (every {CHECK_INTERVAL_SECONDS}s)...")

    dash_port = int(os.environ.get("PORT", 10000))
    print(f"[MAIN] 🚀 Nexora Console running at http://0.0.0.0:{dash_port}")

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
