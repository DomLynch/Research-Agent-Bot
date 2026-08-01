from __future__ import annotations

import json
import re
import importlib
from pathlib import Path
from typing import Any

Change = tuple[str, int, str]


def apply_review_noise_control(text: str, out_dir: Path) -> tuple[str, list[Change]]:
    changes: list[Change] = []
    feedback = _revision_feedback(out_dir)
    text, n = re.subn(r"\bContextual Other\b", "Contextual Adjacent Evidence", text)
    if n:
        changes.append(("rename_contextual_other", n, "renamed broad contextual bucket"))
    if "Contextual Adjacent Evidence" in text and "not pooled with direct outcome evidence" not in text:
        note = (
            "\n\n**Outcome-class note:** Contextual Adjacent Evidence denotes "
            "background, boundary-condition, or adjacent-outcome sources. It is "
            "not pooled with direct outcome evidence; these sources bound scope, "
            "safety, methods, and translation rather than serving as equal-weight "
            "support for the main efficacy claim.\n"
        )
        text, n = re.subn(r"(^## Results\b)", r"\1" + note, text, count=1, flags=re.M)
        if n:
            changes.append(("explain_contextual_adjacent_evidence", 1, "defined broad adjacent-evidence bucket"))
    text, n = re.subn(
        r"not pooled with direct outcome evidence\.",
        "not pooled with direct outcome evidence; these sources bound scope, safety, methods, and translation rather than serving as equal-weight support for the main efficacy claim.",
        text,
    )
    if n:
        changes.append(("expand_contextual_adjacent_evidence_note", n, "clarified contextual-source integration role"))
    text, n = _repair_public_artifact_phrases(text)
    if n:
        changes.append(("repair_public_artifact_phrase", n, f"rewrote {n} public artifact phrase(s)"))
    text, n = _repair_unreferenced_citation_years(text)
    if n:
        changes.append(("repair_unreferenced_citation_year", n, f"aligned {n} inline citation year(s) with References"))
    text, n = _strip_unsupported_inline_citations(text)
    if n:
        changes.append(("strip_unsupported_inline_citation", n, f"removed {n} unsupported inline citation marker(s)"))
    text, n = _dedupe_repeated_blocks(text)
    if n:
        changes.append(("dedupe_repeated_blocks", n, f"removed {n} repeated prose/table block(s)"))
    text, n = _dedupe_duplicate_table_rows(text)
    if n:
        changes.append(("dedupe_duplicate_table_rows", n, f"removed {n} duplicate table row(s)"))
    text, n = _dedupe_repeated_h3_blocks(text)
    if n:
        changes.append(("dedupe_repeated_h3_blocks", n, f"removed {n} repeated subsection block(s)"))
    text, n = _trim_cross_domain_tables(text)
    if n:
        changes.append(("trim_low_value_cross_domain_rows", n, f"removed {n} low-severity agreement row(s)"))
    if _has_verification_limited_sources(out_dir) and "verification-limited context" not in text:
        note = (
            "\n\n**Verification note:** Reference-only or no-abstract records "
            "are treated as verification-limited context, not as equal-weight "
            "support for the main claim.\n"
        )
        text, n = re.subn(r"(^## Limitations\b)", r"\1" + note, text, count=1, flags=re.M)
        if n:
            changes.append(("flag_verification_limited_sources", 1, "flagged lower-weight context sources"))
    text, n = _apply_clinical_policy_caveat(text, feedback)
    if n:
        changes.append(("add_clinical_policy_caveat", n, "addressed reviewer caveat request"))
    return text, changes


def _repair_public_artifact_phrases(text: str) -> tuple[str, int]:
    replacements = (
        (r"\bshould be read as\b", "can be interpreted as"),
        (r"\baccepted receipt bundle contains\b", "included-source bundle includes"),
        (r"\baccepted receipt bundle\b", "included-source bundle"),
        (r"\baccepted receipt set\b", "included source set"),
        (r"\baccepted receipts\b", "included sources"),
        (r"\baccepted receipt\b", "included source"),
        (r"\breceipt set\b", "source set"),
        (r"\bbundle contains\b", "source bundle includes"),
        (r"\bnot extracted\b", "not available"),
    )
    total = 0
    for pattern, repl in replacements:
        text, n = re.subn(pattern, repl, text, flags=re.I)
        total += n
    return text, total


