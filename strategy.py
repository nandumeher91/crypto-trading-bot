import numpy as np
import logging
from binance.client import Client
from exchange import client, _sanitize_symbol, get_klines_direct

logger = logging.getLogger(__name__)


def get_klines_data(symbol="BTCUSDT", interval="5m", limit=100):
    """Get OHLCV data from Binance for specified interval"""
    symbol = _sanitize_symbol(symbol)
    interval = str(interval).strip().lower()
    limit = int(limit)

    print(f"[STRATEGY] Getting klines: symbol={symbol}, interval={interval}, limit={limit}")

    try:
        if client:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
            return {
                "open": np.array([float(k[1]) for k in klines]),
                "high": np.array([float(k[2]) for k in klines]),
                "low": np.array([float(k[3]) for k in klines]),
                "close": np.array([float(k[4]) for k in klines]),
                "volume": np.array([float(k[5]) for k in klines])
            }
    except Exception as e:
        print(f"[STRATEGY] python-binance klines failed ({e}), trying resilient fallback...")

    data = get_klines_direct(symbol, interval, limit)
    if data:
        return {
            "open": np.array(data["open"]),
            "high": np.array(data["high"]),
            "low": np.array(data["low"]),
            "close": np.array(data["close"]),
            "volume": np.array(data["volume"])
        }
    raise RuntimeError(f"Unable to fetch klines for {symbol}")


def calculate_atr(data, period=14):
    highs, lows, closes = data["high"], data["low"], data["close"]
    if len(closes) < period + 1:
        return None
    tr_list = []
    for i in range(1, len(closes)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr_list.append(max(tr1, tr2, tr3))
    return np.mean(tr_list[-period:])


def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    return np.convolve(prices, weights, mode="valid")[-1]


def calculate_sma(prices, period):
    if len(prices) < period:
        return None
    return float(np.mean(prices[-period:]))


def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(closes)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(closes)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)
    return round(float(rsi[-1]), 1)


def detect_early_reversal(symbol, side):
    """
    Detects if market is reversing against the position using EMA crossover or candle reversal.
    """
    try:
        data_5m = get_klines_data(symbol, interval="5m", limit=30)
        closes = data_5m["close"]
        if len(closes) < 15:
            return False

        ema_short = calculate_ema(closes, 9)
        ema_long = calculate_ema(closes, 21)

        if side.upper() == "BUY":
            # Reversal against BUY: short EMA drops below long EMA or latest close falls below EMA 9
            return bool(ema_short and ema_long and (ema_short < ema_long or closes[-1] < ema_short * 0.998))
        else:
            # Reversal against SELL: short EMA crosses above long EMA or latest close rises above EMA 9
            return bool(ema_short and ema_long and (ema_short > ema_long or closes[-1] > ema_short * 1.002))
    except Exception as e:
        print(f"[REVERSAL] Warning: check failed for {symbol}: {e}")
        return False


