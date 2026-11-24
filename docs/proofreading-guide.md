# Proofreading guide

For scholars and readers of Sanskrit and Hindi, including āgama paṇḍitas, who
check machine-read pages against the printed book. Your corrected pages
become the **ground truth**: the reference the whole project measures
itself against, and the text scholars will eventually cite. No programming
is needed.

## Getting set up

Ask a volunteer or the coordinator to do the one-time setup in the
[volunteer guide](volunteer-guide.md) (sections 1 and 2) on your computer.
After that you only need two things: Claude Code and this sentence.

Open a terminal in the `agama-mancha-ocr` folder, type `claude`, and say:

> I want to proofread book B-1a2b3c4d5e, starting at page 231

Claude brings down the latest pages from the shared drive, starts the
viewer, and tells you which address to open in your browser (normally
http://localhost:8791). When you're done for the day, say:

> Upload my proofreading

## The viewer

The scanned page is on the left and the text on the right. Along the top:

- **View** shows one reading of the page. Choose which one in the menu:
  - `claude-code-…`: Claude's reading, with verses, commentary and footnotes
    in labelled boxes, a list of what it changed from Tesseract, and the
    readings it was unsure of.
  - `tesseract-…`: the machine reading. Yellow lines are ones it was unsure
    of. Hover over a line to see where it is on the page.
  - `ground truth`: the proofread text, once someone has saved it.
- **Compare** shows two readings with the differences marked: struck-through
  red text is in the first reading only, green text is in the second only.
- **Proofread** is where you correct the page.

Use ◀ ▶ (or the arrow keys) to move between pages and the zoom slider to
enlarge the scan.

## How to proofread a page

1. Open the page and choose **Proofread**. The box starts from the best
   reading available (the existing proofread text, or Claude's reading).
2. Read the scan line by line and correct the text in the box.
3. If you checked **every** line against the print, tick *I checked every
   line against the print (verified)*. If you only fixed what caught your eye,
   leave it unticked: the page is saved as a draft, and the next reviewer
   knows it still needs a full check.
4. Use the note field for anything the next person should know ("verse 36
   damaged in this copy", "check against the Kashmir edition").
5. Press **Save**. Your name and the date are recorded with the page.

### Helpers in Proofread

- **The scan follows your cursor.** The line you're on is outlined on the
  scan, which scrolls to it. This uses Tesseract's line positions, matched
  line by line, so after you add or remove lines it can be one line off.
- **Unsure lines are yellow.** These are the lines Tesseract was least sure
  of, where most mistakes are. **F2** (or **Alt ↓**) jumps to the next one
  and selects it; **Shift F2** (or **Alt ↑**) goes back.
- **Hard characters.** The button row inserts ऽ । ॥ ् ं ँ ः ॐ, the
  Devanagari digits and a dash at the cursor.
- **Romanised typing.** Type in the box above the text and press Enter to
  insert it in Devanagari. It accepts IAST (`kṛṣṇa`, `prathamo'dhikāraḥ`)
  and Harvard-Kyoto (`kRSNa`, `prathamo'dhikAraH`), but not loose spellings
  like `krishna`, where `ri` could be ऋ or रि.
- **Look-alikes are fixed for you.** A vertical bar `|` becomes `।` and `||`
  becomes `॥` as you type. On save, Latin digits in verse numbers
  (`॥ 39 ॥`) become Devanagari (`॥ ३९ ॥`).
- **Keyboard.** **⌘S** (Ctrl S on Windows and Linux) saves; **⌘↵** saves and
  opens the next page in Proofread.
- **Nothing is lost.** Unsaved edits are kept in your browser. If you close
  the tab or move to another page, they come back when you return, with an
  option to discard them.

For typing longer passages, turn on a Devanagari keyboard in your computer's
settings (on a Mac: System Settings → Keyboard → Input Sources → Devanagari –
QWERTY) and switch to it while you type.

## Conventions: type what is printed

The goal is a faithful record of **this printed edition**, not a corrected
or ideal text. Editorial judgement belongs in notes and in later stages.

**Text**
- Type what is printed, even when it is a misprint. A note can say
  "misprint for कीट".
- Keep the edition's spelling, sandhi, and its choice between anusvāra and
  nasal consonant (संबध्यते vs सम्बध्यते) exactly as printed.
- Keep avagraha (ऽ), daṇḍa (।) and double daṇḍa (॥) as printed. Verse
  numbers in Devanagari digits as printed: `॥ ३९ ॥`.
- Use proper Unicode Devanagari. Don't use legacy fonts or Latin look-alikes
  (a vertical bar `|` is not a daṇḍa).
- Text printed in IAST (romanised Sanskrit) stays in IAST, with diacritics.

**Layout**
- One printed line per line, in reading order. A word broken across lines
  keeps its hyphen as printed: `प्रति-` at the end of one line, `निधियों` at the
  start of the next.
- A blank line between blocks: header, each verse group, each commentary
  paragraph, footnotes.
- Keep the running header and page number at the top
  (`प्रथमोऽधिकारः १७`).
- Keep footnote markers where they appear, as plain digits after the word
  (`मुहूर्तादित्यखेदतः३`), and the footnotes at the bottom as printed
  (`३. क० पु० मुहूर्तादेव खेदत इति पाठः`).
- Keep the printer's signature mark at the foot of some pages (`मा० वि०—३`).

**Variant readings**
- Variant readings recorded in footnotes (पाठः) stay in the footnotes. Never
  move a variant into the verse, even if you prefer it.

**When you can't read something**
- Type your best reading and say so in the note ("line 4: ञ्छ faint, could
  be न्छ"). Don't leave a gap and don't guess silently.

## What happens to your work

Saved pages go into the book's `groundtruth/` folder and are uploaded with
the book to the shared drive. Verified pages are used to measure how
accurate each reading method is, which decides how the team digitises the
remaining books, and they become the text of record for those pages.
