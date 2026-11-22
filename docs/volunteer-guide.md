# Volunteer guide: OCR a book page by page

For anyone helping turn scanned books into text. You don't need to be a
programmer. If a step fails, the [troubleshooting](#troubleshooting) section
at the end covers the common problems, and `amocr doctor` always tells you
what's missing.

**What you'll do:** take a book from the team's Proton Drive, let the computer
read every page (Tesseract, free), let Claude carefully re-read pages in
batches, and upload the results to the team's **OCR Mirror** folder. Other
volunteers can continue where you stopped.

**Time:** setup about 10 minutes, once, with Claude doing most of it. After
that, a batch of 10 pages takes a few minutes of your attention.

---

## Keeping the shared drive safe

You can't damage the original books: you have read-only access to them. The
tool only adds files to OCR Mirror; it has no way to delete, move or rename
anything, and Claude is blocked from running Proton commands that change the
drive. Please don't work around those blocks, and don't use other Proton
tools on the team folders while a Claude session is running.

## 1. What you need

- A Mac (Apple Silicon or Intel), a Windows PC, or Linux.
- A **Proton account** that the coordinator has invited to the library folder
  (viewer) and to the OCR Mirror folder (editor). A shared *link*
  (drive.proton.me/urls/…) is not enough: the tool can only use folders shared
  to your account. Ask the coordinator for an invitation if you only have a link.
- A **Claude** subscription (Pro or higher). Claude sets up your computer and
  does the careful re-reading in step 5. Without one, follow the
  [manual setup](#manual-setup) and skip step 5.

## 2. Setup with Claude

1. **Install Claude Code** and sign in with your Claude account. Follow the
   instructions for your system at https://claude.com/claude-code (one command
   to paste into Terminal on a Mac, or PowerShell on Windows).
2. **Get this repository and start Claude in it.** In Terminal (Mac, Linux) or
   PowerShell (Windows):
   ```sh
   git clone https://github.com/vmkonda/agama-mancha-ocr.git
   cd agama-mancha-ocr
   claude
   ```
   If your Mac asks to install "command line developer tools" for `git`, say
   yes and run the commands again afterwards. Always start Claude from this
   folder: that's what loads the project's rules and safety checks.
3. **Say:**
   > Set me up

   Claude checks what's missing, installs it, downloads the Proton Drive tool
   and the Sanskrit/Hindi reading models, and asks you for:
   - permission before it runs commands (read what it asks, then approve);
   - your **Proton sign-in**: it gives you a link to open in your browser;
   - your **name**, as it should appear on the pages you do;
   - which shared folders are the **library** and **OCR Mirror**.

   Anything that needs your computer's password, Claude gives you as a command
   to type yourself, starting with `!`. Claude never asks for passwords.

   It finishes by running `uv run amocr doctor`, which should say *all good*.

From now on, start Claude (and run any commands) from inside the
`agama-mancha-ocr` folder: `cd ~/agama-mancha-ocr`, then `claude`.

## 3. Claim a book

Open the team's task sheet, pick a book nobody owns, enter its path, put
yourself as owner and set the status to *in progress*. Two people working on
the same book at the same time can overwrite each other's uploads, so the
sheet is the lock.

## 4. Fetch the book and let Tesseract read it

The easy way: tell Claude

> Start OCR on /shared-with-me/<library>/<path>/<book>.pdf

and it does this step and step 5. Say if the book is restricted. By hand:

```sh
uv run amocr fetch "/shared-with-me/<library>/<path>/<book>.pdf"
```

This downloads the PDF, gives it an id like `B-1a2b3c4d5e` (the same id on
everyone's machine), and brings down any pages other volunteers already did.
Note the id. Then:

```sh
uv run amocr ocr B-1a2b3c4d5e
```

Tesseract reads every page (about a second per page). This step is free.

If the book is **restricted** (the coordinator decides which are), add
`--restricted` to the fetch command. Restricted books are never sent to
Claude, and the tool refuses if anyone tries.

## 5. Let Claude re-read pages

Start Claude Code in the repository folder:

```sh
claude
```

and type:

> Continue OCR on book B-1a2b3c4d5e

Claude prepares the next 10 pages, reads each page image, corrects
Tesseract's text, labels verses, commentary and footnotes, stores the
results, and uploads them. It follows the reading rules in `CLAUDE.md`:
transcribe what is printed, never "improve" the text, never drop a line,
and flag anything unclear.

Each page uses part of your Claude plan's limit. Ten pages per session is a
comfortable pace. When you hit your limit, stop; next time say the same
sentence and it continues from where it stopped.

## 6. Upload and update the sheet

Claude uploads after each batch. You can also do it yourself at any time:

```sh
uv run amocr push B-1a2b3c4d5e
uv run amocr status B-1a2b3c4d5e
```

Results appear in Proton Drive under
`OCR Mirror/<same path as the book>/<book>.amocr/`. Update the sheet with the
pages done. When every page is done, set the status to *done*.

## 7. Look at the result (optional)

```sh
uv run amocr serve
```

opens the scan and the text side by side in your browser. See the
[proofreading guide](proofreading-guide.md) for what you can do there.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `amocr doctor` says *team folder not reachable* | Run `proton-drive auth login` again. Check the folder name with `proton-drive filesystem list /shared-with-me`. If the folder isn't listed, ask the coordinator to invite your Proton account. |
| I only have a link and a password | The tool can't use links. Ask the coordinator to invite your Proton account to the folder. |
| Proton login fails over SSH on a Mac (Keychain errors) | Unlock the keychain first: `security unlock-keychain ~/Library/Keychains/login.keychain-db`, or sign in from a terminal on the Mac itself. |
| `tesseract language 'san'` or `'hin'` missing | Mac: `brew install tesseract-lang`. Windows: rerun the Tesseract installer and tick Sanskrit and Hindi. |
| `checksum mismatch` | The PDF changed since it was registered. Tell the coordinator; don't work on it until it's sorted out. |
| Claude says "finished pages not imported" | Run `uv run amocr claude-import <book> --ready`, then continue. |
| A warning says *possible dropped lines* | Open the page in the viewer and compare with the scan. Tell a proofreader if a line is missing. |
| Someone else uploaded pages for my book | Run `uv run amocr pull <book>` to bring them down. Your own files are never overwritten. |
| Claude limit reached | Stop. Push what's done (`uv run amocr push <book>`). Continue another day. |

---

## Manual setup

The same steps Claude does, for setting up without it or fixing something by hand.

### Mac

Open **Terminal** (press ⌘ + Space, type `terminal`, press Enter) and paste
these lines one at a time.

1. Install Homebrew, if you don't have it (it asks for your Mac password):
   ```sh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. Install the tools:
   ```sh
   brew install git uv tesseract tesseract-lang
   ```
3. Get the Proton Drive command-line tool and put it where your Mac finds it:
   ```sh
   mkdir -p ~/bin
   curl -sSLo ~/bin/proton-drive https://proton.me/download/drive/cli/0.9.0/darwin-arm64/proton-drive
   chmod +x ~/bin/proton-drive
   ```
   On an Intel Mac use `darwin-x64` instead of `darwin-arm64`. If a newer
   version is listed on https://proton.me/download/drive/cli/index.html, it
   should also work; this guide was tested with 0.9.0.
4. Install Claude Code: follow https://claude.com/claude-code, then run
   `claude` once and sign in with your own Claude account.
5. Get the repository and its Python packages:
   ```sh
   cd ~
   git clone https://github.com/vmkonda/agama-mancha-ocr.git
   cd agama-mancha-ocr
   uv sync
   ```

### Windows

Open **PowerShell** (Start menu, type `powershell`).

1. Install Git and uv:
   ```powershell
   winget install -e --id Git.Git
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   Close and reopen PowerShell afterwards.
2. Install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki. In the
   installer, under *Additional script data* tick **Devanagari**, and under
   *Additional language data* tick **Sanskrit** and **Hindi**. Then add
   `C:\Program Files\Tesseract-OCR` to your PATH (Start → "Edit the system
   environment variables" → Environment Variables → Path → New).
3. Download `proton-drive.exe` from
   https://proton.me/download/drive/cli/index.html (windows-x64) and save it
   in a folder such as `C:\Tools\`.
4. Install Claude Code (https://claude.com/claude-code) and sign in.
5. Get the repository:
   ```powershell
   cd ~
   git clone https://github.com/vmkonda/agama-mancha-ocr.git
   cd agama-mancha-ocr
   uv sync
   ```

### Linux (Debian/Ubuntu; other distributions have the same packages under similar names)

1. Install the tools:
   ```sh
   sudo apt install git curl tesseract-ocr tesseract-ocr-san tesseract-ocr-hin
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Get the Proton Drive CLI (`linux-arm64` on ARM machines):
   ```sh
   mkdir -p ~/bin
   curl -sSLo ~/bin/proton-drive https://proton.me/download/drive/cli/0.9.0/linux-x64/proton-drive
   chmod +x ~/bin/proton-drive
   ```
   It keeps your Proton sign-in in the system keyring (libsecret, e.g. GNOME
   Keyring). On a server without a desktop, set
   `PROTON_DRIVE_CREDENTIALS_STORE=pass` and set up `pass` instead.
3. Install Claude Code (https://claude.com/claude-code) and sign in.
4. Get the repository: same commands as for the Mac (step 5).

### All systems: Proton sign-in and settings

1. Sign in to Proton Drive (a browser window opens; if it doesn't, open the
   printed link on any device and keep the terminal open until it finishes):
   ```sh
   proton-drive auth login
   ```
   On Windows use the full path, e.g. `C:\Tools\proton-drive.exe auth login`.
2. Accept the team folder invitation, if you haven't in the browser:
   ```sh
   proton-drive invitation list
   proton-drive invitation accept <id from the list>
   ```
3. Find the exact folder names:
   ```sh
   proton-drive filesystem list /shared-with-me
   ```
4. Tell the tool your name (credited on every page you do), the library
   folder and the results folder:
   ```sh
   uv run amocr init --operator "Your Name" --proton-root "/shared-with-me/<library>" --mirror "/shared-with-me/OCR Mirror"
   ```
   Windows only, also: `uv run amocr init --proton-bin "C:\Tools\proton-drive.exe"`
5. Check everything:
   ```sh
   uv run amocr doctor
   ```
   Every line should say `ok`. Fix any `NO` line using the hint below it.

Optional on every system: `uv run amocr setup-models` downloads the exact
Sanskrit/Hindi models the rest of the team uses (pinned and checksum-verified),
and `uv run amocr setup-proton` downloads the Proton Drive tool for your
machine, so you don't need the downloads above.
