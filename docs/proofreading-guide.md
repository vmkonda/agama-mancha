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

Open a terminal in the `agama-mancha` folder, type `claude`, and say:

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
   reading available, always in this order: your saved text, else Claude's
   reading, else Surya's, else Tesseract's. The line above the box names which.
2. Read the scan line by line and correct the text in the box.
3. Choose what the save means, under **Save as** (the status ladder, below).
4. Use the note field for anything the next person should know ("verse 36
   damaged in this copy", "check against the Kashmir edition").
5. Press **Save**. Your name and the date are recorded with the page.

### The same view for every book

Proofread looks and works the same in every book, so nothing has to be
relearned from one book to the next. From top to bottom:

1. **Where the text came from** (saved text, or the reading it starts from).
2. **The button row** of hard characters and the **romanised typing** box.
3. **The page bar:** chapter, printed page number, the verses on the page, the
   commentary that closes on it.
4. **Warnings**, if any: verse numbers the assembler can't use. Each jumps to its line.
5. **The text**, with a **tag beside every line** and the scan beside it.
6. The note, **Save as** (the page's status), **Save**, **Save and next**, **Check with Claude**.

The tags are always one of: `header` (with `ch N` on a chapter heading),
`verse` (with its number on the last line), `comm.` (with `→ N`, the verse it
explains, on its last line), `footnote N`, `colophon`, `signature`. The
highlights are always: the current line (a bar at the left), yellow for an
unsure line, an outlined box for a footnote marker, and a yellow tag for a
line with a warning.

What a book brings is only data that fills these same places: its brief and
glossary, its look-alike profile, and the rules learned from corrections.
A book never gets its own layout, buttons or colours.

### The status ladder: two pairs of eyes

Every page has one status, shown as a coloured chip above the text:

| Status | Means | Who |
|---|---|---|
| **not proofread** | only the engines' readings | |
| **draft** | saved, but not every line checked yet (you fixed what caught your eye) | anyone |
| **proofread** | one person checked **every** line against the print | anyone |
| **validated** | a **second** person checked every line again | anyone except the person who proofread it |
| **problem** | needs an expert, or the scan or print is damaged; the note says what | anyone |
| **no text** | a blank page or a plate | anyone |

A quick read misses look-alikes (ो for ी, बा for आ) far more often than a second
reader does, so a page counts as done only when it is **validated** (or has no
text). The viewer won't let you validate your own proofreading: the option is
greyed out, with the reason. If you change the text of a validated page, save
it as proofread; it then waits for a validation again.

A unit of text (a verse, a commentary passage) is as far along as its least
checked page, and a book is *verified* on the board only when every page is
validated or has no text.

### Helpers in Proofread

- **The scan follows your cursor.** The line you're on is outlined on the
  scan, which scrolls to it. This uses Surya's line positions (Tesseract's if
  the page has no Surya reading), matched line by line, so after you add or
  remove lines it can be one line off.
- **Unsure lines are yellow.** These are the lines Tesseract was least sure
  of, where most mistakes are. **F2** (or **Alt ↓**) jumps to the next one
  and selects it; **Shift F2** (or **Alt ↑**) goes back.
- **Hard characters.** The button row inserts ऽ । ॥ ् ं ँ ः ॐ, the
  Devanagari digits and a dash at the cursor.
- **Romanised typing.** Type in the box above the text and press Enter to
  insert it in Devanagari. It accepts IAST (`kṛṣṇa`, `prathamo'dhikāraḥ`)
  and Harvard-Kyoto (`kRSNa`, `prathamo'dhikAraH`), but not loose spellings
  like `krishna`, where `ri` could be ऋ or रि.
- **Line tags and the page bar** show what the assembler will make of the
  page, worked out from your text as you type. If a tag looks wrong, the text
  usually is: a misread daṇḍa or verse number. The warnings point at those.
- **Another edition as a second pair of eyes.** If the book has a reference
  e-text (see docs/engines.md), each verse line is compared with it and
  differences appear among the warnings, your word first, then the other
  edition's: "घनावृतेन्द्रनोलाभो → GRETIL: घनावृतेन्द्रनीलाभरविबिम्बसमाकृतिम्
  (GRETIL 13.41ab)". Hover to see the reference's whole half-verse.
  Check the print: often it's an OCR slip, sometimes the editions really
  differ. Type what is printed; if the print looks like a misprint, say so in
  the note.
- **Footnote markers stand out.** A digit right after a letter (योगी२) or
  right before a word (१षट्…) is outlined, because Devanagari digits look like
  letters (२ like र, ३ like इ). In View mode they are shown raised, as printed.
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

## Suggestions: fix a mistake once, everywhere

The reading engine (Surya) makes the same mistakes again and again: in this
typeface आ often comes out as भ (भाता for आता), -त्व as -स्व, a reph (र्) gets
dropped. Once you've corrected a few pages, the **Suggestions** tab finds the
same mistake on every other page that isn't verified yet.

1. Press **Learn from corrections**. It compares your corrected pages with what
   the engine read and turns each fix into a rule.
2. Go through the list. Each suggestion shows the line from the scan, the text
   with the change marked, and the page highlighted on the left.
   **a** accepts, **r** rejects, **j**/**k** move, **o** opens the page in Proofread.
3. Reject anything that is printed that way: a misprint stays a misprint.
   Accepting changes only that page's draft. The page still needs its full
   line-by-line check before you save it as *proofread*.

Rules that could do harm start switched off, such as a short word that is
usually right as read, or a fix inside words. The rule list at the bottom of
the tab shows them, with a note, and lets you switch any rule on or off.

## Working with Claude while you proofread

The **Chat** button (top right of the viewer) opens a panel for talking to your
own Claude Code session. Start it once: in your Claude Code session, say
**listen to the viewer chat**. The panel then shows "Claude is listening".

- Questions are about the line your cursor is on in Proofread (or the current
  suggestion); untick "about …" to ask about the book in general.
- **⌘/Ctrl ↵** sends. Answers appear in the panel within a few seconds.
- **Check with Claude** (next to Save in Proofread, or **⌘/Ctrl K**) asks Claude to
  compare the line your cursor is on with the print. Select several lines to check
  them together. Your unsaved edits are saved first, so Claude sees what you see.
- When Claude proposes a new line, it shows the old and new text with
  **Apply to the draft** (or **Apply all** when there are several), and
  **⌘/Ctrl ⇧ ↵** applies Claude's latest proposal from the keyboard. Nothing changes until you press it, and the page still
  needs your full check before you save it as proofread. A rule Claude adds has a button
  that opens its matches in Suggestions.

You can also type the same requests into the Claude Code session directly:

- **"What does line 12 on page 240 say?"** Claude looks at just that line of the
  scan (`amocr line`) and tells you its reading. Line numbers count lines of text,
  as in the Suggestions tab.
- **"I keep fixing भ to आ at the start of words. Can you make a rule?"** Claude
  looks at your corrections (`amocr patterns`), writes a general rule, and adds
  it (`amocr rule add`). Its suggestions appear in the Suggestions tab for you to
  accept or reject; Claude never changes the text itself.
- **"Are there other mistakes like these?"** Claude reads the rule list and the
  pending suggestions, and proposes rules or switches off bad ones.

Each question uses your Claude plan, but far less than having Claude read
whole pages.

## Conventions: type what is printed

The goal is a faithful record of **this printed edition**, not a corrected
or ideal text. Editorial judgement belongs in notes and in later stages.

**Text**
- Type the letter the typeface prints, even where its shape looks like another
  letter. In the Mālinīvijayottara (Hindi) edition, **ी** is printed with a shape
  that looks like **ो** (देवी looks like देवो, उसी like उसो): type **ी**. That is
  how this type prints ी, not a misprint. Its **आ** can also look like भा/बा.
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
the book to the shared drive. Proofread and validated pages are used to measure how
accurate each reading method is, which decides how the team digitises the
remaining books, and they become the text of record for those pages.
