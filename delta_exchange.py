"""
delta_exchange.py
=================
Delta Exchange India Testnet API Integration Layer
Used by: strategy_dhurandhar.py (Dhurandhar 24H Trend Hunter + Options Strangle)

Capabilities:
  - Fetch real-time 24-Hour High / Low for BTC and ETH
  - Place / Close Perpetual Futures orders (Long & Short)
  - Fetch OTM Options Chain and sell Call/Put Strangles
  - Fetch current positions and wallet balance
  - Paper-safe: All orders go to Demo Testnet (zero real money)
"""

import os
import math
import logging
import requests
import time as time_module
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from delta_rest_client import DeltaRestClient, OrderType

# ── Setup ────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DELTA_API_KEY    = os.getenv("DELTA_TESTENT_API_KEY") or os.getenv("DELTA_TESTNET_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_TESTENT_API_SECRET") or os.getenv("DELTA_TESTNET_API_SECRET", "")

# Delta India Testnet base URL
DELTA_BASE_URL = "https://cdn-ind.testnet.deltaex.org"

# Product IDs on Delta India Testnet
BTC_FUTURES_PRODUCT_ID = 84   # BTCUSD Perpetual
ETH_FUTURES_PRODUCT_ID = 1699 # ETHUSD Perpetual

# Contract values: 1 contract = N BTC/ETH
BTC_CONTRACT_VALUE = 0.001   # 1 lot BTCUSD  = 0.001 BTC
ETH_CONTRACT_VALUE = 0.01    # 1 lot ETHUSD  = 0.01 ETH

# Symbol mapping
FUTURES_MAP = {
    "BTC": {"product_id": BTC_FUTURES_PRODUCT_ID, "symbol": "BTCUSD", "contract_value": BTC_CONTRACT_VALUE},
    "ETH": {"product_id": ETH_FUTURES_PRODUCT_ID, "symbol": "ETHUSD", "contract_value": ETH_CONTRACT_VALUE},
}


def _get_client() -> DeltaRestClient:
    """Return a fresh authenticated DeltaRestClient."""
    return DeltaRestClient(
        base_url=DELTA_BASE_URL,
        api_key=DELTA_API_KEY,
        api_secret=DELTA_API_SECRET,
        raise_for_status=False
    )


# ── Account ───────────────────────────────────────────────────────────────────

def get_balance() -> dict:
    """
    Return wallet balances as a clean dict.
    Returns: {"USD": 100.0, "INR": 8500.0, "BTC": 0.0, "ETH": 0.0}
    """
    try:
        client = _get_client()
        raw = client.get_all_wallet_balances()
        if isinstance(raw, dict) and raw.get("code") == "ip_not_whitelisted_for_api_key":
            logger.error("[DELTA] ❌ API Key Error: IP is not whitelisted in Delta Exchange API settings!")
            return {"error": "ip_not_whitelisted"}
        result = {}
        if isinstance(raw, list):
            for item in raw:
                sym = item.get("asset_symbol", "?")
                result[sym] = float(item.get("available_balance", 0))
        logger.info(f"[DELTA] Balance: {result}")
        return result
    except Exception as e:
        logger.error(f"[DELTA] get_balance error: {e}")
        return {}


def get_usd_balance() -> float:
    """Return available USD/USDT/DET balance for margin."""
    bal = get_balance()
    if isinstance(bal, dict) and bal.get("error"):
        return 0.0
    # Check for USD, USDT, or DET (Delta USD token)
    usd = bal.get("USD", 0.0) or bal.get("USDT", 0.0) or bal.get("DET", 0.0)
    if usd == 0.0 and len(bal) > 0:
        usd = sum(v for k, v in bal.items() if isinstance(v, (int, float)))
    return float(usd)


# ── Market Data ───────────────────────────────────────────────────────────────

def get_ticker(asset: str) -> dict:
    """
    Get ticker for BTC or ETH.
    Returns: {mark_price, high_24h, low_24h, best_bid, best_ask, product_id}
    """
    try:
        symbol = f"{asset}USD"
        client = _get_client()
        t = client.get_ticker(symbol)
        return {
            "symbol":     symbol,
            "product_id": t.get("product_id"),
            "mark_price": float(t.get("mark_price", 0)),
            "high_24h":   float(t.get("high", 0)),
            "low_24h":    float(t.get("low", 0)),
            "best_bid":   float(t.get("quotes", {}).get("best_bid", 0) or 0),
            "best_ask":   float(t.get("quotes", {}).get("best_ask", 0) or 0),
        }
    except Exception as e:
        logger.error(f"[DELTA] get_ticker({asset}) error: {e}")
        return {}


