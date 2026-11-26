# Start Agama Mancha in hosted mode (members only) in the background, logging to data\serve.log.
# Usage (from the repository folder):  powershell -ExecutionPolicy Bypass -File scripts\windows\serve.ps1
param([int]$Port = 8770, [string]$Ollama = "http://127.0.0.1:11434")

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { Write-Host "Something is already listening on port $Port (process $($busy[0].OwningProcess)); stop it first."; exit 1 }

$env:AMOCR_OLLAMA = $Ollama
New-Item -ItemType Directory -Force -Path data | Out-Null
$p = Start-Process -FilePath "uv" -ArgumentList @("run", "--extra", "librarian", "amocr", "serve", "--hosted", "--host", "0.0.0.0", "--port", "$Port", "--no-browser") `
    -RedirectStandardOutput "data\serve.log" -RedirectStandardError "data\serve.err.log" -WindowStyle Hidden -PassThru

# Wait until it answers (up to a minute).
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "Agama Mancha is running on port $Port (members only). Log: data\serve.log"
        exit 0
    }
    if ($p.HasExited) { break }
}
Write-Host "It didn't start. The last lines of the logs:"
Get-Content data\serve.log, data\serve.err.log -Tail 15 -ErrorAction SilentlyContinue
exit 1
