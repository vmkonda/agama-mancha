# Plan: from OCR tool to the team's workbench

Agreed 2026-11-25. The goal: one application in which anyone on the team sees every
book in the library, picks one to work on, and sees who is working on what and how far
each book has got. There is no server: the **material folder** on Proton Drive is the
shared board, and every volunteer's copy of the app reads it and writes only its own
small files there.

The library today: **976 PDFs, 32.8 GB** (Authors 325, Texts 336, Studies 173,
Miscellaneous 66, Reference 60, Kula Internal Documents 15).

## Phases

| Phase | What | Status |
|---|---|---|
| A | **Catalog** of every PDF, with refresh; the **Library** page | done (#12) |
| B | **Claims, stages and progress** per book; *Work on this* and *Release* | built, in review |
| C | **Inventory** per book: text layer, page count, script (which need OCR) | later |
| D | **Assemble** units into the material folder layout ([material-folder.md](material-folder.md)) | later |

### A. Catalog and Library page

- `amocr catalog refresh` lists the library (read-only) and updates
  `<material folder>/catalog/catalog.json`: one entry per PDF with path, name, folder,
  size and date. Facts learned later (checksum, pages, script, SL id) are added by
  later phases.
- **Refresh is safe to repeat.** New PDFs are added; removed ones are marked *gone*,
  never deleted; moved or renamed ones are matched by name and size (or checksum) and
  keep their history (`moved_from`); changed ones (same path, new size) are flagged.
  Each refresh appends a line to `catalog/changes.jsonl`.
- **When it runs**: `amocr start` refreshes if the catalog is more than a day old; the
  Library page has a *Refresh* button; one always-on machine can run it nightly.
- **Two people refreshing at once is harmless**: the catalog only reflects the library
  listing. What people do lives in each book's own status file, which a refresh never
  touches.
- The **Library page** lists every book, with search and filters (folder, new, gone),
  shows when the catalog was last refreshed and by whom, and opens books already on
  this machine.

### B. Claims, stages, progress

- **The board**: `<material folder>/catalog/board/<person>.json`, one small file per
  person with their claims and the progress of every book on their machine (page counts
  per step, stage). Nobody edits a shared file, so two people never overwrite each
  other; everyone's app reads all the files and merges them. Books are keyed by the
  PDF's checksum, so claims survive the library being reorganised. (The plan first had
  one `status.json` per book; with no locks on Proton, two people saving it at once
  would lose one of the saves.)
- Stages: listed → inventoried → read by Surya → reviewed → proofreading → verified →
  assembled. Updated automatically as people work.
- *Work on this* reads the board, writes the claim, reads the board back to confirm
  (Proton has no locks); the earliest claim wins, and a later one withdraws itself. It
  also downloads the PDF if it isn't on this machine. A claim with no activity for 14
  days shows as stale; anyone may then release it, and the release is recorded in the
  releaser's own file. Whole books first; page ranges later.
- Progress is shared on every `amocr push` and `amocr start`, and with *Sync board*.
- Commands: `amocr board` (show), `amocr board sync`, `amocr board claim <book>`,
  `amocr board release <book> [--why …]`.

### C. Inventory

The design doc's first OCR step: per PDF, count extractable text and test whether it is
valid Devanagari or IAST. Books with a good text layer need no OCR. Runs when a book is
fetched, or in bulk overnight on one machine (downloads the 31.6 GB). The Library page
then shows only books needing OCR by default.

### D. Assemble

`amocr assemble`: page texts into units with IDs work/chapter/verse/layer, commentary
linked to its verses, written to the material folder as numbered builds.

## Decisions

- Catalog lists **all 976 PDFs**; by default the Library shows those needing OCR (once
  Phase C knows which).
- Claims are **whole books** first.
- **Anyone** may release a claim that has been stale for 14 days; the release is recorded.
- Material folder: `[OCR Mirror]/Agama Mancha`; legible names; Vimarsha's internal use.
