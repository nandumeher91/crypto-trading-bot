"""
strategy.py
===========
Dhurandhar Trading Strategy (Options Strangle + 24H Trend Hunter Futures Breakout)
==================================================================================

Architecture:
1. Leg 1 (Non-Directional / Range):
   - Sell OTM Call (+10% to +14% above current price)
   - Sell OTM Put (-10% to -14% below current price)
   - Earn Theta (Time Decay) premium while price is inside the broad range.

2. Leg 2 (Directional / 24-Hour Trend Hunter Futures Breakout):
   - Monitors live 24-Hour High and 24-Hour Low.
   - LONG_BREAKOUT: If Price breaks above 24H High -> Buy Futures (Hedges Call loss, rides bull trend).
   - SHORT_BREAKDOWN: If Price breaks below 24H Low -> Sell/Short Futures (Hedges Put loss, rides bear crash).
   - RANGE_BOUND: If Price stays inside 24H Range -> Strangle generates profit with minimal futures turnover.
"""

import logging
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)


def _extract_asset(symbol: str) -> str:
    """Normalize symbol to 'BTC' or 'ETH'."""
    s = str(symbol).upper().replace("/", "").replace("_", "")
    if "ETH" in s:
        return "ETH"
    return "BTC"


def get_market_levels(symbol="BTCUSDT"):
    """
    Fetch live 24H High, 24H Low, and Mark Price.
    Prioritizes Delta Exchange Testnet; falls back to Binance/Direct if needed.
    """
    asset = _extract_asset(symbol)
    
    # 1. Delta Exchange live ticker
    try:
        from delta_exchange import get_24h_range
        r = get_24h_range(asset)
        cur = float(r.get("current", 0))
        high = float(r.get("high_24h", 0))
        low = float(r.get("low_24h", 0))
        if cur > 0 and high > 0 and low > 0:
            return {
                "source": "delta_testnet",
                "asset": asset,
                "current_price": cur,
                "high_24h": high,
                "low_24h": low,
            }
    except Exception as e:
        logger.warning(f"[STRATEGY] Delta ticker fetch warning for {asset}: {e}")

    # 2. Resilient Fallback to Binance
    try:
        from exchange import get_current_price
        cur = get_current_price(f"{asset}USDT")
        from exchange import get_klines_direct
        data = get_klines_direct(f"{asset}USDT", "1d", 2)
        if data and len(data["high"]) > 0:
            high = float(data["high"][-1])
            low = float(data["low"][-1])
            return {
                "source": "binance_fallback",
                "asset": asset,
                "current_price": cur,
                "high_24h": high,
                "low_24h": low,
            }
    except Exception as e:
        logger.error(f"[STRATEGY] Fallback ticker fetch failed for {asset}: {e}")

    # Default fallback
    base_price = 81000.0 if asset == "BTC" else 2350.0
    return {
        "source": "default",
        "asset": asset,
        "current_price": base_price,
        "high_24h": base_price * 1.02,
        "low_24h": base_price * 0.98,
    }


def get_strangle_recommendation(asset="BTC"):
    """
    Fetch recommended Call & Put strikes from Delta Exchange options chain.
    """
    try:
        from delta_exchange import get_options_for_strangle
        s = get_options_for_strangle(asset, otm_pct=0.12)
        if s and s.get("call") and s.get("put"):
            return {
                "call_symbol": s["call"]["symbol"],
                "call_strike": float(s["call"]["strike"]),
                "call_product_id": s["call"]["product_id"],
                "put_symbol": s["put"]["symbol"],
                "put_strike": float(s["put"]["strike"]),
                "put_product_id": s["put"]["product_id"],
                "expiry": s.get("expiry"),
                "dte": s.get("dte", 0),
            }
    except Exception as e:
        logger.warning(f"[STRATEGY] Could not fetch live strangle strikes: {e}")

    # Theoretical estimate based on current price
    return None


def detect_early_reversal(symbol, side):
    """
    Checks if market has broken back into the opposite 24-hour boundary.
    Long reversal: Price drops below 24-Hour Low.
    Short reversal: Price surges above 24-Hour High.
    """
    levels = get_market_levels(symbol)
    cur = levels["current_price"]
    high = levels["high_24h"]
    low = levels["low_24h"]

    side = str(side).upper()
    if side == "BUY" or side == "LONG":
        # If long future, reversal triggers if price breaks below 24h low
        return cur <= low
    elif side == "SELL" or side == "SHORT":
        # If short future, reversal triggers if price breaks above 24h high
        return cur >= high
    return False


