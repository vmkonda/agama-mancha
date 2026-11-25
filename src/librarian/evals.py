"""The evaluation set (design doc, "Evaluation"): questions with known answer passages, run after every
index rebuild. Measure: is a correct unit in the top 10? Per question type, so a change that helps one
kind of question and hurts another shows up. Questions are drafted by Claude and become the yardstick
only once the owner approves them (status "approved"): only a scholar can say which passage is right.

Stored in data/library/eval/questions.json (they quote and cite the library, so never in the repo);
every run is appended to data/library/eval/runs.jsonl with the index build it measured.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from amocr.catalog import data_dir

TYPES = {"lookup": "Verse and passage lookup", "concept": "Concept questions", "cross": "Cross-language",
         "commentary": "Commentary comparison", "absent": "Not in the library"}


def eval_dir() -> Path:
    return data_dir() / "library" / "eval"


def load() -> list[dict]:
    f = eval_dir() / "questions.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save(qs: list[dict]) -> None:
    eval_dir().mkdir(parents=True, exist_ok=True)
    (eval_dir() / "questions.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")


def update(qid: str, changes: dict, by: str) -> dict:
    """The owner's corrections: expected units, status (draft / approved / dropped), note."""
    qs = load()
    q = next((x for x in qs if x["id"] == qid), None)
    if not q:
        raise LookupError(f"no question {qid}")
    if "expected" in changes:
        q["expected"] = [str(x).strip() for x in changes["expected"] if str(x).strip()]
    if changes.get("status") in ("draft", "approved", "dropped"):
        q["status"] = changes["status"]
    if "note" in changes:
        q["note"] = str(changes["note"])[:1000]
    if "question" in changes and str(changes["question"]).strip():
        q["question"] = str(changes["question"]).strip()[:500]
    q["edited_by"], q["edited_at"] = by, datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(qs)
    return q


def run(k: int = 10, only_approved: bool = False) -> dict:
    """Search every question; a hit when an expected unit is in the top k. Absent questions can't be
    scored by retrieval alone (the librarian must say 'not found'), so they're listed, not scored."""
    from . import index

    qs = [q for q in load() if q.get("status") != "dropped" and (q.get("status") == "approved" or not only_approved)]
    rows, by_type = [], {}
    for q in qs:
        hits = [h["id"] for h in index.search(q["question"], k=k)]
        if q["type"] == "absent" or not q.get("expected"):
            rows.append({"id": q["id"], "type": q["type"], "scored": False, "top": hits[:3]})
            continue
        rank = next((i + 1 for i, h in enumerate(hits) if h in q["expected"]), None)
        rows.append({"id": q["id"], "type": q["type"], "scored": True, "rank": rank, "top": hits[:3]})
        t = by_type.setdefault(q["type"], {"hits": 0, "n": 0})
        t["n"] += 1
        t["hits"] += rank is not None
    cur = index.index_dir() / "current"
    res = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "k": k,
           "build": cur.read_text().strip() if cur.exists() else None, "only_approved": only_approved,
           "by_type": by_type, "hits": sum(t["hits"] for t in by_type.values()), "scored": sum(t["n"] for t in by_type.values()),
           "rows": rows}
    eval_dir().mkdir(parents=True, exist_ok=True)
    with (eval_dir() / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({x: res[x] for x in res if x != "rows"}, ensure_ascii=False) + "\n")
    (eval_dir() / "last_run.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def last_run() -> dict | None:
    f = eval_dir() / "last_run.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
