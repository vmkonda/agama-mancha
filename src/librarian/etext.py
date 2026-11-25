"""Library works from published e-texts (GRETIL TEI): no OCR, no proofreading, units straight from the edition.

A work gets a provisional ET-NNNN id (stable per source file, in data/library/texts/ids.json) until the
team's SL- list exists. Each work is data/library/texts/<ET-id>/ with work.json (the catalog record:
title, author, source edition, licence) and units.jsonl, in the same shape as assembled units:
work/chapter/verse/layer, Devanagari text with IAST beside it, and status "edition" (a published
edition's text, not proofread by the team). Like every e-text, they stay in data/, never in the repo.

GRETIL files differ in how they mark structure, so blocks (<lg> verse groups, <p> paragraphs) are read
in order and each is placed by the first rule that fits:
  xml:id like AbhT_1.1 / Ipk_1.1.1      chapter and verse from the id
  inline "2.1ab: …" (pāda references)    joined into whole verses
  a verse ending "|| 4 ||" or "// 4"     verse number, chapter from the last heading or reference
  "Ipv:" paragraphs (ĪPK)                Utpala's vṛtti on the preceding kārikā, layer "vrtti"
  other prose                            numbered passages within the chapter, split near 400 words
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from amocr.catalog import data_dir
from amocr.reference import deva

# The Trika core: GRETIL file → title, author, layer name for the main text.
TRIKA = {
    "sa_mAlinIvijayottaratantra": ("Mālinīvijayottaratantra", "", "mula"),
    "sa_vijJAnabhairava": ("Vijñānabhairava", "", "mula"),
    "sa_zivasUtra-with-vArttika": ("Śivasūtra with Vārttika", "Vasugupta; Bhāskara (vārttika)", "mula"),
    "sa_vasugupta-spandakArikA": ("Spandakārikā", "Vasugupta / Kallaṭa", "mula"),
    "sa_abhinavagupta-tantrasAra": ("Tantrasāra", "Abhinavagupta", "mula"),
    "sa_abhinavagupta-tantrAloka": ("Tantrāloka", "Abhinavagupta", "mula"),
    "sa_kSemarAja-pratyabhijJAhRdaya": ("Pratyabhijñāhṛdaya", "Kṣemarāja", "mula"),
    "sa_utpaladeva-IzvarapratyabhijJAkArikA-with-vRtti": ("Īśvarapratyabhijñākārikā with Vṛtti", "Utpaladeva", "mula"),
    "sa_abhinavagupta-paramArthasAra": ("Paramārthasāra", "Abhinavagupta", "mula"),
    "sa_svacchandatantra": ("Svacchandatantra", "", "mula"),
}
PROSE_WORDS = 400


def texts_dir() -> Path:
    return data_dir() / "library" / "texts"


def _ids() -> dict:
    f = texts_dir() / "ids.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def et_id(stem: str) -> str:
    ids = _ids()
    if stem not in ids:
        ids[stem] = f"ET-{len(ids) + 1:04d}"
        texts_dir().mkdir(parents=True, exist_ok=True)
        (texts_dir() / "ids.json").write_text(json.dumps(ids, indent=1), encoding="utf-8")
    return ids[stem]


def _clean(x: str) -> str:
    x = re.sub(r"<note\b.*?</note>", " ", x, flags=re.S)
    x = re.sub(r"<(l|seg|lb)\b[^>]*>", " / ", x)          # a verse line or half-line
    x = html.unescape(re.sub(r"<[^>]+>", " ", x))
    x = re.sub(r"(\s*/\s*)+", " / ", x)
    return re.sub(r"\s+", " ", x).strip(" /")


def _header(s: str) -> dict:
    def tag(t):
        m = re.search(rf"<{t}\b[^>]*>(.*?)</{t}>", s, re.S)
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
    src = re.search(r"<sourceDesc>(.*?)</sourceDesc>", s, re.S)
    lic = re.search(r"<licence[^>]*>(.*?)</licence>", s, re.S)
    clean = lambda m: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
    return {"gretil_title": tag("title"), "source": clean(src)[:600], "licence": clean(lic)[:300] or "see GRETIL"}


XMLID = re.compile(r'xml:id="[A-Za-z]+_(\d+)\.(\d+)(?:\.(\d+))?[a-z]?"')
PADA = re.compile(r"(\d+)\.(\d+)(ab|cd|ef):\s*")
END_NO = re.compile(r"(?:\|\||//)\s*(\d+)\s*(?:\|\||//)?\s*$")
CHAPTER_REF = re.compile(r"\b[A-Za-z]+_(\d+)\.(\d+)")
REF_END = re.compile(r"(?:\|\|\s*)?\b([A-Za-z]+)_(\d+)\.(\d+)(?::(\d+))?\s*(?:\|\|)?\s*\]?\s*$")


def parse(xml: str, main_layer: str = "mula") -> list[dict]:
    """Blocks → [{chapter, verse, layer, iast}] in reading order."""
    body = xml[xml.find("<body"):]
    out: list[dict] = []
    chapter, prose_n, last_verse = "1", 0, None
    # Verse groups, paragraphs, and bare lines outside a verse group (the Śivasūtra's sūtras).
    for m in re.finditer(r"<(lg|p|l)\b([^>]*)>(.*?)</\1>", body, re.S):
        tag, attrs, inner = m.groups()
        text = _clean(inner)
        if not text:
            continue
        idm = XMLID.search(attrs)
        if idm:                                                  # AbhT_1.1, SvaT_1.1, Ipk_1.1.1
            a, b, c = idm.groups()
            ch, v = (f"{a}.{b}", c) if c else (a, b)
            if ch != str(chapter):
                chapter, prose_n = ch, 0
            out.append({"chapter": chapter, "verse": v, "layer": main_layer, "iast": text})
            last_verse = v
            continue
        if PADA.search(text):                                    # Mālinī: "2.1ab: … 2.1cd: …"
            verses: dict[tuple[str, str], list[str]] = {}
            for pm in re.finditer(r"(\d+)\.(\d+)(?:ab|cd|ef):\s*(.*?)(?=\s\d+\.\d+(?:ab|cd|ef):|$)", text):
                verses.setdefault((pm.group(1), pm.group(2)), []).append(pm.group(3).strip(" /"))
            for (ch, v), halves in verses.items():
                chapter = ch
                out.append({"chapter": ch, "verse": v, "layer": main_layer, "iast": " / ".join(halves)})
                last_verse = v
            continue
        rm = REF_END.search(text)                                # Śivasūtra: "… / SivS_1.1", vārttika "… || SivSV_1.1:1 ||"
        if rm and not idm and len(text.split()) <= 60:          # a sūtra or a vārttika verse, never prose
            ch, v, sub = rm.group(2), rm.group(3), rm.group(4)
            body_txt = REF_END.sub("", text)
            body_txt = re.sub(r"^[^/]*\bunmeṣa[^/]*/\s*", "", body_txt)          # the section title before a sūtra
            body_txt = re.sub(r"^\*?\s*\[?<[^>]*>\s*/?\s*\*?\s*", "", body_txt).strip(" */[]")
            if ch != str(chapter):
                chapter, prose_n = ch, 0
            if sub:
                out.append({"chapter": ch, "verse": f"{v}:{sub}", "layer": "varttika", "iast": body_txt, "explains": v})
            else:
                out.append({"chapter": ch, "verse": v, "layer": main_layer, "iast": body_txt})
                last_verse = v
            continue
        if text.startswith("Ipv:"):                              # Utpala's vṛtti on the kārikā above
            out.append({"chapter": chapter, "verse": last_verse or "0", "layer": "vrtti",
                        "iast": text[4:].strip(), "explains": last_verse})
            continue
        ref = CHAPTER_REF.search(text)
        if ref and tag == "p" and int(ref.group(1)) != int(str(chapter).split(".")[0] or 0):
            chapter, prose_n = ref.group(1), 0
        e = END_NO.search(text)
        if tag == "lg" and e:                                    # "… || 4 ||"
            out.append({"chapter": chapter, "verse": e.group(1), "layer": main_layer, "iast": END_NO.sub("", text).strip(" /")})
            last_verse = e.group(1)
            continue
        if tag == "lg":                                          # an unnumbered verse (a quotation, an opening verse)
            out.append({"chapter": chapter, "verse": f"q{len(out) + 1}", "layer": main_layer, "iast": text})
            continue
        words = text.split()                                     # prose: passages of about 400 words
        for k in range(0, len(words), PROSE_WORDS):
            prose_n += 1
            out.append({"chapter": chapter, "verse": f"p{prose_n}", "layer": main_layer, "iast": " ".join(words[k:k + PROSE_WORDS])})
    return out


def ingest(xml_path: Path, title: str | None = None, author: str | None = None, licence: str | None = None,
           source: str | None = None, origin: str = "GRETIL") -> dict:
    """One TEI file → a library work with units. Rebuilding gives the same ids. Title and author come
    from the Trika list, else what the importer gave, else the file's own header."""
    stem = xml_path.stem
    xml = xml_path.read_text(encoding="utf-8")
    head = _header(xml)
    known = TRIKA.get(stem)
    title = (known[0] if known else None) or title or head["gretil_title"] or stem
    author = (known[1] if known else None) or author or ""
    layer = known[2] if known else "mula"
    wid = et_id(stem)
    rows = parse(xml, layer)
    d = texts_dir() / wid
    d.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    units = []
    for r in rows:
        base = f"{wid}/{r['chapter']}/{r['verse']}/{r['layer']}"
        seen[base] = seen.get(base, 0) + 1
        uid = base if seen[base] == 1 else f"{base}~{seen[base]}"
        u = {"id": uid, "work": wid, "chapter": r["chapter"], "verse": r["verse"], "layer": r["layer"], "lang": "san",
             "text": deva(r["iast"].replace(" / ", " । ")), "iast": r["iast"], "status": "edition", "source": origin}
        if r.get("explains"):
            u["explains"] = [f"{wid}/{r['chapter']}/{r['explains']}/mula"]
        units.append(u)
    (d / "units.jsonl").write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units), encoding="utf-8")
    if not units:
        raise ValueError(f"{xml_path.name}: no verses or passages found; is it a TEI e-text?")
    import hashlib

    # A pinned snapshot of an external text: never edited; the checksum and date say exactly which
    # version the citations point at (an update is a new import, not a change to this one).
    meta = {"id": wid, "title": title, "author": author, "lang": "san", "kind": "etext", "file": xml_path.name,
            "origin": origin, "sha256": hashlib.sha256(xml_path.read_bytes()).hexdigest(), "units": len(units), "layers": sorted({u["layer"] for u in units}),
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds")} | head
    if licence:
        meta["licence"] = licence
    if source:
        meta["source"] = source
    (d / "work.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def works() -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(texts_dir().glob("ET-*/work.json"))]


def units(wid: str | None = None):
    for f in sorted(texts_dir().glob(f"{wid or 'ET-*'}/units.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                yield json.loads(ln)