def get_24h_range(asset: str) -> dict:
    """
    Returns the live 24-Hour High and Low for BTC or ETH.
    These are the breakout levels for Dhurandhar Trend Hunter.
    """
    t = get_ticker(asset)
    return {
        "asset":    asset,
        "high_24h": t.get("high_24h", 0),
        "low_24h":  t.get("low_24h", 0),
        "current":  t.get("mark_price", 0),
    }


# ── Futures Orders ─────────────────────────────────────────────────────────────

def _contracts_for_notional(asset: str, notional_usd: float, price: float) -> int:
    """
    Calculate number of contracts for a target USD notional.
    BTCUSD: 1 contract = 0.001 BTC = $price * 0.001
    ETHUSD: 1 contract = 0.01 ETH  = $price * 0.01
    """
    info = FUTURES_MAP.get(asset.upper())
    if not info or price <= 0:
        return 1
    contract_usd_value = price * info["contract_value"]
    raw = notional_usd / contract_usd_value
    contracts = max(1, round(raw))
    return contracts


def place_futures_order(asset: str, side: str, notional_usd: float = 50.0, limit_price: float = None) -> dict:
    """
    Place a Futures order (Long or Short) on Delta Testnet.

    Args:
        asset:        "BTC" or "ETH"
        side:         "buy" (Long) or "sell" (Short)
        notional_usd: Target USD notional size (e.g. 50 = $50 position)
        limit_price:  If None → Market order; otherwise Limit order at this price

    Returns:
        {"success": bool, "order_id": int, "size": int, "side": str, "price": float, "error": str}
    """
    asset = asset.upper()
    side  = side.lower()
    info  = FUTURES_MAP.get(asset)
    if not info:
        return {"success": False, "error": f"Unknown asset: {asset}"}

    try:
        client = _get_client()
        ticker = get_ticker(asset)
        current_price = ticker.get("mark_price", 0)
        if current_price <= 0:
            return {"success": False, "error": "Could not fetch current price"}

        size = _contracts_for_notional(asset, notional_usd, current_price)

        if limit_price:
            order_type = OrderType.LIMIT
            price_str  = str(round(limit_price, 1))
        else:
            # Market order: use aggressive limit inside bid-ask
            order_type = OrderType.LIMIT
            if side == "buy":
                price_str = str(round(ticker.get("best_ask", current_price) * 1.001, 1))
            else:
                price_str = str(round(ticker.get("best_bid", current_price) * 0.999, 1))

        logger.info(f"[DELTA] Placing {side.upper()} Futures {asset}: size={size} contracts, price={price_str}, notional≈${notional_usd:.0f}")
        response = client.place_order(
            product_id   = info["product_id"],
            size         = size,
            side         = side,
            limit_price  = price_str,
            order_type   = order_type,
        )

        if isinstance(response, dict) and response.get("id"):
            order_id = response["id"]
            logger.info(f"[DELTA] ✅ Futures order placed: OrderID={order_id} | {side.upper()} {size} {asset}USD @ {price_str}")
            return {
                "success":  True,
                "order_id": order_id,
                "size":     size,
                "side":     side,
                "price":    float(price_str),
                "asset":    asset,
                "notional": round(size * current_price * info["contract_value"], 2),
            }
        else:
            logger.error(f"[DELTA] Order response unexpected: {response}")
            return {"success": False, "error": str(response)}

    except Exception as e:
        logger.error(f"[DELTA] place_futures_order error: {e}")
        return {"success": False, "error": str(e)}


