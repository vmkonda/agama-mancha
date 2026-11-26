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

# 4. Yourself as the first member: it prints a one-time invite link to choose your password
uv run amocr member add "Vijay" --role admin

# 5. Start it, members only, reachable from the home network
$env:AMOCR_OLLAMA = "http://127.0.0.1:11434"
uv run --extra librarian amocr serve --hosted --host 0.0.0.0 --port 8770
```

When Windows asks whether to allow it through the firewall, allow it on **private networks** only.
Find the machine's address with `ipconfig` (the IPv4 address, e.g. 192.168.1.20).

Open the invite link that step 4 printed, with `HOST` replaced by `localhost` on the Windows machine
itself (or by its address from another device): `http://localhost:8770/invite?code=…`. Choose a
password (10 characters or more); the link works once, for 7 days. From then on
`http://localhost:8770` shows the **sign-in page** (name and password) until you sign in, and the title
band shows your name with *Sign out*; your name opens *Account* (change password, issue a listener token).

**Members, on the server:**

| Command | What it does |
|---|---|
| `amocr member add "Anna" --role proofreader` | adds Anna; prints her invite link to send her |
| `amocr member invite "Anna"` | a new invite link, for a forgotten password |
| `amocr member token "Anna"` | a new listener token for her own machine (or she issues one under *Account*) |
| `amocr member list` / `remove "Anna"` | who's there, and whether they've set a password; remove (signs them out) |

Passwords are kept only as salted scrypt hashes, sessions and tokens only as hashes, all in
`data\hosted\` on the server: never in the shared drive, whose editors could change them.

*If you set up the trial before the login page existed:* your member record and the Mac's listener
token still work; run `amocr member invite "Vijay"` and open the link to choose a password.

### Running it in the background, and redeploying when the code changes

(`serve.cmd`, `redeploy.cmd` and `auto-redeploy.cmd` are small wrappers that run the `.ps1` scripts
with a one-off bypass of Windows' script policy, so they work without changing it. **Type the `.cmd`**:
in PowerShell, `scripts\windows\redeploy` without it picks the `.ps1`, which the policy blocks with
"running scripts is disabled".)

Instead of keeping step 5's window open, start it in the background (it logs to `data\serve.log`):

```powershell
scripts\windows\serve.cmd
```

**Redeploy** after a change is merged on GitHub: it stops the server, pulls `main`, updates the
dependencies and starts it again. `data\` (library, index, members, proofreading) isn't in git and
is never touched; local edits to the code make it stop rather than overwrite them.

```powershell
scripts\windows\redeploy.cmd          # only if main changed
scripts\windows\redeploy.cmd -Force   # restart anyway
```

**Automatically**: a scheduled task checks GitHub every 15 minutes, redeploys when `main` has
changed, and starts the server if it isn't running (after the machine restarts, say). Log:
`data\redeploy.log`:

```powershell
scripts\windows\auto-redeploy.cmd
Unregister-ScheduledTask -TaskName "Agama Mancha redeploy" -Confirm:$false   # to remove it
```

A change that needs more than a restart (a new index format, say) says so in its pull request.
The VPS deployment (GitHub Actions, on every merge to `main`) is in docs/deploy-vps.md.

### Keeping the server in step with Proton Drive

The server works on its own copy of each book (`data\works\`): the viewer reads and saves there.
Proton stays the team's store. **`amocr sync`** brings the two together, for every book that has a
Proton path:

1. **Pull:** new readings and saved pages that volunteers and OCR workers pushed. It never
   overwrites the server's files: a page saved on the server stays as saved, and a different copy on
   Proton is reported ("N files differ on Proton, the server's kept").
2. **Push:** the book's readings, saved text, history and status, but only when something changed
   since the last push, so an unchanged 460-page book isn't uploaded again.

What never goes to Proton: members, passwords, sessions and tokens (`data\hosted\`) and the server's
settings. Back those up privately.

**Once, on the server:** install the Proton tool and sign in (in your own browser; never share the
password), then tell amocr where the team folder and the material folder are, and the name to
credit on what the server pushes:

```powershell
uv run amocr setup-proton
proton-drive auth login
uv run amocr init --operator "Agama Mancha server" --proton-root "/shared-with-me/<team folder>" --material "/shared-with-me/[OCR Mirror]/Agama Mancha"
uv run amocr doctor          # the Proton lines should say ok
```

If the Proton tool isn't found, use the full path that `setup-proton` printed (as in the volunteer
guide, "Proton Drive on Windows"), and give it to init with `--proton-bin`.

**Then:**

```powershell
scripts\windows\sync.cmd               # once, now (or: uv run amocr sync <book>)
scripts\windows\auto-sync.cmd          # every 30 minutes from now on (-Minutes 60 for hourly)
Unregister-ScheduledTask -TaskName "Agama Mancha sync" -Confirm:$false   # to remove it
```

Each run adds a line per book to `data\sync.log`. One sync runs at a time; a book that fails (Proton
signed out, say) doesn't stop the others, and the run says which. On Linux (the VPS), the same with
cron: `*/30 * * * * cd /srv/agama-mancha && uv run --extra librarian amocr sync >> data/sync-task.log 2>&1`.

## On the Mac (a member's machine with Claude Code)

**1. Your server and token, in a private file.** The token is your key to the server: keep it in
this file only, never in the repository, a chat or a message. In your own terminal:

```sh
mkdir -p ~/.config/agama-mancha
nano ~/.config/agama-mancha/hosted.env
```

with these two lines (the **server's** address, from `ipconfig` on the Windows machine, IPv4 Address;
not the Mac's own), then save (Ctrl-O, Enter) and exit (Ctrl-X):

```
AGAMA_SERVER=http://192.168.1.20:8770
AGAMA_TOKEN=am_…
```

```sh
chmod 600 ~/.config/agama-mancha/hosted.env     # readable by you only
```

**2. Check the connection** (it never prints the token):

```sh
uv run librarian hosted check
```

| It says | Meaning |
|---|---|
| `connected to … as <your name>` | ready |
| `… is this machine's own address` | you put the Mac's address in the file; use the Windows machine's |
| `can't reach …` | the server isn't running, the machines aren't on the same network, or the Windows firewall blocks port 8770 (allow it on private networks) |
| `reached …, but it refused: members only…` | the token is wrong or was re-issued; `amocr member add` again on the server and update the file |

