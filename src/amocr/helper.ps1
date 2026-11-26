# Agama Mancha: your Claude helper (Windows PowerShell 5.1, built into Windows).
# Downloaded from your Account page with your server and your own helper token filled in; keep it private.
# It answers your questions from the Proofread and Study panels with your own Claude (Claude Code,
# signed in with your claude.ai account). Claude may only read the image of the lines you ask about.

$ErrorActionPreference = "Continue"   # Windows PowerShell turns a program's warnings into errors under "Stop"
$Server = "__SERVER__"
$Token = "__TOKEN__"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$Host.UI.RawUI.WindowTitle = "Agama Mancha - Claude helper"

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Stop-Helper($text) {
    Say ""; Say $text "Yellow"; Say ""; Read-Host "Press Enter to close this window" | Out-Null; exit 1
}

# ---- talking to Agama Mancha ------------------------------------------------------------------
function Api($method, $path, $body = $null, $timeout = 60) {
    $req = [System.Net.HttpWebRequest]::Create("$Server$path")
    $req.Method = $method
    $req.Timeout = $timeout * 1000
    $req.ReadWriteTimeout = $timeout * 1000
    $req.Headers.Add("Authorization", "Bearer $Token")
    if ($body -ne $null) {
        $bytes = $utf8.GetBytes(($body | ConvertTo-Json -Depth 8 -Compress))
        $req.ContentType = "application/json; charset=utf-8"
        $req.ContentLength = $bytes.Length
        $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
    }
    try { $resp = $req.GetResponse() }
    catch [System.Net.WebException] {
        $r = $_.Exception.Response
        if ($r -ne $null -and [int]$r.StatusCode -in 401, 403) { throw "REFUSED" }
        if ($r -ne $null) {
            $msg = (New-Object System.IO.StreamReader($r.GetResponseStream(), $utf8)).ReadToEnd()
            throw "SERVER: $msg"
        }
        throw "UNREACHABLE"
    }
    $text = (New-Object System.IO.StreamReader($resp.GetResponseStream(), $utf8)).ReadToEnd()
    $resp.Close()
    return $text | ConvertFrom-Json
}

function Download($path, $file) {
    $c = New-Object System.Net.WebClient
    $c.Headers.Add("Authorization", "Bearer $Token")
    $c.DownloadFile("$Server$path", $file)
}

# ---- Claude Code: installed and signed in ------------------------------------------------------
function Find-Claude {
    $c = Get-Command claude -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in "$env:USERPROFILE\.local\bin\claude.exe", "$env:LOCALAPPDATA\Programs\claude\claude.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Say ""
Say "  Agama Mancha - Claude helper" "Cyan"
Say ""

$claude = Find-Claude
if (-not $claude) {
    Say "Claude isn't installed on this computer yet. The helper can install it now"
    Say "(Claude Code, from Anthropic, the makers of Claude; it takes a minute or two)."
    $a = Read-Host "Install it? Type Y and press Enter"
    if ($a -notmatch '^[yY]') { Stop-Helper "Nothing was installed. Double-click the helper again when you're ready." }
    Say "Installing Claude..." "Cyan"
    try { Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression }
    catch { Stop-Helper "The installation didn't finish ($($_.Exception.Message)). Please ask your coordinator for help." }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $claude = Find-Claude
    if (-not $claude) { Stop-Helper "Claude was installed but can't be found yet. Close this window and double-click the helper again." }
}

function Signed-In {
    try { return ((& $claude auth status --json 2>$null | Out-String) | ConvertFrom-Json).loggedIn } catch { return $false }
}
if (-not (Signed-In)) {
    Say "Next, sign in to Claude with your claude.ai account (a paid plan: Pro or higher)."
    Say "Your browser will open; sign in there, then come back to this window."
    Read-Host "Press Enter to open the sign-in page" | Out-Null
    & $claude auth login --claudeai
    if (-not (Signed-In)) { Stop-Helper "You aren't signed in to Claude yet. Double-click the helper again to try once more." }
}

try { Api GET "/api/helper/next?timeout=1" | Out-Null }   # checks the token (a question stays waiting until answered)
catch {
    if ("$_" -eq "REFUSED") { Stop-Helper "This helper file no longer works: a newer one was downloaded, or access was turned off. Download it again from your Account page in Agama Mancha." }
    Say "Agama Mancha isn't reachable right now; the helper will keep trying." "Yellow"
}

# ---- answering -----------------------------------------------------------------------------------
$work = Join-Path $env:TEMP "agama-mancha-helper"
New-Item -ItemType Directory -Force -Path $work | Out-Null

function Ask-Claude($task) {
    $dir = Join-Path $work ([guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    try {
        $prompt = $task.prompt
        $i = 0
        foreach ($img in $task.images) {
            $i++
            $file = Join-Path $dir "image$i.png"
            Download $img $file
            $prompt = $prompt.Replace("{IMAGE$i}", $file)
        }
        $schema = ($task.schema | ConvertTo-Json -Depth 8 -Compress) -replace '"', '\"'   # Windows PowerShell drops bare quotes
        Push-Location $dir
        try {
            $out = $prompt | & $claude -p --output-format json --json-schema $schema `
                --allowedTools Read --disallowedTools "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent" 2>&1 | Out-String
        } finally { Pop-Location }
        $start = $out.IndexOf("{")
        if ($start -lt 0) { throw ($out.Trim() -split "`n")[0] }
        $r = $out.Substring($start) | ConvertFrom-Json
        if ($r.is_error -or -not $r.structured_output) { throw "Claude: $($r.result)" }
        return $r.structured_output
    } finally {
        Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
    }
}

Say "Claude is ready to help you on Agama Mancha." "Green"
Say "Keep this window open while you work; close it to stop."
Say ""
$away = $false
while ($true) {
    try {
        $t = (Api GET "/api/helper/next?timeout=25" $null 60).task
        if ($away) { Say "Agama Mancha is back." "Green"; $away = $false }
    } catch {
        if ("$_" -eq "REFUSED") { Stop-Helper "This helper file no longer works: a newer one was downloaded, or access was turned off. Download it again from your Account page." }
        if (-not $away) { Say "Can't reach Agama Mancha just now; trying again every 15 seconds." "Yellow"; $away = $true }
        Start-Sleep -Seconds 15
        continue
    }
    if (-not $t) { continue }
    Say ("{0}  Answering your question about {1}..." -f (Get-Date -Format "HH:mm"), $t.summary) "Cyan"
    $body = @{ kind = $t.kind; work = $t.work; id = $t.id }
    try {
        $a = Ask-Claude $t
        $body.answer = $a.answer
        if ($t.kind -eq "proofread") { $body.fixes = @($a.fixes) } else { $body.cites = @($a.cites) }
        $note = "answered"
    } catch {
        $msg = "$($_.Exception.Message)"
        if ($msg -match "log ?in|sign ?in|authenticat") { $msg = "please sign in to Claude again: close this window and double-click the helper" }
        $body.answer = "The helper couldn't get an answer from Claude ($msg). Ask again in a moment."
        $note = "couldn't answer: $msg"
    }
    try { Api POST "/api/helper/answer" $body | Out-Null; Say "        $note; the answer is in your panel." }
    catch { Say "        $note, but couldn't send it ($_)." "Yellow" }
}
