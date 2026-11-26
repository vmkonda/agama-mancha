# Start Agama Mancha in hosted mode (members only) in the background, logging to data\serve.log.
# Usage (from the repository folder):  powershell -ExecutionPolicy Bypass -File scripts\windows\serve.ps1
param([int]$Port = 8770, [string]$Ollama = "http://127.0.0.1:11434")

$ErrorActionPreference = "Stop"
function Port-Answers([int]$p) {     # is a server really answering on this port? (the port list can show ghosts)
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.ConnectAsync("127.0.0.1", $p).Wait(1500) -and $c.Connected } catch { $false } finally { $c.Close() }
}
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

if (Port-Answers $Port) { Write-Host "Something is already answering on port $Port (an older server?). Use  scripts\windows\redeploy.cmd -Force  to replace it."; exit 1 }

$env:AMOCR_OLLAMA = $Ollama
New-Item -ItemType Directory -Force -Path data | Out-Null
# Start it fully detached from this window: cmd writes the log itself, so nothing ties the server's
# output to this console and the prompt comes back as soon as it's up.
$cmdline = "uv run --extra librarian amocr serve --hosted --host 0.0.0.0 --port $Port --no-browser > data\serve.log 2>&1"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmdline -WorkingDirectory $repo -WindowStyle Hidden | Out-Null
Write-Host "Starting Agama Mancha on port $Port " -NoNewline

# Wait until it answers (up to two minutes: the first start after an update can take a while).
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 1
    if (Port-Answers $Port) {
        Write-Host ""
        Write-Host "Agama Mancha is running on port $Port (members only). Log: data\serve.log"
        Write-Host "It keeps running after you close this window; scripts\windows\redeploy.cmd restarts it."
        exit 0
    }
    if ($i % 5 -eq 4) { Write-Host "." -NoNewline }
}
Write-Host ""
Write-Host "It didn't start within two minutes. The last lines of the log:"
Get-Content data\serve.log -Tail 20 -ErrorAction SilentlyContinue
exit 1
