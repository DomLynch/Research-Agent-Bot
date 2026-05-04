"""Universal corpus quality filter — flag off-topic mechanistic noise.

Reads a topic's parsed/<paper>.paper_sections.json files and returns
the SET of paper_ids that should be deprioritized to "background_only"
(kept in the corpus for context, excluded from primary synthesis).

Heuristic (conservative — false positives are worse than false
negatives):

A paper is OFF-TOPIC if BOTH conditions hold:
  1. Its title + abstract contains an off-topic mechanistic marker
     (TBI / burn wound / in vitro only / rodent only / unrelated
     condition like cardioversion or empagliflozin), AND
  2. Its title + abstract does NOT mention any keyword derived from
     the topic pack's expected_evidence_slots, AND
  3. Its title + abstract does NOT contain a clinical-effect signal
     (RCT, cohort, mortality, primary/secondary prevention, etc.).

When in doubt, KEEP the paper. The filter never rejects a paper that
shows ANY clinical signal, because the cost of losing real evidence
outweighs the cost of carrying mechanistic noise.

Usage (CLI):
    python scripts/corpus_filter.py \\
        --parsed-dir docs/quality-reference/statins/parsed \\
        --topic-pack topic_packs/statins.toml
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

__all__ = ["filter_corpus"]


# Off-topic markers — phrases that strongly suggest the paper is
# mechanistic/preclinical noise unrelated to the topic's clinical
# evidence base. Match is substring (lower-cased).
_OFF_TOPIC_MARKERS: tuple[str, ...] = (
    "traumatic brain injury",
    " tbi ",
    "tbi-",
    "burn wound",
    "burn injury",
    "cerebral cavernous malformation",
    "in vitro only",
    "yeast",
    "c. elegans",
    "drosophila",
    " mcf7",  # leading space — avoid matching "mcf7-derived"-style noise unintentionally? still substring
    "wistar rat",
    "wistar rats",
    "rodent model only",
    "preclinical mouse model",
    "juvenile rodent",
    "geriatric wistar",
    "cardioversion",
    "atrial fibrillation",
    "empagliflozin",
    "sglt2",
    "stroke patients",  # generic stroke-only, not statin-driven
    "neurovascular unit",
    "blood-brain barrier",
)

# Clinical-effect rescue lexicon — if ANY of these appears in
# title+abstract, we KEEP the paper regardless of mechanistic hits.
# This is the conservative safety net.
_CLINICAL_RESCUE: tuple[str, ...] = (
    "randomized clinical trial",
    "randomised clinical trial",
    "randomized controlled trial",
    "randomised controlled trial",
    " rct ",
    "(rct)",
    "cohort study",
    "case-control",
    "meta-analysis",
    "systematic review",
    "all-cause mortality",
    "cardiovascular mortality",
    "primary prevention",
    "secondary prevention",
    "cv events",
    "cardiovascular event",
    "mace",
    "incident cancer",
    "cancer mortality",
    "cancer incidence",
    "cancer survivors",
    "real-world evidence",
    "real world evidence",
    "trial emulation",
    "biobank",
    "national health insurance",
    "registry-based",
)


def _slot_to_keywords(slot: str) -> tuple[str, ...]:
    """Map an expected_evidence_slot to plausible title/abstract keywords.

    Universal mapping — no per-topic logic. Slots are typically
    ``snake_case`` semantic categories from the topic pack.
    """
    base = slot.lower().replace("_", " ")
    extras: list[str] = [base]
    if "rct" in slot or "trial" in slot:
        extras += ["randomized", "randomised", "trial"]
    if "observational" in slot:
        extras += ["cohort", "case-control", "registry"]
    if "mortality" in slot:
        extras += ["mortality", "death"]
    if "myopathy" in slot or "muscle" in slot or "sarcopenia" in slot:
        extras += ["myopathy", "myalgia", "muscle", "sarcopenia"]
    if "lifespan" in slot or "longevity" in slot:
        extras += ["lifespan", "longevity", "healthspan"]
    if "safety" in slot or "tolerability" in slot or "adverse" in slot:
        extras += ["adverse", "safety", "tolerability", "side effect"]
    if "primary_prevention" in slot:
        extras += ["primary prevention"]
    if "secondary_prevention" in slot:
        extras += ["secondary prevention"]
    if "cancer" in slot:
        extras += ["cancer", "neoplasm"]
    if "bleeding" in slot:
        extras += ["bleeding", "hemorrhage", "haemorrhage"]
    if "exercise" in slot:
        extras += ["exercise", "physical activity"]
    if "ongoing" in slot:
        extras += ["ongoing", "registered", "protocol"]
    return tuple(extras)


def _gather_text(paper: dict) -> str:
    """Concatenate title + abstract, lower-cased, padded for word-boundary."""
    title = paper.get("title") or ""
    abstract = (paper.get("sections") or {}).get("abstract") or ""
    return f" {title} {abstract} ".lower()


def filter_corpus(parsed_dir: Path, topic_pack_path: Path) -> set[str]:
    """Return the set of paper_ids to mark background_only.

    Conservative — emits a paper_id only if it's mechanistic AND has
    no topic-keyword hit AND no clinical-effect rescue hit.
    """
    if not parsed_dir.exists() or not parsed_dir.is_dir():
        return set()

    pack_data = tomllib.loads(topic_pack_path.read_text(encoding="utf-8"))
    slots: tuple[str, ...] = tuple(pack_data.get("expected_evidence_slots", ()))
    aliases: tuple[str, ...] = tuple(
        a.lower() for a in pack_data.get("aliases", ()) if isinstance(a, str)
    )
    topic_keywords: set[str] = set()
    for slot in slots:
        for kw in _slot_to_keywords(slot):
            topic_keywords.add(kw)

    flagged: set[str] = set()
    for path in sorted(parsed_dir.glob("*.paper_sections.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        text = _gather_text(data)
        # Step 1: mechanistic marker?
        mech_hit = any(marker in text for marker in _OFF_TOPIC_MARKERS)
        if not mech_hit:
            continue
        # Step 2: clinical-effect rescue?
        if any(rescue in text for rescue in _CLINICAL_RESCUE):
            continue
        # Step 3: any topic-slot keyword? Skip the topic aliases themselves
        # (every paper mentions "statin"); we want substantive evidence-type
        # keywords from the slots.
        topic_hit = any(kw in text for kw in topic_keywords if kw not in aliases)
        if topic_hit:
            continue
        flagged.add(data.get("paper_id") or path.stem)
    return flagged


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parsed-dir", type=Path, required=True)
    parser.add_argument("--topic-pack", type=Path, required=True)
    args = parser.parse_args(argv)
    flagged = filter_corpus(args.parsed_dir, args.topic_pack)
    total = len(list(args.parsed_dir.glob("*.paper_sections.json")))
    print(f"Total papers: {total}")
    print(f"Flagged (background_only): {len(flagged)}")
    for pid in sorted(flagged):
        print(f"  - {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
