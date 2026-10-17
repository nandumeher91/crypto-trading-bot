"""
strategy_dhurandhar.py
======================
Delta Hedged Strangle V1 (Quantitative Institutional Engine)
Based on Pushkar Raj Thakur's Dhurandhar Concept upgraded to:
  - 15m Timeframe with 96-bar (24H) Rolling High/Low & ATR(14)
  - 0.15 Delta OTM Strangle Selling (~12% OTM)
  - 50% Profit Target on Combined Premium Decay
  - Dynamic 15m Candle Close Breakout Hedge (Close > 24H High + 0.5 ATR / Close < 24H Low - 0.5 ATR)
  - Max 2 Whipsaws Cap per 24H Window (False Breakout Trap Protection)
  - 2.0% Global Capital Portfolio Drawdown Hard Stop
  - 24/7/365 Non-Stop Execution (Continuous Weekend Theta Harvest)

Platform: Delta Exchange India Testnet via delta_exchange.py
"""

import os
import json
import logging
import time as time_module
from datetime import datetime, timezone
from typing import Optional

import delta_exchange as dx
try:
    from memory import log_new_trade, close_trade, get_open_trades
except Exception:
    log_new_trade = None
    close_trade = None
    get_open_trades = None

try:
    from exchange import get_klines_direct
except Exception:
    get_klines_direct = None

logger = logging.getLogger("Dhurandhar")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "dhurandhar_state.json")

# ── 1. System Parameters & Configuration (Bot Config) ─────────────────────────

DHURANDHAR_CONFIG = {
    "STRATEGY_NAME":            "Delta_Hedged_Strangle_V1",
    "TIMEFRAME":                "15m",
    "LOOKBACK_WINDOW":          96,       # 96 bars on 15m = 24 Hours
    "INITIAL_DELTA":            0.15,     # OTM Strike selection (~0.15 Delta / ~12% OTM)
    "IV_RANK_MIN":              25,       # Entry allowed only if IV Rank >= 25
    "BREAKOUT_BUFFER_ATR_MULT": 0.5,      # Price > 24h High + (0.5 * ATR)
    "CANDLE_CLOSE_CONFIRM":     True,     # Wick touch ignored; candle close required
    "MAX_WHIPSAW_COUNT":        2,        # Max false breakout attempts before pausing
    "TARGET_PROFIT_PCT":        50,       # Close when 50% combined premium melts
    "GLOBAL_PORTFOLIO_SL_PCT":  2.0,      # Kill switch at 2% total capital drawdown

    # Asset Settings
    "assets":                   ["BTC", "ETH"],
    "btc_notional_usd":         50.0,
    "eth_notional_usd":         50.0,
    "option_contracts":         1,
    "enabled":                  True,
}


# ── 2. State Persistence ──────────────────────────────────────────────────────

def _load_state() -> dict:
    """Load strategy state from disk."""
    default = {
        "btc": {
            "state": "STRANGLE_ACTIVE",
            "whipsaw_count": 0,
            "whipsaw_date": "",
            "initial_total_premium": 80.0,
            "hedge_entry_price": 0.0,
            "hedge_sl": 0.0,
            "trade_id": None,
            "position": "none",
            "entry_price": 0,
            "contracts": 0,
        },
        "eth": {
            "state": "STRANGLE_ACTIVE",
            "whipsaw_count": 0,
            "whipsaw_date": "",
            "initial_total_premium": 80.0,
            "hedge_entry_price": 0.0,
            "hedge_sl": 0.0,
            "trade_id": None,
            "position": "none",
            "entry_price": 0,
            "contracts": 0,
        },
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
        "today_pnl":    0.0,
        "total_trades": 0,
        "last_cycle":   None,
        "is_halted":    False,
        "halt_reason":  "",
    }
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
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
    return _load_state()


def reset_state():
    """Reset strategy state."""
    state = _load_state()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for asset in ["btc", "eth"]:
        state[asset] = {
            "state": "STRANGLE_ACTIVE",
            "whipsaw_count": 0,
            "whipsaw_date": today_str,
            "initial_total_premium": 80.0,
            "hedge_entry_price": 0.0,
            "hedge_sl": 0.0,
            "trade_id": None,
            "position": "none",
            "entry_price": 0,
            "contracts": 0,
        }
    state["options"] = {
        "btc_strangle_active": False, "btc_call_symbol": None, "btc_put_symbol": None, "btc_strangle_time": None,
        "eth_strangle_active": False, "eth_call_symbol": None, "eth_put_symbol": None, "eth_strangle_time": None,
    }
    state["is_halted"] = False
    state["halt_reason"] = ""
    _save_state(state)
    logger.info("[DHURANDHAR] State reset complete.")


