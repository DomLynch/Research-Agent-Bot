"""Per-source advanced query translators — Slice 6 step 3
(Wave 7 cont., 2026-05-05).

Consumes a RetrievalSpec (from topic_pack.[retrieval] block) and
emits per-source query strings tailored to each adapter's native
syntax. The 5-class corpus classifier remains the FINAL winnowing
layer — these queries do the calibrated retrieval that produces a
focused candidate pool (3-8K papers) instead of naive trawls of
60-200K.

Per-source dialects supported:
  pubmed       MeSH + [tiab] + [pt] + [lang] + [dp]
  europepmc    KW: + PUB_TYPE: + LANG: + PUB_YEAR:[a TO b]
  openalex     plain keyword query (filter dict handled separately)
  crossref     plain keyword query (filter dict handled separately)
  fallback     simple boolean keyword query

Universal across topics + domains. Pure-Python; no IO, no LLM.
"""
from __future__ import annotations

from agent.topic_pack import RetrievalSpec


def _quote_if_phrase(term: str) -> str:
    """Quote multi-word terms so the source's parser treats them
    as a phrase, not separate ANDed words."""
    t = term.strip()
    if not t:
        return ""
    if " " in t and not (t.startswith('"') and t.endswith('"')):
        return f'"{t}"'
    return t


def _or_group(
    terms: tuple[str, ...], *, field_tag: str = "",
    quote: bool = True,
) -> str:
    """Return `(t1[tag] OR t2[tag] OR ...)`. Empty input → empty
    string so the caller can omit the conjunct cleanly."""
    if not terms:
        return ""
    quoted = [
        (_quote_if_phrase(t) if quote else t.strip())
        for t in terms
    ]
    formatted = [
        f"{q}{field_tag}" if field_tag else q
        for q in quoted if q
    ]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    return "(" + " OR ".join(formatted) + ")"


# ---------- PubMed ---------------------------------------------------

def build_pubmed_query(spec: RetrievalSpec) -> str:
    """Compose a PubMed advanced-search string using [tiab] field
    tags + [pt] publication-type filters + humans[MeSH] +
    "YYYY"[dp] range. Each conjunct is omitted when its source
    field on the spec is empty.

    Example output for rapamycin:
      (rapamycin[tiab] OR sirolimus[tiab] OR ...)
      AND (aging[tiab] OR longevity[tiab] OR ...)
      AND (clinical trial[pt] OR cohort study[pt] OR ...)
      AND humans[MeSH] AND English[lang]
      AND ("2010"[dp] : "2026"[dp])
      NOT ("transplant rejection"[tiab] OR ...)
    """
    parts: list[str] = []
    if spec.topic_terms:
        parts.append(_or_group(spec.topic_terms, field_tag="[tiab]"))
    if spec.scope_terms:
        parts.append(_or_group(spec.scope_terms, field_tag="[tiab]"))
    if spec.evidence_types:
        parts.append(_or_group(spec.evidence_types, field_tag="[pt]"))
    for sp in spec.species:
        parts.append(f"{sp.lower()}[MeSH]")
    for lang in spec.languages:
        parts.append(f"{lang}[lang]")
    if spec.date_from or spec.date_to:
        a = spec.date_from or 1900
        b = spec.date_to or 2100
        parts.append(f'("{a}"[dp] : "{b}"[dp])')
    main = " AND ".join(p for p in parts if p)
    if spec.exclude_terms:
        excl = _or_group(spec.exclude_terms, field_tag="[tiab]")
        if excl:
            main = f"{main} NOT {excl}" if main else f"NOT {excl}"
    return main


# ---------- Europe PMC ----------------------------------------------

def build_europepmc_query(spec: RetrievalSpec) -> str:
    """Compose a Europe PMC query.

    Europe PMC's default field search hits title + abstract +
    keywords + body — that's what we want for free-text terms. The
    explicit `KW:` field tag is a strict CONTROLLED-VOCABULARY match
    that would drop ~7x of relevant hits (verified live: rapamycin
    KW: 175, no-tag: 1178). So topic + scope + exclude terms run
    bare; only structural filters (PUB_TYPE / LANG / PUB_YEAR /
    HAS_HUMAN_AVAILABLE) carry tags."""
    parts: list[str] = []
    if spec.topic_terms:
        parts.append(_or_group(spec.topic_terms))
    if spec.scope_terms:
        parts.append(_or_group(spec.scope_terms))
    if spec.evidence_types:
        parts.append(_or_group(
            tuple(
                f'PUB_TYPE:"{t.strip()}"' for t in spec.evidence_types
            ),
            field_tag="", quote=False,
        ))
    for sp in spec.species:
        if sp.strip().lower() == "humans":
            parts.append("HAS_HUMAN_AVAILABLE:Y")
    for lang in spec.languages:
        # Europe PMC uses ISO code: eng / fre / ger ...
        code = "eng" if lang.lower().startswith("en") else lang.lower()[:3]
        parts.append(f"LANG:{code}")
    if spec.date_from or spec.date_to:
        a = spec.date_from or 1900
        b = spec.date_to or 2100
        parts.append(f"PUB_YEAR:[{a} TO {b}]")
    main = " AND ".join(p for p in parts if p)
    if spec.exclude_terms:
        excl = _or_group(spec.exclude_terms)
        if excl:
            main = f"{main} NOT {excl}" if main else f"NOT {excl}"
    return main


# ---------- Generic / OpenAlex / Crossref ----------------------------

def build_keyword_query(spec: RetrievalSpec) -> str:
    """Plain boolean keyword query for sources that don't accept
    field tags in the URL `q=` param (OpenAlex search, Crossref
    query, Semantic Scholar). Filters like date range and
    publication type are passed via separate URL params at the
    adapter level — this string carries the topic + scope intent."""
    parts: list[str] = []
    if spec.topic_terms:
        parts.append(_or_group(spec.topic_terms))
    if spec.scope_terms:
        parts.append(_or_group(spec.scope_terms))
    main = " AND ".join(p for p in parts if p)
    if spec.exclude_terms:
        excl = _or_group(spec.exclude_terms)
        if excl:
            main = f"{main} NOT {excl}" if main else f"NOT {excl}"
    return main


# ---------- Dispatcher -----------------------------------------------

_BUILDERS = {
    "pubmed": build_pubmed_query,
    "europepmc": build_europepmc_query,
    "openalex": build_keyword_query,
    "crossref": build_keyword_query,
    "semantic_scholar": build_keyword_query,
    "biorxiv": build_keyword_query,
    "medrxiv": build_keyword_query,
    "doaj": build_keyword_query,
    "openaire": build_keyword_query,
    "core": build_keyword_query,
    "pmc_oai": build_keyword_query,
    "arxiv": build_keyword_query,
    "clinicaltrials": build_keyword_query,
    "unpaywall": build_keyword_query,
    "chembl": build_keyword_query,
    "researka_database": build_keyword_query,
}


def build_query_for_source(
    source_name: str, spec: RetrievalSpec,
) -> str:
    """Return the source's native query format. Unknown source →
    falls through to the simple boolean keyword query (back-compat
    + safe default)."""
    builder = _BUILDERS.get(source_name.lower(), build_keyword_query)
    return builder(spec)


__all__ = [
    "build_pubmed_query",
    "build_europepmc_query",
    "build_keyword_query",
    "build_query_for_source",
]
