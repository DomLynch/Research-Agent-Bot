from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any


_P_VALUE_RE = re.compile(r"\bp\s*([<≤=])\s*(0?\.\d+|\d+(?:\.\d+)?)", re.I)

_CONTEXT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Oncology and cancer context", ("cancer", "carcinoma", "tumor", "tumour", "oncology", "metastatic", "neuroendocrine")),
    ("Transplant and fibrosis context", ("transplant", "allograft", "graft", "fibrosis", "fibrotic")),
    ("Infectious-disease and immunology context", ("respiratory tract infection", "influenza", "virus", "viral", "vaccine", "immunotherapy")),
    ("Skeletal and muscle context", ("bone", "fracture", "osteoporosis", "postmenopausal", "muscle", "resistance training")),
    ("Dosing and pharmacokinetics context", ("pharmacokinetic", "pharmacokinetics", "dose", "dosing")),
    ("Pulmonary and rare-disease context", ("lymphangioleiomyomatosis", "pulmonary", "lung disease")),
    ("Aging and geroscience context", ("aging", "ageing", "older adults", "elderly", "frailty", "healthspan", "longevity")),
)


def significant_p_value_count(row: Mapping[str, Any]) -> int:
    total = 0
    for raw in row.get("p_values") or ():
        match = _P_VALUE_RE.search(str(raw).replace("\xa0", " "))
        if not match:
            continue
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        op = match.group(1)
        if (op in {"<", "≤"} and value <= 0.05) or (op == "=" and value < 0.05):
            total += 1
    return total


def signal_summary_cell(rows: Iterable[Mapping[str, Any]]) -> str:
    items = list(rows)
    n = len(items)
    if not n:
        return "no sources"
    effects = Counter(str(row.get("effect_direction") or "").strip().lower() for row in items)
    effects.pop("", None)
    top_effect = max(effects.items(), key=lambda kv: (kv[1], kv[0]))[0] if effects else "unclear"
    top_n = effects.get(top_effect, 0)
    significant_n = sum(1 for row in items if significant_p_value_count(row))
    statistic_n = sum(1 for row in items if row.get("p_values"))
    if top_effect in {"positive", "negative", "mixed"}:
        return f"{top_effect} signal in {top_n}/{n} sources"
    if significant_n:
        return f"significant source statistic in {significant_n}/{n} sources; receipt-level direction coded {top_effect}"
    if statistic_n:
        return f"reported statistic in {statistic_n}/{n} sources; receipt-level direction coded {top_effect}"
    if top_effect == "null":
        return f"no extracted directional signal in {top_n}/{n} sources"
    return f"{top_effect} signal in {top_n}/{n} sources"


def source_context_label(row: Mapping[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("source_title", "citation_token", "receipt_id")
    ).lower()
    for label, needles in _CONTEXT_PATTERNS:
        if any(needle in text for needle in needles):
            return label
    return ""


_SOURCE_CONTEXT_MAP_RE = re.compile(
    r"\n+\*\*Source-context map:\*\*.*?(?=\n###\s+|\n##\s+|\Z)",
    re.S,
)


def strip_source_context_map(markdown: str) -> str:
    return _SOURCE_CONTEXT_MAP_RE.sub("\n", markdown)


def source_context_map(rows: Iterable[Mapping[str, Any]]) -> str:
    by_context: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        label = source_context_label(row)
        if label:
            by_context.setdefault(label, []).append(row)
    if len(by_context) < 2:
        return ""
    lines = [
        "**Source-context map:** Source-title contexts are separated for interpretation and are not pooled as one clinical effect.",
        "",
        "| Source context | Sources | Signal summary |",
        "|---|---:|---|",
    ]
    for label, group in sorted(by_context.items(), key=lambda item: (-len(item[1]), item[0])):
        lines.append(f"| {label} | {len(group)} | {signal_summary_cell(group)} |")
    return "\n".join(lines) + "\n"
