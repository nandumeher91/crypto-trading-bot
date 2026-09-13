import os
import json
import re
import time as time_module
from dotenv import load_dotenv
from groq import Groq

from strategy import get_enhanced_signal
from exchange import get_current_price
from memory import get_open_trades, get_recent_ledger, get_all_learnings, get_stats, get_recent_learnings

ENV_PATH = os.path.join("C:/Users/nandu/OneDrive/Desktop/BOT", ".env")
load_dotenv(ENV_PATH)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# UPDATED MODELS - Valid Groq models
MODEL_NAME = "openai/gpt-oss-120b"
FALLBACK_MODEL_NAME = "openai/gpt-oss-20b"


def safe_print(msg):
    """Safely print messages on Windows without crashing on Unicode characters"""
    try:
        print(msg)
    except Exception:
        try:
            print(str(msg).encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass


def build_context(symbol="BTCUSDT"):
    """Build market context for LLM decision making"""
    if not isinstance(symbol, str):
        safe_print(f"[BRAIN] WARNING: build_context got non-string symbol: {type(symbol).__name__}. Using BTCUSDT.")
        symbol = "BTCUSDT"

    signal_data = get_enhanced_signal(symbol)
    price = get_current_price(symbol)
    open_trades = get_open_trades()
    recent_trades = get_recent_ledger(limit=5)
    stats = get_stats()
    recent_learnings = get_recent_learnings(limit=10)

    trades_text = ""
    for t in recent_trades:
        outcome = "PROFIT" if t.get('pnl', 0) >= 0 else "LOSS"
        trades_text += f"\n  - Trade #{t['trade_id']}: {t['side']} at ${t['entry_price']}, closed at ${t['exit_price']}, PnL: ${t.get('pnl', 0):.4f} ({outcome})"

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


def extract_json(text):
    """Extract JSON from any text response - handles markdown, reasoning, etc."""
    if not text:
        return None
    text = text.strip()

    # 1. Try direct JSON load
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. Try markdown code block regex
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    # 3. Try finding outer curly braces
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


def ask_brain(brain_input=None, symbol="BTCUSDT"):
    """Ask Groq AI for trading decision."""
    if brain_input is not None:
        if isinstance(brain_input, dict):
            symbol = brain_input.get("symbol", "BTCUSDT")
            safe_print(f"[BRAIN] Called with dict input. Using symbol: {symbol}")
        elif isinstance(brain_input, str):
            symbol = brain_input
            safe_print(f"[BRAIN] Called with string: {symbol}")
        else:
            safe_print(f"[BRAIN] WARNING: Unexpected input type: {type(brain_input).__name__}. Using BTCUSDT.")
            symbol = "BTCUSDT"

    context = build_context(symbol)
    sd = context['signal_data']

    prompt = f"""You are an elite Crypto Derivatives Quant & Smart Money Concepts (SMC) Execution Specialist for BTCUSDT.

## CURRENT MARKET & SMC TRIAD DATA
- Symbol: {context['symbol']}
- Price: ${context['current_price']:,.2f}
- Technical Signal: {sd['signal']} (Score: {sd['score']}/100, Confirmations: {sd['confirmations']})
- Liquidity Sweep Signal: {sd.get('sweep_signal', 'NONE')}
- 15m/5m Macro Trend: {sd.get('macro_trend', 'NEUTRAL')}
- 5m Fib OTE Sweet Spot (0.705): ${sd.get('fib_ote_sweet_spot', 0) or 0:,.2f}
- ATR (Volatility): ${sd['atr']:.2f}
- Reasons & Checklist: {', '.join(sd['reasons'])}

## TRADING PERFORMANCE & CAPITAL RISK
- Total Trades: {context['stats']['total_trades']}
- Win Rate: {context['stats'].get('win_rate', 0)}%
- Current Streak: {context['stats']['current_streak']}
- Total PnL: ${context['stats']['total_pnl']:.4f}

## OPEN POSITION
{context['open_trades_text']}

## PAST LEARNINGS
{context['learnings']}

## MANDATORY EXECUTION RULES:
1. Approve BUY ONLY if 15m/5m Sell-Side Liquidity Sweep (SSL) + 5m Displacement + 0.618-0.786 Fib OTE Retracement + 1m CHoCH trigger is confirmed (Signal = STRONG_BUY).
2. Approve SELL ONLY if Buy-Side Liquidity Sweep (BSL) + 5m Displacement + 0.618-0.786 Fib OTE Retracement + 1m CHoCH trigger is confirmed (Signal = STRONG_SELL).
3. Require Minimum 1:3.0 Risk-to-Reward Ratio (R:R) for full execution.
4. If ANY checklist item is incomplete, output "action": "HOLD".

Output MUST be a JSON object with keys: "action" ("BUY", "SELL", or "HOLD"), "confidence" (1-10 integer), "reasoning" (string), "risk_level" ("LOW", "MEDIUM", or "HIGH").
"""

    models_to_try = [MODEL_NAME, FALLBACK_MODEL_NAME]
    response = None
    last_error = None

    for model in models_to_try:
        try:
            safe_print(f"[BRAIN] Calling Groq API model: {model}...")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a professional crypto trading AI assistant. Always output a valid JSON object."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            if response and response.choices:
                break
        except Exception as e:
            last_error = str(e)
            safe_print(f"[WARNING] Groq API call with {model} failed: {e}")
            time_module.sleep(2)

    if response is None:
        safe_print(f"[BRAIN] All models failed. Last error: {last_error}")
        return {"action": "HOLD", "confidence": 0, "reason": "Brain API unavailable - safety fallback", "risk_level": "HIGH"}

    text = response.choices[0].message.content.strip()

    decision = extract_json(text)

    if decision is None:
        safe_print(f"[WARNING] Could not parse brain response")
        return {"action": "HOLD", "confidence": 0, "reason": "Failed to parse response", "risk_level": "HIGH"}

    action = decision.get("action", "HOLD").upper()
    confidence = decision.get("confidence", 5)
    reasoning = decision.get("reasoning", "No reasoning provided")
    risk_level = decision.get("risk_level", "MEDIUM").upper()

    if action not in ["BUY", "SELL", "HOLD"]:
        action = "HOLD"

    # Sanitize reasoning text for printing safely
    clean_reason = reasoning.encode('ascii', errors='replace').decode('ascii')
    safe_print(f"[BRAIN] Parsed: {action} | Confidence: {confidence}/10 | Risk: {risk_level}")
    safe_print(f"[BRAIN] Reasoning: {clean_reason}")

    return {
        "action": action,
        "confidence": confidence,
        "reason": clean_reason,
        "risk_level": risk_level
    }


def test_brain():
    safe_print("Testing enhanced Groq brain...\n")
    safe_print("--- Test 1: Direct string call ---")
    result = ask_brain(symbol="BTCUSDT")
    safe_print(f"Action: {result['action']}")
    safe_print(f"Confidence: {result['confidence']}/10")
    safe_print(f"Risk Level: {result['risk_level']}")
    safe_print(f"Reason: {result['reason']}")

    safe_print("\n--- Test 2: Dict call (bot.py style) ---")
    brain_input = {
        "signal": "BUY",
        "score": 75,
        "price": 65000.0,
        "stats": {"total_trades": 4, "win_rate": 25},
        "open_positions": 0
    }
    result = ask_brain(brain_input)
    safe_print(f"Action: {result['action']}")
    safe_print(f"Confidence: {result['confidence']}/10")
    safe_print(f"Reason: {result['reason']}")


if __name__ == "__main__":
    test_brain()