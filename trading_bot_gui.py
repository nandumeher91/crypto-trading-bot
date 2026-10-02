import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import subprocess
import sys
import os
import json
import time
from datetime import datetime
from pathlib import Path

class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 Crypto Trading Bot")
        self.root.geometry("1200x800")
        self.root.configure(bg="#0d1117")

        # Bot process
        self.bot_process = None
        self.dashboard_process = None
        self.is_running = False

        self.setup_ui()
        self.update_stats()

    def setup_ui(self):
        # Main container
        main_frame = tk.Frame(self.root, bg="#0d1117")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ===== HEADER =====
        header = tk.Frame(main_frame, bg="#0d1117")
        header.pack(fill=tk.X, pady=(0, 20))

        tk.Label(header, text="🤖 Crypto Trading Bot", 
                font=("Segoe UI", 24, "bold"), fg="#58a6ff", bg="#0d1117").pack(side=tk.LEFT)

        self.status_label = tk.Label(header, text="● OFFLINE", 
                                     font=("Segoe UI", 14, "bold"), fg="#da3633", bg="#0d1117")
        self.status_label.pack(side=tk.RIGHT)

        # ===== CONTROL BUTTONS =====
        control_frame = tk.Frame(main_frame, bg="#161b22", bd=1, relief=tk.SOLID)
        control_frame.pack(fill=tk.X, pady=(0, 20), ipady=10)

        self.start_btn = tk.Button(control_frame, text="▶ START BOT", 
                                   font=("Segoe UI", 14, "bold"),
                                   bg="#238636", fg="white", 
                                   activebackground="#2ea043",
                                   padx=30, pady=10,
                                   command=self.start_bot,
                                   cursor="hand2")
        self.start_btn.pack(side=tk.LEFT, padx=20)

        self.stop_btn = tk.Button(control_frame, text="⏹ STOP BOT", 
                                  font=("Segoe UI", 14, "bold"),
                                  bg="#da3633", fg="white",
                                  activebackground="#f85149",
                                  padx=30, pady=10,
                                  command=self.stop_bot,
                                  state=tk.DISABLED,
                                  cursor="hand2")
        self.stop_btn.pack(side=tk.LEFT, padx=10)

        self.dashboard_btn = tk.Button(control_frame, text="📊 OPEN DASHBOARD", 
                                       font=("Segoe UI", 12),
                                       bg="#1f6feb", fg="white",
                                       activebackground="#388bfd",
                                       padx=20, pady=10,
                                       command=self.open_dashboard,
                                       cursor="hand2")
        self.dashboard_btn.pack(side=tk.RIGHT, padx=20)

        # ===== STATS CARDS =====
        stats_frame = tk.Frame(main_frame, bg="#0d1117")
        stats_frame.pack(fill=tk.X, pady=(0, 20))

        self.stats_cards = {}
        stats = [
            ("Total P&L", "-$0.91", "#da3633"),
            ("Win Rate", "50.0%", "#58a6ff"),
            ("Current Streak", "-1 ❄️", "#da3633"),
            ("Max Drawdown", "$0.91", "#da3633")
        ]

        for i, (title, value, color) in enumerate(stats):
            card = tk.Frame(stats_frame, bg="#161b22", bd=1, relief=tk.SOLID)
            card.grid(row=0, column=i, padx=10, pady=5, sticky="nsew")
            stats_frame.grid_columnconfigure(i, weight=1)

            tk.Label(card, text=title, font=("Segoe UI", 10), 
                    fg="#8b949e", bg="#161b22").pack(pady=(15, 5))

            value_label = tk.Label(card, text=value, font=("Segoe UI", 20, "bold"),
                                  fg=color, bg="#161b22")
            value_label.pack(pady=(0, 15))
            self.stats_cards[title] = value_label

        # ===== MAIN CONTENT: 2 COLUMNS =====
        content_frame = tk.Frame(main_frame, bg="#0d1117")
        content_frame.pack(fill=tk.BOTH, expand=True)

        # LEFT: Market Info + Brain Decision
        left_frame = tk.Frame(content_frame, bg="#161b22", bd=1, relief=tk.SOLID)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(left_frame, text="📊 Current Market", 
                font=("Segoe UI", 14, "bold"), fg="#e6edf3", bg="#161b22").pack(pady=15)

        # Price display
        price_frame = tk.Frame(left_frame, bg="#0d1117")
        price_frame.pack(fill=tk.X, padx=15, pady=10)

        self.price_label = tk.Label(price_frame, text="$64,850.40", 
                                   font=("Segoe UI", 28, "bold"),
                                   fg="#e6edf3", bg="#0d1117")
        self.price_label.pack(side=tk.LEFT)

        self.signal_label = tk.Label(price_frame, text="SELL", 
                                    font=("Segoe UI", 12, "bold"),
                                    fg="white", bg="#da3633",
                                    padx=15, pady=5)
        self.signal_label.pack(side=tk.RIGHT)

        # Indicators
        ind_frame = tk.Frame(left_frame, bg="#161b22")
        ind_frame.pack(fill=tk.X, padx=15, pady=10)

        self.indicators = {}
        indicators_data = [
            ("RSI (14)", "48.2"),
            ("ATR", "$25.58"),
            ("ADX", "18.8 ⚠️"),
            ("Volume", "0.09x")
        ]

        for i, (name, value) in enumerate(indicators_data):
            row = i // 2
            col = i % 2
            ind_card = tk.Frame(ind_frame, bg="#0d1117")
            ind_card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            ind_frame.grid_columnconfigure(col, weight=1)

            tk.Label(ind_card, text=name, font=("Segoe UI", 9),
                    fg="#8b949e", bg="#0d1117").pack(pady=(8, 2))

            val_label = tk.Label(ind_card, text=value, font=("Segoe UI", 14, "bold"),
                               fg="#e6edf3", bg="#0d1117")
            val_label.pack(pady=(0, 8))
            self.indicators[name] = val_label

        # Brain Decision
        brain_frame = tk.Frame(left_frame, bg="#0d1117", bd=1, relief=tk.SOLID)
        brain_frame.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(brain_frame, text="🧠 Brain Decision", 
                font=("Segoe UI", 11), fg="#8b949e", bg="#0d1117").pack(anchor=tk.W, padx=10, pady=(10, 5))

        self.brain_decision = tk.Label(brain_frame, text="HOLD — Confidence: 6/10 | Risk: MEDIUM",
                                      font=("Segoe UI", 12, "bold"),
                                      fg="#e6edf3", bg="#0d1117")
        self.brain_decision.pack(anchor=tk.W, padx=10)

        self.brain_reason = tk.Label(brain_frame, 
                                    text="Current technical signal is SELL but with a low score of 35/100...",
                                    font=("Segoe UI", 10), fg="#8b949e", bg="#0d1117",
                                    wraplength=400, justify=tk.LEFT)
        self.brain_reason.pack(anchor=tk.W, padx=10, pady=(5, 10))

        # RIGHT: Logs
        right_frame = tk.Frame(content_frame, bg="#161b22", bd=1, relief=tk.SOLID)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        tk.Label(right_frame, text="📋 Bot Logs", 
                font=("Segoe UI", 14, "bold"), fg="#e6edf3", bg="#161b22").pack(pady=15)

        self.log_text = scrolledtext.ScrolledText(right_frame, 
                                                   font=("Consolas", 10),
                                                   bg="#0d1117", fg="#e6edf3",
                                                   insertbackground="white",
                                                   wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        self.log_text.config(state=tk.DISABLED)

        # ===== FOOTER =====
        footer = tk.Frame(main_frame, bg="#0d1117")
        footer.pack(fill=tk.X, pady=(20, 0))

        self.footer_label = tk.Label(footer, 
                                    text="🤖 Enhanced Trading Bot v2.0 • Last updated: --",
                                    font=("Segoe UI", 10), fg="#484f58", bg="#0d1117")
        self.footer_label.pack()

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def start_bot(self):
        if self.is_running:
            return

        try:
            # Change to BOT directory
            bot_dir = Path(__file__).resolve().parent

            # Start bot in background
            self.bot_process = subprocess.Popen(
                [sys.executable, "bot.py"],
                cwd=bot_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )

            self.is_running = True
            self.status_label.config(text="● LIVE", fg="#3fb950")
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)

            self.log("✅ Bot started successfully!")
            self.log("📊 Checking market every 5 minutes...")

            # Start log reader thread
            threading.Thread(target=self.read_bot_logs, daemon=True).start()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start bot: {str(e)}")
            self.log(f"❌ Error starting bot: {str(e)}")

    def stop_bot(self):
        if not self.is_running:
            return

        try:
            if self.bot_process:
                self.bot_process.terminate()
                self.bot_process = None

            self.is_running = False
            self.status_label.config(text="● OFFLINE", fg="#da3633")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

            self.log("⏹ Bot stopped.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop bot: {str(e)}")

    def read_bot_logs(self):
        if self.bot_process:
            for line in self.bot_process.stdout:
                if line.strip():
                    self.root.after(0, lambda l=line.strip(): self.log(l))

    def open_dashboard(self):
        try:
            bot_dir = Path(__file__).resolve().parent
            self.dashboard_process = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.headless", "true"],
                cwd=bot_dir,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.log("📊 Dashboard opened! Visit: http://localhost:8501")
            messagebox.showinfo("Dashboard", "Dashboard opened!\nVisit: http://localhost:8501")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open dashboard: {str(e)}")

    def update_stats(self):
        # Read stats from file
        try:
            stats_file = Path(__file__).resolve().parent / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r') as f:
                    stats = json.load(f)

                # Update cards
                pnl = stats.get('total_pnl', 0)
                pnl_color = "#3fb950" if pnl >= 0 else "#da3633"
                self.stats_cards["Total P&L"].config(text=f"${pnl:.2f}", fg=pnl_color)

                self.stats_cards["Win Rate"].config(text=f"{stats.get('win_rate', 0):.1f}%")

                streak = stats.get('current_streak', 0)
                streak_text = f"{streak} {'🔥' if streak > 0 else '❄️' if streak < 0 else '➖'}"
                self.stats_cards["Current Streak"].config(text=streak_text)

                self.stats_cards["Max Drawdown"].config(text=f"${stats.get('max_drawdown', 0):.2f}")
        except:
            pass

        # Update footer time
        self.footer_label.config(text=f"🤖 Enhanced Trading Bot v2.0 • Last updated: {datetime.now().strftime('%H:%M:%S')}")

        # Schedule next update
        self.root.after(5000, self.update_stats)  # Every 5 seconds

    def on_closing(self):
        if self.is_running:
            if messagebox.askyesno("Quit", "Bot is running! Stop bot and exit?"):
                self.stop_bot()
            else:
                return
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
