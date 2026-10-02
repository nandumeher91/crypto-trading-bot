import streamlit as st
import json
import time
from datetime import datetime
from pathlib import Path
import pandas as pd
import os

# Page config
st.set_page_config(
    page_title="🤖 Crypto Trading Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for dark theme
st.markdown("""
<style>
    .main { background-color: #0d1117; }
    .stApp { background-color: #0d1117; }
    h1, h2, h3, h4, h5, h6 { color: #e6edf3 !important; }
    .stMetric { background-color: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 16px; }
    .stMetric label { color: #8b949e !important; font-size: 12px !important; text-transform: uppercase; }
    .stMetric div { color: #e6edf3 !important; font-size: 24px !important; font-weight: 700 !important; }
    div[data-testid="stVerticalBlock"] > div { background-color: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
    .stDataFrame { background-color: #161b22 !important; }
    .stDataFrame td { color: #e6edf3 !important; }
    .stDataFrame th { color: #8b949e !important; }
</style>
""", unsafe_allow_html=True)

BASE_DIR = Path(__file__).resolve().parent

# Helper functions
def read_ledger():
    ledger_file = BASE_DIR / "ledger.json"
    if ledger_file.exists():
        try:
            with open(ledger_file, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def read_stats():
    stats_file = BASE_DIR / "stats.json"
    if stats_file.exists():
        try:
            with open(stats_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "total_pnl": 0.0, "largest_win": 0.0, "largest_loss": 0.0,
        "current_streak": 0, "max_drawdown": 0.0, "win_rate": 0
    }

def read_learnings():
    learnings_file = BASE_DIR / "learnings.txt"
    if learnings_file.exists():
        try:
            with open(learnings_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            return lines[-10:]  # Last 10 lines
        except Exception:
            return []
    return []

# Load data
ledger = read_ledger()
stats = read_stats()
learnings = read_learnings()

# Header
st.markdown("""
<div style="display:flex;justify-space-between;align-items:center;margin-bottom:24px;">
    <div>
        <h1 style="margin:0;color:#58a6ff;">🤖 Crypto Trading Bot Dashboard</h1>
        <p style="margin:4px 0 0;color:#8b949e;font-size:14px;">BTCUSDT • Testnet • Auto-Trading Active</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Stats Row
col1, col2, col3, col4 = st.columns(4)

pnl_color = "#3fb950" if stats.get("total_pnl", 0) >= 0 else "#da3633"
streak = stats.get("current_streak", 0)
streak_emoji = "🔥" if streak > 0 else "❄️" if streak < 0 else "➖"

with col1:
    st.metric("Total P&L", f"${stats.get('total_pnl', 0):.2f}", "Lifetime")
with col2:
    st.metric("Win Rate", f"{stats.get('win_rate', 0):.1f}%", f"{stats.get('total_trades', 0)} trades")
with col3:
    st.metric("Current Streak", f"{streak} {streak_emoji}", "Win/Loss streak")
with col4:
    st.metric("Max Drawdown", f"${stats.get('max_drawdown', 0):.2f}", "Peak to trough")

# Main Content: 2 columns
left_col, right_col = st.columns(2)

with left_col:
    st.subheader("📊 Recent Performance Summary")
    open_trades = [t for t in ledger if t.get("status") == "open"]
    st.markdown(f"**Active Open Positions:** {len(open_trades)}")
    for ot in open_trades:
        st.info(f"Trade #{ot['trade_id']} | {ot['side']} @ ${ot['entry_price']} | SL: ${ot.get('stop_loss', 'N/A')} | TP: ${ot.get('take_profit', 'N/A')}")

with right_col:
    st.subheader("📈 P&L Over Time")
    if ledger:
        closed_trades = [t for t in ledger if t.get("status") == "closed"]
        if closed_trades:
            df = pd.DataFrame(closed_trades)
            if 'exit_timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['exit_timestamp'])
                df['cumulative_pnl'] = df['pnl'].cumsum()
                st.line_chart(df.set_index('timestamp')['cumulative_pnl'], use_container_width=True)
            else:
                st.info("Insufficient timestamps for chart")
        else:
            st.info("No closed trades yet")
    else:
        st.info("No trades yet")

# Bottom Row
bottom_left, bottom_right = st.columns(2)

with bottom_left:
    st.subheader("📋 Recent Trades Ledger")
    if ledger:
        trades_data = []
        for t in ledger[-10:]:
            trades_data.append({
                "ID": f"#{t['trade_id']}",
                "Side": t['side'],
                "Entry": f"${t['entry_price']:,.2f}",
                "Exit": f"${t['exit_price']:,.2f}" if t.get('exit_price') else "—",
                "PnL": f"${t['pnl']:+.4f}" if t.get('pnl') is not None else "—",
                "Status": t.get('status', 'unknown').upper()
            })
        df_trades = pd.DataFrame(trades_data)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No trades recorded")

with bottom_right:
    st.subheader("🧠 Brain Decision & Learnings Log")
    if learnings:
        for line in reversed(learnings):
            line = line.strip()
            if line:
                border_color = "#1f6feb" if "Trade #" in line else "#238636"
                st.markdown(f"""
                <div style="padding:10px;background:#0d1117;border-radius:8px;margin-bottom:8px;border-left:3px solid {border_color};">
                    <p style="margin:0;font-size:12px;color:#8b949e;line-height:1.4;">{line}</p>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("No learnings recorded yet")

# Footer
st.markdown("""
<div style="margin-top:24px;text-align:center;padding:16px;border-top:1px solid #30363d;">
    <p style="margin:0;font-size:12px;color:#484f58;">🤖 Crypto Trading Bot Dashboard • Binance Testnet</p>
    <p style="margin:4px 0 0;font-size:11px;color:#484f58;">Last updated: {}</p>
</div>
""".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)