def close_futures_position(asset: str, size: int = None) -> dict:
    """
    Close the current open Futures position for an asset.
    Automatically determines direction from current position.
    """
    asset = asset.upper()
    info  = FUTURES_MAP.get(asset)
    if not info:
        return {"success": False, "error": f"Unknown asset: {asset}"}

    try:
        client = _get_client()
        pos    = client.get_position(info["product_id"])
        pos_size = int(pos.get("size", 0))

        if pos_size == 0:
            logger.info(f"[DELTA] No open position for {asset}. Nothing to close.")
            return {"success": True, "message": "No open position", "size": 0}

        close_size = abs(size) if size else abs(pos_size)
        # If position is positive → Long → Close with SELL
        # If position is negative → Short → Close with BUY
        close_side = "sell" if pos_size > 0 else "buy"

        ticker    = get_ticker(asset)
        cur_price = ticker.get("mark_price", 0)

        if close_side == "sell":
            price_str = str(round(ticker.get("best_bid", cur_price) * 0.999, 1))
        else:
            price_str = str(round(ticker.get("best_ask", cur_price) * 1.001, 1))

        logger.info(f"[DELTA] Closing {asset} position: {close_side.upper()} {close_size} @ {price_str}")
        response = client.place_order(
            product_id  = info["product_id"],
            size        = close_size,
            side        = close_side,
            limit_price = price_str,
            order_type  = OrderType.LIMIT,
            reduce_only = "true",
        )

        if isinstance(response, dict) and response.get("id"):
            logger.info(f"[DELTA] ✅ Position closed: OrderID={response['id']}")
            return {"success": True, "order_id": response["id"], "size": close_size, "side": close_side}
        else:
            return {"success": False, "error": str(response)}

    except Exception as e:
        logger.error(f"[DELTA] close_futures_position error: {e}")
        return {"success": False, "error": str(e)}


def get_futures_position(asset: str) -> dict:
    """
    Returns current Futures position for an asset.
    Returns: {"size": int, "side": "long"/"short"/"none", "entry_price": float}
    """
    asset = asset.upper()
    info  = FUTURES_MAP.get(asset)
    if not info:
        return {"size": 0, "side": "none", "entry_price": 0}
    try:
        client = _get_client()
        pos    = client.get_position(info["product_id"])
        size   = int(pos.get("size", 0))
        entry  = float(pos.get("entry_price") or 0)
        side   = "long" if size > 0 else ("short" if size < 0 else "none")
        return {"size": abs(size), "side": side, "entry_price": entry}
    except Exception as e:
        logger.error(f"[DELTA] get_futures_position error: {e}")
        return {"size": 0, "side": "none", "entry_price": 0}


# ── Options (OTM Strangle Selling) ───────────────────────────────────────────

def _round_to_nearest(value: float, step: float) -> float:
    """Round a value down to the nearest multiple of step."""
    return math.floor(value / step) * step