def _repair_unreferenced_citation_years(text: str) -> tuple[str, int]:
    from agent.journal_surface_gate import _AUTHOR_YEAR_RE, _fold, _reference_entries, _section_body, unreferenced_citation_tokens
    refs_by_author: dict[str, list[str]] = {}
    labels = re.findall(r"(?m)^[-*]\s+\*\*([^*\n]+?)\.?\*\*", _section_body(text, "References") or "")
    for raw, _folded in _reference_entries(text):
        match = _AUTHOR_YEAR_RE.search(raw)
        if not match:
            continue
        refs_by_author.setdefault(_fold(match.group(1)), []).append(raw)
    out = text
    n = 0
    for token in unreferenced_citation_tokens(text):
        match = _AUTHOR_YEAR_RE.fullmatch(token)
        if not match:
            continue
        candidates = refs_by_author.get(_fold(match.group(1)), [])
        candidates = candidates if len(candidates) == 1 else [label.rstrip(".") for label in labels if label.casefold().startswith(match.group(1).casefold() + " ") and label.rstrip(".").endswith(" " + match.group(2))]
        if len(candidates) != 1 or candidates[0] == token:
            continue
        out, changed = re.subn(rf"\b{re.escape(token)}\b", candidates[0], out)
        n += changed
    return out, n


def _strip_unsupported_inline_citations(text: str) -> tuple[str, int]:
    from agent.journal_surface_gate import _AUTHOR_YEAR_RE, _fold, _reference_entries, unreferenced_citation_tokens

    ref_authors = {
        _fold(match.group(1))
        for raw, _folded in _reference_entries(text)
        if (match := _AUTHOR_YEAR_RE.search(raw))
    }
    out = text
    n = 0
    for token in unreferenced_citation_tokens(text):
        match = _AUTHOR_YEAR_RE.fullmatch(token)
        if not match or _fold(match.group(1)) in ref_authors:
            continue
        author, year = match.groups()
        marker = rf"{re.escape(author)}(?:\s+et\s+al\.)?\s+{re.escape(year)}"
        out, changed = re.subn(
            rf"{marker},?\s+as cited across the corpus;?\s*",
            "",
            out,
            count=1,
        )
        before = len(re.findall(marker, out))
        out = "\n".join(line if line.lstrip().startswith(("|", "- ")) else re.sub(rf"(?:^|(?<=[.!?])\s+)(?:(?![!?]|\.(?!\d))[^\n])*{marker}(?:(?![!?]|\.(?!\d))[^\n])*(?:[!?]|\.(?!\d)|$)", "", line) for line in out.split("\n"))
        n += changed + before - len(re.findall(marker, out))
    return out, n


