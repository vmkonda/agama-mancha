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

(`serve`, `redeploy` and `auto-redeploy` are small `.cmd` wrappers that run the `.ps1` scripts with a
one-off bypass of Windows' script policy, so they work without changing it.)

Instead of keeping step 5's window open, start it in the background (it logs to `data\serve.log`):

```powershell
scripts\windows\serve
```

**Redeploy** after a change is merged on GitHub: it stops the server, pulls `main`, updates the
dependencies and starts it again. `data\` (library, index, members, proofreading) isn't in git and
is never touched; local edits to the code make it stop rather than overwrite them.

```powershell
scripts\windows\redeploy          # only if main changed
scripts\windows\redeploy -Force   # restart anyway
```

**Automatically**: a scheduled task checks GitHub every 15 minutes, redeploys when `main` has
changed, and starts the server if it isn't running (after the machine restarts, say). Log:
`data\redeploy.log`:

```powershell
scripts\windows\auto-redeploy
Unregister-ScheduledTask -TaskName "Agama Mancha redeploy" -Confirm:$false   # to remove it
```

A change that needs more than a restart (a new index format, say) says so in its pull request; on
the real deployment this becomes a container image built on every merge (docs/plan.md).

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
