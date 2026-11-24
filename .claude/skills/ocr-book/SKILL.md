---
name: ocr-book
description: Volunteer OCR workflow for a book - fetch it from Proton Drive, run Tesseract, have Claude read the next batch of pages, import, and push results to the team's OCR Mirror; also set up proofreading sessions. Use when the user says "continue OCR on book X", "start a new book", "OCR this PDF", "I want to proofread book X", "upload my proofreading", or asks for progress on a book.
---

# ocr-book

Run every command from the repository root with `uv run amocr ...`.

## Before anything

Run `uv run amocr doctor`. If any line says NO, help the user fix it using the
hint, following docs/volunteer-guide.md section 2. Never ask for or handle
Proton passwords or share-link passwords; Proton sign-in is `proton-drive auth login`
in the user's own terminal.

## "Continue OCR on book <id>"

1. `uv run amocr pull <id>` (bring down others' work; skip if the book has no Proton path).
2. `uv run amocr ocr <id>` if Tesseract hasn't run on all pages yet (`amocr status <id>` shows it). Run it in the background for long books.
3. `uv run amocr claude-import <id> --ready` (anything left from a previous session).
4. `uv run amocr claude-next <id> -n 10`. It refuses restricted books: stop and tell the user.
5. For each packet folder it prints, follow CLAUDE.md exactly and don't read the
   book's groundtruth/ folder:
   - **review mode** (the default when Surya is installed): read review.txt and
     every sheet*.png, check each numbered line against its image, and write
     result.json with mode "review" and only the corrections.
   - **bands mode**: read band0.png, band1.png, band2.png and tesseract.txt, and
     write result.json with mode "correct" (transcribe as printed, every edit in
     `changes`, unclear readings in `uncertain`, never drop a line).
6. `uv run amocr claude-import <id> --ready`. If a page warns about dropped
   lines, re-read that page and fix result.json, then import with `--force`
   for that page.
7. `uv run amocr push <id>`, then report pages done in this batch and overall
   (`uv run amocr status <id>`), so the user can update the task sheet.
8. Ask whether to do another batch; each page uses the user's Claude plan.

## "Start a new book" / "OCR <proton path>"

`uv run amocr fetch "<proton path>"` (add `--restricted` if the user says the
book is restricted; ask if unsure), note the printed id, then continue as above.
A local PDF without Proton: `uv run amocr add <file>`.

## "I want to proofread book <id> [from page N]"

1. `uv run amocr pull <id>`.
2. Start the viewer as in the ocr-view skill and give the URL, defaulting to
   page N. Point them to the Proofread tab and docs/proofreading-guide.md.

## "Upload my proofreading"

`uv run amocr push <id>`, then report how many pages are now verified.