def restore_surface_floors(text: str, out_dir: Path, entries: list[Any], entry_cls: type[Any]) -> tuple[str, list[Any]]:
    manifest = _load_json(out_dir / "manifest.json")
    if not (out_dir / "full_paper.journal_surface.json").is_file() or not isinstance(manifest, dict) or not (
        isinstance(manifest.get("total_words"), int) or isinstance(manifest.get("section_words"), dict)
    ):
        return text, entries
    try:
        orch = importlib.import_module("scripts.run_v06_synthesis")
        setattr(orch, "_ACTIVE_TOPIC", str(manifest.get("topic") or ""))
        setattr(orch, "_ACTIVE_MANIFEST", manifest)
        fixed, repairs = orch._restore_public_surface_floors(
            text,
            review_type=manifest.get("review_type") if isinstance(manifest.get("review_type"), str) else None,
        )
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return text, entries
    entries.extend(
        entry_cls("N_surface_floor_backstop", str(item.get("reason") or "surface_floor_backstop"), 1, f"{item.get('section')}: restored journal-surface floor")
        for item in repairs
    )
    return fixed, entries


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _revision_feedback(out_dir: Path) -> str:
    try:
        data = json.loads((out_dir / "researka_revision_request.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return " ".join(str(data.get("feedback") or "").split())[:4000] if isinstance(data, dict) else ""


def repair_revision_surface(
    text: str, feedback: str, out_dir: Path | None = None,
) -> tuple[str, list[str]]:
    """Apply reviewer-requested placement and classification repairs."""
    coverage = importlib.import_module(
        f"{__package__}.revision_coverage" if __package__ else "revision_coverage",
    )
    changes: list[str] = []
    asks = coverage.revision_asks(feedback)
    tension_asks = [ask for ask in asks if coverage.asks_tension_section_placement(ask)]
    if tension_asks:
        request = " ".join(tension_asks)
        target = "Discussion" if "discussion" in request.lower() and "## Discussion" in text else "Conclusion"
        labels = re.findall(
            r"\b[A-Z][A-Za-z'’.-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", request,
        )
        candidates = [part.strip() for part in re.split(r"\n\s*\n", text)
                      if any(token in part.lower() for token in ("tension", "disagreement", "conflict", " versus ", " vs "))]
        paragraph = next((part for part in candidates
                          if all(label.lower() in part.lower() for label in labels)), "")
        section = re.search(rf"^## {target}\b[^\n]*\n(?P<body>.*?)(?=^## |\Z)", text, re.M | re.S)
        if paragraph and section and paragraph not in section.group("body"):
            text = re.sub(r"\n{3,}", "\n\n", text.replace(paragraph, "", 1))
            text, n = re.subn(rf"(^## {target}\b[^\n]*\n)",
                              lambda match: match.group(1) + "\n" + paragraph + "\n", text, count=1, flags=re.M)
            if n:
                changes.append("tension_section_placement")
    if coverage.asks_mechanistic_content_reconciliation(feedback):
        replacement = (
            "No retained source is classified primarily as mechanistic or model-system evidence under the "
            "source-level directness schema; however, mechanistic or biomarker content can occur within "
            "sources classified by their primary study role, so this is a classification statement and "
            "not evidence that mechanistic content is absent."
        )
        text, n = re.subn(r"(?P<lead>[ \t]*)[^.\n]*\bno sources classified primarily as mechanistic\b[^.\n]*\.",
                          lambda match: match.group("lead") + replacement, text, count=1, flags=re.I)
        if n:
            changes.append("mechanistic_content_framing")
    lower = feedback.lower()
    if out_dir and "quantitative evidence index" in lower and "## Quantitative Evidence Index" not in text:
        supplement = _load_text(out_dir / "structured_evidence_tables.md")
        index = re.search(r"^## Quantitative Evidence Index\b.*?(?=^## |\Z)", supplement, re.M | re.S)
        if index:
            text, n = re.subn(r"(?=^## References\b)", index.group(0).rstrip() + "\n\n", text, count=1, flags=re.M)
            if not n:
                text, n = text.rstrip() + "\n\n" + index.group(0).rstrip() + "\n", 1
            if n:
                changes.append("quantitative_evidence_index")
    if "conclusion" in lower and "boundary-condition matrix" in lower and "quantitative evidence index" in lower:
        note = (
            "This bounded outcome-class conclusion maps to the Boundary-Condition Matrix and Quantitative "
            "Evidence Index: direct human endpoints set the interpretive ceiling, while indirect or biomarker "
            "evidence defines mechanism and transferability boundaries."
        )
        text, n = _append_section_sentence(text, "Conclusion", note)
        if n:
            changes.append("bounded_conclusion_evidence_map")
    return text, changes


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _apply_clinical_policy_caveat(text: str, feedback: str) -> tuple[str, int]:
    lowered = feedback.lower()
    if not (
        ("clinical" in lowered or "medical" in lowered or "policy" in lowered)
        and any(term in lowered for term in ("caveat", "not supported", "not support", "not recommended"))
    ):
        return text, 0
    sentence = (
        "Current evidence does not support clinical or policy use for broad aging-related benefit; "
        "the synthesis is evidentiary, not medical guidance."
    )
    changed = 0
    for heading in ("Abstract", "Conclusion"):
        text, n = _append_section_sentence(text, heading, sentence)
        changed += n
    return text, changed


def _append_section_sentence(text: str, heading: str, sentence: str) -> tuple[str, int]:
    pattern = re.compile(rf"(^## {re.escape(heading)}\b\s*\n)(?P<body>.*?)(?=^## |\Z)", re.M | re.S)
    match = pattern.search(text)
    if not match or sentence.lower() in match.group("body").lower():
        return text, 0
    body = match.group("body").rstrip()
    replacement = match.group(1) + body + ("\n\n" if body else "") + sentence + "\n\n"
    return text[:match.start()] + replacement + text[match.end():], 1


def _dedupe_repeated_blocks(text: str) -> tuple[str, int]:
    parts = re.split(r"(^## References\b.*)", text, maxsplit=1, flags=re.M | re.S)
    body, tail = parts[0], "".join(parts[1:])
    # Abstracts and introductions intentionally recap body findings; never let
    # cross-section near-duplicate pruning collapse the public front matter.
    start = re.search(r"^##\s+(?:Background|Methods|Results)\b", body, flags=re.M)
    prefix, body = (body[:start.start()], body[start.start():]) if start else ("", body)
    chunks = re.split(r"(\n{2,})", body)
    seen: set[str] = set()
    seen_tokens: list[set[str]] = []
    removed = 0
    for i in range(0, len(chunks), 2):
        block = chunks[i]
        norm = re.sub(r"\s+", " ", block.strip())
        words = norm.split()
        if not norm:
            continue
        if re.match(r"\*\*\s*(?:thesis|resolution\s+criteria)\s*:", norm, flags=re.I) or norm.lower().startswith("outcome-class coded-direction reconciliation:"):
            continue
        table_like = block.lstrip().startswith("|") and block.count("\n|") >= 1
        # A bulleted / numbered block is structured enumeration, not prose
        # recap. Its vocabulary is often a small subset of richer prose (e.g. a
        # templated search-query list), which falsely trips the asymmetric
        # near-duplicate test below. Prune lists only on EXACT duplication.
        list_like = bool(re.match(r"\s*(?:[-*]|\d+[.)])\s", block))
        tokens = set(re.findall(r"[a-z0-9]+", norm.lower()))
        near_seen = not (list_like or table_like) and len(words) >= 18 and any(
            _token_overlap(tokens, prior) >= 0.85 for prior in seen_tokens
        )
        if (norm in seen and (table_like or len(words) >= 18)) or near_seen:
            chunks[i] = ""
            removed += 1
        else:
            seen.add(norm)
            if len(words) >= 18 and not table_like and not list_like:
                seen_tokens.append(tokens)
    return prefix + "".join(chunks) + tail, removed


def _token_overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, min(len(a), len(b)))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _separator_row(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", line))


def _dedupe_duplicate_table_rows(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    out: list[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            out.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            i += 1
        table = lines[start:i]
        if len(table) < 3 or not _separator_row(table[1]):
            out.extend(table)
            continue
        header = [c.lower() for c in _cells(table[0])]
        idxs = [next((j for j, c in enumerate(header) if name in c), -1) for name in ("study", "endpoint", "arm")]
        if min(idxs) < 0:
            out.extend(table)
            continue
        timepoint_idx = next(
            (j for j, c in enumerate(header) if any(
                name in c for name in ("timepoint", "time point", "follow-up", "follow up")
            )),
            -1,
        )
        key_idxs = idxs + ([timepoint_idx] if timepoint_idx >= 0 else [])
        seen: set[tuple[str, ...]] = set()
        kept = table[:2]
        for row in table[2:]:
            cells = _cells(row)
            key = tuple(cells[j].lower() for j in key_idxs if j < len(cells))
            if len(key) == len(key_idxs) and key in seen:
                removed += 1
            else:
                seen.add(key)
                kept.append(row)
        out.extend(kept)
    return "\n".join(out), removed


def _dedupe_repeated_h3_blocks(text: str) -> tuple[str, int]:
    match = re.search(r"^## Methods\b(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    if not match or "### " not in match.group(0):
        return text, 0
    parts = re.split(r"(?=^###\s+)", match.group(0), flags=re.M)
    kept = [parts[0]]
    seen: set[str] = set()
    removed = 0
    for block in parts[1:]:
        body = re.sub(r"^###.*?\n", "", block, count=1, flags=re.S).strip()
        norm = re.sub(r"\s+", " ", body).lower()
        if len(norm.split()) >= 12 and norm in seen:
            removed += 1
        else:
            seen.add(norm)
            kept.append(block)
    return text[:match.start()] + "".join(kept) + text[match.end():], removed


def _trim_cross_domain_tables(text: str) -> tuple[str, int]:
    match = re.search(r"^## Cross-Domain Synthesis\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not match:
        return text, 0
    lines = match.group(0).splitlines()
    out: list[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            out.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            i += 1
        table = lines[start:i]
        if len(table) < 3 or not _separator_row(table[1]):
            out.extend(table)
            continue
        header = [c.lower() for c in _cells(table[0])]
        sev_idx = next((j for j, c in enumerate(header) if "severity" in c), -1)
        kind_idx = next((j for j, c in enumerate(header) if any(k in c for k in ("kind", "type", "tension", "conflict"))), -1)
        kept = table[:2]
        for row in table[2:]:
            cells = _cells(row)
            kind = cells[kind_idx].lower() if 0 <= kind_idx < len(cells) else ""
            m = re.search(r"\b([0-5])\b", cells[sev_idx]) if 0 <= sev_idx < len(cells) else None
            severity = int(m.group(1)) if m else None
            if (severity is not None and severity <= 1) or ("agreement" in kind and "disagreement" not in kind):
                removed += 1
            else:
                kept.append(row)
        out.extend(kept)
    return text[:match.start()] + "\n".join(out) + text[match.end():], removed


def _has_verification_limited_sources(out_dir: Path) -> bool:
    try:
        data = json.loads((out_dir / "citation_registry.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return any(isinstance(row, dict) and not row.get("title") and not row.get("source_journal") for row in data.values())
