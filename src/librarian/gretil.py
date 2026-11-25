"""GRETIL as a source of e-texts: its catalogue (cached), search by title, and downloading a TEI file.

Only GRETIL's own TEI files can be fetched (gretil/corpustei/sa_….xml): the importer never follows an
arbitrary address. The catalogue page is read at most once a month and cached in data/etexts/.
"""

from __future__ import annotations

import html
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

from amocr.catalog import data_dir

BASE = "https://gretil.sub.uni-goettingen.de/"
CATALOGUE_PAGE = BASE + "gretil.html"
TEI_PATH = re.compile(r"^gretil/corpustei/sa_[\w\-.]+\.xml$")
MAX_AGE = 30 * 86400
UA = {"User-Agent": "agama-mancha-librarian"}


def cache_path() -> Path:
    return data_dir() / "etexts" / "gretil-catalogue.json"


def gretil_dir() -> Path:
    return data_dir() / "etexts" / "gretil"


# GRETIL's file names are Harvard-Kyoto (bodhapaJcadazikA); shown and searched as IAST (bodhapañcadaśikā).
_HK = [("lRR", "ḹ"), ("lR", "ḷ"), ("RR", "ṝ"), ("A", "ā"), ("I", "ī"), ("U", "ū"), ("R", "ṛ"), ("M", "ṃ"), ("H", "ḥ"),
       ("G", "ṅ"), ("J", "ñ"), ("T", "ṭ"), ("D", "ḍ"), ("N", "ṇ"), ("z", "ś"), ("S", "ṣ")]


def hk_to_iast(t: str) -> str:
    for a, b in _HK:
        t = t.replace(a, b)
    return t


def _title_from_file(path: str) -> str:
    stem = hk_to_iast(Path(path).stem.removeprefix("sa_"))
    return " ".join(w[:1].upper() + w[1:] for w in stem.replace("-", " ").split())


def parse(page: str) -> list[dict]:
    out, seen = [], set()
    for item in re.findall(r"<li>(.*?)</li>", page, re.S):
        m = re.search(r'href="(gretil/corpustei/sa_[^"]+\.xml)"', item)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", item.split("<span")[0]))).strip()
        if not title or title.startswith("TEI-conformant"):
            title = _title_from_file(m.group(1))
        out.append({"title": title, "path": m.group(1)})
    return out


def catalogue(refresh: bool = False) -> list[dict]:
    f = cache_path()
    if f.exists() and not refresh and time.time() - f.stat().st_mtime < MAX_AGE:
        return json.loads(f.read_text(encoding="utf-8"))
    req = urllib.request.Request(CATALOGUE_PAGE, headers=UA)
    page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    items = parse(page)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return items


def _fold(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def search(q: str, limit: int = 40) -> list[dict]:
    words = _fold(q).split()
    hits = [x for x in catalogue() if all(w in _fold(x["title"] + " " + hk_to_iast(x["path"])) for w in words)]
    return hits[:limit]


def download(path: str) -> Path:
    if not TEI_PATH.match(path):
        raise ValueError("only GRETIL TEI files (gretil/corpustei/sa_….xml) can be imported")
    req = urllib.request.Request(BASE + path, headers=UA)
    data = urllib.request.urlopen(req, timeout=120).read()
    if b"<TEI" not in data[:5000] and b"<tei" not in data[:5000].lower():
        raise ValueError(f"{path} isn't a TEI file")
    out = gretil_dir() / Path(path).name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out
