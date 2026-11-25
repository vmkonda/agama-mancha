# Drive setup for the folder owner

For whoever owns the team's Proton Drive folders. It's the short technical
version: what the tool does, what it needs from the drive, the trust model,
and the decisions that are the owner's. The [coordinator guide](coordinator-guide.md)
covers day-to-day running; the [developer guide](developer-guide.md) covers the code.

## What it is

`amocr` is a Python CLI (uv, pymupdf, Tesseract). It runs on each
volunteer's machine and treats Proton Drive as the shared store:

```
fetch   proton-drive download <library>/<path>/book.pdf -> data/sources/<id>.pdf
        id = "B-" + sha256[:10], so the same PDF gets the same id everywhere
ocr     Tesseract (san+hin by default) per page -> text, line confidences, bboxes
claude  the volunteer's Claude Code session reads page images in batches of 10
        and writes structured results (regions, changes vs Tesseract, uncertain);
        no API keys, it runs on the volunteer's own Claude plan
push    exports <id>/ -> <material folder>/<same path>/<book>.amocr/ via proton-drive upload
pull    merges results others pushed; local files are never overwritten
serve   local viewer (127.0.0.1) for side-by-side review and proofreading
```

Output per book in the material folder: `book.json` (page status, operators,
reviewers), `book.txt` (best reading per page), `pages/pNNNN/*.json|txt`
(every engine's result, append-only), `groundtruth/pNNNN.txt` plus
`.meta.json` (proofread text, reviewer, verified flag). It sits next to the
team's ocrmypdf PDFs and replaces nothing.

Proton access goes through the official CLI (`ProtonDriveApps/sdk`, tested
against 0.9.0). The CLI has no way to open public share links: volunteers
must be invited by email, and the folders appear under
`/shared-with-me/<share>/`.

## Trust model

The risk is a volunteer's Claude session, which has shell access and the
volunteer's Proton credentials, doing something destructive on the drive.
The defences, strongest first:

1. **Proton permissions (the folder owner's part).** Volunteers get viewer access to the
   library and editor access only to the material folder. Nothing client-side can get
   past a viewer role.
2. **`src/amocr/proton.py`.** The only code path to Proton. It allow-lists
   `version`, `filesystem info|list|download`, `filesystem create-folder` and
   `filesystem upload`. Writes are confined to the material folder, which must
   already exist; the tool never creates it. Uploads use
   `--file-conflict-strategy create-new-revision`, so revision history is kept,
   never trash-and-replace. Every call is logged to `data/proton.log`.
3. **A Claude Code PreToolUse hook** (`.claude/hooks/guard_proton.py`, wired in
   `.claude/settings.json`). It blocks `proton-drive` invocations other than
   read-only ones, scripts written to disk that call Proton write or delete
   operations, and edits to `proton.py`, the hook or the settings unless
   `AMOCR_DEV=1`. It's regex-based, so a backstop, not a boundary.
4. **Tests.** `tests/test_safety.py` covers the allow-list, path confinement
   (including `..` tricks) and the hook. `tests/test_volunteer_flow.py` runs two
   volunteers through fetch, work, push and fetch against a fake CLI backed by
   a temp folder.

## What to set up on the drive

1. **A material folder, writable, apart from the library.** This is where
   Agama Mancha's material goes (see [material-folder.md](material-folder.md)).
   It must be shared with volunteers as **Editor** through its own share, never
   be writable through the library's share, and never contain the originals.
   Proton has an `inherited` role, so a folder nested inside the library share
   would follow the library's permissions: keep it out of the library.
   The team's `[OCR Mirror]` (their ocrmypdf PDFs) is a separate share already,
   so a subfolder of it, `[OCR Mirror]/Agama Mancha`, qualifies; so does a new
   share of its own.
2. **Roles** (CLI roles: `viewer`, `editor`, `admin`; the CLI defaults to
   `viewer`):
   ```sh
   proton-drive sharing invite --user <email> --role viewer "/my-files/<library>"
   proton-drive sharing invite --user <email> --role editor "/my-files/<material folder>"
   proton-drive sharing status "/my-files/<library>"      # audit members and links
   ```
   Downgrade anyone who has editor on the library and doesn't add books.
3. **Backup** of the library outside Proton, refreshed when books are added.
   Proton's trash and revisions cover small accidents only.
4. **Public links:** review them with `sharing status`. Anyone holding a link
   and its password can open the folder, and the tool can't use links anyway.

Run these in a terminal of your own, not through Claude in this repo: the guard
hook blocks Proton write commands there by design.

Volunteers then configure:

```sh
uv run amocr init --operator "Name" --proton-root "/shared-with-me/<library>" --material "/shared-with-me/[OCR Mirror]/Agama Mancha"
uv run amocr doctor      # checks Tesseract langs, CLI, login, both folders
```

## Decisions for the folder owner

1. **Restricted works.** Claude-processed pages go to Anthropic. A book fetched
   with `--restricted` makes every Claude step refuse to run for it, but only
   if volunteers pass the flag, so mark restricted books in the task sheet.
   A list kept on the drive that the tool enforces would be a small change.
2. **Locking.** The CLI has no locks. The task sheet stays the lock: one owner
   per book. Page results are append-only and merge safely; `book.json` and
   `book.txt` are regenerated on push, so the last push wins for those.
3. **Who uses Claude.** It needs a paid Claude plan (Pro or higher) per
   volunteer. A full 460-page book is many sessions, so it's best used for
   core works. Tesseract and proofreading are free.

## Findings so far

- **Language models:** on one page of the Mālinīvijayottara with Hindi
  commentary, `iast+eng+san` gave 13.7% CER and `san+hin` gave 5.7%. The
  `eng`/`iast` models turn Hindi words into Latin junk (`ata`, `ag`, `ġ`). One
  page and a draft answer key, so a signal, not a rule; a 10-page proofread
  sample per book type would settle it. `amocr eval` reports CER per engine.
- **Tesseract on Macs:** on Apple Silicon, Homebrew's tessdata is
  `/opt/homebrew/share/tessdata`, not `/usr/local/share/tessdata` (the Intel
  location older instructions often give). Extra models such as
  `iast.traineddata` go there.
- **Not yet tested:** against the real Proton Drive (only the fake CLI) and on
  Windows. The first real run will tell us whether the CLI's Keychain login
  works over SSH on macOS.

## Checklist

- [ ] The material folder exists, outside the library, in a share of its own
- [ ] Volunteers: viewer on the library, editor on the material folder; links reviewed
- [ ] Backup of the library outside Proton
- [ ] Restricted works marked in the task sheet
- [ ] Volunteers pointed to the [volunteer guide](volunteer-guide.md), scholars to the
      [proofreading guide](proofreading-guide.md)