def get_enhanced_signal(symbol="BTCUSDT", interval="24h"):
    """
    Dhurandhar Strategy Core Signal Generator:
    - Analyzes 24-Hour High/Low boundary
    - Identifies Breakout (Future Long), Breakdown (Future Short), or Range-Bound (Strangle)
    - Computes Dynamic Hedging TP/SL targets
    """
    asset = _extract_asset(symbol)
    levels = get_market_levels(symbol)
    current_price = levels["current_price"]
    high_24h = levels["high_24h"]
    low_24h = levels["low_24h"]

    # Calculate range metrics
    range_span = max(1.0, high_24h - low_24h)
    range_pct = round((range_span / low_24h) * 100.0, 2)

    dist_to_high_pct = round(((high_24h - current_price) / current_price) * 100.0, 2)
    dist_to_low_pct = round(((current_price - low_24h) / current_price) * 100.0, 2)

    # Fetch live Strangle recommendations
    strangle_info = get_strangle_recommendation(asset)
    if strangle_info:
        call_strike = strangle_info["call_strike"]
        put_strike = strangle_info["put_strike"]
        dte = strangle_info["dte"]
        profit_zone = f"${put_strike:,.0f} - ${call_strike:,.0f} ({dte} DTE)"
    else:
        call_strike = round(current_price * 1.12, 0)
        put_strike = round(current_price * 0.88, 0)
        profit_zone = f"${put_strike:,.0f} - ${call_strike:,.0f}"

    reasons = []
    reasons.append(f"Dhurandhar Strategy | Asset: {asset}USD on Delta Testnet")
    reasons.append(f"24H High: ${high_24h:,.2f} | 24H Low: ${low_24h:,.2f} | Range: {range_pct}%")

    # ── Signal Decision Logic ────────────────────────────────────────────────
    # Breakout threshold: 0.1% tolerance
    is_bullish_breakout = current_price >= (high_24h * 0.999)
    is_bearish_breakdown = current_price <= (low_24h * 1.001)

    if is_bullish_breakout:
        signal = "STRONG_BUY"
        score = 90
        macro_trend = "BULLISH_BREAKOUT"
        reasons.append(f"🚀 24H High Breakout: Current ${current_price:,.2f} >= 24H High ${high_24h:,.2f}")
        reasons.append("Trend Hunter Future: Open LONG to ride bull trend and hedge Call short loss")

        # Future Targets
        tp1 = round(current_price * 1.015, 2)   # +1.5% target
        tp2 = round(current_price * 1.035, 2)   # +3.5% extension
        structure_sl = round(low_24h, 2)        # 24H Low trailing SL

    elif is_bearish_breakdown:
        signal = "STRONG_SELL"
        score = 10
        macro_trend = "BEARISH_BREAKDOWN"
        reasons.append(f"🔻 24H Low Breakdown: Current ${current_price:,.2f} <= 24H Low ${low_24h:,.2f}")
        reasons.append("Trend Hunter Future: Open SHORT to ride bear crash and hedge Put short loss")

        # Future Targets
        tp1 = round(current_price * 0.985, 2)   # -1.5% target
        tp2 = round(current_price * 0.965, 2)   # -3.5% extension
        structure_sl = round(high_24h, 2)       # 24H High trailing SL

    else:
        signal = "HOLD"
        score = 50
        macro_trend = "RANGE_BOUND"
        reasons.append(f"⏸️ Range-Bound: Inside 24H channel ({dist_to_low_pct}% above Low, {dist_to_high_pct}% below High)")
        reasons.append(f"Option Strangle Leg Active: Safe Profit Zone {profit_zone}")

        tp1 = round(high_24h, 2)
        tp2 = round(call_strike, 2)
        structure_sl = round(low_24h, 2)

    return {
        "symbol": f"{asset}USDT",
        "asset": asset,
        "strategy": "Dhurandhar Hybrid Strategy (Options Strangle + 24H Trend Hunter Futures)",
        "signal": signal,
        "score": score,
        "confirmations": 2 if signal != "HOLD" else 0,
        "current_price": current_price,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "range_pct": range_pct,
        "dist_to_high_pct": dist_to_high_pct,
        "dist_to_low_pct": dist_to_low_pct,
        "call_strike": call_strike,
        "put_strike": put_strike,
        "profit_zone": profit_zone,
        "strangle_info": strangle_info,
        "tp1": tp1,
        "tp2": tp2,
        "structure_sl": structure_sl,
        "atr": round(range_span, 2),
        "rsi": 50.0,
        "adx": 25.0,
        "volume_ratio": 1.0,
        "macro_trend": macro_trend,
        "reasons": reasons
    }


def test_strategy():
    print("=" * 65)
    print("  DHURANDHAR TRADING STRATEGY TEST (OPTIONS + 24H FUTURES BREAKOUT)")
    print("=" * 65)
    for asset in ["BTC", "ETH"]:
        result = get_enhanced_signal(asset)
        print(f"\n[{asset}] Signal: {result['signal']} (Score: {result['score']}/100) | State: {result['macro_trend']}")
        print(f"Price: ${result['current_price']:,.2f} | 24H High: ${result['high_24h']:,.2f} | 24H Low: ${result['low_24h']:,.2f}")
        print(f"Option Strangle Profit Zone: {result['profit_zone']}")
        print(f"Targets: TP1=${result['tp1']:,.2f} | TP2=${result['tp2']:,.2f} | SL=${result['structure_sl']:,.2f}")
        print("Reasons:")
        for r in result["reasons"]:
            print(f"  - {r}")
    print("\n" + "=" * 65)


if __name__ == "__main__":
    test_strategy()