# ── 3. Quantitative Calculations (15m ATR & 24H Levels) ───────────────────────

def calculate_atr_and_24h_levels(asset: str, period: int = 14, lookback: int = 96) -> dict:
    """
    Calculates 15m ATR(14) and 24H rolling High/Low (96 bars on 15m):
      - h_24: Highest High across last 96 15m bars
      - l_24: Lowest Low across last 96 15m bars
      - atr: 14-period Average True Range
      - last_close: Confirmed 15m candle close
      - upper_trigger: h_24 + (0.5 * atr)
      - lower_trigger: l_24 - (0.5 * atr)
    """
    sym = f"{asset.upper()}USDT"
    klines = None
    if get_klines_direct:
        try:
            klines = get_klines_direct(symbol=sym, interval="15m", limit=max(120, lookback + period))
        except Exception as e:
            logger.warning(f"[DHURANDHAR] klines fetch error for {sym}: {e}")

    if klines and len(klines.get("close", [])) >= lookback:
        highs  = klines["high"][-lookback:]
        lows   = klines["low"][-lookback:]
        closes = klines["close"][-lookback:]

        tr_list = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            tr_list.append(tr)

        atr = sum(tr_list[-period:]) / float(period) if len(tr_list) >= period else (highs[-1] - lows[-1])
        h_24 = max(highs)
        l_24 = min(lows)
        last_close = closes[-1]
        buffer_val = 0.5 * atr

        return {
            "success": True,
            "h_24": round(h_24, 2),
            "l_24": round(l_24, 2),
            "atr": round(atr, 2),
            "last_close": round(last_close, 2),
            "upper_trigger": round(h_24 + buffer_val, 2),
            "lower_trigger": round(l_24 - buffer_val, 2),
            "candles_count": len(highs)
        }

    # Resilient Fallback to Delta Exchange 24h Ticker
    ticker = dx.get_ticker(asset)
    mark_p = ticker.get("mark_price", 0)
    h_24   = ticker.get("high_24h", mark_p * 1.02)
    l_24   = ticker.get("low_24h", mark_p * 0.98)
    atr_est = mark_p * 0.015
    return {
        "success": False,
        "h_24": round(h_24, 2),
        "l_24": round(l_24, 2),
        "atr": round(atr_est, 2),
        "last_close": round(mark_p, 2),
        "upper_trigger": round(h_24 + (0.5 * atr_est), 2),
        "lower_trigger": round(l_24 - (0.5 * atr_est), 2),
        "candles_count": 0
    }


# ── 4. Core State Machine Engine ──────────────────────────────────────────────

