"""The librarian as a local MCP tool: Claude in the user's own Claude Code session searches the library and
reads passages through it. No API calls; everything runs on this machine."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import index, store

RULES = """You are the librarian of a closed library of Śaiva and Trika texts (Sarvāmnāya literature).
Answer only from passages you have retrieved with these tools. Rules:
- Every claim carries a citation: unit id, work, and (for printed books) pages.
- Quote the passage in its original language and script, with your translation beneath it; flag terms
  you translate loosely (śakti, spanda, vimarśa …).
- When sources disagree, show each with its work and tradition; don't merge them.
- If nothing relevant is found, say so and name the nearest works; never fill the gap from general knowledge.
- Units with status "draft" are unproofread OCR; say so when you rely on one. "edition" means a published
  e-text (GRETIL), not the team's printed copy.
- Search in Sanskrit terms (IAST or Devanagari) as well as the question's own words: keyword search
  works on Sanskrit forms, meaning search across languages."""

mcp = MCPServer("agama-librarian", instructions=RULES)


@mcp.tool()
def search(query: str, k: int = 8, work: str | None = None, layer: str | None = None) -> list[dict]:
    """Find passages: hybrid keyword (Sanskrit forms, diacritics optional) and meaning search.
    Optional filters: work id (e.g. ET-0006) and layer (mula, vrtti, varttika, hindi-mishra …).
    Returns passages read from the library, best first, with how each was found."""
    hits = index.search(query, k=k, work=work, layer=layer)
    out = []
    for h in hits:
        u = store.get(h["id"], context=0)
        if u:
            u.pop("neighbours", None)
            out.append(u | {"found_by": {x: h[x] for x in ("keyword", "meaning") if x in h}})
    return out


@mcp.tool()
def get_unit(unit_id: str, context: int = 1) -> dict:
    """Read one passage by id, with the commentary units that explain it and the ids of its neighbours."""
    return store.get(unit_id, context=context) or {"error": f"no unit {unit_id!r}"}


@mcp.tool()
def list_works() -> list[dict]:
    """The works in the library, with ids and unit counts."""
    return store.catalog()


def main() -> None:
    mcp.run()
