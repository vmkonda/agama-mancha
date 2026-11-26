# Optional: sync with Proton Drive every 30 minutes (a Windows scheduled task).
# Run once, in PowerShell as yourself:  scripts\windows\auto-sync.cmd   (or -Minutes 60)
# Remove it again with:                 Unregister-ScheduledTask -TaskName "Agama Mancha sync" -Confirm:$false
# Needs Proton signed in on this machine first (amocr setup-proton, then proton-drive auth login).
param([int]$Minutes = 30)

$script = Join-Path $PSScriptRoot "sync.ps1"
$log = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "data\sync-task.log"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"& '$script' *>> '$log'`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
Register-ScheduledTask -TaskName "Agama Mancha sync" -Action $action -Trigger $trigger `
    -Description "Pull new readings from the material folder on Proton and push the server's proofreading" -Force | Out-Null
Write-Host "Every $Minutes minutes: sync with Proton. What each run did: data\sync.log; its output: $log"
