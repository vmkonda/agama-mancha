# Coordinator guide

For whoever runs the OCR effort: sharing, assigning books, restricted texts,
and following progress.

## Protect the drive first

Volunteers run Claude on their own machines with their own Proton login. If that
login can edit the originals, a mistake can damage them. Set Proton up so it can't:

1. **Two separate shares.** Keep the originals and the results in two folders
   that are shared separately, neither inside the other:
   - the library of original PDFs, shared as **Viewer**;
   - the **material folder** (results; for example `[OCR Mirror]/Agama Mancha`), shared as **Editor**.

   With viewer rights, nothing a volunteer's computer does can change an
   original, whatever the software or Claude does. This is the protection that
   matters most; everything below is a backstop.
2. **Create the results folder yourself.** The tool never creates it and
   refuses to write anywhere else.
3. **Keep an offline backup of the originals** (an external disk or a second
   account the volunteers can't reach), and refresh it when books are added.
   Proton's trash and file versions help with accidents, but a backup is the
   real undo.
4. **Don't give volunteers admin roles**, and don't share your own top-level
   "My files" with them.

Volunteers then configure both paths (the volunteer guide shows this):

```sh
uv run amocr init --proton-root "/shared-with-me/<library>" --material "/shared-with-me/[OCR Mirror]/Agama Mancha"
```

What the software adds on top (enforced in code and tested):

- `amocr` can only read, list, download, create folders and upload. It has no
  delete, trash, move, rename, restore or sharing operations at all.
- It writes only inside the results folder, and only below it.
- Re-uploading a page adds a new version of the file; nothing is trashed.
- Every Proton call is logged on the volunteer's machine (`data/proton.log`).
- A Claude Code guard in the repo blocks Claude from running Proton write
  or delete commands directly, from writing scripts that would, and from
  editing these safety rules. It is a strong backstop, not a guarantee, which
  is why step 1 matters.

## Give a volunteer access

1. **Proton Drive.** Invite the volunteer's Proton account to the library as
   **Viewer** and to the material folder as **Editor** (see above). For the material folder (in the web app: Share → invite by email, role
   *Editor*; or `proton-drive sharing invite --user <their email> --role editor "<folder>"`.
   The CLI's default role is *viewer*, which can download but not upload).
   Share links (drive.proton.me/urls/…, with or without a password) work in a
   browser but **not** with the tool, so every volunteer needs an invitation.
   Proofreaders need the same: their corrections are uploaded to the material folder.
2. **GitHub.** The repository is public, so anyone can clone it; no account
   or invitation is needed. It holds code and documentation only, never book
   scans or book text.
3. **Task sheet.** Give them edit access to the team sheet.
4. Point them to the [volunteer guide](volunteer-guide.md), or the
   [proofreading guide](proofreading-guide.md) for scholars.

## Assigning books

Keep using the task sheet: one owner per book at a time. Suggested columns:

| Path | Book id | Owner | Status | Pages total | Tesseract done | Claude done | Proofread (verified) | Restricted | Notes |
|---|---|---|---|---|---|---|---|---|---|

The book id (e.g. `B-1a2b3c4d5e`) comes from `amocr fetch`. It's derived
from the PDF itself, so it's the same on every machine and changes only if
the file changes. The page counts can be read from the book's `book.json`
in the material folder, or with `uv run amocr status <id>`.

Who is working on which book, and how far each has got, is on the app's
**Library** page (or `uv run amocr board`). It's shared through
`<material folder>/catalog/board/`, one small file per person. A claim with no
activity for 14 days shows as stale, and anyone may release it; the release is
recorded with their name.

A book can be handed over: the holder presses *Release*, and the next volunteer
presses *Work on this*, which downloads the PDF and everything already uploaded.

## Restricted texts

Pages processed with Claude are sent to Anthropic's servers. Any work
restricted by lineage or initiation must be fetched with `--restricted`.
The tool then refuses every Claude step for it, and only Tesseract and human
proofreading are used. Mark these books in the sheet so volunteers know.
Deciding which works are restricted is the coordinator's call.

## What ends up in Proton Drive

```
<material folder>/<same path as the original>/<book>.amocr/
  book.json        who did what, page counts, which pages are verified
  book.txt         the whole book as text, best reading per page
  pages/p0231/     every reading of page 231 (Tesseract, Claude), with credits
  groundtruth/     proofread pages, with reviewer and verified flag
```

`book.txt` is the file most people want: one section per page, using the
proofread text where it exists, then Claude's reading, then Tesseract's.

It is separate from the team's `[OCR Mirror]` PDFs (from ocrmypdf) and doesn't
replace them. The planned layout, by work, for Agama Mancha is in
[material-folder.md](material-folder.md).

## Quality: what to watch

- **Proofread a sample.** Ask a scholar to fully verify about 10 pages of
  each book, spread across it. Then `uv run amocr eval <id>` reports the
  character error rate of each method on those pages.
- **First measurement, one pilot page:** the team's `iast+eng+san` setting
  had 13.7% character errors on a Hindi-commentary page, against 5.7% with
  `san+hin`. This is one page, not yet a decision, but books with Hindi
  commentary probably need `hin`.
- **Claude's main risk** is producing a smooth, plausible text that differs
  from the print, for example by "correcting" toward a familiar reading.
  Its output always lists what it changed and what it was unsure of, and
  verified proofreading is what catches the rest.
- **Cost:** each volunteer uses their own Claude plan. A 460-page book is
  many sessions for one person, so spread long books across volunteers by
  page ranges only if they coordinate closely, or one volunteer per book.
