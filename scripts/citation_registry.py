"""Fix #3: Citation registry — eliminate PMCID/internal-handle body
leaks BY CONSTRUCTION rather than by post-hoc cleanup.

Pre-fix the writer received raw receipt_ids like
`PMC12978362_molecular_mechanisms_of_metformin_acti` and emitted them
in body prose ("the PMC12978362 receipt..."). A post-processor then
chased the leaks with regex substitution and missed many — the latest
paper had 53 PMCID body leaks.

Fix: build a registry mapping each receipt_id → a clean body_citation
string ("Smith 2026", "PMC-12978362 2026", etc.) BEFORE the writer
runs, then substitute the receipt list passed to the writer so it
never sees the long handles. The post-processor still runs as belt-
and-braces, but the registry is the single source of truth.

Architecture: deterministic, no LLM. The registry shape is per-receipt
(one entry per source paper); body_citation is bounded by an explicit
allowed-shape list (Surname YYYY / Surname et al YYYY / PMCID YYYY)."""
from __future__ import annotations

import dataclasses
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass


# Latin-script letters whose modification is a stroke/slash/ligature have NO
# NFKD base+combining decomposition, so NFKD leaves them intact and the
# downstream [^A-Za-z-] strip then DELETES them — corrupting surnames
# (Ławiński → "awinski", Strømland → "Strmland", Đorđević → "orevic").
# Transliterate them to an ASCII base first. Standard Unicode→ASCII set,
# domain-agnostic (any Latin-script author, any field).
_TRANSLIT = {
    "Ł": "L", "ł": "l", "Ø": "O", "ø": "o", "Đ": "D", "đ": "d",
    "Ð": "D", "ð": "d", "Þ": "Th", "þ": "th", "Æ": "Ae", "æ": "ae",
    "Œ": "Oe", "œ": "oe", "ß": "ss", "Ħ": "H", "ħ": "h",
    "İ": "I", "ı": "i",
}


def _ascii_fold(text: str) -> str:
    """Transliterate stroke/ligature letters, then NFKD-decompose and strip
    combining marks. Universal — turns any Latin-script letter into its ASCII
    base (Hernández → Hernandez, Müller → Muller, Ławiński → Lawinski,
    Strømland → Stromland). Used so the author-year token in References matches
    inline citations whatever diacritics the source metadata carries, and so a
    leading non-decomposable letter is never dropped. No per-language table."""
    text = "".join(_TRANSLIT.get(c, c) for c in text)
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationEntry:
    """One source paper's allowed body citation + reference metadata.

    Cross-stage object → frozen+slots+kw_only per project rule.
    body_citation is what the writer / Methods text may reference.
    Internal handles (long receipt_id, PMCID-only forms) NEVER appear
    in body prose — only inside ## References."""
    receipt_id: str        # internal long handle (the registry key)
    body_citation: str     # allowed in body prose
    reference_id: str      # short identifier in ## References (e.g. "R03")
    source_year: int | None = None
    source_doi: str | None = None
    source_pmid: str | None = None
    source_pmcid: str | None = None
    source_journal: str | None = None
    title: str | None = None


# Receipt-id shape: Author_YYYY_TRAIL or PMC<digits>_TRAIL.
# PMCID still uses a strict regex (the `PMC` prefix uniquely identifies
# the form); author-year extraction is now token-based to handle
# multi-word surnames (Van de Werf, O'Brien, Smith-Jones).
_PMCID_RE = re.compile(r"^(PMC\d{6,9})(?:_|$)")
_YEAR_RE = re.compile(r"^(20\d{2}|19\d{2})$")
# Plausibility window for inferred publication years. The upper bound is
# the current year, not a fixed ceiling: a publication year can never be
# in the future. Without this a source carrying a future date (e.g. an
# ongoing trial's estimated completion year, 2035) leaks a future-dated
# citation that correctly trips the certification gate. Universal — no
# topic logic; a future year is invalid in every domain.
_MIN_PLAUSIBLE_YEAR = 1990


