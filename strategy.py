import numpy as np
from binance.client import Client
from exchange import client


def get_klines_data(symbol="BTCUSDT", interval="1m", limit=100):
    """Get OHLCV data from Binance"""
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    return {
        'open': np.array([float(k[1]) for k in klines]),
        'high': np.array([float(k[2]) for k in klines]),
        'low': np.array([float(k[3]) for k in klines]),
        'close': np.array([float(k[4]) for k in klines]),
        'volume': np.array([float(k[5]) for k in klines])
    }


def calculate_ema(prices, period):
    """Exponential Moving Average"""
    if len(prices) < period:
        return None
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    return np.convolve(prices, weights, mode='valid')[-1]


def calculate_rsi(prices, period=14):
    """RSI - Overbought/Oversold"""
    if len(prices) < period + 1:
        return None
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD for trend momentum"""
    if len(prices) < slow:
        return None, None, None
    
    ema_fast = np.mean(prices[-fast:])
    ema_slow = np.mean(prices[-slow:])
    macd_line = ema_fast - ema_slow
    
    # Signal line (simplified)
    signal_prices = prices[-(slow+signal):-slow] if len(prices) >= slow+signal else prices[-slow:]
    signal_line = np.mean(signal_prices) if len(signal_prices) > 0 else ema_slow
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Bollinger Bands for volatility"""
    if len(prices) < period:
        return None, None, None
    
    sma = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def calculate_atr(data, period=14):
    """Average True Range for volatility-based stops"""
    highs, lows, closes = data['high'], data['low'], data['close']
    if len(closes) < period + 1:
        return None
    
    tr_list = []
    for i in range(1, len(closes)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr_list.append(max(tr1, tr2, tr3))
    
    return np.mean(tr_list[-period:])


def calculate_adx(data, period=14):
    """Average Directional Index - Trend strength"""
    highs, lows, closes = data['high'], data['low'], data['close']
    if len(closes) < period * 2:
        return None
    
    # Simplified ADX
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        plus_dm.append(max(up_move, 0) if up_move > down_move else 0)
        minus_dm.append(max(down_move, 0) if down_move > up_move else 0)
        
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr_list.append(max(tr1, tr2, tr3))
    
    # Smoothed averages
    atr = np.mean(tr_list[-period:])
    plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr > 0 else 0
    minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr > 0 else 0
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
    return dx  # Simplified ADX


def get_enhanced_signal(symbol="BTCUSDT", interval="1m"):
    """
    Enhanced strategy with multiple indicators and scoring
    Returns: dict with signal, score, and all indicator values
    """
    data = get_klines_data(symbol, interval, limit=100)
    closes = data['close']
    current_price = closes[-1]
    
    # Calculate all indicators
    short_ema = calculate_ema(closes, 9)
    long_ema = calculate_ema(closes, 21)
    rsi = calculate_rsi(closes)
    macd_line, signal_line, macd_hist = calculate_macd(closes)
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(closes)
    atr = calculate_atr(data)
    adx = calculate_adx(data)
    
    # Scoring system (0-100)
    score = 50  # Neutral start
    reasons = []
    confirmations = 0
    
    # 1. EMA Crossover (Weight: 25)
    if short_ema and long_ema:
        if short_ema > long_ema * 1.001:  # 0.1% buffer to avoid whipsaws
            score += 15
            reasons.append("EMA Bullish crossover")
            confirmations += 1
        elif short_ema < long_ema * 0.999:
            score -= 15
            reasons.append("EMA Bearish crossover")
            confirmations += 1
    
    # 2. RSI Filter (Weight: 20)
    if rsi:
        if rsi < 30:
            score += 10
            reasons.append(f"RSI Oversold ({rsi:.1f})")
            confirmations += 1
        elif rsi > 70:
            score -= 10
            reasons.append(f"RSI Overbought ({rsi:.1f})")
            confirmations += 1
        elif 40 < rsi < 60:
            reasons.append(f"RSI Neutral ({rsi:.1f})")
    
    # 3. MACD (Weight: 20)
    if macd_hist is not None:
        if macd_hist > 0:
            score += 10
            reasons.append("MACD Bullish")
            confirmations += 1
        else:
            score -= 10
            reasons.append("MACD Bearish")
            confirmations += 1
    
    # 4. Bollinger Bands (Weight: 15)
    if bb_upper and bb_lower:
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower)
        if bb_position < 0.1:  # Near lower band
            score += 8
            reasons.append("Price near BB Lower (oversold)")
            confirmations += 1
        elif bb_position > 0.9:  # Near upper band
            score -= 8
            reasons.append("Price near BB Upper (overbought)")
            confirmations += 1
    
    # 5. Volume confirmation (Weight: 10)
    volumes = data['volume']
    avg_volume = np.mean(volumes[-20:])
    current_volume = volumes[-1]
    if current_volume > avg_volume * 1.5:
        score += (5 if score > 50 else -5)  # Confirm current direction
        reasons.append("High volume confirmation")
        confirmations += 1
    
    # 6. ADX - Trend strength filter (Weight: 10)
    if adx:
        if adx < 20:
            score = 50  # Reset to neutral in weak trend
            reasons.append("Weak trend (ADX < 20) - AVOID")
        elif adx > 40:
            score += (5 if score > 50 else -5)
            reasons.append("Strong trend confirmed")
    
    # Determine signal
    if score >= 70 and confirmations >= 3:
        signal = "STRONG_BUY"
    elif score >= 60 and confirmations >= 2:
        signal = "BUY"
    elif score <= 30 and confirmations >= 3:
        signal = "STRONG_SELL"
    elif score <= 40 and confirmations >= 2:
        signal = "SELL"
    else:
        signal = "HOLD"
    
    return {
        "signal": signal,
        "score": score,
        "confirmations": confirmations,
        "current_price": current_price,
        "short_ema": short_ema,
        "long_ema": long_ema,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "bb_position": bb_position if bb_upper else None,
        "atr": atr,
        "adx": adx,
        "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 1,
        "reasons": reasons
    }


def test_strategy():
    print("Testing enhanced strategy on BTCUSDT...\n")
    result = get_enhanced_signal("BTCUSDT")
    
    print(f"Signal: {result['signal']} (Score: {result['score']}/100, Confirmations: {result['confirmations']})")
    print(f"Price: ${result['current_price']:,.2f}")
    print(f"RSI: {result['rsi']:.1f}")
    print(f"ATR: {result['atr']:.2f}")
    print(f"ADX: {result['adx']:.1f}" if result['adx'] else "ADX: N/A")
    print(f"Volume Ratio: {result['volume_ratio']:.2f}x")
    print(f"Reasons: {', '.join(result['reasons'])}")


if __name__ == "__main__":
    test_strategy()