def get_options_for_strangle(asset: str, otm_pct: float = 0.12, prefer_monthly: bool = True) -> dict:
    """
    Find the best OTM Call and Put to sell for a Strangle.

    Pushkar's Dhurandhar logic:
      - Asset at $72k → Sell $81k CALL (~12% OTM) + $62k PUT (~14% OTM)
      - Target: Monthly expiry (8-35 days away) for maximum Theta decay
      - If no monthly found → use nearest weekly (>5 days)

    Args:
        asset:         "BTC" or "ETH"
        otm_pct:       Percentage OTM for strike selection (default 12%)
        prefer_monthly: Try to get 2-week+ expiry for better Theta

    Returns:
        {"call": {product_id, symbol, strike, expiry}, "put": {...}, "current_price": float}
    """
    try:
        client = _get_client()
        ticker = get_ticker(asset)
        current_price = ticker.get("mark_price", 0)
        if current_price <= 0:
            return {}

        products = client.get_products()
        now      = datetime.now(timezone.utc)
        min_days = 7 if prefer_monthly else 2
        max_days = 60

        # Filter to this asset's options within target expiry window
        opts = [
            p for p in products
            if (p.get("underlying_asset", {}).get("symbol") == asset.upper()
                and p.get("contract_type") in ["call_options", "put_options"]
                and p.get("settlement_time"))
        ]

        def days_to_expiry(p):
            try:
                exp = datetime.fromisoformat(p["settlement_time"].replace("Z", "+00:00"))
                return (exp - now).days
            except Exception:
                return -1

        # Sort by expiry, pick target window
        valid_opts = [p for p in opts if min_days <= days_to_expiry(p) <= max_days]
        if not valid_opts:
            valid_opts = [p for p in opts if 2 <= days_to_expiry(p) <= max_days]
        if not valid_opts:
            logger.warning(f"[DELTA] No valid options found for {asset} in {min_days}-{max_days} day window")
            return {}

        valid_opts.sort(key=lambda p: p.get("settlement_time", ""))
        target_expiry = valid_opts[0]["settlement_time"]

        expiry_opts  = [p for p in valid_opts if p["settlement_time"] == target_expiry]
        calls        = sorted([p for p in expiry_opts if p["contract_type"] == "call_options"],
                               key=lambda p: float(p.get("strike_price", 0)))
        puts         = sorted([p for p in expiry_opts if p["contract_type"] == "put_options"],
                               key=lambda p: float(p.get("strike_price", 0)), reverse=True)

        # Target strikes: otm_pct above/below current price
        target_call_strike = current_price * (1 + otm_pct)
        target_put_strike  = current_price * (1 - otm_pct)

        # Find nearest available call strike >= target
        best_call = None
        for c in calls:
            if float(c.get("strike_price", 0)) >= target_call_strike:
                best_call = c
                break
        if best_call is None and calls:
            best_call = calls[-1]  # Furthest OTM available

        # Find nearest available put strike <= target
        best_put = None
        for p in puts:
            if float(p.get("strike_price", 0)) <= target_put_strike:
                best_put = p
                break
        if best_put is None and puts:
            best_put = puts[-1]

        if not best_call or not best_put:
            logger.warning(f"[DELTA] Could not find suitable strikes for {asset} strangle")
            return {}

        dte = days_to_expiry(best_call)
        logger.info(f"[DELTA] Strangle found for {asset}: "
                    f"SELL {best_call['symbol']} (Call {best_call['strike_price']}) + "
                    f"SELL {best_put['symbol']} (Put {best_put['strike_price']}) | "
                    f"Expiry: {target_expiry} ({dte} DTE) | Current: ${current_price:,.0f}")

        return {
            "current_price": current_price,
            "expiry":        target_expiry,
            "dte":           dte,
            "call": {
                "product_id": best_call["id"],
                "symbol":     best_call["symbol"],
                "strike":     float(best_call["strike_price"]),
                "contract_type": "call_options",
            },
            "put": {
                "product_id": best_put["id"],
                "symbol":     best_put["symbol"],
                "strike":     float(best_put["strike_price"]),
                "contract_type": "put_options",
            },
        }
    except Exception as e:
        logger.error(f"[DELTA] get_options_for_strangle error: {e}")
        return {}


def sell_option(product_id: int, symbol: str, contracts: int = 1) -> dict:
    """
    Sell (short) an Options contract.
    Selling options = collecting premium (Theta decay profit).

    Args:
        product_id: Delta Exchange product ID for the option
        symbol:     Option symbol (e.g. C-BTC-90000-091026)
        contracts:  Number of contracts to sell

    Returns:
        {"success": bool, "order_id": int}
    """
    try:
        client = _get_client()

        # Fetch option's current best bid for limit sell
        try:
            ticker    = client.get_ticker(symbol)
            best_bid  = float(ticker.get("quotes", {}).get("best_bid", 0) or 0)
            best_ask  = float(ticker.get("quotes", {}).get("best_ask", 0) or 0)
            # Sell slightly below mid to ensure fill
            mid_price = (best_bid + best_ask) / 2 if best_ask > 0 else best_bid
            sell_price = round(mid_price * 0.98, 1) if mid_price > 0 else round(best_bid, 1)
        except Exception:
            sell_price = None

        if sell_price is None or sell_price <= 0:
            # Use market-like limit
            sell_price = 1.0

        price_str = str(sell_price)
        logger.info(f"[DELTA] Selling option {symbol} (product_id={product_id}): "
                    f"{contracts} contract(s) @ {price_str}")

        response = client.place_order(
            product_id  = product_id,
            size        = contracts,
            side        = "sell",
            limit_price = price_str,
            order_type  = OrderType.LIMIT,
        )

        if isinstance(response, dict) and response.get("id"):
            order_id = response["id"]
            logger.info(f"[DELTA] ✅ Option SOLD: OrderID={order_id} | {symbol} x{contracts}")
            return {"success": True, "order_id": order_id, "symbol": symbol, "size": contracts}
        else:
            logger.error(f"[DELTA] Option sell response: {response}")
            return {"success": False, "error": str(response)}

    except Exception as e:
        logger.error(f"[DELTA] sell_option error: {e}")
        return {"success": False, "error": str(e)}


