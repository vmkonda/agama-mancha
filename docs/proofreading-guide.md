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
http://localhost:8791/proofread, at your page; http://localhost:8791 itself opens the Library,
with Proofreading one click away in the title band). When you're done for the day, say:

> Upload my proofreading

## The viewer

The scanned page is on the left and the text on the right. Along the top:
**Proofread**, **Pages**, **View** and **Compare**. The viewer opens in
Proofread (for proofreaders and validators, on the next page nobody has
finished). Everything that concerns one page, its warnings, scores and
suggested fixes, is shown on that page in Proofread.

- **Proofread** is where you correct the page.
- **Pages** shows every page of the book as a small square in its status
  colour, grouped by chapter, with a count of warnings on each page and how
  much of each chapter is done. Click a page to proofread it; *Next to
  proofread* and *Next to validate* jump to the next page that needs you.
  Front matter and the indexes at the back are grouped separately and get no
  warnings, since they aren't verse and commentary.
  A page still waiting for OCR has a hollow dot in its corner, a filled one while
  a machine is reading it, and a red one if it was set aside; the Library page
  shows how far the book's OCR has got and roughly how long is left.

- **View** shows one reading of the page. Choose which one in the menu:
  - `claude-code-…`: Claude's reading, with verses, commentary and footnotes
    in labelled boxes, a list of what it changed from Tesseract, and the
    readings it was unsure of.
  - `tesseract-…`: the machine reading. Yellow lines are ones it was unsure
    of. Hover over a line to see where it is on the page.
  - `ground truth`: the proofread text, once someone has saved it.
- **Compare** shows two readings with the differences marked: struck-through
  red text is in the first reading only, green text is in the second only.

Use ◀ ▶ (or the arrow keys) to move between pages and the zoom slider to
enlarge the scan.

## How to proofread a page

**Which text you start from.** Until someone saves the page, the top of Proofread says
*No saved text yet; start from* with a menu of the page's readings. The best one is chosen
for you, in this order: Claude's review, Claude's other readings, Surya, Tesseract. Pick
another if it looks closer to the print (compare them in **Compare** first). If you have
already typed on the page, it asks before replacing your edits. The choice is kept in your
browser until you save; the save records which reading the page started from, and from
then on everyone works on the saved text. The outline on the scan follows Surya's lines,
so starting from Tesseract, which splits lines differently, can put it a line off.

1. Open the page and choose **Proofread**. The box starts from the best
   reading available (your saved text, else the reading in **Start from**).
2. Read the scan line by line and correct the text in the box.
3. Choose what the save means, under **Save as** (the status ladder, below).
4. Use the note field for anything the next person should know ("verse 36
   damaged in this copy", "check against the Kashmir edition").
5. Press **Save**. Your name and the date are recorded with the page.

### Working alongside others

On the shared server several people proofread the same book. Three things keep you from undoing each
other's work:

- **Someone else on the page:** the line at the top says *"Anna is also on this page"*.
  **Next to proofread** skips pages someone else has open, so it rarely happens.
- **No silent overwrites:** if someone saved the page after you opened it, your save is refused with
  their name and the time. Your edits stay in the box (and in this browser); reload the page to see
  their changes, then put yours back and save. The top line also warns you as soon as it happens.
- **Your answers are yours:** what Claude or the local AI proposes for your question appears only in
  your chat panel, and only you can apply it.

Every save is kept in **History**, so even a mistake can be undone.

### The same view for every book

Proofread looks and works the same in every book, so nothing has to be
relearned from one book to the next. From top to bottom:

1. **Where the text came from**: the saved text, or, before the first save, a **Start from** menu
   with the reading it starts from (see "How to proofread a page"), and, in red, **who else
   is on this page** and whether someone saved it after you opened it.
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
unsure line, orange for a line worth a second look (darker for a higher score,
with the score beside its tag and the suspect words underlined), an outlined box
for a footnote marker, and a yellow tag for a line with a warning.

What a book brings is only data that fills these same places: its brief and
glossary, its look-alike profile, and the rules learned from corrections.
A book never gets its own layout, buttons or colours.

For proofreaders, validators and readers on the hosted server, the page bar
leaves out two notes meant for experts (which e-text the verses were checked
against, and that the tags are guessed), and book and page names are plain.
Everything else is the same for everyone.

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

### History: every save is kept

Under the Save buttons, **History and changes since the OCR** lists every save of
the page (who, when, which status, and whether it was a save in Proofread,
accepted suggestions or a fix from the chat), newest first. *What changed* shows
the difference from the save before it. **Changes since the OCR** shows
everything changed from the engine reading the page started from: this is what
a validator should read first, then check the rest of the page against the print.
Nothing in the history is ever deleted.

### Helpers in Proofread

- **The scan follows your cursor.** The line you're on is outlined on the
  scan, which scrolls to it. This uses Surya's line positions (Tesseract's if
  the page has no Surya reading), matched line by line, so after you add or
  remove lines it can be one line off.
