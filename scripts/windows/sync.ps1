# Bring the server's books in step with the material folder on Proton Drive: pull new readings,
# push the server's proofreading. Logs to data\sync.log (one line per book per run).
# Usage (from the repository folder):  scripts\windows\sync.cmd   [book ...]
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
Write-Host "$(Get-Date -Format s) sync"
uv run --extra librarian amocr sync @args
exit $LASTEXITCODE
