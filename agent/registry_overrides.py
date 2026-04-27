"""Registry-pinned role overrides — the moat layer.

Hard rule, posted at top of compiler.py and every relevant prompt:
  LLM PROPOSES. CODE DISPOSES.
  - Role assignment: registry override > deterministic abstract classifier. Never LLM.

This module is the "registry override > deterministic abstract classifier"
edge of that hard rule. It checks a Source's registry id (NCT or ISRCTN)
against a TopicPack's `known_role_overrides` table BEFORE any abstract
classifier runs. A hit pins role/design/tier irrevocably; the LLM never
sees this layer, and even the deterministic classifier in
role_classifier.py is bypassed when an override hits.

Why this matters for Proof 001 metformin: a TAME (NCT04264897) abstract
literally describes a registered protocol — phrases like "designed to test"
and "primary composite endpoint" — but a malicious or hand-edited
submission could rewrite the abstract to read like results prose. The
registry override lookup ignores the abstract for role assignment; it
consults the registry id alone. This is the second layer of defense for
planted-failure case 1 (the topic_pack alias whitelist already provides
the first).

Day 3.0 — abstract-NCT-scan addition (live-smoke finding 2026-04-27):
PubMed/OpenAlex routinely return papers with the trial NCT in the
abstract (e.g., "ClinicalTrials.gov Identifier: NCT02308228") rather than
in any structured field. The dedup-merge pathway in retrieve.py promotes
NCT-in-abstract to source.nct ONLY when ClinicalTrials.gov also returned
the same NCT for the topic query — when CT.gov's query semantics miss
the trial, the merge doesn't fire, and the OpenAlex paper carries
source.nct=None even though MASTERS' NCT is plainly in its abstract.
The live smoke caught this for MASTERS (NCT02308228); fixture replay
didn't because the captured CT.gov fixture had MASTERS in it.

Fix: lookup_override now scans `abstract` for NCT/ISRCTN patterns AFTER
the source.nct + source.url checks. Pure additive change — same hits as
before still fire on source.nct; new hits fire when the registry id is
only in the abstract. Discriminating regression test:
test_master_pinned_via_nct_in_abstract.
"""
from __future__ import annotations

import re

from agent.topic_pack import OverrideRecord, TopicPack
from agent.types import Source

__all__ = ["lookup_override"]

# Match `ISRCTN` followed by 1+ digits, case-insensitive. Required because
# the same string `ISRCTN` appears in the domain `isrctn.com` (no digits
# after) — the V1.1 idiom of `find("ISRCTN")` matched the domain and
# returned the wrong slice. The regex requires at least one digit after the
# prefix, so domain matches are rejected.
_ISRCTN_RE = re.compile(r"ISRCTN(\d+)", re.IGNORECASE)

# Match standard NCT ids: literal `NCT` followed by exactly 8 digits, with
# word boundaries so `NCT01765946abc` doesn't match as a long id. Used to
# scan abstracts for trial registrations not already in source.nct.
_NCT_RE = re.compile(r"\bNCT\d{8}\b")


def lookup_override(
    source: Source,
    pack: TopicPack | None,
    abstract: str = "",
) -> OverrideRecord | None:
    """Return the pinned override for a Source, or None.

    Lookup precedence (each step short-circuits on a hit):
      1. NCT (`source.nct`) — primary registry id for clinicaltrials.gov
         hits; the adapter normally populates this.
      2. ISRCTN-in-URL — only if `source.url` carries the marker `ISRCTN`.
         Source has no dedicated ISRCTN field; the V1.1 retrieval adapters
         encode it in URL.
      3. NCT/ISRCTN in `abstract` — Day 3.0 addition. PubMed and OpenAlex
         routinely return papers with the trial registry id only in the
         abstract text (e.g., "ClinicalTrials.gov Identifier: NCT02308228")
         rather than in any structured field. Without this scan, the live
         retrieval misses canonical-trial overrides whenever the
         dedup-merge with CT.gov doesn't fire.

    Returns None if:
      - pack is None (caller didn't load a topic pack)
      - source has no NCT, no ISRCTN-URL, and no NCT/ISRCTN in abstract
      - none of the above ids are in the pack's known_role_overrides table

    None means: fall through to role_classifier.classify_role with the
    abstract as input. The override is opt-in by registry hit, not a
    requirement.
    """
    if pack is None:
        return None

    # 1. NCT in source.nct — most clinicaltrials.gov adapter results.
    if source.nct:
        record = pack.lookup_role_override(source.nct)
        if record is not None:
            return record

    # 2. ISRCTN in source.url — V1.1 adapters encode ISRCTN ids in URLs.
    if source.url:
        isrctn_id = _extract_isrctn(source.url)
        if isrctn_id is not None:
            record = pack.lookup_role_override(isrctn_id)
            if record is not None:
                return record

    # 3. NCT or ISRCTN in abstract — Day 3.0 addition.
    if abstract:
        for nct_match in _NCT_RE.findall(abstract):
            record = pack.lookup_role_override(nct_match)
            if record is not None:
                return record
        for isrctn_match in _ISRCTN_RE.findall(abstract):
            record = pack.lookup_role_override(f"ISRCTN{isrctn_match}")
            if record is not None:
                return record

    return None


def _extract_isrctn(url: str) -> str | None:
    """Extract an ISRCTN registry id from a URL.

    Returns the canonical uppercase form (`ISRCTN29932357`) when the URL
    contains an `ISRCTN` literal followed by digits. Returns None when no
    such pattern matches.

    Why not a string find: the literal `ISRCTN` also appears in the domain
    `isrctn.com`, where there are no trailing digits. A naive find would
    match the domain and return None (or worse, the wrong slice). The
    regex requires `\\d+` after the prefix, so the domain match is skipped
    and the registry-id match is found.
    """
    match = _ISRCTN_RE.search(url)
    if match is None:
        return None
    digits = match.group(1)
    return f"ISRCTN{digits}"
