# Bring the hosted server up to date with GitHub's main branch and restart it.
# data\ (library, index, members, proofreading) is not in git and is never touched.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows\redeploy.ps1          # only if main changed
#   powershell -ExecutionPolicy Bypass -File scripts\windows\redeploy.ps1 -Force   # restart anyway
param([int]$Port = 8770, [switch]$Force)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"

git fetch --quiet origin main
$here = (git rev-parse HEAD).Trim()
$there = (git rev-parse origin/main).Trim()
$running = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
# Which code the running server was started from (older servers don't say: treat that as stale).
$serving = ""
if ($running) { try { $serving = (Invoke-RestMethod "http://127.0.0.1:$Port/api/version" -TimeoutSec 10).code } catch { } }
if ($here -eq $there -and $running -and $serving -ne $here) {
    Write-Host "$stamp  the code is up to date ($($here.Substring(0,7))) but the server is running older code: restarting it"
    $Force = $true
}
if ($here -eq $there -and -not $Force) {
    if ($running) { Write-Host "$stamp  up to date ($($here.Substring(0,7))), running"; exit 0 }
    # Up to date but not running (after a restart of the machine, say): just start it.
    Write-Host "$stamp  up to date ($($here.Substring(0,7))), not running: starting it"
    & (Join-Path $PSScriptRoot "serve.ps1") -Port $Port
    exit $LASTEXITCODE
}

# Local edits to tracked files would block the update: refuse rather than overwrite them.
if (git status --porcelain --untracked-files=no) { Write-Host "$stamp  local changes to the code; not updating:"; git status --short; exit 1 }

Write-Host "$stamp  updating $($here.Substring(0,7)) -> $($there.Substring(0,7))"
git log --oneline "$here..$there"

# Stop the running server (whatever is listening on the port), and make sure it really stopped: a server
# started from an Administrator window can't be stopped from a normal one, and would keep the old code running.
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) {
    try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop }
    catch { Write-Host "$stamp  couldn't stop the running server (process $($c.OwningProcess)): $($_.Exception.Message)" }
}
for ($i = 0; $i -lt 10 -and (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Seconds 1 }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "$stamp  the old server is still running on port $Port, so the update can't start."
    Write-Host "         It was probably started as Administrator: run this again in a PowerShell opened with 'Run as administrator'."
    exit 1
}

git pull --ff-only --quiet origin main
uv sync --extra librarian

& (Join-Path $PSScriptRoot "serve.ps1") -Port $Port
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
try { $code = (Invoke-RestMethod "http://127.0.0.1:$Port/api/version" -TimeoutSec 10).code } catch { $code = "" }
$now = (git rev-parse HEAD).Trim()
if ($code -and $code -ne $now) { Write-Host "$stamp  warning: the server answers with code $($code.Substring(0,7)), not $($now.Substring(0,7))"; exit 1 }
Write-Host "$stamp  running $($now.Substring(0,7))"
exit 0
