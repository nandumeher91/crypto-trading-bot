# create_startup_shortcut.ps1
$StartupFolder = [Environment]::GetFolderPath('Startup')
$ShortcutPath  = "$StartupFolder\NexoraAlgoBot.lnk"
$BatFile       = "C:\Users\nandu\OneDrive\Desktop\BOT\run_bot_hidden.bat"
$WorkDir       = "C:\Users\nandu\OneDrive\Desktop\BOT"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $BatFile
$Shortcut.WorkingDirectory = $WorkDir
$Shortcut.WindowStyle = 7
$Shortcut.Description = "Nexora Algo Trading Bot Auto-Start"
$Shortcut.Save()

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AUTO-START SETUP COMPLETE!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Shortcut: $ShortcutPath" -ForegroundColor White
Write-Host ""
Write-Host "  Ab se Windows login hone par bot" -ForegroundColor Green
Write-Host "  automatically start hoga!" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard: http://localhost:10000" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
