# Trying the hosted version at home: Windows as the server, a Mac as a member's machine

A trial of the hosted design (docs/plan.md, "Proposed: a hosted version") on a home network: the
Windows machine runs Agama Mancha in hosted mode (members only), and a Claude Code session on the
Mac answers your study questions as a **listener**, connecting out to the Windows server. The real
deployment adds HTTPS and a gate in front (Cloudflare Access or Tailscale); this trial uses plain
HTTP on the home network.

## On the Windows machine (the server)

In PowerShell:

```powershell
# 1. Tools: git, uv, Ollama (with the embedding model the index uses)
winget install --id Git.Git -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install --id Ollama.Ollama -e
ollama pull bge-m3

# 2. The code
cd $HOME
git clone https://github.com/vmkonda/agama-mancha.git
cd agama-mancha
uv sync --extra librarian

# 3. The data, copied from the Mac (the library, its index, and the pilot book): about 190 MB
scp vijaymohankonda@Vijaymohans-Mac-Studio.local:Projects/agama-mancha-ocr/data/hosted-bundle.tar.gz .
tar -xzf hosted-bundle.tar.gz

# 4. Yourself as the first member (the token is shown once; keep it)
uv run amocr member add "Vijay" --role admin

# 5. Start it, members only, reachable from the home network
$env:AMOCR_OLLAMA = "http://127.0.0.1:11434"
uv run --extra librarian amocr serve --hosted --host 0.0.0.0 --port 8770
```

When Windows asks whether to allow it through the firewall, allow it on **private networks** only.
Find the machine's address with `ipconfig` (the IPv4 address, e.g. 192.168.1.20).

Open the sign-in link that step 4 printed, with `HOST` replaced by `localhost` on the Windows machine
itself (or by its address from another device): `http://localhost:8770/login?token=…`. Without the
link (or after signing out of the browser) every page says *members only*.

### Running it in the background, and redeploying when the code changes

Instead of keeping step 5's window open, start it in the background (it logs to `data\serve.log`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\serve.ps1
```

**Redeploy** after a change is merged on GitHub: it stops the server, pulls `main`, updates the
dependencies and starts it again. `data\` (library, index, members, proofreading) isn't in git and
is never touched; local edits to the code make it stop rather than overwrite them.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\redeploy.ps1          # only if main changed
powershell -ExecutionPolicy Bypass -File scripts\windows\redeploy.ps1 -Force   # restart anyway
```

**Automatically**: a scheduled task checks GitHub every 15 minutes, redeploys when `main` has
changed, and starts the server if it isn't running (after the machine restarts, say). Log:
`data\redeploy.log`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\auto-redeploy.ps1
Unregister-ScheduledTask -TaskName "Agama Mancha redeploy" -Confirm:$false   # to remove it
```

A change that needs more than a restart (a new index format, say) says so in its pull request; on
the real deployment this becomes a container image built on every merge (docs/plan.md).

## On the Mac (a member's machine with Claude Code)

In a terminal in the project folder, or ask Claude Code to do it:

```sh
export AGAMA_SERVER=http://192.168.1.20:8770     # the Windows machine's address
export AGAMA_TOKEN=am_…                          # your member token from step 4
uv run librarian study wait                      # waits for your questions on the Windows server
```

In Claude Code, say: *"listen to the study chat on the hosted server"*. Claude runs the wait in the
background, reads passages with `librarian get` / `librarian search` (which go to the server, because
`AGAMA_SERVER` is set), answers with `librarian study reply <id> --text … --cite …`, and waits again.

Then, in the browser on Windows: Librarian → a work → *Read* → *Study with Claude*, and ask. The panel
shows *Claude is listening* while the Mac's listener is polling; your answer arrives in the panel.

## What this shows

- **Members only:** every page, scan and API call needs your token (a cookie after the sign-in link,
  or `Authorization: Bearer` for the listener). Only a hash of the token is stored on the server.
- **The listener needs no access to the Mac's network:** the Mac makes all the connections, out to the
  Windows server; the Windows server never connects to the Mac.
- **Your Claude stays yours:** the listener answers only your own questions, with your Claude plan.
  Claude listeners are personal and never shared (a shared worker is only for local engines like
  Surya, which come later as OCR workers).

## Not in this trial

HTTPS and the gate (Cloudflare Access or Tailscale); a database (it still uses the same files); the
proofreading chat and OCR workers over the network; Proton on the server (claims and pushes that
write to Proton won't work there, as Proton isn't signed in on it).