def _run_delta_hedged_cycle(asset: str, config: dict, state: dict) -> dict:
    """
    Executes the Delta Hedged Strangle V1 state machine for an asset (BTC or ETH).

    States:
      - STATE 0: SCAN & IDLE
      - STATE 1: STRANGLE_ACTIVE (Harvesting Theta)
      - STATE 2: HEDGE_LONG (15m close > 24h High + 0.5*ATR)
      - STATE 3: HEDGE_SHORT (15m close < 24h Low - 0.5*ATR)
      - STATE 4: TAKE_PROFIT (Combined remaining premium <= 50% of initial)
      - STATE 5: EMERGENCY_CIRCUIT_BREAKER (Global capital drawdown >= 2%)
    """
    asset_key    = asset.lower()
    asset_state  = state.get(asset_key, {})
    opts_state   = state.get("options", {})
    notional_usd = config.get(f"{asset_key}_notional_usd", 50.0)

    # 1. Reset daily whipsaws
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if asset_state.get("whipsaw_date") != today_str:
        asset_state["whipsaw_date"] = today_str
        asset_state["whipsaw_count"] = 0

    # 2. Fetch live levels (15m Candle Close, 24H High/Low, ATR)
    levels = calculate_atr_and_24h_levels(asset, period=14, lookback=config.get("LOOKBACK_WINDOW", 96))
    last_close    = levels["last_close"]
    h_24          = levels["h_24"]
    l_24          = levels["l_24"]
    atr           = levels["atr"]
    upper_trigger = levels["upper_trigger"]
    lower_trigger = levels["lower_trigger"]

    # 3. Live Ticker
    ticker        = dx.get_ticker(asset)
    current_price = ticker.get("mark_price", last_close)

    call_key   = f"{asset_key}_call_symbol"
    put_key    = f"{asset_key}_put_symbol"
    time_key   = f"{asset_key}_strangle_time"
    active_key = f"{asset_key}_strangle_active"

    # Verify if Strangle is currently open in ledger
    is_strangle_open = False
    if get_open_trades:
        try:
            op_t = get_open_trades()
            is_strangle_open = any(t.get("status") in ["open", "partial_tp"] and f"{asset}-STRANGLE" in str(t.get("symbol", "")) for t in op_t)
        except Exception:
            pass

    if not is_strangle_open and opts_state.get(active_key):
        opts_state[active_key] = False
        asset_state["state"] = "IDLE"

    # ── CHECK STATE 4: 50% TAKE PROFIT TARGET ─────────────────────────────────
    if opts_state.get(active_key):
        c_sym = opts_state.get(call_key)
        p_sym = opts_state.get(put_key)
        cur_c_prem   = dx.get_option_premium(c_sym)
        cur_p_prem   = dx.get_option_premium(p_sym)
        cur_tot_prem = round(cur_c_prem + cur_p_prem, 2)
        init_tot_prem = float(asset_state.get("initial_total_premium") or 80.0)

        # 50% Profit Target: Close when remaining combined premium <= 50% of initial
        target_melt_thresh = init_tot_prem * (1.0 - (config.get("TARGET_PROFIT_PCT", 50) / 100.0))
        if init_tot_prem > 0 and cur_tot_prem > 0 and cur_tot_prem <= target_melt_thresh:
            logger.info(f"[DHURANDHAR] 🎯 50% TAKE PROFIT HIT for {asset}: "
                        f"Initial=${init_tot_prem:.2f} -> Remaining=${cur_tot_prem:.2f} (<= ${target_melt_thresh:.2f})")
            # Close any active hedge future
            dx.close_futures_position(asset)
            # Close Strangle in ledger
            if close_trade and opts_state.get("trade_id"):
                try:
                    close_trade(opts_state["trade_id"], current_price, "50% Combined Premium Melted", symbol=f"{asset}-STRANGLE")
                except Exception:
                    pass

            opts_state[active_key] = False
            asset_state["state"] = "IDLE"
            asset_state["initial_total_premium"] = 0.0
            asset_state["position"] = "none"
            logger.info(f"[DHURANDHAR] ✅ {asset} 50% Profit Booked. Capital recycled. Returning to STATE 0 (SCAN/IDLE).")
            return asset_state

    # ── STATE 0 -> STATE 1: INITIAL ENTRY (Delta-Neutral Strangle) ─────────────
    if not opts_state.get(active_key):
        iv_rank = dx.get_iv_rank(asset)
        if iv_rank < config.get("IV_RANK_MIN", 25):
            logger.info(f"[DHURANDHAR] {asset} IV Rank {iv_rank:.1f} < {config.get('IV_RANK_MIN', 25)}. Waiting for sufficient volatility before entry.")
            asset_state["state"] = "IDLE"
            return asset_state

        logger.info(f"[DHURANDHAR] {asset}: IV Rank {iv_rank:.1f} >= 25. Deploying Delta-Neutral Strangle (~0.15 Delta)...")
        res = dx.place_strangle(asset, contracts=config.get("option_contracts", 1), otm_pct=0.12)
        if res.get("success"):
            strangle_info = res.get("strangle_info", {})
            init_prem = res.get("initial_total_premium") or 80.0
            c_sym  = res["call_order"].get("symbol", strangle_info.get("call", {}).get("symbol"))
            p_sym  = res["put_order"].get("symbol",  strangle_info.get("put", {}).get("symbol"))
            c_strk = strangle_info.get("call", {}).get("strike", 0)
            p_strk = strangle_info.get("put", {}).get("strike", 0)
            dte    = strangle_info.get("dte", 13)

            t_id = None
            if log_new_trade:
                t_id = log_new_trade(
                    symbol=f"{asset}-STRANGLE",
                    side="SELL",
                    entry_price=current_price,
                    quantity=config.get("option_contracts", 1),
                    reason=f"Strangle: Call ${c_strk:,.0f} + Put ${p_strk:,.0f} ({dte} DTE)",
                    stop_loss=None,
                    take_profit=None,
                    strategy_name="Dhurandhar Strategy",
                    strategy_id="strat_dhurandhar",
                    trade_type="strangle",
                    margin_usd=50.0,
                    call_strike=c_strk,
                    put_strike=p_strk,
                    expiry=strangle_info.get("expiry"),
                    dte=dte,
                    initial_premium=init_prem,
                    call_symbol=c_sym,
                    put_symbol=p_sym
                )

            opts_state.update({
                active_key: True,
                call_key: c_sym,
                put_key:  p_sym,
                time_key: datetime.now(timezone.utc).isoformat(),
                "trade_id": t_id,
                f"{asset_key}_call_strike": c_strk,
                f"{asset_key}_put_strike":  p_strk,
                f"{asset_key}_expiry":      strangle_info.get("expiry"),
                f"{asset_key}_dte":         dte,
                f"{asset_key}_margin_usd":  50.0,
            })
            asset_state["state"] = "STRANGLE_ACTIVE"
            asset_state["initial_total_premium"] = float(init_prem)
            logger.info(f"[DHURANDHAR] ✅ {asset} Strangle Active: CALL ${c_strk:,.0f} | PUT ${p_strk:,.0f} | Initial Prem: ${init_prem:.2f}")
            return asset_state
        else:
            logger.warning(f"[DHURANDHAR] ⚠️ {asset} Strangle placement failed: {res.get('error')}")
            return asset_state

    # ── STATE 1: STRANGLE_ACTIVE (Harvesting Theta & Monitoring Breakouts) ─────
    whipsaws    = asset_state.get("whipsaw_count", 0)
    max_whipsaw = config.get("MAX_WHIPSAW_COUNT", 2)

    logger.info(f"[DHURANDHAR] {asset} [STRANGLE_ACTIVE] | 15m Close: ${last_close:,.2f} | "
                f"Upper Trig (24H H + 0.5 ATR): ${upper_trigger:,.2f} | "
                f"Lower Trig (24H L - 0.5 ATR): ${lower_trigger:,.2f} | Whipsaws: {whipsaws}/{max_whipsaw}")

    if asset_state.get("state") == "STRANGLE_ACTIVE":
        # 1. Bullish Breakout Confirmation (15m Candle Close > 24H High + 0.5 ATR)
        if last_close > upper_trigger:
            if whipsaws < max_whipsaw:
                logger.info(f"[DHURANDHAR] 🚀 {asset} Bullish Breakout! 15m Close (${last_close:,.2f}) > Upper Trigger (${upper_trigger:,.2f}). Opening LONG Future Hedge...")
                order = dx.place_futures_order(asset, side="buy", notional_usd=notional_usd)
                if order.get("success"):
                    hedge_sl = round(h_24 - (0.5 * atr), 2)
                    asset_state["state"] = "HEDGE_LONG"
                    asset_state["position"] = "long"
                    asset_state["hedge_entry_price"] = current_price
                    asset_state["hedge_sl"] = hedge_sl
                    asset_state["whipsaw_count"] = whipsaws + 1

                    if log_new_trade:
                        t_id = log_new_trade(
                            symbol=f"{asset}USD",
                            side="BUY",
                            entry_price=current_price,
                            quantity=order.get("size", 1),
                            reason=f"Delta Hedge LONG (15m Close > ${upper_trigger:,.2f})",
                            stop_loss=hedge_sl,
                            take_profit=None,
                            strategy_name="Dhurandhar Strategy",
                            strategy_id="strat_dhurandhar",
                            trade_type="dhurandhar_futures",
                            margin_usd=notional_usd
                        )
                        asset_state["trade_id"] = t_id
                    logger.info(f"[DHURANDHAR] 🛡️ {asset} LONG Hedge entered @ ${current_price:,.2f} | SL: ${hedge_sl:,.2f}")
            else:
                logger.info(f"[DHURANDHAR] ⚠️ Max whipsaw count reached ({whipsaws}/{max_whipsaw}). Pausing hedge entry to avoid chop.")

        # 2. Bearish Breakdown Confirmation (15m Candle Close < 24H Low - 0.5 ATR)
        elif last_close < lower_trigger:
            if whipsaws < max_whipsaw:
                logger.info(f"[DHURANDHAR] 📉 {asset} Bearish Breakdown! 15m Close (${last_close:,.2f}) < Lower Trigger (${lower_trigger:,.2f}). Opening SHORT Future Hedge...")
                order = dx.place_futures_order(asset, side="sell", notional_usd=notional_usd)
                if order.get("success"):
                    hedge_sl = round(l_24 + (0.5 * atr), 2)
                    asset_state["state"] = "HEDGE_SHORT"
                    asset_state["position"] = "short"
                    asset_state["hedge_entry_price"] = current_price
                    asset_state["hedge_sl"] = hedge_sl
                    asset_state["whipsaw_count"] = whipsaws + 1

                    if log_new_trade:
                        t_id = log_new_trade(
                            symbol=f"{asset}USD",
                            side="SELL",
                            entry_price=current_price,
                            quantity=order.get("size", 1),
                            reason=f"Delta Hedge SHORT (15m Close < ${lower_trigger:,.2f})",
                            stop_loss=hedge_sl,
                            take_profit=None,
                            strategy_name="Dhurandhar Strategy",
                            strategy_id="strat_dhurandhar",
                            trade_type="dhurandhar_futures",
                            margin_usd=notional_usd
                        )
                        asset_state["trade_id"] = t_id
                    logger.info(f"[DHURANDHAR] 🛡️ {asset} SHORT Hedge entered @ ${current_price:,.2f} | SL: ${hedge_sl:,.2f}")
            else:
                logger.info(f"[DHURANDHAR] ⚠️ Max whipsaw count reached ({whipsaws}/{max_whipsaw}). Pausing hedge entry to avoid chop.")

    # ── STATE 2 & 3: ACTIVE HEDGE MANAGEMENT (Trailing Stop & False Breakout) ──
    elif asset_state.get("state") == "HEDGE_LONG":
        hedge_sl = float(asset_state.get("hedge_sl") or 0)
        if current_price <= hedge_sl:
            logger.info(f"[DHURANDHAR] ⚠️ FALSE BREAKOUT / WHIPSAW: {asset} hit Long Hedge SL (${hedge_sl:,.2f}). Cutting hedge, returning to STRANGLE_ACTIVE.")
            dx.close_futures_position(asset)
            if close_trade and asset_state.get("trade_id"):
                try:
                    close_trade(asset_state["trade_id"], current_price, "Hedge SL Hit (False Breakout)", symbol=f"{asset}USD")
                except Exception:
                    pass
            asset_state["state"] = "STRANGLE_ACTIVE"
            asset_state["position"] = "none"
            asset_state["hedge_entry_price"] = 0
            asset_state["hedge_sl"] = 0
        else:
            trail_sl = round(current_price - (0.8 * atr), 2)
            if trail_sl > hedge_sl:
                asset_state["hedge_sl"] = trail_sl
                logger.info(f"[DHURANDHAR] 📈 Trailing Long Hedge SL for {asset} to ${trail_sl:,.2f}")

    elif asset_state.get("state") == "HEDGE_SHORT":
        hedge_sl = float(asset_state.get("hedge_sl") or 999999)
        if current_price >= hedge_sl:
            logger.info(f"[DHURANDHAR] ⚠️ FALSE BREAKOUT / WHIPSAW: {asset} hit Short Hedge SL (${hedge_sl:,.2f}). Cutting hedge, returning to STRANGLE_ACTIVE.")
            dx.close_futures_position(asset)
            if close_trade and asset_state.get("trade_id"):
                try:
                    close_trade(asset_state["trade_id"], current_price, "Hedge SL Hit (False Breakout)", symbol=f"{asset}USD")
                except Exception:
                    pass
            asset_state["state"] = "STRANGLE_ACTIVE"
            asset_state["position"] = "none"
            asset_state["hedge_entry_price"] = 0
            asset_state["hedge_sl"] = 0
        else:
            trail_sl = round(current_price + (0.8 * atr), 2)
            if trail_sl < hedge_sl:
                asset_state["hedge_sl"] = trail_sl
                logger.info(f"[DHURANDHAR] 📉 Trailing Short Hedge SL for {asset} to ${trail_sl:,.2f}")

    return asset_state


