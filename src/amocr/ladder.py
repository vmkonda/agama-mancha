"""A page's status: the ladder from OCR to validated, after Wikisource's proofreading levels.

    none        no saved text: only engine readings
    draft       saved, but not every line checked against the print
    proofread   one person checked every line
    validated   a second person checked every line again (never the person who proofread it)
    problem     needs an expert, or the scan/print is damaged; the note says what
    blank       no text on the page (blank, plate)

Stored in data/works/<book>/groundtruth/pNNNN.meta.json. Pages saved before the ladder have only
`verified`: true reads as proofread, false as draft. `verified` is still written (true for proofread
and validated) because it means "a person checked every line", which is what scoring engines needs.
"""

from __future__ import annotations

from datetime import datetime, timezone

STATUSES = ("none", "draft", "proofread", "validated", "problem", "blank")
LABEL = {"none": "not proofread", "draft": "draft", "proofread": "proofread", "validated": "validated",
         "problem": "problem", "blank": "no text"}
CHECKED = ("proofread", "validated")      # a person checked every line
DONE = ("validated", "blank")             # nothing left to do on the page


def of(meta: dict | None) -> str:
    if not meta:
        return "none"
    s = meta.get("status")
    if s in STATUSES:
        return s
    return "proofread" if meta.get("verified") else "draft"


def checked(meta: dict | None) -> bool:
    return of(meta) in CHECKED


def change(old: dict | None, status: str, operator: str, note: str = "", now: str | None = None) -> dict:
    """The page's new meta after a save with this status; raises ValueError if the step isn't allowed."""
    if status not in STATUSES or status == "none":
        raise ValueError(f"status must be one of {', '.join(STATUSES[1:])}")
    if not operator:
        raise ValueError('set your name first: `amocr init --operator "<name>"`')
    old = dict(old or {})
    prev = of(old)
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if status == "validated":
        if prev not in CHECKED:
            raise ValueError("only a proofread page can be validated: someone has to check every line first")
        if old.get("proofread_by", old.get("reviewer")) == operator:
            raise ValueError("you proofread this page; validation needs a second person")
    if status == "problem" and not note.strip():
        raise ValueError("say what the problem is in the note")
    meta = old | {"status": status, "verified": status in CHECKED, "reviewer": operator, "saved": now, "note": note}
    if status == "proofread":
        meta |= {"proofread_by": operator, "proofread_at": now}
    if status == "validated":
        meta |= {"validated_by": operator, "validated_at": now}
        meta.setdefault("proofread_by", old.get("reviewer"))
    else:
        meta.pop("validated_by", None)
        meta.pop("validated_at", None)
    if status in ("draft", "problem", "blank"):
        meta.pop("proofread_by", None)
        meta.pop("proofread_at", None)
    meta["history"] = (old.get("history") or [])[-49:] + [{"status": status, "by": operator, "at": now}]
    return meta


def can_validate(meta: dict | None, operator: str) -> tuple[bool, str]:
    """Whether this person may validate the page now, and if not, why (for the viewer)."""
    if of(meta) not in CHECKED:
        return False, "only a proofread page can be validated"
    if (meta or {}).get("proofread_by", (meta or {}).get("reviewer")) == operator:
        return False, "you proofread this page; a second person validates it"
    return True, ""