def _current_year() -> int:
    return dt.date.today().year


def _normalize_pub_year(value: object) -> int | None:
    """Coerce a raw year to a plausible publication year, or None when it
    is missing / unparseable / out-of-window / in the future."""
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if _is_plausible_year(year) else None


def _body_citation_for(receipt_id: str, source_year: int | None = None) -> str:
    """Deterministic body citation from receipt_id shape.

    Token-based extraction (not regex-anchored) so multi-word
    surnames work: split on `_`, find the first 4-digit year token,
    everything before that is the author name (joined by spaces).

    Rules:
      - <token>...<YYYY>_*  → "<token>... YYYY"
            handles Walton_2019, Van_de_Werf_2019, O'Brien_2019,
            Smith-Jones_2019 (any token shape before the year is fine)
      - PMC#######_*        → "PMC####### <year>"
      - anything else       → fail-loud (raises in build_registry)
    """
    # PMCID first — distinct shape, won't have an author-year prefix.
    if m := _PMCID_RE.match(receipt_id):
        year = source_year or _extract_year_from_id(receipt_id) or ""
        if year:
            return f"{m.group(1)} {year}"
        return m.group(1)
    # Token-based author + year. Find the FIRST 4-digit token in the
    # plausible publication-year window.
    parts = receipt_id.split("_")
    for i, tok in enumerate(parts):
        if (m := _YEAR_RE.match(tok)) and _is_plausible_year(int(m.group(1))):
            year = m.group(1)
            author_tokens = [p for p in parts[:i] if p]
            if author_tokens:
                # First token always capitalized (leading char of the
                # surname); subsequent tokens use particle-aware rule.
                first = author_tokens[0]
                head = first[0].upper() + first[1:] if first else ""
                tail = [_smart_title(t) for t in author_tokens[1:]]
                author = " ".join([head, *tail]).strip()
                return f"{author} {year}"
            break
    # Fallback: short slug + year if any. Caller's
    # build_registry.validate_body_citation will catch leak-shaped
    # output and raise.
    slug = receipt_id[:30].rstrip("_")
    if source_year:
        return f"{slug} {source_year}"
    return slug


def _is_plausible_year(y: int) -> bool:
    return _MIN_PLAUSIBLE_YEAR <= y <= _current_year()


# Lowercase nobiliary particles preserved as-is in surnames (the
# Western convention: "Van de Werf", not "Van De Werf").
_LOWERCASE_PARTICLES: frozenset[str] = frozenset({
    "de", "van", "von", "der", "den", "du", "la", "le",
    "el", "of", "the", "y", "i",
})


def _smart_title(token: str) -> str:
    """Capitalize the first letter of a surname token while preserving
    interior uppercase ('O'Brien' stays 'O'Brien', 'MASTERS' stays
    'MASTERS', 'walton' → 'Walton'). Lowercase nobiliary particles
    ('de', 'van', 'von', etc.) are left lowercase per Western surname
    convention."""
    if not token:
        return token
    if token.lower() in _LOWERCASE_PARTICLES:
        return token.lower()
    if any(c.isupper() for c in token):
        return token
    return token[0].upper() + token[1:]


def _extract_year_from_id(receipt_id: str) -> int | None:
    """Best-effort year extraction from a slug like
    `..._2026_...`. P2 reviewer fix: scan ALL year-shaped matches
    and pick the most plausible publication year (1990-2100)
    instead of the first hit (which could be `n=2018` or `v2019`)."""
    candidates: list[int] = []
    for m in re.finditer(r"(?:^|[_\-\s])(20\d{2}|19\d{2})(?:[_\-\s]|$)", receipt_id):
        try:
            y = int(m.group(1))
        except (ValueError, TypeError):
            continue
        if _is_plausible_year(y):
            candidates.append(y)
    if not candidates:
        return None
    # Prefer the LAST plausible year — receipt_ids put the publication
    # year before the descriptive slug, but pre-print year is often
    # appended at the end (..._2026_revised). Last-wins matches the
    # observed corpus naming.
    return candidates[-1]


