"""Deterministic claim-strength repair pass for writer/audit gates."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from agent.synthesis_schemas import ReceiptSummary

__all__ = ["ClaimStrengthRepair", "repair_abstract_claim_strength", "repair_claim_strength", "REPAIR_PREFIX"]

# Pre-pended to violating sentences. Contains "suggests" which Q10's
# hedge regex matches, AND "evidence suggests" as a fuller phrase.
REPAIR_PREFIX = "Evidence suggests that "
# Day 10.17 Fix B contract: REPAIR_PREFIX must stay in lockstep with
# `_Q11_REPAIR_MARKER` in agent/synthesis_audit_q8q9q10.py — Q11
# scans the rendered body for this exact byte sequence to count
# repairs. If you change this string, change Q11's marker too AND
# regenerate any pinned audit JSON in tests.
REPAIR_INLINE_HEDGE = " (potentially)"
# Inline hedge for healthspan-claim repairs — same lockstep contract.
# Q11 also counts this string in the body.


@dataclass(frozen=True, slots=True)
class ClaimStrengthRepair:
    """One audit-log entry per repaired sentence."""
    original: str
    repaired: str
    receipt_ids: tuple[str, ...]
    triggering_verb: str


# Mirror of Q10's verb pattern. Kept in lockstep deliberately rather
# than imported (cycle: audit imports nothing from paper_writer side).
# If Q10's _Q10_CAUSAL_RE changes, update here too.
_REPAIR_CAUSAL_RE = re.compile(
    r"\b(?:improves?|causes?|drives?|explains?|"
    r"demonstrates?|confirms?|proves?|robust|potent)\b",
    re.IGNORECASE,
)
# Day 10.17 Fix B v2 — also trigger on Q5's healthspan-claim phrases.
# Initial Fix B fired only on Q10 causal verbs, missing sentences
# like "...metformin's geroprotective potential..." that have no
# Q10 verb but trigger Q5. The repair-prefix "Evidence suggests
# that " contains "suggests" which is also one of Q5's hedge tokens,
# so the same prefix patches both checks. Mirrors Q5's
# _HEALTHSPAN_CLAIMS in agent/synthesis_audit.py.
_REPAIR_HEALTHSPAN_RE = re.compile(
    # Day 10.17 Phase 0 reviewer fix: word-boundary anchored. Pre-fix
    # the regex matched "longevity benefit" inside "longevity
    # benefits" and produced visible "(potentially)s" artifact when
    # the inline insertion ran. Now matches the full word(s) with
    # optional plural; longest pattern wins (lifespan before life)
    # so we don't accidentally short-match.
    r"(?:\bextends?\s+lifespan\b|"
    r"\blongevity\s+benefits?\b|"
    r"\bincreases?\s+healthspan\b|"
    r"\bgeroprotective\b|"
    r"\bextends?\s+life\b)",
    re.IGNORECASE,
)
# Mirror of Q10's hedge set. Same lockstep contract.
_REPAIR_HEDGES = (
    " may ", " might ", " could ", " appears to",
    " evidence suggests", " suggests",
    " consistent with", " associated with",
    " has been proposed", " in this corpus", " we interpret ",
    " hypothesized", " preliminary",
    " remains to be confirmed", " is not yet established",
)
# Receipt-id token shape. Mirrors Q9 / Q10's pattern.
_REPAIR_RECEIPT_ID_RE = re.compile(
    r"\b[a-z]+(?:-[a-z0-9]+){3,}\b", re.IGNORECASE,
)
# Splits markdown body into sentences. Same shape as Q10's regex.
_REPAIR_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")
# Strip _Cited: footer lines BEFORE scanning so the sentence regex
# doesn't absorb citation metadata into surrounding prose. Mirrors
# Q10's same fix from Phase 1.5.
_REPAIR_CITED_FOOTER_RE = re.compile(
    r"^\s*_Cited:.*_\s*$", re.MULTILINE,
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def _has_hedge(sentence: str) -> bool:
    sentence_norm = _normalize(sentence)
    return any(h.strip() in sentence_norm for h in _REPAIR_HEDGES)


def repair_abstract_claim_strength(body_md: str) -> tuple[str, int]:
    repaired = body_md
    replacements = (
        (r"\bpositive signals\b", "context-specific signals"),
        (r"\b[Dd]emonstrated\s+(?:in|by)\b", "suggested by"),
        (r"(?<!not yet )(?<!not )(?<!cannot )\b[Ee]stablish(?:es|ed)?\b", "is consistent with"),
        (r"(?<!not yet )(?<!not )(?<!cannot )\b[Pp]rove(?:s|d)?\b", "is consistent with"),
        (r"(?<!not yet )(?<!not )(?<!cannot )\b[Cc]onfirm(?:s|ed)?\b", "is consistent with"),
        (r"\bsupport(?:s|ed)? biological plausibility for\b", "are consistent with biological plausibility but do not establish"),
        (r"\bIn a preclinical model,\s*", "In preclinical evidence, "),
        (r"\b[Rr]obust\s+(effects?|benefits?|signals?)\b", r"context-dependent \1"),
        (r"\bclinical signals justify\b", "clinical signals can motivate"),
        (r"\bjustify further targeted testing\b", "can motivate further targeted testing"),
        (r"\bremains a bounded geroscience case\b", "should be treated as a bounded evidence hypothesis"),
        (r"\battenuated\b", "was reported to attenuate"),
        (r"\bmodulated\b", "was reported to modulate"),
    )
    for pattern, repl in replacements:
        repaired = re.sub(pattern, repl, repaired, flags=re.IGNORECASE)
    return repaired, int(repaired != body_md)


def repair_claim_strength(
    body_md: str,
    accepted: Sequence[ReceiptSummary],
) -> tuple[str, list[ClaimStrengthRepair]]:
    weak_ids = {
        r.receipt_id for r in accepted
        if (r.evidence_tier or "").upper() == "C"
        or r.directness in ("mechanistic", "indirect")
        # A receipt the evidence table coded null/unclear/mixed does not
        # support a single asserted direction — a causal/directional verb
        # anchored to it overclaims against the paper's own table (the
        # dominant reviewer revise ask). null/unclear carry no direction;
        # `mixed` has findings in BOTH directions, so asserting one is also
        # an overclaim. Hedge like any other weak anchor. Universal: keyed
        # on the coded effect_direction, no topic-specific assumptions.
        or str(r.effect_direction or "").lower() in ("null", "unclear", "mixed")
    }
    # Note: we deliberately do NOT short-circuit on empty weak_ids.
    # Q5 healthspan-claim violations can fire on prose with no
    # tier-C citations at all (the LLM might write "metformin's
    # geroprotective potential" in Background without citing).

    repairs: list[ClaimStrengthRepair] = []

    # Scan only the prose body, NOT the _Cited: footers (those would
    # false-positive on receipt IDs that happen to include numerics
    # or repeated content).
    def _maybe_repair(match: re.Match[str]) -> str:
        sentence = match.group(0)
        if _has_hedge(sentence):
            return sentence
        cited_in_sentence = {
            tok.group(0)
            for tok in _REPAIR_RECEIPT_ID_RE.finditer(sentence)
        }
        causal_match = _REPAIR_CAUSAL_RE.search(sentence)
        causal_violation = (
            causal_match is not None
            and bool(cited_in_sentence & weak_ids)
        )
        healthspan_match = _REPAIR_HEALTHSPAN_RE.search(sentence)
        if not causal_violation and healthspan_match is None:
            return sentence

        # Two repair strategies, picked by violation type:
        #   - Causal-verb violations (Q10): prepend "Evidence suggests
        #     that " to the sentence. The Q10 hedge regex scans the
        #     whole sentence so a sentence-prefix is sufficient.
        #   - Healthspan-claim violations (Q5): Q5 only looks at an
        #     80-char window around the trigger term, so the hedge
        #     MUST be inserted adjacent to the term, not at the
        #     sentence start. We insert " (potentially) " right after
        #     the matched term — "potentially" is in Q5's hedge set
        #     and the parenthetical reads cleanly.
        if healthspan_match is not None and not causal_violation:
            term = healthspan_match.group(0)
            inline_repair = f"{term}{REPAIR_INLINE_HEDGE}"
            repaired = (
                sentence[:healthspan_match.start()]
                + inline_repair
                + sentence[healthspan_match.end():]
            )
            triggering = term
        else:
            leading_ws = sentence[: len(sentence) - len(sentence.lstrip())]
            body = sentence.lstrip()
            # Day 10.17 Fix B reviewer fix: preserve acronym case
            # (AMPK, mTOR, GDF15). Only down-case the first letter
            # when the second character is also lowercase — that
            # avoids "AMPK demonstrates..." → "aMPK demonstrates..."
            # while still smoothing "Metformin extends..." →
            # "metformin extends..." after the prefix.
            if (
                len(body) >= 2
                and body[0].isupper()
                and body[1].islower()
            ):
                body = body[0].lower() + body[1:]
            repaired = f"{leading_ws}{REPAIR_PREFIX}{body}"
            triggering = (
                causal_match.group(0) if causal_match
                else (healthspan_match.group(0) if healthspan_match else "")
            )
        repairs.append(ClaimStrengthRepair(
            original=sentence.strip(),
            repaired=repaired.strip(),
            receipt_ids=tuple(sorted(cited_in_sentence & weak_ids)),
            triggering_verb=triggering,
        ))
        return repaired

    # The repair regex must NOT match content inside _Cited: footers,
    # so we mask those during the scan and restore them afterward.
    footers: list[str] = []

    def _stash_footer(m: re.Match[str]) -> str:
        footers.append(m.group(0))
        return f"\x00FOOTER{len(footers) - 1}\x00"

    masked = _REPAIR_CITED_FOOTER_RE.sub(_stash_footer, body_md)
    repaired_masked = _REPAIR_SENTENCE_RE.sub(_maybe_repair, masked)

    def _restore_footer(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return footers[idx]

    repaired_body = re.sub(
        r"\x00FOOTER(\d+)\x00", _restore_footer, repaired_masked,
    )
    return repaired_body, repairs
