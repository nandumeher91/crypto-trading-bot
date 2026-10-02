@echo off
title Nexora Algo Trading Bot & Live Web Console
color 0D
cls
echo ======================================================================
echo           NEXORA ALGO TRADING ENGINE - INSTITUTIONAL CONSOLE
echo ======================================================================
echo.
echo [1/4] Navigating to BOT directory...
cd /d "C:\Users\nandu\OneDrive\Desktop\BOT"

echo [2/4] Checking environment keys (.env)...
if not exist .env (
    echo [ERROR] .env file not found!
    pause
    exit /b 1
)

echo [3/4] Setting UTF-8 mode for emoji & special characters...
set PYTHONUTF8=1

echo [4/4] Launching Nexora Bot (Binance Testnet + Dhurandhar Delta Demo)...
echo.
echo   Binance Testnet Bot    : http://localhost:10000
echo   Dhurandhar Strategy    : http://localhost:10000/#dhurandhar
echo   Delta Exchange Demo    : https://cdn-ind.testnet.deltaex.org
echo.
echo Press Ctrl+C to stop all engines.
echo ======================================================================
echo.
python -X utf8 bot.py
pause
