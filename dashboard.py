
dashboard_code = '''import streamlit as st
import json
import time
from datetime import datetime
from pathlib import Path
import pandas as pd

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

# Helper functions
def read_ledger():
    ledger_file = Path("ledger.json")
    if ledger_file.exists():
        with open(ledger_file, 'r') as f:
            return json.load(f)
    return []

def read_stats():
    stats_file = Path("stats.json")
    if stats_file.exists():
        with open(stats_file, 'r') as f:
            return json.load(f)
    return {
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "total_pnl": 0.0, "largest_win": 0.0, "largest_loss": 0.0,
        "current_streak": 0, "max_drawdown": 0.0, "win_rate": 0
    }

def read_learnings():
    learnings_file = Path("learnings.txt")
    if learnings_file.exists():
        with open(learnings_file, 'r') as f:
            lines = f.readlines()
        return lines[-10:]  # Last 10 lines
    return []

# Load data
ledger = read_ledger()
stats = read_stats()
learnings = read_learnings()

# Header
st.markdown("""
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
    <div>
        <h1 style="margin:0;color:#58a6ff;">🤖 Crypto Trading Bot</h1>
        <p style="margin:4px 0 0;color:#8b949e;font-size:14px;">BTCUSDT • Testnet • Auto-Trading Active</p>
    </div>
    <div style="display:flex;gap:12px;">
        <span style="background:#238636;color:#fff;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600;">● LIVE</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Stats Row
col1, col2, col3, col4 = st.columns(4)

pnl_color = "#3fb950" if stats["total_pnl"] >= 0 else "#da3633"
streak_emoji = "🔥" if stats["current_streak"] > 0 else "❄️" if stats["current_streak"] < 0 else "➖"

with col1:
    st.metric("Total P&L", f"${stats['total_pnl']:.2f}", "Lifetime")
with col2:
    st.metric("Win Rate", f"{stats['win_rate']:.1f}%", f"{stats['total_trades']} trades")
with col3:
    st.metric("Current Streak", f"{stats['current_streak']} {streak_emoji}", "Win/Loss streak")
with col4:
    st.metric("Max Drawdown", f"${stats['max_drawdown']:.2f}", "Peak to trough")

# Main Content: 2 columns
left_col, right_col = st.columns(2)

with left_col:
    st.subheader("📊 Current Market")
    
    # Get latest trade for current price reference
    current_price = 64850.40  # Will be fetched from exchange in real version
    
    st.markdown(f"""
    <div style="padding:16px;background:#0d1117;border-radius:8px;margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <p style="margin:0;font-size:32px;font-weight:700;color:#e6edf3;">${current_price:,.2f}</p>
                <p style="margin:4px 0 0;font-size:13px;color:#3fb950;">▲ +1.2% (24h)</p>
            </div>
            <div style="text-align:right;">
                <span style="background:#da3633;color:#fff;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:600;">SELL</span>
                <p style="margin:4px 0 0;font-size:12px;color:#8b949e;">Score: 35/100</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Indicators
    ind_col1, ind_col2 = st.columns(2)
    with ind_col1:
        st.markdown("""
        <div style="padding:10px 14px;background:#0d1117;border-radius:8px;margin-bottom:8px;">
            <p style="margin:0;font-size:11px;color:#8b949e;">RSI (14)</p>
            <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:#e6edf3;">48.2</p>
        </div>
        <div style="padding:10px 14px;background:#0d1117;border-radius:8px;">
            <p style="margin:0;font-size:11px;color:#8b949e;">ADX</p>
            <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:#da3633;">18.8 ⚠️</p>
        </div>
        """, unsafe_allow_html=True)
    with ind_col2:
        st.markdown("""
        <div style="padding:10px 14px;background:#0d1117;border-radius:8px;margin-bottom:8px;">
            <p style="margin:0;font-size:11px;color:#8b949e;">ATR</p>
            <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:#e6edf3;">$25.58</p>
        </div>
        <div style="padding:10px 14px;background:#0d1117;border-radius:8px;">
            <p style="margin:0;font-size:11px;color:#8b949e;">Volume</p>
            <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:#e6edf3;">0.09x</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Brain Decision
    st.markdown("""
    <div style="margin-top:16px;padding:12px;background:#0d1117;border-radius:8px;border-left:3px solid #1f6feb;">
        <p style="margin:0;font-size:12px;color:#8b949e;">🧠 Brain Decision</p>
        <p style="margin:4px 0 0;font-size:14px;color:#e6edf3;"><strong>HOLD</strong> — Confidence: 6/10 | Risk: MEDIUM</p>
        <p style="margin:4px 0 0;font-size:12px;color:#8b949e;line-height:1.5;">Current technical signal is SELL but with a low score of 35/100 and ADX indicates a weak trend, combined with an open position...</p>
    </div>
    """, unsafe_allow_html=True)

with right_col:
    st.subheader("📈 P&L Over Time")
    
    # Create P&L chart data
    if ledger:
        closed_trades = [t for t in ledger if t.get("status") == "closed"]
        if closed_trades:
            df = pd.DataFrame(closed_trades)
            df['timestamp'] = pd.to_datetime(df['exit_timestamp'])
            df['cumulative_pnl'] = df['pnl'].cumsum()
            
            st.line_chart(df.set_index('timestamp')['cumulative_pnl'], use_container_width=True)
        else:
            st.info("No closed trades yet")
    else:
        st.info("No trades yet")

# Bottom Row
bottom_left, bottom_right = st.columns(2)

with bottom_left:
    st.subheader("📋 Recent Trades")
    
    if ledger:
        # Prepare trades data
        trades_data = []
        for t in ledger[-10:]:  # Last 10 trades
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
    st.subheader("🧠 Brain Decisions Log")
    
    if learnings:
        for line in reversed(learnings):
            line = line.strip()
            if line:
                # Parse learning line
                if "Trade #" in line:
                    st.markdown(f"""
                    <div style="padding:10px;background:#0d1117;border-radius:8px;margin-bottom:8px;border-left:3px solid #1f6feb;">
                        <p style="margin:0;font-size:12px;color:#8b949e;line-height:1.4;">{line}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="padding:10px;background:#0d1117;border-radius:8px;margin-bottom:8px;border-left:3px solid #238636;">
                        <p style="margin:0;font-size:12px;color:#8b949e;line-height:1.4;">{line}</p>
                    </div>
                    """, unsafe_allow_html=True)
    else:
        st.info("No learnings recorded yet")

# Footer
st.markdown("""
<div style="margin-top:24px;text-align:center;padding:16px;border-top:1px solid #30363d;">
    <p style="margin:0;font-size:12px;color:#484f58;">🤖 Enhanced Trading Bot v2.0 • Powered by Groq AI • Binance Testnet</p>
    <p style="margin:4px 0 0;font-size:11px;color:#484f58;">Last updated: {}</p>
</div>
""".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)

# Auto-refresh
st.markdown("""
<script>
    setTimeout(function(){
        window.location.reload();
    }, 30000);
</script>
""", unsafe_allow_html=True)
'''

with open('/mnt/agents/output/dashboard.py', 'w') as f:
    f.write(dashboard_code)

print("dashboard.py created successfully!")
print(f"File size: {len(dashboard_code)} characters")
