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

__all__ = ["lookup_override", "resolve_override"]

# Match `ISRCTN` followed by 1+ digits, case-insensitive. Required because
# the same string `ISRCTN` appears in the domain `isrctn.com` (no digits
# after) — the V1.1 idiom of `find("ISRCTN")` matched the domain and
# returned the wrong slice. The regex requires at least one digit after the
# prefix, so domain matches are rejected.
_ISRCTN_RE = re.compile(r"ISRCTN(\d+)", re.IGNORECASE)

# Match standard NCT ids: literal `NCT` followed by exactly 8 digits, with
# word boundaries so `NCT01765946abc` doesn't match as a long id. Used to
# scan abstracts for trial registrations not already in source.nct.
# Case-insensitive: lowercase `nct…` and mixed-case `NcT…` are valid PubMed
# / OpenAlex outputs and must hit the override; pack.lookup_role_override
# normalizes its input to uppercase before the dict lookup.
_NCT_RE = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)


def lookup_override(source: Source, pack: TopicPack | None,
                    abstract: str = "") -> OverrideRecord | None:
    """Return one unambiguous pinned override across structured and declared IDs."""
    return resolve_override(source, pack, abstract=abstract)[0]


def resolve_override(source: Source, pack: TopicPack | None,
                     abstract: str = "") -> tuple[OverrideRecord | None, bool]:
    """Return the override and whether known registry identities conflict."""
    if pack is None:
        return None, False

    structured_ids: set[str] = set()
    if source.nct:
        structured_ids.add(source.nct.upper())

    if source.url:
        isrctn_id = _extract_isrctn(source.url)
        if isrctn_id is not None:
            structured_ids.add(isrctn_id)

    declared_ids: set[str] = set()
    if abstract:
        registration_context = re.compile(
            r"(?:clinicaltrials\.gov(?:\s+(?:identifier|registration|number))?\s*:|"
            r"clinicaltrials\.gov\s+(?:identifier|registration|number)|"
            r"(?:trial\s+)?(?:registered|registration)\s*(?::\s*|(?:as|number)\s*)?|"
            r"registration\s+(?:identifier|number))",
            re.I,
        )
        declared_ids = {
            identifier.upper()
            for match in registration_context.finditer(abstract)
            for identifier in (
                *_NCT_RE.findall(abstract[match.start():match.end() + 120]),
                *(f"ISRCTN{value}" for value in _ISRCTN_RE.findall(
                    abstract[match.start():match.end() + 120]
                )),
            )
        }
    identities = structured_ids | declared_ids
    matches = {
        identifier: record for identifier in sorted(identities)
        if (record := pack.lookup_role_override(identifier)) is not None
    }
    # Every supplied identity must resolve, and all resolutions must agree.
    # A known ID beside an unknown or conflicting ID is ambiguous.
    if len(identities) == 1 and matches.keys() == identities:
        return next(iter(matches.values())), False

    return None, bool(matches)


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