def _author_year_citation_from_id(receipt_id: str, source_year: int | None) -> str | None:
    if _PMCID_RE.match(receipt_id) or receipt_id.startswith(("DOI_", "HIT_", "PMID")):
        return None
    parts = receipt_id.split("_")
    has_author_year = any(
        i > 0 and (m := _YEAR_RE.match(tok))
        and _is_plausible_year(int(m.group(1)))
        for i, tok in enumerate(parts)
    )
    if not has_author_year:
        return None
    candidate = _body_citation_for(receipt_id, source_year=source_year)
    return None if validate_body_citation(candidate) else candidate


# Phrases the body_citation MUST NOT match. Anything matching these
# patterns means the body prose still contains an internal handle.
# Includes BARE-handle shapes (Author_YYYY without trailing keyword,
# bare PMCID without year) — those are still leaks the user would
# notice.
_BLOCKED_BODY_CITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Abstract-fallback/source handles from closed-access records.
    re.compile(r"^DOI_[A-Za-z0-9_]+"),
    re.compile(r"^HIT_[A-Za-z0-9_]+"),
    re.compile(r"^PMID\d+_[A-Za-z0-9_]+"),
    # Long descriptive PMCID slug like "PMC12978362_molecular_mechanisms_..."
    re.compile(r"PMC\d{6,9}_[a-zA-Z_]{10,}"),
    # Author_YYYY_TRAIL_KEYWORDS
    re.compile(r"[A-Z][a-zA-Z]+_\d{4}_[A-Za-z_]+_"),
    # Bare Author_YYYY (no trailing) — still an internal handle leak
    re.compile(r"^[A-Z][a-zA-Z]+_\d{4}$"),
    # Bare PMCID with no year decoration
    re.compile(r"^PMC\d{6,9}$"),
    # Extraction / correction artifacts are not author-year citations.
    re.compile(r"^CORRECT(?:ING|ION)?\s+\d{4}[a-z]?$", re.IGNORECASE),
    # Duplicate-year malformed labels (e.g. "Smith 2019 2019").
    re.compile(r"\b(19\d{2}|20\d{2})\b.*\b\1\b"),
    # Long all-caps title fragments; short acronyms and surname-year labels
    # such as HBOT 2024 / TSUBONE 2013 are OK.
    re.compile(r"^(?!PMC\d)[A-Z][A-Z0-9-]{12,}(?:\s+\d{4}[a-z]?)?$"),
)


def validate_body_citation(citation: str) -> list[str]:
    """Return list of blocked patterns the citation matches. Empty
    list = clean. Used by tests + the orchestrator's pre-write gate."""
    found: list[str] = []
    for pat in _BLOCKED_BODY_CITATION_PATTERNS:
        if pat.search(citation):
            found.append(pat.pattern)
    return found


