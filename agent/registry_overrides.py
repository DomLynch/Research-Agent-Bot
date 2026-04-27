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
registry override lookup ignores the abstract entirely; it consults the
registry id alone. This is the second layer of defense for planted-failure
case 1 (the topic_pack alias whitelist already provides the first).
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


def lookup_override(source: Source, pack: TopicPack | None) -> OverrideRecord | None:
    """Return the pinned override for a Source, or None.

    Lookup precedence:
      1. NCT (`source.nct`) — primary registry id for clinicaltrials.gov
      2. ISRCTN — only if `source.url` carries the marker `ISRCTN`. We do
         not have a dedicated ISRCTN field on Source; it's encoded in URL
         for the V1.1 retrieval adapters.

    Returns None if:
      - pack is None (caller didn't load a topic pack)
      - source has no NCT and no ISRCTN-bearing URL
      - the registry id is not in the pack's known_role_overrides table

    None means: fall through to role_classifier.classify_role with the
    abstract as input. The override is opt-in by registry hit, not a
    requirement.
    """
    if pack is None:
        return None

    # NCT takes precedence — most clinicaltrials.gov hits arrive with
    # source.nct populated by the adapter.
    if source.nct:
        record = pack.lookup_role_override(source.nct)
        if record is not None:
            return record

    # ISRCTN fallback: registry id is encoded in the URL by retrieve.py
    # because Source has no dedicated isrctn field. _extract_isrctn uses a
    # regex requiring digits after the prefix so the literal `ISRCTN` in
    # the `isrctn.com` domain doesn't match.
    if source.url:
        isrctn_id = _extract_isrctn(source.url)
        if isrctn_id is not None:
            record = pack.lookup_role_override(isrctn_id)
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
