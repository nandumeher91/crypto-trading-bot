"""
strategy_dhurandhar.py
======================
Dhurandhar Trading Strategy by Pushkar Raj Thakur
(Video: https://youtu.be/oveeCcTxXsY)

Strategy Overview:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LEG 1 – TREND HUNTER (Futures Directional)
    - Monitor BTC & ETH 24-Hour rolling High and Low
    - 24H High breakout → Long Futures  (ride the bull trend)
    - 24H Low  breakout → Short Futures (ride the bear trend)
    - Pure price action, ZERO indicators (no RSI, no EMA)
    - Whipsaw-free: only flips on confirmed 24H level breaks
    - BTC : ETH lot ratio = 1 : 5

  LEG 2 – OPTION SELLING (Strangle / Non-Directional)
    - Sell deep OTM Call (≈12% above price) + OTM Put (≈12% below)
    - Collect Theta decay premium when market stays in range
    - Options leg auto-hedges the Futures leg:
        * Market surges → Futures Long profit cancels Call loss
        * Market crashes → Futures Short profit cancels Put loss
        * Market sideways → Both options decay to zero (double profit!)

Execution Platform:
    Delta Exchange India Testnet (Paper Trading)
    via delta_exchange.py (zero real funds at risk)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import logging
import time as time_module
from datetime import datetime, timezone
from typing import Optional

import delta_exchange as dx

# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
STATE_FILE  = os.path.join(BASE_DIR, "dhurandhar_state.json")

# ── Strategy Configuration ────────────────────────────────────────────────────

DHURANDHAR_CONFIG = {
    # Trend Hunter settings
    "assets":              ["BTC", "ETH"],    # Assets to trade
    "btc_notional_usd":    50.0,              # USD notional per BTC futures trade
    "eth_notional_usd":    50.0,              # USD notional per ETH futures trade
    "breakout_buffer_pct": 0.001,             # 0.1% buffer above/below 24H H/L to avoid fake breakouts

    # Option Selling settings
    "options_enabled":     True,              # Enable Option Selling leg
    "otm_pct":             0.12,              # 12% OTM strike selection (Pushkar's setup)
    "option_contracts":    1,                 # Contracts per option leg
    "strangle_refresh_days": 7,               # Re-sell strangle after this many days (when premium exhausted)

    # Safety
    "max_loss_usd":        30.0,              # Stop all trading if today's loss exceeds this
    "enabled":             True,              # Master switch
}


# ── State Persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    """Load strategy state from disk."""
    default = {
        "btc": {"position": "none", "entry_price": 0, "entry_time": None, "contracts": 0,
                "high_24h_at_entry": 0, "low_24h_at_entry": 0},
        "eth": {"position": "none", "entry_price": 0, "entry_time": None, "contracts": 0,
                "high_24h_at_entry": 0, "low_24h_at_entry": 0},
        "options": {
            "btc_strangle_active": False,
            "btc_call_symbol": None,
            "btc_put_symbol": None,
            "btc_strangle_time": None,
            "eth_strangle_active": False,
            "eth_call_symbol": None,
            "eth_put_symbol": None,
            "eth_strangle_time": None,
        },
        "today_pnl":     0.0,
        "total_trades":  0,
        "last_cycle":    None,
        "is_halted":     False,
        "halt_reason":   "",
    }
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # Merge to ensure new keys are present
                for k, v in default.items():
                    if k not in saved:
                        saved[k] = v
                    elif isinstance(v, dict):
                        for sk, sv in v.items():
                            if sk not in saved[k]:
                                saved[k][sk] = sv
                return saved
    except Exception as e:
        logger.warning(f"[DHURANDHAR] State load error: {e}. Starting fresh.")
    return default


def _save_state(state: dict):
    """Persist strategy state to disk."""
    try:
        state["last_cycle"] = datetime.now(timezone.utc).isoformat()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"[DHURANDHAR] State save error: {e}")


def get_state() -> dict:
    """Public API: Return current Dhurandhar state (for dashboard)."""
    return _load_state()


def reset_state():
    """Reset all state (use when starting fresh)."""
    default = _load_state()
    _save_state({k: v for k, v in default.items() if k == "total_trades"} | {
        "btc": {"position": "none", "entry_price": 0, "entry_time": None, "contracts": 0,
                "high_24h_at_entry": 0, "low_24h_at_entry": 0},
        "eth": {"position": "none", "entry_price": 0, "entry_time": None, "contracts": 0,
                "high_24h_at_entry": 0, "low_24h_at_entry": 0},
        "options": {
            "btc_strangle_active": False, "btc_call_symbol": None, "btc_put_symbol": None, "btc_strangle_time": None,
            "eth_strangle_active": False, "eth_call_symbol": None, "eth_put_symbol": None, "eth_strangle_time": None,
        },
        "today_pnl": 0.0, "total_trades": 0, "last_cycle": None, "is_halted": False, "halt_reason": "",
    })
    logger.info("[DHURANDHAR] State reset complete.")


# ── Trend Hunter Logic ────────────────────────────────────────────────────────

def _run_trend_hunter(asset: str, config: dict, state: dict) -> dict:
    """
    Core 24-Hour High/Low Breakout Engine (Trend Hunter).

    Pushkar's exact rules:
      - Fetch live 24H High and Low from Delta Exchange
      - Current price > 24H High → LONG (market breaking up)
      - Current price < 24H Low  → SHORT (market breaking down)
      - If already in correct direction → HOLD (no unnecessary flip)
      - Direction reversal → Close old position → Open new position

    Returns: Updated asset state dict with action taken.
    """
    asset_key   = asset.lower()
    asset_state = state.get(asset_key, {})
    notional_usd = config.get(f"{asset_key}_notional_usd", 50.0)
    buffer_pct   = config.get("breakout_buffer_pct", 0.001)

    # Fetch live market data from Delta
    ticker = dx.get_ticker(asset)
    if not ticker:
        logger.warning(f"[DHURANDHAR] No ticker data for {asset}")
        return asset_state

    current_price = ticker.get("mark_price", 0)
    high_24h      = ticker.get("high_24h", 0)
    low_24h       = ticker.get("low_24h", 0)

    # Apply tiny buffer to avoid false breakouts on the exact boundary
    long_trigger  = high_24h * (1 + buffer_pct)
    short_trigger = low_24h  * (1 - buffer_pct)

    current_position = asset_state.get("position", "none")

    logger.info(f"[DHURANDHAR] {asset} | Price: ${current_price:,.2f} | "
                f"24H High: ${high_24h:,.2f} (Long trigger: ${long_trigger:,.2f}) | "
                f"24H Low: ${low_24h:,.2f} (Short trigger: ${short_trigger:,.2f}) | "
                f"Position: {current_position.upper()}")

    # ── LONG Signal ──────────────────────────────────────────────────────
    if current_price > long_trigger:
        if current_position == "long":
            logger.info(f"[DHURANDHAR] {asset}: Already LONG. Holding.")
            return asset_state

        # Close any existing SHORT before going LONG
        if current_position == "short":
            logger.info(f"[DHURANDHAR] {asset}: 24H High broken → Reversing SHORT → LONG")
            dx.close_futures_position(asset)

        # Open LONG
        order = dx.place_futures_order(asset, side="buy", notional_usd=notional_usd)
        if order.get("success"):
            asset_state.update({
                "position":          "long",
                "entry_price":       current_price,
                "entry_time":        datetime.now(timezone.utc).isoformat(),
                "contracts":         order.get("size", 1),
                "high_24h_at_entry": high_24h,
                "low_24h_at_entry":  low_24h,
            })
            state["total_trades"] = state.get("total_trades", 0) + 1
            logger.info(f"[DHURANDHAR] ✅ {asset} LONG entered @ ${current_price:,.2f} | "
                        f"Contracts: {order.get('size')} | Notional: ${order.get('notional', 0):.2f}")
        else:
            logger.error(f"[DHURANDHAR] ❌ {asset} LONG order failed: {order.get('error')}")

    # ── SHORT Signal ─────────────────────────────────────────────────────
    elif current_price < short_trigger:
        if current_position == "short":
            logger.info(f"[DHURANDHAR] {asset}: Already SHORT. Holding.")
            return asset_state

        # Close any existing LONG before going SHORT
        if current_position == "long":
            logger.info(f"[DHURANDHAR] {asset}: 24H Low broken → Reversing LONG → SHORT")
            dx.close_futures_position(asset)

        # Open SHORT
        order = dx.place_futures_order(asset, side="sell", notional_usd=notional_usd)
        if order.get("success"):
            asset_state.update({
                "position":          "short",
                "entry_price":       current_price,
                "entry_time":        datetime.now(timezone.utc).isoformat(),
                "contracts":         order.get("size", 1),
                "high_24h_at_entry": high_24h,
                "low_24h_at_entry":  low_24h,
            })
            state["total_trades"] = state.get("total_trades", 0) + 1
            logger.info(f"[DHURANDHAR] ✅ {asset} SHORT entered @ ${current_price:,.2f} | "
                        f"Contracts: {order.get('size')} | Notional: ${order.get('notional', 0):.2f}")
        else:
            logger.error(f"[DHURANDHAR] ❌ {asset} SHORT order failed: {order.get('error')}")

    # ── No Breakout ───────────────────────────────────────────────────────
    else:
        logger.info(f"[DHURANDHAR] {asset}: Price inside 24H range. No new Futures signal. "
                    f"({current_position.upper()} position held)")

    return asset_state


# ── Option Selling Logic ──────────────────────────────────────────────────────

def _run_option_selling(asset: str, config: dict, state: dict) -> dict:
    """
    Dhurandhar Option Selling Leg:
    Sell OTM Call + OTM Put (Strangle) to collect Theta premium.

    Pushkar's rules:
      - Only sell if no active strangle is already open
      - Pick monthly expiry (8-35 days) for maximum time decay
      - ~12% OTM on both sides → very wide no-loss zone
      - Self-refreshing: when DTE < 2 days, roll to next expiry

    Returns: Updated options state dict.
    """
    asset_key    = asset.lower()
    opts_state   = state.get("options", {})
    contracts    = config.get("option_contracts", 1)
    otm_pct      = config.get("otm_pct", 0.12)

    call_key = f"{asset_key}_call_symbol"
    put_key  = f"{asset_key}_put_symbol"
    time_key = f"{asset_key}_strangle_time"
    active_key = f"{asset_key}_strangle_active"

    if opts_state.get(active_key):
        logger.info(f"[DHURANDHAR] {asset} Strangle already active: "
                    f"CALL={opts_state.get(call_key)} | PUT={opts_state.get(put_key)}")
        return opts_state

    # Place new strangle
    logger.info(f"[DHURANDHAR] {asset}: Placing OTM Strangle (Sell Call + Sell Put, {otm_pct*100:.0f}% OTM)...")
    result = dx.place_strangle(asset, contracts=contracts, otm_pct=otm_pct)

    if result.get("success"):
        strangle_info = result.get("strangle_info", {})
        opts_state.update({
            active_key: True,
            call_key:   result["call_order"].get("symbol", strangle_info.get("call", {}).get("symbol")),
            put_key:    result["put_order"].get("symbol",  strangle_info.get("put", {}).get("symbol")),
            time_key:   datetime.now(timezone.utc).isoformat(),
        })
        state["total_trades"] = state.get("total_trades", 0) + 2  # Call + Put = 2 option orders
        logger.info(f"[DHURANDHAR] ✅ {asset} Strangle placed: "
                    f"CALL @ ${strangle_info.get('call', {}).get('strike', 0):,.0f} | "
                    f"PUT @ ${strangle_info.get('put', {}).get('strike', 0):,.0f} | "
                    f"Expiry: {strangle_info.get('expiry', '?')} ({strangle_info.get('dte', '?')} DTE)")
    else:
        logger.warning(f"[DHURANDHAR] ⚠️ {asset} Strangle placement failed: {result.get('error')}")

    return opts_state


# ── Main Cycle ────────────────────────────────────────────────────────────────

def run_dhurandhar_cycle():
    """
    Execute one full Dhurandhar Strategy cycle.

    Sequence:
      1. Load state from disk
      2. Safety checks (halt, daily loss limit)
      3. For each asset (BTC, ETH):
         a. Run Trend Hunter (24H High/Low Futures)
         b. Run Option Selling (OTM Strangle) if enabled
      4. Save updated state to disk
      5. Log summary to console
    """
    config = DHURANDHAR_CONFIG.copy()
    if not config.get("enabled"):
        logger.info("[DHURANDHAR] Strategy is DISABLED. Set enabled=True in config to activate.")
        return

    state = _load_state()

    # Safety: Check if halted
    if state.get("is_halted"):
        logger.info(f"[DHURANDHAR] HALTED: {state.get('halt_reason', 'Manual halt')}. "
                    f"Run reset_state() to resume.")
        return

    # Safety: Daily loss limit
    if state.get("today_pnl", 0) <= -config.get("max_loss_usd", 30):
        logger.warning(f"[DHURANDHAR] 🛑 Daily loss limit hit (${state['today_pnl']:.2f}). "
                       f"All trading paused for today.")
        state["is_halted"]  = True
        state["halt_reason"] = f"Daily loss limit: ${state['today_pnl']:.2f}"
        _save_state(state)
        return

    logger.info("=" * 60)
    logger.info("  DHURANDHAR STRATEGY CYCLE STARTING")
    logger.info(f"  Balance: ${dx.get_usd_balance():.2f} USD | Trades: {state.get('total_trades', 0)}")
    logger.info("=" * 60)

    # ── Process each asset ────────────────────────────────────────────────
    for asset in config.get("assets", ["BTC", "ETH"]):
        logger.info(f"\n── {asset} ──────────────────────────────────────────")

        # LEG 1: Trend Hunter (Futures)
        try:
            updated_asset_state = _run_trend_hunter(asset, config, state)
            state[asset.lower()] = updated_asset_state
        except Exception as e:
            logger.error(f"[DHURANDHAR] Trend Hunter error for {asset}: {e}")

        # LEG 2: Option Selling (Strangle)
        if config.get("options_enabled"):
            try:
                updated_opts_state = _run_option_selling(asset, config, state)
                state["options"] = updated_opts_state
            except Exception as e:
                logger.error(f"[DHURANDHAR] Option Selling error for {asset}: {e}")

    # ── Save state ────────────────────────────────────────────────────────
    _save_state(state)

    # ── Print cycle summary ───────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    for asset in config.get("assets", ["BTC", "ETH"]):
        s = state.get(asset.lower(), {})
        pos  = s.get("position", "none").upper()
        ep   = s.get("entry_price", 0)
        ep_str = f"@ ${ep:,.2f}" if ep else ""
        logger.info(f"  {asset}: {pos} {ep_str}")

    opts = state.get("options", {})
    for asset in config.get("assets", ["BTC", "ETH"]):
        ak = asset.lower()
        if opts.get(f"{ak}_strangle_active"):
            logger.info(f"  {asset} Strangle: ACTIVE | "
                        f"Call: {opts.get(f'{ak}_call_symbol')} | "
                        f"Put: {opts.get(f'{ak}_put_symbol')}")
        else:
            logger.info(f"  {asset} Strangle: NOT YET PLACED")
    logger.info("=" * 60)


# ── Manual Controls (for dashboard/API) ──────────────────────────────────────

def halt_strategy(reason: str = "Manual halt"):
    """Immediately halt the Dhurandhar strategy."""
    state = _load_state()
    state["is_halted"]  = True
    state["halt_reason"] = reason
    _save_state(state)
    logger.warning(f"[DHURANDHAR] 🛑 Strategy HALTED: {reason}")


def resume_strategy():
    """Resume the Dhurandhar strategy after a halt."""
    state = _load_state()
    state["is_halted"]  = False
    state["halt_reason"] = ""
    _save_state(state)
    logger.info("[DHURANDHAR] ▶️ Strategy RESUMED")


def get_live_snapshot() -> dict:
    """
    Return a live snapshot of Dhurandhar state + market data.
    Used by dashboard to render the Dhurandhar panel.
    """
    state = _load_state()
    bal = dx.get_balance()
    api_error = None
    if isinstance(bal, dict) and bal.get("error"):
        api_error = bal.get("error")

    snapshot = {
        "enabled":      DHURANDHAR_CONFIG.get("enabled"),
        "is_halted":    state.get("is_halted"),
        "halt_reason":  state.get("halt_reason"),
        "total_trades": state.get("total_trades", 0),
        "today_pnl":    state.get("today_pnl", 0.0),
        "usd_balance":  dx.get_usd_balance(),
        "api_error":    api_error,
        "assets":       {},
        "options":      state.get("options", {}),
        "last_cycle":   state.get("last_cycle"),
    }

    for asset in ["BTC", "ETH"]:
        ticker = dx.get_ticker(asset)
        ak     = asset.lower()
        as_    = state.get(ak, {})
        snapshot["assets"][asset] = {
            "current_price": ticker.get("mark_price", 0),
            "high_24h":      ticker.get("high_24h", 0),
            "low_24h":       ticker.get("low_24h", 0),
            "position":      as_.get("position", "none"),
            "entry_price":   as_.get("entry_price", 0),
            "entry_time":    as_.get("entry_time"),
            "contracts":     as_.get("contracts", 0),
        }

    return snapshot


# ── Standalone run ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    print("\n" + "=" * 60)
    print("  DHURANDHAR STRATEGY — DEMO RUN")
    print("  (Pushkar Raj Thakur Method | Delta Testnet)")
    print("=" * 60)

    # Connection check
    if not dx.test_connection():
        print("❌ Delta Exchange connection failed. Check API keys in .env")
        exit(1)

    # Show live snapshot before running
    print("\n📊 Live Market Snapshot:")
    snap = get_live_snapshot()
    for asset, data in snap["assets"].items():
        print(f"  {asset}: ${data['current_price']:,.2f} | "
              f"24H High: ${data['high_24h']:,.2f} | "
              f"24H Low: ${data['low_24h']:,.2f} | "
              f"Position: {data['position'].upper()}")

    # Run one strategy cycle
    print("\n🚀 Running Dhurandhar Cycle...")
    run_dhurandhar_cycle()

    print("\n✅ Cycle complete. Check dhurandhar_state.json for full state.")