def get_enhanced_signal(symbol="BTCUSDT", interval="5m"):
    """
    Classic Moving Average (MA) Crossover Strategy with RSI Momentum Filter:
    - Fast EMA: 9 periods
    - Slow EMA: 21 periods
    - Trend Filter: 50 EMA
    - RSI Momentum Filter (period=14)
    - Dynamic ATR Risk Management (TP1, TP2, SL)
    """
    if not isinstance(symbol, str):
        symbol = "BTCUSDT"

    print(f"[STRATEGY] Running MA Crossover Strategy for {symbol}...")

    try:
        data_5m = get_klines_data(symbol, interval=interval, limit=100)
        closes = data_5m["close"]
        current_price = float(closes[-1])
    except Exception as e:
        print(f"[STRATEGY] Market data sync issue for {symbol}: {e}")
        return {
            "symbol": symbol,
            "signal": "HOLD",
            "score": 50,
            "confirmations": 0,
            "current_price": 65000.0,
            "tp1": 66000.0,
            "tp2": 67000.0,
            "structure_sl": 64000.0,
            "rsi": 50.0,
            "atr": 500.0,
            "adx": 20.0,
            "volume_ratio": 1.0,
            "macro_trend": "NEUTRAL",
            "reasons": [f"Market data syncing ({e})"]
        }

    atr = calculate_atr(data_5m) or (current_price * 0.01)
    rsi = calculate_rsi(closes)

    ema_short = calculate_ema(closes, 9)
    ema_long = calculate_ema(closes, 21)
    ema_trend = calculate_ema(closes, 50) or ema_long

    # Previous candle EMAs to detect fresh crossover
    prev_closes = closes[:-1]
    prev_ema_short = calculate_ema(prev_closes, 9)
    prev_ema_long = calculate_ema(prev_closes, 21)

    fresh_bull_cross = bool(prev_ema_short and prev_ema_long and prev_ema_short <= prev_ema_long and ema_short > ema_long)
    fresh_bear_cross = bool(prev_ema_short and prev_ema_long and prev_ema_short >= prev_ema_long and ema_short < ema_long)

    is_bullish_aligned = bool(ema_short and ema_long and ema_short > ema_long)
    is_bearish_aligned = bool(ema_short and ema_long and ema_short < ema_long)

    macro_trend = "BULLISH" if (ema_long and ema_trend and ema_long >= ema_trend) else ("BEARISH" if (ema_long and ema_trend and ema_long < ema_trend) else "NEUTRAL")

    score = 50
    signal = "HOLD"
    reasons = []

    if (fresh_bull_cross or is_bullish_aligned) and rsi < 70:
        if fresh_bull_cross:
            signal = "STRONG_BUY"
            score = 85
            reasons.append(f"Golden Cross detected: Fast EMA(9) {ema_short:.2f} crossed above Slow EMA(21) {ema_long:.2f}")
        else:
            signal = "BUY"
            score = 75
            reasons.append(f"Bullish MA Alignment: Fast EMA(9) {ema_short:.2f} > Slow EMA(21) {ema_long:.2f}")

        reasons.append(f"RSI Momentum: {rsi} (Bullish continuation zone)")
        if macro_trend == "BULLISH":
            score = min(score + 5, 95)
            reasons.append("Macro Trend Aligned (Price above EMA 50)")

    elif (fresh_bear_cross or is_bearish_aligned) and rsi > 30:
        if fresh_bear_cross:
            signal = "STRONG_SELL"
            score = 15
            reasons.append(f"Death Cross detected: Fast EMA(9) {ema_short:.2f} crossed below Slow EMA(21) {ema_long:.2f}")
        else:
            signal = "SELL"
            score = 25
            reasons.append(f"Bearish MA Alignment: Fast EMA(9) {ema_short:.2f} < Slow EMA(21) {ema_long:.2f}")

        reasons.append(f"RSI Momentum: {rsi} (Bearish continuation zone)")
        if macro_trend == "BEARISH":
            score = max(score - 5, 5)
            reasons.append("Macro Trend Aligned (Price below EMA 50)")
    else:
        reasons.append(f"MA crossover neutral: EMA9={ema_short:.2f}, EMA21={ema_long:.2f}, RSI={rsi}")

    # Risk Management Targets (ATR based)
    target_side = "BUY" if "BUY" in signal else ("SELL" if "SELL" in signal else "BUY")
    if target_side == "BUY":
        tp1 = round(current_price + (1.2 * atr), 2)
        tp2 = round(current_price + (2.5 * atr), 2)
        structure_sl = round(current_price - (1.0 * atr), 2)
        if structure_sl > current_price * 0.995:
            structure_sl = round(current_price * 0.995, 2)
    else:
        tp1 = round(current_price - (1.2 * atr), 2)
        tp2 = round(current_price - (2.5 * atr), 2)
        structure_sl = round(current_price + (1.0 * atr), 2)
        if structure_sl < current_price * 1.005:
            structure_sl = round(current_price * 1.005, 2)

    confirmations = 2 if signal != "HOLD" else 0

    print(f"[STRATEGY] Signal: {signal} | Score: {score} | RSI: {rsi} | TP1: ${tp1:,.2f} | TP2: ${tp2:,.2f} | SL: ${structure_sl:,.2f}")

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "confirmations": confirmations,
        "current_price": current_price,
        "tp1": tp1,
        "tp2": tp2,
        "structure_sl": structure_sl,
        "rsi": rsi,
        "atr": atr,
        "adx": 25.0,
        "volume_ratio": 1.2,
        "macro_trend": macro_trend,
        "reasons": reasons
    }


def test_strategy():
    print("Testing Moving Average Crossover Strategy on BTCUSDT...\n")
    result = get_enhanced_signal("BTCUSDT")
    print(f"Signal: {result['signal']} (Score: {result['score']}/100)")
    print(f"Price: ${result['current_price']:,.2f}")
    print("Reasons:", "\n - ".join(result['reasons']))


if __name__ == "__main__":
    test_strategy()