def build_registry(
    receipts: list,
    paper_meta_by_id: dict[str, dict] | None = None,
) -> dict[str, CitationEntry]:
    """Build the registry from a list of ReceiptSummary objects.

    Fix #10: when `paper_meta_by_id` is provided, extract Author-Year
    citations from parsed paper metadata (authors + year fields) for
    PMC papers. Pre-fix Fix #3 produced `PMC12978362 2026` body
    citations; a PhD reviewer would never accept PMC handles in body
    prose. Now PMC papers cite as e.g. `Yu 2025`, `Shadyab 2025`.

    Each entry's body_citation is computed once + validated + de-
    duplicated (collisions like Smith 2024a / Smith 2024b). Raises
    only if every available citation candidate matches a blocked pattern."""
    registry: dict[str, CitationEntry] = {}
    paper_meta_by_id = paper_meta_by_id or {}
    # Track distinct source-level citation bases before assigning suffixes.
    # Standard citation convention is Smith 2024a / Smith 2024b, not
    # Smith 2024 / Smith 2024b. Duplicate receipts for the same DOI/PMID/PMCID
    # still share one token.
    prepared: list[tuple[int, object, str, int | None, tuple[str, str]]] = []
    citation_base_by_source: dict[tuple[str, str], str] = {}
    source_order: list[tuple[str, str]] = []
    for idx, r in enumerate(receipts, start=1):
        receipt_id = getattr(r, "receipt_id", "") or ""
        if not receipt_id.strip():
            raise ValueError(
                f"Receipt at index {idx-1} has empty receipt_id; "
                "registry cannot key by empty string"
            )
        # Prefer metadata-derived Author-Year for PMC papers; fall
        # back to receipt_id-derived form (legacy + Walton-style).
        meta = paper_meta_by_id.get(receipt_id, {})
        # Normalize once: every citation-derivation path and the stored
        # source_year use the clamped year, so a future date never renders.
        source_year = _normalize_pub_year(getattr(r, "source_year", None))
        source_key = _source_key(r)
        group_key = source_key or ("receipt_id", receipt_id)
        if group_key not in citation_base_by_source:
            body_citation = _first_clean_body_citation(receipt_id, source_year, meta)
            citation_base_by_source[group_key] = body_citation
            source_order.append(group_key)
        prepared.append((idx, r, receipt_id, source_year, group_key))

    groups_by_base: dict[str, list[tuple[str, str]]] = {}
    for group_key in source_order:
        groups_by_base.setdefault(citation_base_by_source[group_key], []).append(group_key)
    citation_by_source: dict[tuple[str, str], str] = {}
    for base, group_keys in groups_by_base.items():
        if len(group_keys) == 1:
            citation_by_source[group_keys[0]] = base
            continue
        for suffix_index, group_key in enumerate(group_keys):
            citation_by_source[group_key] = f"{base}{_alpha_suffix(suffix_index)}"

    for idx, r, receipt_id, source_year, group_key in prepared:
        body_citation = citation_by_source[group_key]
        reference_id = f"R{idx:02d}"
        entry = CitationEntry(
            receipt_id=receipt_id,
            body_citation=body_citation,
            reference_id=reference_id,
            source_year=source_year,  # normalized above (no future years)
            source_doi=getattr(r, "source_doi", None),
            source_pmid=getattr(r, "source_pmid", None),
            source_pmcid=getattr(r, "source_pmcid", None),
            source_journal=getattr(r, "source_journal", None),
            title=getattr(r, "title", None),
        )
        registry[receipt_id] = entry
    return registry


def _first_clean_body_citation(receipt_id: str, source_year: int | None, meta: dict) -> str:
    candidates = [
        _author_year_citation_from_id(receipt_id, source_year),
        _body_citation_from_metadata(meta),
        _body_citation_for(receipt_id, source_year=source_year),
    ]
    blocked: list[tuple[str, list[str]]] = []
    for candidate in candidates:
        if not candidate:
            continue
        leaks = validate_body_citation(candidate)
        if not leaks:
            return candidate
        blocked.append((candidate, leaks))
    candidate, leaks = blocked[-1] if blocked else (receipt_id, validate_body_citation(receipt_id))
    raise ValueError(
        f"Generated body_citation for {receipt_id!r} matches "
        f"blocked pattern(s) {leaks}: {candidate!r}"
    )


def _alpha_suffix(index: int) -> str:
    letters = "abcdefghijklmnopqrstuvwxyz"
    out = ""
    i = index
    while True:
        out = letters[i % len(letters)] + out
        i = i // len(letters) - 1
        if i < 0:
            return out


def _source_key(receipt) -> tuple[str, str] | None:
    for field in ("source_doi", "source_pmid", "source_pmcid"):
        value = str(getattr(receipt, field, "") or "").strip().lower()
        if value:
            return field, value
    return None