# ── 5. Main Dhurandhar Cycle (Called by bot.py) ────────────────────────────────

def run_dhurandhar_cycle():
    """
    Execute one full Delta Hedged Strangle V1 cycle across BTC and ETH.
    Runs 24/7/365 without stopping on weekends.
    """
    config = DHURANDHAR_CONFIG.copy()
    if not config.get("enabled"):
        return

    state = _load_state()

    # Safety: Check if halted
    if state.get("is_halted"):
        logger.info(f"[DHURANDHAR] HALTED: {state.get('halt_reason', 'Manual halt')}. Run reset_state() to resume.")
        return

    # Safety: Global 2.0% Capital Drawdown Hard Stop
    usd_bal = dx.get_usd_balance()
    today_pnl = float(state.get("today_pnl", 0.0))
    max_allowed_loss = (usd_bal * (config.get("GLOBAL_PORTFOLIO_SL_PCT", 2.0) / 100.0)) if usd_bal > 0 else 30.0

    if today_pnl <= -max_allowed_loss:
        logger.warning(f"[DHURANDHAR] 🛑 GLOBAL 2% PORTFOLIO CIRCUIT BREAKER TRIGGERED: Loss=${today_pnl:.2f} >= 2% limit (${max_allowed_loss:.2f})")
        dx.close_futures_position("BTC")
        dx.close_futures_position("ETH")
        state["is_halted"] = True
        state["halt_reason"] = f"Global 2.0% Capital SL Hit: ${today_pnl:.2f}"
        _save_state(state)
        return

    logger.info("=" * 60)
    logger.info("  DELTA HEDGED STRANGLE V1 (DHURANDHAR QUANT CYCLE)")
    logger.info(f"  Balance: ${usd_bal:.2f} USD | 24/7 Theta Harvesting Active")
    logger.info("=" * 60)

    # Process each asset
    for asset in config.get("assets", ["BTC", "ETH"]):
        try:
            updated_state = _run_delta_hedged_cycle(asset, config, state)
            state[asset.lower()] = updated_state
        except Exception as e:
            logger.error(f"[DHURANDHAR] Cycle execution error for {asset}: {e}")

    # Persist state
    _save_state(state)


