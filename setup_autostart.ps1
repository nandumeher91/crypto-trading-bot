# setup_autostart.ps1
# Nexora Bot ko Windows startup pe automatically chalane ke liye
# Run this ONCE as Administrator

$TaskName = "NexoraAlgoBot"
$BotDir   = "C:\Users\nandu\OneDrive\Desktop\BOT"
$BatFile  = "$BotDir\start_nexora.bat"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  NEXORA BOT — WINDOWS AUTO-START SETUP" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# Remove old task if exists
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] Purana task mila, hata raha hoon..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: Run pythonw (no black window) directly
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    $PythonExe = "C:\Users\nandu\AppData\Local\Programs\Python\Python314\python.exe"
}

Write-Host "[INFO] Python found at: $PythonExe" -ForegroundColor Green

# Create the action — run python bot.py in BOT directory, hidden window
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-X utf8 bot.py" `
    -WorkingDirectory $BotDir

# Trigger: At login (so bot starts when you log in to Windows)
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# Settings: Allow running when on battery, restart on failure
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# Principal: Run as current user (no UAC popup)
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Nexora Algo Trading Bot (Binance Testnet + Dhurandhar Delta Demo) — Auto starts on Windows login" `
    -Force

Write-Host ""
Write-Host "[SUCCESS] Task registered!" -ForegroundColor Green
Write-Host ""
Write-Host "  Task Name  : $TaskName" -ForegroundColor White
Write-Host "  Trigger    : Windows login pe automatically start" -ForegroundColor White
Write-Host "  Python     : $PythonExe" -ForegroundColor White
Write-Host "  WorkingDir : $BotDir" -ForegroundColor White
Write-Host "  Auto-Retry : 5 baar (har 2 minute me agar crash ho)" -ForegroundColor White
Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Ab se computer ON karo — bot khud start hoga!" -ForegroundColor Green
Write-Host "  Dashboard: http://localhost:10000" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Task abhi bhi manually chalane ke liye:" -ForegroundColor Gray
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "Band karne ke liye:" -ForegroundColor Gray
Write-Host "  Stop-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
pause
