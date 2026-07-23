import os
import json
import time as time_module
from dotenv import load_dotenv
from groq import Groq

from strategy import get_enhanced_signal
from exchange import get_current_price
from memory import get_open_trades, get_recent_ledger, get_all_learnings, get_stats, get_recent_learnings

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "llama-3.3-70b-versatile"


def build_context(symbol="BTCUSDT"):
    # Get enhanced market data
    signal_data = get_enhanced_signal(symbol)
    price = get_current_price(symbol)
    open_trades = get_open_trades()
    recent_trades = get_recent_ledger(limit=5)
    stats = get_stats()
    recent_learnings = get_recent_learnings(limit=10)
    
    # Format recent trades for LLM
    trades_text = ""
    for t in recent_trades:
        outcome = "✅ PROFIT" if t.get('pnl', 0) >= 0 else "❌ LOSS"
        trades_text += f"\n  - Trade #{t['trade_id']}: {t['side']} at ${t['entry_price']}, closed at ${t['exit_price']}, PnL: ${t.get('pnl', 0):.4f} ({outcome})"
    
    # Format open trades
    open_text = "None"
    if open_trades:
        ot = open_trades[0]
        open_text = f"Trade #{ot['trade_id']}: {ot['side']} at ${ot['entry_price']} (Reason: {ot['reason']})"
        if ot.get('stop_loss'):
            open_text += f", SL: ${ot['stop_loss']}"
        if ot.get('take_profit'):
            open_text += f", TP: ${ot['take_profit']}"
    
    return {
        "symbol": symbol,
        "current_price": price,
        "signal_data": signal_data,
        "open_trades_text": open_text,
        "recent_trades_text": trades_text,
        "stats": stats,
        "learnings": recent_learnings
    }


def ask_brain(symbol="BTCUSDT"):
    context = build_context(symbol)
    sd = context['signal_data']
    
    # Enhanced prompt with structured data
    prompt = f"""You are an expert crypto trading analyst with strict risk management rules.

## CURRENT MARKET DATA
- Symbol: {context['symbol']}
- Price: ${context['current_price']:,.2f}
- Technical Signal: {sd['signal']} (Score: {sd['score']}/100, Confirmations: {sd['confirmations']})
- Short EMA (9): ${sd['short_ema']:,.2f}
- Long EMA (21): ${sd['long_ema']:,.2f}
- RSI: {sd['rsi']:.1f} (30=oversold, 70=overbought)
- MACD Histogram: {sd['macd_hist']:.4f}
- ATR (Volatility): ${sd['atr']:.2f}
- ADX (Trend Strength): {sd['adx']:.1f} (<20=weak, >40=strong)
- Volume Ratio: {sd['volume_ratio']:.2f}x average
- Reasons: {', '.join(sd['reasons'])}

## TRADING PERFORMANCE
- Total Trades: {context['stats']['total_trades']}
- Win Rate: {context['stats'].get('win_rate', 0)}%
- Current Streak: {context['stats']['current_streak']} ({'win' if context['stats']['current_streak'] > 0 else 'loss' if context['stats']['current_streak'] < 0 else 'neutral'})
- Total PnL: ${context['stats']['total_pnl']:.4f}
- Max Drawdown: ${context['stats']['max_drawdown']:.4f}

## OPEN POSITION
{context['open_trades_text']}

## RECENT TRADES
{context['recent_trades_text']}

## PAST LEARNINGS
{context['learnings']}

## YOUR TASK
Based on the technical signal, market conditions, and past performance, decide the best action.

CRITICAL RULES:
1. If ADX < 20 (weak trend), prefer HOLD unless signal is VERY strong
2. If on a losing streak (streak <= -2), reduce confidence and prefer HOLD
3. If drawdown > $1, prefer HOLD to protect capital
4. If there's an open position, only reverse if signal is STRONG and opposite
5. Consider fees: each trade costs ~0.2% round-trip

Respond ONLY with valid JSON:
{{"action": "BUY" or "SELL" or "HOLD", "confidence": 1-10, "reasoning": "brief explanation", "risk_level": "LOW" or "MEDIUM" or "HIGH"}}
"""

    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # Lower = more consistent
                max_tokens=200
            )
            break
        except Exception as e:
            print(f"[WARNING] Brain call failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time_module.sleep(10)

    if response is None:
        return "HOLD", "Brain unavailable - safety fallback", 0, "HIGH"

    text = response.choices[0].message.content.strip()

    # Clean code blocks
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        decision = json.loads(text)
        action = decision.get("action", "HOLD").upper()
        confidence = decision.get("confidence", 5)
        reasoning = decision.get("reasoning", "No reasoning provided")
        risk_level = decision.get("risk_level", "MEDIUM").upper()
        
        # Validate action
        if action not in ["BUY", "SELL", "HOLD"]:
            action = "HOLD"
        
        return action, reasoning, confidence, risk_level
        
    except json.JSONDecodeError:
        print(f"[WARNING] Could not parse brain response: {text[:200]}")
        return "HOLD", "Failed to parse response", 0, "HIGH"


def test_brain():
    print("Testing enhanced Groq brain...\n")
    action, reasoning, confidence, risk = ask_brain("BTCUSDT")
    print(f"Action: {action}")
    print(f"Confidence: {confidence}/10")
    print(f"Risk Level: {risk}")
    print(f"Reasoning: {reasoning}")


if __name__ == "__main__":
    test_brain()