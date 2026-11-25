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
| B | **Claims, stages and progress** per book; *Work on this* and *Release* | done (#13) |
| C | **Inventory** per book: text layer, page count, script (which need OCR) | done (#14) |
| D | **Assemble** units into the material folder layout ([material-folder.md](material-folder.md)) | done (#15) |

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
fetched, or in bulk overnight on one machine (downloads the 32.8 GB, one PDF at a time,
deleting each after measuring). The Library page then shows only books needing OCR by default.

- `amocr catalog inventory [--limit N] [--folder Texts] [--max-mb M] [--local]`: smallest
  PDFs first; resumable (saved after every PDF); skips PDFs anyone has already measured.
- Facts per PDF (keyed by SHA-1), shared like the board, one file per person in
  `<material folder>/catalog/inventory/`: pages, scanned pages, page kinds (Devanagari,
  IAST, Latin, legacy-font text, none), verdict (*needs OCR*, *has a text layer*,
  *partly usable text*, *not a PDF*), why (scanned pages, or the legacy font's name),
  and the script from Tesseract's script detection on three pages. No book text.
- **A text layer isn't trusted just for being in the right script.** Three checks:
  - *Born-digital or OCR?* Text lying over a full-page scan (or a PDF made by an OCR
    program) is someone's OCR. Word or Distiller documents that merely contain page images
    are born-digital.
  - *Garbled?* A text-only screen: Devanagari vowel signs or viramas with no consonant
    before them (real text: 0%; over 1% means fonts that don't map back to Unicode), and,
    on Latin pages, leftovers of legacy fonts (Ë Ý Æ µ …) beyond IAST, ISO 15919, European
    accents and other Indic scripts (Śāradā is real text).
  - *How good is an OCR layer?* Three of its pages are read afresh (Surya, else Tesseract)
    and the words compared, in any order: the share of the layer's words confirmed, the
    share of the page's words the layer has, and how many IAST diacritics survived. Good,
    fair or poor; anything but good counts as needing OCR.
- Found on the first 15 PDFs: placeholder files that aren't PDFs (macOS iCloud stubs,
  a web filter's "blocked download" page saved as .pdf), and texts typeset in the
  legacy Sanskrit99 font (Devanagari stored as Latin letters). Those could be converted
  by a font map instead of OCR.

### D. Assemble

`amocr assemble <book> [--commentary-layer hindi-mishra] [--chapter-at PAGE=CH] [--push]`:
page texts into units with IDs work/chapter/verse/layer, written as numbered builds
(`units/v001/`, never changed; an unchanged result makes no new build) and shared with the
book's folder.

- Each page's best text: the person's saved text, else Claude's, else Surya's.
- Lines are classed from the text, not from the engines' labels (which proved unreliable):
  running header, verse (ends in a daṇḍa, numbered ॥ ३४ ॥), commentary (Hindi words),
  footnote (१. … at the foot), colophon (इति … तन्त्रे …, and the Hindi … अधिकार परिपूर्ण).
- **Two streams.** A verse is complete at its number; a commentary passage at the number of
  the verse(s) it explains (॥ ३५-३६ ॥), which gives `explains`. Commentary runs on across
  pages while the next verses are printed above it.
- Chapters from the running header (ordinal + अधिकारः/पटलः/अध्यायः, also -तितम forms and
  OCR's dropped anusvāra); pages before chapter 1 and after the last colophon are left out.
- A unit is `validated` or `proofread` only if all its pages are; otherwise `draft`; `types: "guessed"`.
- `build.json` lists, per chapter, verse numbers missing or seen twice: the places for a
  proofreader to look (a misread number, or a line taken for the wrong layer).

First build of the pilot (from Surya, unproofread): 23 chapters, 1,317 verse units,
977 commentary passages, 461 footnotes; 15 verse numbers missing and 9 seen twice out of 1,280.

## Decisions

- Catalog lists **all 976 PDFs**; by default the Library shows those needing OCR (once
  Phase C knows which).
- Claims are **whole books** first.
- **Anyone** may release a claim that has been stale for 14 days; the release is recorded.
- Material folder: `[OCR Mirror]/Agama Mancha`; legible names; Vimarsha's internal use.
