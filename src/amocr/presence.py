"""Who has which page open, so two people don't proofread the same page at once.

The viewer reports the page it shows every 15 s; a page counts as someone's for 45 s after that.
In memory only (a restart forgets it, which is harmless). The real guard against overwriting is the
page's version check on save; this is the courtesy in front of it.
"""

from __future__ import annotations

import threading
import time

FRESH = 45
_LOCK = threading.Lock()
_SEEN: dict[tuple[str, int], dict[str, float]] = {}


def touch(work_id: str, page: int, who: str) -> None:
    with _LOCK:
        for (w, p), people in list(_SEEN.items()):     # one page per person: leaving a page frees it
            if w == work_id and p != page:
                people.pop(who, None)
        _SEEN.setdefault((work_id, page), {})[who] = time.time()


def others(work_id: str, page: int, who: str) -> list[str]:
    now = time.time()
    with _LOCK:
        return sorted(n for n, t in _SEEN.get((work_id, page), {}).items() if n != who and now - t < FRESH)


def busy(work_id: str, who: str) -> dict[int, list[str]]:
    """Pages of a book that someone else has open: page -> names."""
    now = time.time()
    with _LOCK:
        out = {p: sorted(n for n, t in people.items() if n != who and now - t < FRESH)
               for (w, p), people in _SEEN.items() if w == work_id}
    return {p: names for p, names in out.items() if names}