def _body_citation_from_metadata(meta: dict) -> str | None:
    """Extract `<Surname> <Year>` from parsed paper metadata. Returns
    None if metadata insufficient (caller falls back to receipt_id-
    derived citation).

    Surname extraction: take the LAST token of the first author name
    (Western-style). For multi-word surnames (Van de Werf), this
    grabs only the last token — acceptable since the disambiguator
    suffix handles collisions."""
    if not meta:
        return None
    raw_year = meta.get("year")
    if not raw_year:
        return None
    authors = meta.get("authors") or []
    # A present-but-future/implausible year (e.g. an ongoing trial's 2035
    # completion estimate) must never render as a real publication year:
    # cite the source undated ("n.d.") instead of fabricating a future date.
    normalized = _normalize_pub_year(raw_year)
    year_str = str(normalized) if normalized is not None else "n.d."
    if not authors:
        return _title_citation_from_metadata(meta, year_str)
    first_author = (authors[0] or "").strip()
    if not first_author:
        return _title_citation_from_metadata(meta, year_str)
    # Bug-fix 2026-05-13: surname extraction was lossy for Latin-script
    # diacritics (Hernández → Hernndez because é dropped, breaking the
    # journal_surface gate's "unreferenced citation" check). NFKD-fold
    # first so the accent → ASCII base (Hernández → Hernandez); same
    # for any other Latin-script source.
    surname = re.sub(
        r"[^A-Za-z-]", "", _ascii_fold(first_author.split()[-1]),
    )
    if not surname or _citation_placeholder_key(surname) in _GENERIC_AUTHOR_TOKENS:
        return _title_citation_from_metadata(meta, year_str)
    # A citation key must never begin lowercase (defense-in-depth if any glyph
    # still slips through the fold above).
    surname = surname[:1].upper() + surname[1:]
    return f"{surname} {year_str}"


# Common English function words kept lowercase inside a title-derived
# citation phrase. Domain-agnostic (biomedical, AI, business, any field) —
# used only to format the no-author title fallback below.
_TITLE_CONNECTORS: frozenset[str] = frozenset({
    "a", "an", "the", "of", "on", "in", "for", "and", "or", "to", "with",
    "by", "from", "at", "as", "vs", "versus", "into", "within", "among",
    "between", "during", "after", "before", "via",
})

_GENERIC_CITATION_PLACEHOLDERS: frozenset[str] = frozenset({
    "article", "evidence", "evidence receipt", "missing", "n a", "none",
    "receipt", "record", "reference", "report", "source", "unknown", "untitled",
})

_GENERIC_AUTHOR_TOKENS: frozenset[str] = frozenset({
    "trial", "study", "group", "committee", "collaborators",
    "collaboration", "investigators", "officers", "coordinators",
}) | _GENERIC_CITATION_PLACEHOLDERS


