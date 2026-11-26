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
if ($here -eq $there -and -not $Force) { Write-Host "$stamp  up to date ($($here.Substring(0,7)))"; exit 0 }

# Local edits to tracked files would block the update: refuse rather than overwrite them.
if (git status --porcelain --untracked-files=no) { Write-Host "$stamp  local changes to the code; not updating:"; git status --short; exit 1 }

Write-Host "$stamp  updating $($here.Substring(0,7)) -> $($there.Substring(0,7))"
git log --oneline "$here..$there"

# Stop the running server (whatever is listening on the port).
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

git pull --ff-only --quiet origin main
uv sync --extra librarian

& (Join-Path $PSScriptRoot "serve.ps1") -Port $Port
exit $LASTEXITCODE