**3. Listen.** In Claude Code in the project folder, say *"listen to the study chat on the hosted
server"*. Claude runs `librarian --hosted study wait` in the background, reads passages with
`librarian --hosted get` / `search`, answers with `librarian --hosted study reply …`, and waits again.
`--hosted` takes the server and token from the file; without it the commands use this Mac's own
library, as before.

Then, in the browser on Windows: Librarian → a work → *Read* → *Study with Claude*, and ask. The panel
shows *Claude is listening* while the Mac's listener is polling; your answer arrives in the panel.

**On a Mac, about "No route to host":** recent macOS blocks programs it hasn't approved (Python among
them) from reaching other machines on the home network, while its own tools such as `curl` are
allowed. The listener notices and makes its calls through `curl` (the token passes on curl's standard
input, never the command line), so nothing needs changing in System Settings. Allowing your terminal app
under System Settings → Privacy & Security → Local Network also works.

## The proofreading chat on the server

*Check with Claude* and the chat panel in Proofread work on the hosted server too, the same way as the
study chat: your questions are yours alone, and your own Claude answers them from your machine.

In Claude Code on the Mac, say *"listen to the viewer chat on the hosted server"*. Claude runs

```sh
uv run amocr chat any wait --hosted          # your next question, in any book (or name one book)
```

which prints the line(s) as they stand and saves an image of them from the scan on your Mac, then
answers with `uv run amocr chat <book> reply <id> --hosted --text "…" --fix PAGE:LINE:"…"`. Proposed
fixes are checked on the server (pages you've proofread or validated stay locked), and you apply them in
the panel as before. Restricted books are never handed to the listener.

## The Claude helper: Claude for volunteers, with no setup

Volunteers don't use Claude Code or a terminal. On their **Account** page they click *Download my
Claude helper (Windows)* and get a file made for them: the server's address and a fresh personal
helper token are already inside (separate from a listener token, so it never breaks one). They
double-click it whenever they want Claude's help:

- the first time, it offers to install Claude Code (Anthropic's installer) and opens the Claude
  sign-in page: they sign in with their claude.ai account (a paid plan, Pro or higher);
- then it says *Claude is ready to help you on Agama Mancha*, and the panels show *Claude is
  listening*. Questions from *Check with Claude*, the Proofread chat and *Study with Claude* are
  answered inline, with *Apply* buttons as before; closing the window stops it.

The server builds each task (the rules, the lines or passages, links to the images, the shape of
the answer), so improving the prompts reaches every helper without a new download. The helper runs
`claude -p` allowed to read that image and nothing else (no commands, no other files). Downloading
again replaces the file; a coordinator can turn a member's access off. If Windows shows *Windows
protected your PC* the first time, choose *More info* → *Run anyway*.

## OCR workers: your Mac reads pages for the server

The server keeps a queue of pages waiting for an engine; a **worker** on a member's machine leases a
batch, reads them with its own engines (Surya, Tesseract), sends the readings back and deletes its
copies of the images. Workers serve everyone's pages (local engines may be shared; Claude is never a
worker). Every connection goes out from the worker's machine.

**On the server** (a coordinator or admin), queue a book:

```powershell
uv run amocr queue B-c43bd56b1c --engine surya               # every page with no text layer and no Surya reading
uv run amocr queue B-c43bd56b1c --engine surya --pages 221-238
uv run amocr queue                                           # what's waiting, being read, done; which workers are active
```

**On the Mac** (any member but a reader), using the same settings file and listener token as the
study listener:

```sh
uv run --extra surya amocr worker --engines surya            # keeps going, waits when the queue is empty
uv run --extra surya amocr worker --engines surya --once     # stops when the queue is empty
```

A lease lasts 15 minutes; if the worker stops (Ctrl-C, sleep), its pages go back to the queue. A page
that fails three times is set aside. A reading is saved exactly like `amocr ocr` saves it, never over an
existing one, and credited to the member whose worker read it. Rehearsed on the Mac with real Surya: three
pages leased over HTTP, read at about 12 s a page, and the readings were byte for byte the ones made locally.

**Languages.** Each queued page carries its book's Tesseract models (`amocr languages <book>`;
docs/engines.md), so a worker reads an English book with `eng` and a Devanagari one with `san+hin`.
Workers need those models installed (`uv run amocr setup-models` installs san, hin and eng).

## What this shows

- **Members only:** every page, scan and API call needs a signed-in session (name and password) or,
  for the listener, your token (`Authorization: Bearer`). Pages without one go to the sign-in page.
  Only hashes are stored on the server.
- **The listener needs no access to the Mac's network:** the Mac makes all the connections, out to the
  Windows server; the Windows server never connects to the Mac.
- **Your Claude stays yours:** the listener answers only your own questions, with your Claude plan.
  Claude listeners are personal and never shared (a shared worker is only for local engines like
  Surya, which come later as OCR workers).

## Not in this trial

HTTPS and the gate (Cloudflare Access or Tailscale); a database (it still uses the same files); the
proofreading chat and OCR workers over the network; Proton on the server (claims and pushes that
write to Proton won't work there, as Proton isn't signed in on it).