# ── 6. Manual Controls & Dashboard Snapshot ───────────────────────────────────

def halt_strategy(reason: str = "Manual halt"):
    state = _load_state()
    state["is_halted"] = True
    state["halt_reason"] = reason
    _save_state(state)
    logger.warning(f"[DHURANDHAR] 🛑 Strategy HALTED: {reason}")


def resume_strategy():
    state = _load_state()
    state["is_halted"] = False
    state["halt_reason"] = ""
    _save_state(state)
    logger.info("[DHURANDHAR] ▶️ Strategy RESUMED")


def get_live_snapshot() -> dict:
    state = _load_state()
    bal = dx.get_balance()
    api_error = None
    if isinstance(bal, dict) and bal.get("error"):
        api_error = bal.get("error")

    snapshot = {
        "strategy_name": DHURANDHAR_CONFIG.get("STRATEGY_NAME", "Delta_Hedged_Strangle_V1"),
        "timeframe":     DHURANDHAR_CONFIG.get("TIMEFRAME", "15m"),
        "enabled":       DHURANDHAR_CONFIG.get("enabled"),
        "is_halted":     state.get("is_halted"),
        "halt_reason":   state.get("halt_reason"),
        "total_trades":  state.get("total_trades", 0),
        "today_pnl":     state.get("today_pnl", 0.0),
        "usd_balance":   dx.get_usd_balance(),
        "api_error":     api_error,
        "assets":        {},
        "options":       state.get("options", {}),
        "last_cycle":    state.get("last_cycle"),
    }

    for asset in ["BTC", "ETH"]:
        ak = asset.lower()
        as_ = state.get(ak, {})
        levels = calculate_atr_and_24h_levels(asset, period=14, lookback=96)
        ticker = dx.get_ticker(asset)
        snapshot["assets"][asset] = {
            "current_price": ticker.get("mark_price", levels.get("last_close", 0)),
            "h_24":          levels.get("h_24", 0),
            "l_24":          levels.get("l_24", 0),
            "atr":           round(levels.get("atr", 0), 2),
            "upper_trigger": levels.get("upper_trigger", 0),
            "lower_trigger": levels.get("lower_trigger", 0),
            "state":         as_.get("state", "STRANGLE_ACTIVE"),
            "whipsaws":      as_.get("whipsaw_count", 0),
            "position":      as_.get("position", "none"),
            "hedge_sl":      as_.get("hedge_sl", 0),
            "iv_rank":       dx.get_iv_rank(asset),
            "initial_prem":  as_.get("initial_total_premium", 80.0),
        }

    return snapshot


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
    print("Running Delta Hedged Strangle V1 Cycle...")
    run_dhurandhar_cycle()