def _citation_placeholder_key(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _title_citation_from_metadata(meta: dict, year_str: str) -> str | None:
    """Fallback for abstract-only hits with no author metadata.

    Closed-access DOI/HIT records often carry title+year but no parsed
    authors. A title-derived token beats leaking an internal handle into
    public prose — but it must read as a TITLE, not a fabricated surname:
    a lone leading word ("Impact 2025", "Effect 2025") is indistinguishable
    from an author-year cite. So emit a short multi-word title phrase
    ("Impact of Intermittent Fasting 2025"), capped at the third content
    word, connectors preserved. Universal across domains — no word list.
    """
    title = str(meta.get("title") or "").strip()
    if _citation_placeholder_key(title) in _GENERIC_CITATION_PLACEHOLDERS:
        return None
    # A parenthesised study/trial acronym is a recognised short name.
    for acronym in re.findall(r"\(([A-Z][A-Z0-9-]{2,})\)", title):
        return f"{acronym.split('-', 1)[0]} {year_str}"
    phrase: list[str] = []
    content = 0
    for word in re.findall(r"[A-Za-z][A-Za-z'’\-]*", title):
        connector = word.lower() in _TITLE_CONNECTORS
        if connector and not phrase:
            continue  # never lead with an article / preposition
        phrase.append(word.lower() if connector else _smart_title(word.strip("-")))
        content += 0 if connector else 1
        if content >= 3:
            break
    while phrase and phrase[-1].lower() in _TITLE_CONNECTORS:
        phrase.pop()  # never end on a connector
    return f"{' '.join(phrase)} {year_str}" if phrase else None


def _safe_variants_across_registry(
    registry: dict[str, CitationEntry],
) -> list[tuple[str, str, str]]:
    """Build [(variant, body_citation, year)] triples across the whole
    registry, with cross-receipt collision detection AND a year-lookahead
    self-substitution guard.

    A variant is SAFE only when it's a prefix of EXACTLY ONE receipt's
    id (no cross-receipt ambiguity).

    For variants that ARE substrings of their own body_citation
    (e.g. `Walton` is a substring of `Walton 2019`; `PMC12978362`
    is a substring of `PMC12978362 2026`), the substitution uses a
    negative-year-lookahead regex so:
      - `(Walton)` → `(Walton 2019)` (bare → decorated)
      - `(Walton 2019)` → unchanged (already has year)
    Pre-fix this branch was dropped entirely, leaving bare PMCID
    handles in body prose untouched — the 96 PMCID leaks in the
    latest E2E paper.

    Returns triples; the empty `year` string signals "use plain
    str.replace, no lookahead needed"."""
    variant_to_owners: dict[str, set[str]] = {}
    for receipt_id in registry:
        for v in _variants_for(receipt_id):
            variant_to_owners.setdefault(v, set()).add(receipt_id)
    triples: list[tuple[str, str, str]] = []
    for v, owners in variant_to_owners.items():
        if len(owners) != 1:
            continue
        (rid,) = owners
        body_citation = registry[rid].body_citation
        if v not in body_citation:
            triples.append((v, body_citation, ""))
            continue
        # Variant is a substring of body_citation. Try the year-
        # lookahead path: only safe if body_citation has the shape
        # `<variant> <year>` so we can negative-lookahead the year.
        year = _year_suffix_after(v, body_citation)
        if year:
            triples.append((v, body_citation, year))
        # else: variant is contained in body_citation in some other
        # shape (e.g. `Walton` inside `Walton et al. 2019`) — drop it
        # because the lookahead pattern wouldn't be unambiguous.
    return triples


def _year_suffix_after(variant: str, body_citation: str) -> str:
    """If body_citation ends with `<variant> <YYYY>`, return the year
    string. Otherwise empty. Used for the negative-year-lookahead
    substitution path."""
    if not body_citation.startswith(variant):
        return ""
    rest = body_citation[len(variant):]
    if m := re.match(r"\s+(\d{4})$", rest):
        return m.group(1)
    return ""


def _variants_for(receipt_id: str) -> list[str]:
    """Generate prefix variants of a receipt_id that could appear as
    leaks in body prose. Two families: underscore-segment prefixes
    (the writer often drops trailing tokens) and character-truncation
    forms (the writer sometimes hard-truncates at 20/25/30).

    P2 reviewer fix: floor lowered to 5 chars to cover short surnames
    (Wu, Li, He, Yu — common Chinese surnames). The cross-receipt
    collision check in `_safe_variants_across_registry` ensures short
    variants don't blast across unrelated receipts."""
    if not receipt_id:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        if v and len(v) >= 5 and v not in seen:
            seen.add(v)
            out.append(v)

    # Underscore-segment prefixes: full → drop one trailing segment → ...
    parts = receipt_id.split("_")
    for i in range(len(parts), 0, -1):
        _add("_".join(parts[:i]))
    # Character-truncation variants the writer sometimes produces.
    for length in (30, 25, 20, 18, 15, 12, 10):
        _add(receipt_id[:length])
    return out


def substitute_receipt_ids(
    paper_md: str, registry: dict[str, CitationEntry],
) -> str:
    """Substitute every receipt_id leak in the paper with its body_
    citation. Belt-and-braces backstop for the upstream substitution
    in the writer-input transform.

    Two substitution paths:
      1. Plain str.replace for variants NOT contained in body_citation
         (e.g. `Walton_2019_MASTERS` → `Walton 2019`).
      2. Regex with negative-year-lookahead for variants contained in
         body_citation in `<variant> <year>` shape (e.g.
         `PMC12978362` → `PMC12978362 2026` only when the year is NOT
         already present — preventing `PMC12978362 2026 2026`).

    Cross-receipt collision detection drops ambiguous variants. Sorted
    longest-first within the safe set."""
    triples = _safe_variants_across_registry(registry)
    triples.sort(key=lambda t: -len(t[0]))
    out = paper_md
    for variant, body_citation, year in triples:
        if not year:
            out = out.replace(variant, body_citation)
        else:
            # Negative-year-lookahead: substitute the variant ONLY when
            # NOT already followed by ` <year>`. Avoids the double-apply
            # `(Walton 2019)` → `(Walton 2019 2019)` regression.
            pattern = re.compile(
                rf"{re.escape(variant)}(?!\s+{re.escape(year)})"
            )
            out = pattern.sub(body_citation, out)
    return out


def transform_receipts_for_writer(
    receipts: list, registry: dict[str, CitationEntry],
) -> list:
    """Rewrite each receipt's receipt_id to its body_citation BEFORE
    the writer sees the list. The writer's prompt builder iterates
    over receipts and emits receipt_id verbatim — by the time the
    writer reads a receipt, its receipt_id is already a clean
    body_citation token, not an internal handle.

    Returns NEW ReceiptSummary instances (frozen dataclass — can't
    mutate). Original receipts list is untouched for downstream uses
    (manifest, References block).

    IMPORTANT: callers MUST also call `transform_matrix_for_writer`
    on any TensionMatrix derived from these receipts. The matrix
    holds its own `receipts` field AND each Tension references
    `receipt_a_id`/`receipt_b_id` strings — those need rewriting
    in lockstep, otherwise the writer's anchor-validator sees
    transformed receipt_ids in writer_receipts but original handles
    in matrix.receipts and trips invariant checks."""
    transformed: list = []
    for r in receipts:
        rid = getattr(r, "receipt_id", "")
        entry = registry.get(rid)
        if entry is None:
            transformed.append(r)
            continue
        transformed.append(
            dataclasses.replace(r, receipt_id=entry.body_citation)
        )
    return transformed


def transform_matrix_for_writer(matrix, registry: dict[str, CitationEntry]):
    """Rewrite a TensionMatrix's `receipts` AND every `Tension`'s
    `receipt_a_id` / `receipt_b_id` to use body_citation strings.
    Pairs lockstep with `transform_receipts_for_writer`.

    Returns a NEW TensionMatrix (frozen) with rewritten receipts
    and pairs. Original matrix is untouched.

    Returns matrix unchanged when registry has no matching receipt
    (defensive — should not happen if matrix was built from the same
    receipts that built the registry)."""
    new_receipts = transform_receipts_for_writer(
        list(matrix.receipts), registry,
    )
    new_pairs = []
    for pair in matrix.pairs:
        a_entry = registry.get(pair.receipt_a_id)
        b_entry = registry.get(pair.receipt_b_id)
        new_a = a_entry.body_citation if a_entry else pair.receipt_a_id
        new_b = b_entry.body_citation if b_entry else pair.receipt_b_id
        # Fix #21 follow-up: the Tension's `summary` string contains
        # the raw receipt_a_id and receipt_b_id verbatim (built by
        # build_tension_matrix in run_v06_synthesis.py). When that
        # summary surfaces in the writer-facing tables (Table 3),
        # the raw paper-ID handles trip Q3 leak detection. Rewrite
        # every raw receipt_id substring in the summary to its
        # body_citation form too.
        new_summary = pair.summary
        for raw_id, entry in registry.items():
            if raw_id in new_summary:
                new_summary = new_summary.replace(raw_id, entry.body_citation)
        new_pairs.append(dataclasses.replace(
            pair, receipt_a_id=new_a, receipt_b_id=new_b,
            summary=new_summary,
        ))
    return dataclasses.replace(
        matrix,
        receipts=tuple(new_receipts),
        pairs=tuple(new_pairs),
    )
