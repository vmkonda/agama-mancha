---
name: setup
description: Set up this machine for a volunteer or proofreader - install missing tools, download the Proton Drive CLI and pinned Tesseract models, guide Proton sign-in, find the shared folders, save the volunteer's name and folders, and verify with doctor. Use when the user says "set me up", "set up this computer", "install", "get started", or when `amocr doctor` shows NO lines.
---

# setup

Goal: from a fresh clone to `uv run amocr doctor` saying "all good", with the
user doing only what needs a person (passwords, browser sign-in, choices).
Work from the repository root. Explain each step in one short line; the user
may not be technical.

Never ask for, type or store passwords (computer, Proton, or share-link).
When a step needs one, give the user the command to run themselves with the
`!` prefix, e.g. `! sudo apt install tesseract-ocr`.

## 1. Find out where we are

Run `uv run amocr doctor` if `uv` exists (`uv --version`). Note the OS
(`uname -s`, or Windows if that fails) and skip any step whose check is already ok.

## 2. Tools (only what's missing)

| Missing | macOS | Windows (PowerShell) | Linux (Debian/Ubuntu) |
|---|---|---|---|
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` | same as macOS |
| tesseract | `brew install tesseract` (if no Homebrew, give the user the install command from https://brew.sh to run with `!`) | `winget install -e --id UB-Mannheim.TesseractOCR`, then make sure `C:\Program Files\Tesseract-OCR` is on PATH | user runs `! sudo apt install tesseract-ocr` |

After installing uv, a new shell may be needed; use its full path
(`~/.local/bin/uv` or `%USERPROFILE%\.local\bin\uv.exe`) if `uv` isn't found.

Then:

```sh
uv sync
uv run amocr setup-models     # pinned Sanskrit/Hindi models in data/tessdata (no admin rights)
uv run amocr setup-proton     # Proton Drive CLI for this OS/CPU in data/bin, saved in the config
```

## 3. Proton sign-in (the user does this part)

Start `data/bin/proton-drive auth login` in the background (on Windows
`data\bin\proton-drive.exe auth login`), read its output, and give the user
the sign-in link it prints. They can open it on any device. Wait until it
reports success. If it fails with a keychain error over SSH on a Mac, tell the
user to run `! security unlock-keychain ~/Library/Keychains/login.keychain-db`
and try again.

## 4. Find the shared folders

`uv run amocr folders`. Expect the library and `OCR Mirror` under
/shared-with-me.

- Nothing there: check `data/bin/proton-drive invitation list`. If invitations
  are pending, ask the user to accept them in the Proton Drive web app (or run
  `! data/bin/proton-drive invitation accept <id>` themselves). If there are
  none, the coordinator hasn't invited their Proton account yet: draft a short
  message they can send, asking for viewer access to the library and editor
  access to OCR Mirror. Share links won't work with the tool.
- Folders present: confirm with the user which one is the library and which
  is OCR Mirror. Don't guess between similar names.

## 5. Save their settings

Ask for the name they want credited on their pages, then:

```sh
uv run amocr init --operator "<name>" --proton-root "/shared-with-me/<library>" --mirror "/shared-with-me/<OCR Mirror>"
uv run amocr doctor
```

Fix any remaining NO line. Claude Code is already installed, since you're
running in it.

## 6. Hand over

Tell them, in two or three lines:
- to OCR a book: claim it in the team's task sheet, then say
  "Start OCR on <Proton path of the PDF>" (the ocr-book skill takes over);
- to proofread: "I want to proofread book <id>";
- the guides are in docs/ (volunteer and proofreading guides).
