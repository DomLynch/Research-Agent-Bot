"""Topic-pack matcher for BRIEFS-V1."""
from __future__ import annotations

import re
from pathlib import Path

from agent.briefs.question_parser import BriefQuery
from agent.topic_pack import TopicPack, load_topic_pack

__all__ = ["load_brief_topic_packs", "match_topics"]


def load_brief_topic_packs(topic_packs_dir: str | Path) -> tuple[TopicPack, ...]:
    """Load all TOML topic packs in stable order."""
    root = Path(topic_packs_dir)
    return tuple(
        load_topic_pack(path) for path in sorted(root.glob("*.toml"))
        if not path.stem.startswith("_")
    )


def match_topics(
    query: BriefQuery, topic_packs_dir: str | Path,
) -> tuple[TopicPack, ...]:
    """Return topic packs whose aliases match query interventions."""
    interventions = tuple(_norm(i) for i in query.interventions if i.strip())
    if not interventions:
        return ()
    ranked: list[tuple[int, str, TopicPack]] = []
    for pack in load_brief_topic_packs(topic_packs_dir):
        aliases = tuple(_norm(a) for a in pack.aliases)
        score = max(
            (_match_score(term, alias) for term in interventions
             for alias in aliases),
            default=0,
        )
        if score:
            ranked.append((score, pack.topic, pack))
    return tuple(p for _, _, p in sorted(ranked, key=lambda x: (-x[0], x[1])))


def _norm(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    words = [w[:-1] if len(w) > 3 and w.endswith("s") else w
             for w in text.split()]
    return " ".join(words)


def _match_score(term: str, alias: str) -> int:
    if term == alias:
        return 3
    if term and alias and (term in alias or alias in term):
        return 1
    return 0
