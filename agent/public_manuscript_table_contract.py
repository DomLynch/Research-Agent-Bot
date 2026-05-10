"""Compact table/conclusion checks for public_manuscript_contract."""
from __future__ import annotations

import re


def _section(md: str, pat: re.Pattern[str]) -> str:
    m = pat.search(md)
    if not m:
        return ""
    nxt = re.search(r"^#{1,6}\s+\S", md[m.end():], re.M)
    return md[m.end():m.end() + nxt.start()] if nxt else md[m.end():]


def _table(md: str, n: int) -> str:
    return _section(md, re.compile(rf"^#{{1,4}}\s*Table\s+{n}\b[^\n]*\n", re.I | re.M))


def _rows(section: str) -> list[list[str]]:
    out: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if cells and cells[0].lower() not in {"citation", "endpoint", "tension kind"}:
            out.append(cells)
    return out


def _cite(cell: str) -> str | None:
    m = re.match(
        r"^([A-Za-z0-9][A-Za-z0-9\-']*(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)",
        cell,
    )
    return m.group(1).strip() if m else None


def table1_metadata(md: str) -> dict[str, tuple[str, str]]:
    sec = _section(md, re.compile(r"^#{1,4}\s*(?:Included\s+Studies|Studies\s+Included|Table\s+1\b)\b[^\n]*\n", re.I | re.M))
    out: dict[str, tuple[str, str]] = {}
    for cells in _rows(sec):
        if len(cells) >= 8 and (cite := _cite(cells[0])):
            out[cite] = (cells[2], cells[7].lower())
    return out


def other_table_citations(md: str) -> set[str]:
    out: set[str] = set()
    for cells in _rows(_table(md, 2)):
        if len(cells) >= 2 and (cite := _cite(cells[1])):
            out.add(cite)
    for cells in _rows(_table(md, 3)):
        for idx in (2, 3):
            if len(cells) > idx and (cite := _cite(cells[idx])):
                out.add(cite)
    for n in (4, 5):
        for cells in _rows(_table(md, n)):
            if cells and (cite := _cite(cells[0])):
                out.add(cite)
    return out


def table_set_failures(md: str) -> list[str]:
    table1 = set(table1_metadata(md))
    return sorted(other_table_citations(md) - table1) if table1 else []


def metadata_conflicts(md: str) -> list[str]:
    table1 = table1_metadata(md)
    out: list[str] = []
    for cells in _rows(_table(md, 2)):
        if len(cells) < 6 or not (cite := _cite(cells[1])) or cite not in table1:
            continue
        t1_tier, t1_direct = table1[cite]
        if cells[5] != t1_tier or cells[4].lower() != t1_direct:
            out.append(f"{cite}: Table1={t1_tier}/{t1_direct}, Table2={cells[5]}/{cells[4].lower()}")
    for cells in _rows(_table(md, 4)):
        if len(cells) >= 2 and (cite := _cite(cells[0])) and cite in table1 and cells[1] != table1[cite][0]:
            out.append(f"{cite}: Table1 tier={table1[cite][0]}, Table4={cells[1]}")
    return out


def tension_fault_counts(md: str) -> tuple[int, int]:
    seen: set[tuple[str, str, str, str]] = set()
    self_pairs = dupes = 0
    for cells in _rows(_table(md, 3)):
        if len(cells) < 5:
            continue
        kind, a, b, outcome = cells[0], cells[2], cells[3], cells[4]
        if a == b:
            self_pairs += 1
            continue
        left, right = sorted((a, b))
        key = (kind.lower(), left, right, outcome.lower())
        if key in seen:
            dupes += 1
        else:
            seen.add(key)
    return self_pairs, dupes


def conclusion_faults(md: str) -> tuple[list[str], list[str]]:
    sec = _section(md, re.compile(r"^#{1,4}\s*Conclusion\b[^\n]*\n", re.I | re.M))
    hits = sorted(set(re.findall(
        r"\b(?:Prior narrative reviews|Prior reviews|Table\s+[1-9]|What This Synthesis Adds|Boundary-Condition Matrix|Evidence-Gap Priority|Next-Study Design Recommendation)\b",
        sec,
        flags=re.I,
    )))
    subheads = re.findall(r"(?m)^#{3,6}\s+(.+)$", sec)
    return hits, subheads


_OUTCOME_STOP = {
    "and", "or", "the", "a", "an", "of", "for", "in", "to", "from",
    "outcome", "outcomes", "endpoint", "endpoints", "finding",
    "findings", "clinical", "function", "functions", "effect",
    "effects", "domain", "domains",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _OUTCOME_STOP}


def section_outcome_failures(md: str, receipts: list[dict]) -> list[str]:
    items = [
        (
            str(r.get("citation_token") or "").strip(),
            str(r.get("outcome_class") or "").strip(),
            _tokens(str(r.get("outcome_class") or "")),
        )
        for r in receipts
        if str(r.get("citation_token") or "").strip()
    ]
    out: list[str] = []
    headings = list(re.finditer(r"^(#{1,6})\s+([^\n]+)$", md, re.M))
    for i, m in enumerate(headings):
        heading = m.group(2).strip()
        if len(m.group(1)) != 3 or "cross-domain" in heading.lower():
            continue
        if not re.search(r"\b(?:outcomes?|endpoints?|findings?)\b", heading, re.I):
            continue
        ht = _tokens(heading)
        if not ht:
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(md)
        section = md[m.end():end]
        for cite, outcome, ot in items:
            if ot and ot.isdisjoint(ht) and re.search(r"\b" + re.escape(cite) + r"\b", section):
                out.append(
                    f"citation '{cite}' with outcome_class='{outcome}' appears under subsection '{heading}'."
                )
    return out
