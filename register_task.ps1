# register_task.ps1 — Run this once to setup auto-start
$TaskName  = "NexoraAlgoBot"
$BotDir    = "C:\Users\nandu\OneDrive\Desktop\BOT"
$WrapperBat = "$BotDir\run_bot_hidden.bat"

# Remove old task silently
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Action: run cmd /c run_bot_hidden.bat
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ("/c `"" + $WrapperBat + "`"")

# Trigger: at logon (this user)
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: no time limit, restart 5 times if it crashes
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2)

# Principal: current user, highest privileges
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Nexora Algo Trading Bot — Binance Testnet + Dhurandhar Delta Demo" `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AUTO-START SETUP COMPLETE!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Task Name : $($task.TaskName)" -ForegroundColor White
Write-Host "  Status    : $($task.State)" -ForegroundColor Yellow
Write-Host "  Trigger   : Windows Login (automatic)" -ForegroundColor White
Write-Host "  Restart   : 5 times if it crashes" -ForegroundColor White
Write-Host ""
Write-Host "  Ab computer ON karo — bot khud start hoga!" -ForegroundColor Green
Write-Host "  Dashboard : http://localhost:10000" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
