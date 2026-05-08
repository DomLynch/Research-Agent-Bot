"""Deterministic BRIEFS-V1 writer/renderer skeleton."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent.briefs.question_parser import BriefQuery

__all__ = ["BriefDraft", "write_brief", "render_brief_markdown"]


@dataclass(frozen=True, slots=True)
class BriefDraft:
    """Rendered focused brief plus its minimal provenance."""

    query: BriefQuery
    topic: str
    receipts: tuple[dict[str, Any], ...]
    body_md: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "topic": self.topic,
            "n_receipts": len(self.receipts),
            "receipt_ids": [
                str(r.get("receipt_id") or r.get("paper_id") or "")
                for r in self.receipts
            ],
            "body_md": self.body_md,
        }


def write_brief(
    query: BriefQuery, *, topic: str,
    receipts: Sequence[Mapping[str, Any]],
) -> BriefDraft:
    """Render a deterministic brief skeleton from filtered receipts."""
    receipt_dicts = tuple(dict(r) for r in receipts)
    return BriefDraft(
        query=query,
        topic=topic,
        receipts=receipt_dicts,
        body_md=render_brief_markdown(query, topic=topic, receipts=receipt_dicts),
    )


def render_brief_markdown(
    query: BriefQuery, *, topic: str,
    receipts: Sequence[Mapping[str, Any]],
) -> str:
    """Markdown skeleton for a focused evidence brief."""
    direct = [r for r in receipts if _is_direct(r)]
    indirect = [r for r in receipts if not _is_direct(r)]
    lines = [
        f"# Evidence Brief: {query.question}",
        "",
        "## Question",
        "",
        query.question,
        "",
        "## Direct Evidence",
        "",
        *_receipt_lines(direct),
        "",
        "## Indirect and Extrapolated Evidence",
        "",
        *_receipt_lines(indirect),
        "",
        "## Tensions and Unknowns",
        "",
        _tension_stub(receipts),
        "",
        "## Bottom Line",
        "",
        _bottom_line(query, topic=topic, receipts=receipts),
        "",
        "## Provenance",
        "",
        f"- Topic pack: `{topic}`",
        f"- Filtered receipts used: {len(receipts)}",
        f"- Outcome filters: {', '.join(query.outcome_classes) or 'none'}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _is_direct(receipt: Mapping[str, Any]) -> bool:
    directness = str(receipt.get("directness") or "").lower()
    tier = str(receipt.get("evidence_tier") or "").upper()
    return directness == "direct" or tier in {"A1", "A2"}


def _receipt_lines(receipts: Sequence[Mapping[str, Any]]) -> list[str]:
    if not receipts:
        return ["- No matching receipts in this slice."]
    return [f"- {_receipt_label(r)} — {_receipt_summary(r)}" for r in receipts]


def _receipt_label(receipt: Mapping[str, Any]) -> str:
    return str(
        receipt.get("citation_token")
        or receipt.get("receipt_id")
        or receipt.get("paper_id")
        or "unknown receipt"
    )


def _receipt_summary(receipt: Mapping[str, Any]) -> str:
    parts = [
        f"outcome={receipt.get('outcome_class', 'unknown')}",
        f"tier={receipt.get('evidence_tier', 'unknown')}",
        f"directness={receipt.get('directness', 'unknown')}",
        f"direction={receipt.get('effect_direction', 'unknown')}",
    ]
    if receipt.get("n_claims") is not None:
        parts.append(f"claims={receipt['n_claims']}")
    return "; ".join(parts)


def _tension_stub(receipts: Sequence[Mapping[str, Any]]) -> str:
    if not receipts:
        return "No filtered receipts were available, so no tension map is rendered."
    outcomes = sorted({
        str(r.get("outcome_class") or "unknown") for r in receipts
    })
    return (
        "This brief inherits the parent paper's tension matrix. The filtered "
        f"slice covers {len(outcomes)} outcome class(es): {', '.join(outcomes)}."
    )


def _bottom_line(
    query: BriefQuery, *, topic: str, receipts: Sequence[Mapping[str, Any]],
) -> str:
    if not receipts:
        return (
            f"No receipt in the current certified `{topic}` corpus matched this "
            "question. The brief should not infer beyond the filtered corpus."
        )
    return (
        f"For `{topic}`, the filtered evidence slice contains {len(receipts)} "
        "receipt(s). Interpret the answer through the direct/indirect split "
        "above; no new numeric claims are introduced in this skeleton."
    )