def place_strangle(asset: str, contracts: int = 1, otm_pct: float = 0.12) -> dict:
    """
    Full Dhurandhar Option Selling: Sell OTM Call + Sell OTM Put.

    Both legs are sold simultaneously to collect premium from both sides.
    Profit comes from Theta (time decay) as long as price stays in the range.

    Args:
        asset:     "BTC" or "ETH"
        contracts: Number of contracts per leg (default: 1)
        otm_pct:   How far OTM for strike selection (default: 12%)

    Returns:
        {"success": bool, "call_order": dict, "put_order": dict, "strangle_info": dict}
    """
    strangle = get_options_for_strangle(asset, otm_pct=otm_pct)
    if not strangle:
        return {"success": False, "error": "Could not find strangle strikes"}

    call_info = strangle.get("call", {})
    put_info  = strangle.get("put", {})

    call_result = sell_option(call_info["product_id"], call_info["symbol"], contracts)
    put_result  = sell_option(put_info["product_id"],  put_info["symbol"],  contracts)

    success = call_result.get("success") and put_result.get("success")
    logger.info(f"[DELTA] {'✅' if success else '❌'} Strangle for {asset}: "
                f"Call={call_info.get('strike')} ({call_result.get('success')}) | "
                f"Put={put_info.get('strike')} ({put_result.get('success')})")

    return {
        "success":       success,
        "asset":         asset,
        "call_order":    call_result,
        "put_order":     put_result,
        "strangle_info": strangle,
    }


# ── Positions Overview ────────────────────────────────────────────────────────

def get_all_positions() -> list:
    """Return all open positions (Futures + Options)."""
    try:
        client = _get_client()
        positions = []
        for asset, info in FUTURES_MAP.items():
            pos = client.get_position(info["product_id"])
            size = int(pos.get("size", 0))
            if size != 0:
                positions.append({
                    "type":        "futures",
                    "asset":       asset,
                    "symbol":      info["symbol"],
                    "product_id":  info["product_id"],
                    "size":        size,
                    "side":        "long" if size > 0 else "short",
                    "entry_price": float(pos.get("entry_price") or 0),
                })
        return positions
    except Exception as e:
        logger.error(f"[DELTA] get_all_positions error: {e}")
        return []


# ── Health Check ──────────────────────────────────────────────────────────────

def test_connection() -> bool:
    """Test API connectivity and return True if healthy."""
    try:
        bal = get_balance()
        usd = bal.get("USD", 0)
        logger.info(f"[DELTA] [OK] Connection OK | USD Balance: ${usd:.2f}")
        print(f"[DELTA] [OK] Connection OK | USD Balance: ${usd:.2f}")
        return True
    except Exception as e:
        logger.error(f"[DELTA] [FAIL] Connection FAILED: {e}")
        print(f"[DELTA] [FAIL] Connection FAILED: {e}")
        return False


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("\n" + "="*55)
    print("  DELTA EXCHANGE TESTNET - CONNECTION TEST")
    print("="*55)
    test_connection()
    print("\n--- 24-Hour Range (Dhurandhar Breakout Levels) ---")
    for asset in ["BTC", "ETH"]:
        r = get_24h_range(asset)
        print(f"  {asset}: Current ${r['current']:,.2f} | 24H High ${r['high_24h']:,.2f} | 24H Low ${r['low_24h']:,.2f}")
    print("\n--- BTC Futures Position ---")
    pos = get_futures_position("BTC")
    print(f"  BTC: {pos}")
    print("\n--- Finding BTC Strangle Strikes ---")
    strangle = get_options_for_strangle("BTC")
    if strangle:
        print(f"  Current Price:  ${strangle['current_price']:,.0f}")
        print(f"  SELL CALL: {strangle['call']['symbol']} (Strike: ${strangle['call']['strike']:,.0f})")
        print(f"  SELL PUT:  {strangle['put']['symbol']}  (Strike: ${strangle['put']['strike']:,.0f})")
        print(f"  Expiry: {strangle['expiry']} ({strangle['dte']} DTE)")
    print("="*55)
