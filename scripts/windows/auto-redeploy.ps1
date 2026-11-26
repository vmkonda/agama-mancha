# Optional: check GitHub every 15 minutes and redeploy when main has changed (a Windows scheduled task).
# Run once, in PowerShell as yourself:  powershell -ExecutionPolicy Bypass -File scripts\windows\auto-redeploy.ps1
# Remove it again with:                 Unregister-ScheduledTask -TaskName "Agama Mancha redeploy" -Confirm:$false
param([int]$Minutes = 15)

$script = Join-Path $PSScriptRoot "redeploy.ps1"
$log = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "data\redeploy.log"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"& '$script' *>> '$log'`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
Register-ScheduledTask -TaskName "Agama Mancha redeploy" -Action $action -Trigger $trigger `
    -Description "Update Agama Mancha from GitHub main and restart it when main changes" -Force | Out-Null
Write-Host "Every $Minutes minutes: redeploy when main changes. Log: $log"
