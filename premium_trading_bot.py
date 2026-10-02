import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, Canvas
import threading
import subprocess
import sys
import os
import json
import time
from datetime import datetime
from pathlib import Path
import webbrowser


class PremiumTradingBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Crypto Trading Bot - Professional Edition")
        self.root.geometry("1400x900")
        self.root.configure(bg="#0a0e1a")
        self.root.minsize(1200, 700)

        # State
        self.bot_process = None
        self.dashboard_process = None
        self.is_running = False
        self.log_lines = []
        self.stats_cards = {}
        self.indicator_labels = {}

        # Colors
        self.colors = {
            'bg': '#0a0e1a',
            'card': '#111827',
            'card_border': '#1e293b',
            'primary': '#00d4ff',
            'success': '#10b981',
            'danger': '#ef4444',
            'warning': '#f59e0b',
            'text': '#f1f5f9',
            'text_muted': '#64748b',
            'border': '#1e293b',
            'hover': '#1e293b'
        }

        self.setup_ui()
        self.load_stats()
        self.update_market_data()

    def setup_ui(self):
        # Main container
        main_frame = tk.Frame(self.root, bg=self.colors['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Header
        header = tk.Frame(main_frame, bg=self.colors['bg'])
        header.pack(fill=tk.X, pady=(0, 20))

        # Logo and title
        title_frame = tk.Frame(header, bg=self.colors['bg'])
        title_frame.pack(side=tk.LEFT)

        logo_label = tk.Label(title_frame, text="🤖", font=("Segoe UI", 24), bg=self.colors['bg'])
        logo_label.pack(side=tk.LEFT, padx=(0, 10))

        title_label = tk.Label(title_frame, text="Crypto Trading Bot", 
                              font=("Segoe UI", 24, "bold"), 
                              fg=self.colors['primary'], bg=self.colors['bg'])
        title_label.pack(side=tk.LEFT)

        subtitle = tk.Label(title_frame, text="AI-Powered Trading System v2.0", 
                           font=("Segoe UI", 10), 
                           fg=self.colors['text_muted'], bg=self.colors['bg'])
        subtitle.pack(side=tk.LEFT, padx=(10, 0))

        # Status
        self.status_frame = tk.Frame(header, bg=self.colors['bg'])
        self.status_frame.pack(side=tk.RIGHT)

        self.status_dot = tk.Label(self.status_frame, text="●", 
                                  font=("Segoe UI", 16), 
                                  fg=self.colors['danger'], bg=self.colors['bg'])
        self.status_dot.pack(side=tk.LEFT, padx=(0, 5))

        self.status_label = tk.Label(self.status_frame, text="OFFLINE", 
                                    font=("Segoe UI", 14, "bold"), 
                                    fg=self.colors['danger'], bg=self.colors['bg'])
        self.status_label.pack(side=tk.LEFT)

        # Control Panel
        control_frame = tk.Frame(main_frame, bg=self.colors['card'], 
                                highlightbackground=self.colors['border'],
                                highlightthickness=1, bd=0)
        control_frame.pack(fill=tk.X, pady=(0, 20))

        # Buttons
        btn_frame = tk.Frame(control_frame, bg=self.colors['card'])
        btn_frame.pack(padx=20, pady=15)

        self.start_btn = tk.Button(btn_frame, text="▶  START BOT", 
                                  font=("Segoe UI", 12, "bold"),
                                  bg=self.colors['success'], fg="white",
                                  activebackground="#059669",
                                  bd=0, padx=30, pady=12,
                                  cursor="hand2",
                                  command=self.start_bot)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(btn_frame, text="⏹  STOP BOT", 
                                 font=("Segoe UI", 12, "bold"),
                                 bg=self.colors['danger'], fg="white",
                                 activebackground="#dc2626",
                                 bd=0, padx=30, pady=12,
                                 cursor="hand2",
                                 command=self.stop_bot,
                                 state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Dashboard button
        dashboard_btn = tk.Button(btn_frame, text="📊 Dashboard", 
                                 font=("Segoe UI", 11),
                                 bg=self.colors['card'], fg=self.colors['text'],
                                 activebackground=self.colors['hover'],
                                 bd=1, padx=20, pady=10,
                                 cursor="hand2",
                                 command=self.open_dashboard)
        dashboard_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Clear logs button
        clear_btn = tk.Button(btn_frame, text="🗑 Clear Logs", 
                             font=("Segoe UI", 11),
                             bg=self.colors['card'], fg=self.colors['text'],
                             activebackground=self.colors['hover'],
                             bd=1, padx=20, pady=10,
                             cursor="hand2",
                             command=self.clear_logs)
        clear_btn.pack(side=tk.LEFT)

        # Stats Grid
        stats_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        stats_frame.pack(fill=tk.X, pady=(0, 20))

        stats = [
            ("Total P&L", "$0.00", self.colors['success'], "Lifetime profit/loss"),
            ("Win Rate", "0.0%", self.colors['primary'], "Overall success rate"),
            ("Current Streak", "0 ➖", self.colors['text'], "Consecutive trades"),
            ("Max Drawdown", "$0.00", self.colors['warning'], "Peak to trough loss"),
            ("Total Trades", "0", self.colors['text'], "Completed trades"),
            ("Open Position", "None", self.colors['success'], "Active trade")
        ]

        for i, (title, value, color, desc) in enumerate(stats):
            card = tk.Frame(stats_frame, bg=self.colors['card'],
                           highlightbackground=self.colors['border'],
                           highlightthickness=1, bd=0)
            card.grid(row=0, column=i, padx=(0, 10) if i < 5 else 0, pady=5, sticky="nsew")
            stats_frame.grid_columnconfigure(i, weight=1)

            top_border = tk.Frame(card, bg=color, height=3)
            top_border.pack(fill=tk.X)

            title_label = tk.Label(card, text=title, font=("Segoe UI", 10),
                                  fg=self.colors['text_muted'], bg=self.colors['card'])
            title_label.pack(pady=(10, 5))

            value_label = tk.Label(card, text=value, font=("Segoe UI", 20, "bold"),
                                  fg=color, bg=self.colors['card'])
            value_label.pack()

            desc_label = tk.Label(card, text=desc, font=("Segoe UI", 9),
                                 fg=self.colors['text_muted'], bg=self.colors['card'])
            desc_label.pack(pady=(5, 10))

            self.stats_cards[title] = value_label

        # Bottom Section
        bottom_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        bottom_frame.pack(fill=tk.BOTH, expand=True)

        # Market Overview (Left)
        market_frame = tk.Frame(bottom_frame, bg=self.colors['card'],
                               highlightbackground=self.colors['border'],
                               highlightthickness=1, bd=0)
        market_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        market_header = tk.Frame(market_frame, bg=self.colors['card'])
        market_header.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(market_header, text="📊 Market Overview (Live)", 
                font=("Segoe UI", 14, "bold"),
                fg=self.colors['text'], bg=self.colors['card']).pack(side=tk.LEFT)

        # Price display
        price_frame = tk.Frame(market_frame, bg=self.colors['card'])
        price_frame.pack(padx=15, pady=10)

        self.price_label = tk.Label(price_frame, text="--.--", 
                                   font=("Segoe UI", 36, "bold"),
                                   fg=self.colors['text'], bg=self.colors['card'])
        self.price_label.pack(side=tk.LEFT)

        self.signal_label = tk.Label(price_frame, text="FETCHING...", 
                                    font=("Segoe UI", 12, "bold"),
                                    fg="white", bg=self.colors['warning'],
                                    padx=15, pady=5)
        self.signal_label.pack(side=tk.LEFT, padx=(15, 0))

        # Indicators grid
        indicators_frame = tk.Frame(market_frame, bg=self.colors['card'])
        indicators_frame.pack(fill=tk.X, padx=15, pady=10)

        indicators = [
            ("RSI (14)", "--", "--"),
            ("ATR", "--", "Volatility"),
            ("ADX", "--", "Trend"),
            ("Volume", "--", "Ratio"),
            ("Score", "--", "Signal Score"),
            ("Confidence", "--", "AI Confidence")
        ]

        for i, (name, value, status) in enumerate(indicators):
            row = i // 3
            col = i % 3

            ind_card = tk.Frame(indicators_frame, bg=self.colors['bg'],
                               highlightbackground=self.colors['border'],
                               highlightthickness=1, bd=0)
            ind_card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            indicators_frame.grid_columnconfigure(col, weight=1)

            tk.Label(ind_card, text=name, font=("Segoe UI", 10),
                    fg=self.colors['text_muted'], bg=self.colors['bg']).pack(pady=(8, 2))
            val_lbl = tk.Label(ind_card, text=value, font=("Segoe UI", 16, "bold"),
                    fg=self.colors['text'], bg=self.colors['bg'])
            val_lbl.pack()
            stat_lbl = tk.Label(ind_card, text=status, font=("Segoe UI", 9),
                    fg=self.colors['text_muted'], bg=self.colors['bg'])
            stat_lbl.pack(pady=(2, 8))

            self.indicator_labels[name] = (val_lbl, stat_lbl)

        # System Logs (Right)
        logs_frame = tk.Frame(bottom_frame, bg=self.colors['card'],
                             highlightbackground=self.colors['border'],
                             highlightthickness=1, bd=0)
        logs_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        logs_header = tk.Frame(logs_frame, bg=self.colors['card'])
        logs_header.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(logs_header, text="📝 System Logs", 
                font=("Segoe UI", 14, "bold"),
                fg=self.colors['text'], bg=self.colors['card']).pack(side=tk.LEFT)

        # Log filter
        self.log_filter = ttk.Combobox(logs_header, values=["All", "Check", "Signal", "Trade", "Error"],
                                      state="readonly", width=10)
        self.log_filter.set("All")
        self.log_filter.pack(side=tk.RIGHT)
        self.log_filter.bind("<<ComboboxSelected>>", self.filter_logs)

        # Log text area
        self.log_text = scrolledtext.ScrolledText(logs_frame, 
                                                 font=("Consolas", 10),
                                                 bg=self.colors['bg'],
                                                 fg=self.colors['text'],
                                                 insertbackground=self.colors['text'],
                                                 selectbackground=self.colors['primary'],
                                                 bd=0, padx=10, pady=10,
                                                 wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        self.log_text.config(state=tk.DISABLED)

    def update_status(self, status, color):
        self.status_label.config(text=status, fg=color)
        self.status_dot.config(fg=color)

    def log(self, message, level="info", timestamp=None):
        if not timestamp:
            timestamp = datetime.now().strftime("[%H:%M:%S]")
        elif not (timestamp.startswith("[") and timestamp.endswith("]")):
            timestamp = f"[{timestamp}]"

        colors = {
            "info": self.colors['text'],
            "success": self.colors['success'],
            "warning": self.colors['warning'],
            "error": self.colors['danger'],
            "check": self.colors['primary'],
            "signal": "#f59e0b",
            "trade": self.colors['success']
        }

        self.log_lines.append((timestamp, message, level))

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{timestamp} ", "timestamp")
        self.log_text.insert(tk.END, f"{message}\n", level)
        self.log_text.tag_config("timestamp", foreground=self.colors['text_muted'])
        self.log_text.tag_config("info", foreground=colors["info"])
        self.log_text.tag_config("success", foreground=colors["success"])
        self.log_text.tag_config("warning", foreground=colors["warning"])
        self.log_text.tag_config("error", foreground=colors["error"])
        self.log_text.tag_config("check", foreground=colors["check"])
        self.log_text.tag_config("signal", foreground=colors["signal"])
        self.log_text.tag_config("trade", foreground=colors["trade"])
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def filter_logs(self, event=None):
        filter_level = self.log_filter.get()

        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)

        for timestamp, message, level in self.log_lines:
            if filter_level == "All":
                show = True
            elif filter_level == "Check" and "CHECK" in message:
                show = True
            elif filter_level == "Signal" and "SIGNAL" in message:
                show = True
            elif filter_level == "Trade" and "TRADE" in message:
                show = True
            elif filter_level == "Error" and level == "error":
                show = True
            else:
                show = False

            if show:
                self.log_text.insert(tk.END, f"{timestamp} ", "timestamp")
                self.log_text.insert(tk.END, f"{message}\n", level)

        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_logs(self):
        self.log_lines = []
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def update_market_data(self):
        """Periodically update UI with real-time market_state.json data"""
        try:
            state_file = Path(__file__).resolve().parent / "market_state.json"
            if state_file.exists():
                with open(state_file, 'r') as f:
                    state = json.load(f)

                price = state.get("price", 0)
                signal = state.get("signal", "HOLD")
                rsi = state.get("rsi", 50)
                atr = state.get("atr", 0)
                adx = state.get("adx", 0)
                vol = state.get("volume_ratio", 1)
                score = state.get("score", 50)
                confidence = state.get("confidence", 0)

                # Price & Signal
                self.price_label.config(text=f"${price:,.2f}")
                sig_bg = self.colors['success'] if signal in ['BUY', 'STRONG_BUY'] else self.colors['danger'] if signal in ['SELL', 'STRONG_SELL'] else self.colors['warning']
                self.signal_label.config(text=signal, bg=sig_bg)

                # Indicators
                if "RSI (14)" in self.indicator_labels:
                    v_lbl, s_lbl = self.indicator_labels["RSI (14)"]
                    v_lbl.config(text=f"{rsi:.1f}")
                    s_lbl.config(text="Oversold" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral")

                if "ATR" in self.indicator_labels:
                    v_lbl, s_lbl = self.indicator_labels["ATR"]
                    v_lbl.config(text=f"${atr:.2f}")

                if "ADX" in self.indicator_labels:
                    v_lbl, s_lbl = self.indicator_labels["ADX"]
                    v_lbl.config(text=f"{adx:.1f}")
                    s_lbl.config(text="Weak Trend" if adx < 20 else "Strong Trend" if adx > 40 else "Moderate")

                if "Volume" in self.indicator_labels:
                    v_lbl, s_lbl = self.indicator_labels["Volume"]
                    v_lbl.config(text=f"{vol:.2f}x")

                if "Score" in self.indicator_labels:
                    v_lbl, s_lbl = self.indicator_labels["Score"]
                    v_lbl.config(text=f"{score}/100")
                    s_lbl.config(text="Strong" if score >= 70 else "Weak" if score <= 30 else "Moderate")

                if "Confidence" in self.indicator_labels:
                    v_lbl, s_lbl = self.indicator_labels["Confidence"]
                    v_lbl.config(text=f"{confidence}/10")

            # Also reload stats
            self.load_stats()
        except Exception:
            pass

        self.root.after(3000, self.update_market_data)

    def load_stats(self):
        try:
            stats_file = Path(__file__).resolve().parent / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r') as f:
                    stats = json.load(f)

                pnl = stats.get('total_pnl', 0)
                pnl_color = self.colors['success'] if pnl >= 0 else self.colors['danger']
                if "Total P&L" in self.stats_cards:
                    self.stats_cards["Total P&L"].config(text=f"${pnl:.2f}", fg=pnl_color)

                if "Win Rate" in self.stats_cards:
                    self.stats_cards["Win Rate"].config(text=f"{stats.get('win_rate', 0):.1f}%")

                if "Current Streak" in self.stats_cards:
                    streak = stats.get('current_streak', 0)
                    streak_text = f"{streak} {'🔥' if streak > 0 else '❄️' if streak < 0 else '➖'}"
                    self.stats_cards["Current Streak"].config(text=streak_text)

                if "Max Drawdown" in self.stats_cards:
                    self.stats_cards["Max Drawdown"].config(text=f"${stats.get('max_drawdown', 0):.2f}")

                if "Total Trades" in self.stats_cards:
                    self.stats_cards["Total Trades"].config(text=str(stats.get('total_trades', 0)))

            # Check open position
            ledger_file = Path(__file__).resolve().parent / "ledger.json"
            if ledger_file.exists():
                with open(ledger_file, 'r') as f:
                    ledger = json.load(f)
                open_trades = [t for t in ledger if t.get("status") == "open"]
                if "Open Position" in self.stats_cards:
                    if open_trades:
                        ot = open_trades[0]
                        self.stats_cards["Open Position"].config(text=f"#{ot['trade_id']} {ot['side']}", fg=self.colors['success'])
                    else:
                        self.stats_cards["Open Position"].config(text="None", fg=self.colors['text_muted'])
        except Exception:
            pass

    def start_bot(self):
        if self.is_running:
            return

        try:
            bot_dir = Path(__file__).resolve().parent
            log_file = bot_dir / "bot.log"

            # Clear old logs from UI and file for a fresh start
            self.clear_logs()
            try:
                if log_file.exists():
                    open(log_file, "w").close()
            except Exception:
                pass

            exe_path = os.path.join(bot_dir, "dist", "BotEngine.exe")
            if os.path.exists(exe_path):
                cmd = [exe_path]
            else:
                cmd = [sys.executable, "bot.py"]

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            self.bot_process = subprocess.Popen(
                cmd,
                cwd=bot_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            self.is_running = True
            self.update_status("LIVE", self.colors['success'])
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)

            self.log("Bot started successfully", "success")
            self.log("Monitoring market every 5 minutes...", "info")

            threading.Thread(target=self.read_bot_output, daemon=True).start()

        except Exception as e:
            self.log(f"Failed to start bot: {str(e)}", "error")
            messagebox.showerror("Error", f"Failed to start bot: {str(e)}")

    def stop_bot(self):
        if not self.is_running:
            return

        try:
            if self.bot_process:
                self.bot_process.terminate()
                self.bot_process = None

            self.is_running = False
            self.update_status("OFFLINE", self.colors['danger'])
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

            self.log("Bot stopped", "warning")

        except Exception as e:
            self.log(f"Error stopping bot: {str(e)}", "error")

    def read_bot_output(self):
        """Read bot logs from file safely without holding Windows file locks"""
        log_file = Path(__file__).resolve().parent / "bot.log"

        last_pos = 0

        while self.is_running:
            if not log_file.exists():
                time.sleep(0.5)
                continue

            try:
                with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(last_pos)
                    lines = f.readlines()
                    last_pos = f.tell()

                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue

                    parts = stripped.split(" | ", 2)
                    if len(parts) >= 3:
                        log_time = parts[0]
                        message = parts[2]
                        gui_level = "info"

                        if "CHECK" in message:
                            gui_level = "check"
                        elif "SIGNAL" in message:
                            gui_level = "signal"
                        elif "TRADE" in message:
                            gui_level = "trade"
                        elif "ERROR" in message:
                            gui_level = "error"

                        if "=" in message and len(message) < 60:
                            continue

                        self.log(message, gui_level, timestamp=log_time)
                    else:
                        self.log(stripped, "info")
            except Exception as e:
                pass

            time.sleep(0.5)

    def get_python_exe(self):
        """Get the true Python executable path, even when running inside PyInstaller"""
        if getattr(sys, 'frozen', False):
            import shutil
            py = shutil.which("python")
            if py:
                return py
            user_py = os.path.expanduser("~\\AppData\\Local\\Programs\\Python\\Python314\\python.exe")
            if os.path.exists(user_py):
                return user_py
            return "python"
        return sys.executable

    def open_dashboard(self):
        try:
            bot_dir = Path(__file__).resolve().parent
            python_exe = self.get_python_exe()

            if self.dashboard_process:
                try:
                    self.dashboard_process.terminate()
                except Exception:
                    pass

            self.dashboard_process = subprocess.Popen(
                [python_exe, "-m", "streamlit", "run", "dashboard.py",
                 "--server.headless", "true", "--server.port", "8501"],
                cwd=bot_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.log("Dashboard starting... Opening http://localhost:8501", "success")
            time.sleep(2)
            webbrowser.open("http://localhost:8501")
        except Exception as e:
            self.log(f"Failed to open dashboard: {str(e)}", "error")
            messagebox.showerror("Error", f"Failed to open dashboard: {str(e)}")


def main():
    root = tk.Tk()
    app = PremiumTradingBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