- **Unsure lines are yellow.** These are the lines Tesseract was least sure
  of, where most mistakes are. **F2** (or **Alt ↓**) jumps to the next yellow
  or orange line and selects it; **Shift F2** (or **Alt ↑**) goes back.
- **Orange lines are worth a second look.** Each line is scored from the text
  alone (free, no Claude), the same way as `amocr suspects` (docs/engines.md): a
  word that is rare in this book while its look-alike is common (उसो where उसी is
  usual: this typeface prints ी like ो), a word that doesn't fit the next one
  (उसो तरह), an unusual word, a verse with the wrong syllable count, or a line
  Tesseract reads differently. The score is the number beside the line's tag, and
  the orange is darker the higher it is; the suspect words are underlined. The
  line under the text says why, for the line your cursor is on. **F2** jumps to
  orange lines as well as yellow ones. A score is a place to look, never a
  correction: type what is printed, and read the other lines too, since a wrong
  letter that makes a real word isn't caught.
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

## Suggested fixes: a mistake fixed once is suggested everywhere

The reading engine (Surya) makes the same mistakes again and again: in this
typeface आ often comes out as भ (भाता for आता), ी as ो (उसो for उसी), -त्व as -स्व,
a reph (र्) gets dropped. Every time a page is saved, the viewer compares it with
what the engine read and learns each fix as a rule. From then on, Proofread shows
the same fix on every other page where it applies, as you open it:

1. **Below the page bar**, *N suggested fixes on this page* lists each one: the
   line, the change, and why (corrected on how many pages, or the book's usual
   spelling). Click the line to go to it. The word is underlined in green in the
   text, with a *fix* mark beside the line's tag, and the line under the text
   offers **Apply** when your cursor is on it.
2. **Apply** makes the change in the text, as if you had typed it (**Apply all**
   does every one on the page). Nothing is saved until you save, and the page
   still needs its full line-by-line check before you save it as *proofread*.
3. **Reject** means "not here: the print has it this way" (a misprint stays a
   misprint); it isn't suggested on this line again. **Never** switches the fix
   off for the whole book.

Fixes that could do harm start switched off, such as a short word that is usually
right as read, or a fix inside words, and are never suggested.

## Working with Claude while you proofread

The **Chat** button (top right of the viewer) opens a panel for talking to your
own Claude Code session. Start it once: in your Claude Code session, say
**listen to the viewer chat**. The panel then shows "Claude is listening".

- Questions are about the line your cursor is on in Proofread; untick "about …" to ask about the book in general.
- **⌘/Ctrl ↵** sends. Answers appear in the panel within a few seconds.
- **Check with Claude** (next to Save in Proofread, or **⌘/Ctrl K**) asks Claude to
  compare the line your cursor is on with the print. Select several lines to check
  them together. Your unsaved edits are saved first, so Claude sees what you see.
- When Claude proposes a new line, it shows the old and new text with
  **Apply to the draft** (or **Apply all** when there are several), and
  **⌘/Ctrl ⇧ ↵** applies Claude's latest proposal from the keyboard. Nothing changes until you press it, and the page still
  needs your full check before you save it as proofread. A rule Claude adds has a button
  that opens the first page where it suggests a fix.
- **Answer with: Claude · Local AI**, above the text box, picks who answers your next message;
  it's one conversation either way, each answer labelled with who gave it. With **Local AI** you
  describe a change so you don't have to retype the line: select the line(s) in the text, type
  what to change (“the marker after योगी is २”, “षण्माससभ्यसेद् should be षण्मासमभ्यसेद्”, “remove the
  quotes”) and press **Send**. Sending never changes the draft: the answer is a proposal you can
  check, ask again about, or apply. The status line shows whether the one you picked is
  ready; *Check with Claude* always goes to Claude. A local model on the team's machine (free, shared by everyone) returns the edited
  line(s) with **Apply to the draft**, marked *Local AI*. It doesn't look at the scan or decide
  what's right; it only carries out your words, so check the old and new text before applying.
  Claude never receives these requests. If no local AI is running, the panel says so and the
  request waits.

You can also type the same requests into the Claude Code session directly:

- **"What does line 12 on page 240 say?"** Claude looks at just that line of the
  scan (`amocr line`) and tells you its reading. Line numbers count lines of text,
  as in Proofread.
- **"I keep fixing भ to आ at the start of words. Can you make a rule?"** Claude
  looks at your corrections (`amocr patterns`), writes a general rule, and adds
  it (`amocr rule add`). Its fixes appear on their pages in Proofread for you
  to apply or reject; Claude never changes the text itself.
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
