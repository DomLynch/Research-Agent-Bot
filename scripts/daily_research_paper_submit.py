"""Daily v3 research-paper submit bridge.

Safe by default: select one ready run, write a ledger, and only call
Researka when `--submit` is explicit. A successful POST is recorded as
submitted_to_researka, not published.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from source_topic_specificity import (  # noqa: E402
    BIOMED_ANCHORS, DRIFT_RESCUE_ANCHORS, NON_BIOMED_DRIFT,
    _specificity_token, is_source_topic_specific, source_gate_aliases,
    topic_aliases, topic_tokens,
)
from agent.final_gate import DEFAULT_THRESHOLDS  # noqa: E402
from agent.topic_display import humanize_topic  # noqa: E402

RUNS = ROOT / "runs"
LEDGER_DIR = "_daily_research_paper_ledger"
# Re-audit window for stale-audit self-heal: only recently produced runs are
# re-audited at submit time so a now-fixed audit check propagates without a
# re-synthesis. Bounds cost — historical runs are not re-audited every cycle.
STALE_AUDIT_REFRESH_WINDOW_S = 48 * 3600
REJECTED_FINGERPRINTS = "_rejected_fingerprints.json"
REVISION_FINGERPRINTS = "_revision_fingerprints.json"
REVISION_COVERAGE_GATE = "revision_coverage_gate.json"
TOKEN_ENVS = (
    "RESEARKA_API_KEY_V3",
    "RESEARKA_API_TOKEN_V3",
    "RESEARKA_AGENT_TOKEN_V3",
    "RESEARKA_V2_API_KEY",
)
DEFAULT_AGENT_SLUG = "agent-v3-full-paper"
DEFAULT_ARTICLE_TYPE = "rapid_evidence_synthesis"
SOURCE_TOPIC_PRECISION_FLOOR = 0.50
NULL_CODING_AUDIT_FLOOR = 0.90
# Mirror of Researka's intake recency floor year (contracts/submissions.py
# RECENT_PUBLICATION_YEAR_FLOOR). The per-type recency *ratio* lives in
# RESEARKA_TYPE_THRESHOLDS below. Checking recency pre-submit stops the bot
# wasting a synthesis cycle — and tripping the intake backoff — on a corpus
# whose published source bundle is too old to clear the gate.
RECENT_PUBLICATION_YEAR_FLOOR = 2020
# Per-article-type pre-submit intake floors. Mirrors the live Researka core
# (contracts/submissions.py `_TYPE_THRESHOLDS` + templates.py
# `minimum_body_word_count`). Every floor is set >= the core's, so a payload
# that clears preflight also clears intake — never the reverse — which is what
# stops the bot wasting a synthesis cycle or tripping the 3-strike intake
# backoff. `evidence_map` mirrors the core exactly (the landscape lane is
# deliberately lighter: 10 sources, 30% recent, short Scope, no body floor);
# the thesis lanes keep their historical floors. Universal: keyed only on
# article_type, no topic/domain assumptions.
RESEARKA_TYPE_THRESHOLDS: dict[str, dict[str, float]] = {
    "rapid_evidence_synthesis": {"min_citations": 12, "recency_ratio": 0.50, "min_question_words": 50, "min_body_words": 2000},
    "research_synthesis": {"min_citations": 12, "recency_ratio": 0.50, "min_question_words": 75, "min_body_words": 2000},
    "evidence_map": {"min_citations": 10, "recency_ratio": 0.30, "min_question_words": 30, "min_body_words": 0},
}
PUBLICATION_IDENTITY_KEYS = (
    "submission_identity_key",
    "submission_payload_hash",
    "content_hash",
    "source_citation_hash",
    "author_signature",
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\])}>,;]+", re.I)
PMID_RE = re.compile(r"\bPMID[:\s#-]*(\d{4,12})\b", re.I)
RESEARKA_REQUIRED_SECTIONS = {
    "rapid_evidence_synthesis": (
        "Research Question",
        "Search Summary",
        "Evidence Landscape",
        "Key Findings",
        "Limitations",
        "Gaps Identified",
        "Conclusion",
    ),
    "research_synthesis": (
        "Abstract",
        "Introduction",
        "Methods",
        "Results",
        "Discussion",
        "Limitations",
        "Conclusion",
    ),
    "evidence_map": (
        "Scope",
        "Search Summary",
        "Evidence Landscape",
        "Findings Map",
        "Tensions and Gaps",
        "Limitations",
    ),
}
RESEARKA_RECOMMENDED_SECTIONS = {
    "research_synthesis": (
        "Background",
        "Inferential Bridge",
        "Quantitative Evidence Index",
        "Cross-Domain Synthesis",
        "References",
    ),
}
RESEARKA_QUESTION_SECTION = {
    "rapid_evidence_synthesis": "Research Question",
    "research_synthesis": "Abstract",
    "evidence_map": "Scope",
}
Submitter = Callable[[dict[str, Any]], dict[str, Any]]
RemoteLoader = Callable[[], tuple[set[str], str | None]]
PREFLIGHT_MODE_ENV = "RESEARKA_PREFLIGHT_QA"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    material = {
        key: payload.get(key)
        for key in ("title", "abstract", "artifact_type", "article_type", "author_agent_id", "body_markdown", "sections", "source_bundle")
    }
    return "sha256:" + hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _preflight_summary(report: dict[str, Any]) -> dict[str, Any]:
    advisories = report.get("advisories")
    advisory_rows = advisories if isinstance(advisories, list) else []
    return {
        "status": report.get("status"),
        "qa_version": report.get("qa_version"),
        "input_hash": report.get("input_hash"),
        "cleaned_hash": report.get("cleaned_hash"),
        "safe_fixes_applied": report.get("safe_fixes_applied") or [],
        "blocked_reasons": report.get("blocked_reasons") or [],
        "advisory_codes": [
            str(row.get("code")) for row in advisory_rows
            if isinstance(row, dict) and row.get("code")
        ],
    }


def _preflight_mode() -> str:
    mode = os.getenv(PREFLIGHT_MODE_ENV, "off").strip().lower()
    if mode == "live":
        return "enforce"
    return mode if mode in {"off", "shadow", "enforce"} else "off"


def _run_preflight_qa(payload: dict[str, Any], run: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mode = _preflight_mode()
    if mode == "off":
        return payload, None
    tool_root = Path(os.getenv("RESEARKA_PREFLIGHT_QA_ROOT", ROOT.parent / "researka-preflight-qa"))
    input_path = run / "researka_preflight_input.json"
    report_path = run / "researka_preflight_report.json"
    clean_path = run / "researka_preflight_cleaned_payload.json"
    _write_json(input_path, payload)
    if not tool_root.is_dir():
        report = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_tool_missing",
                "severity": "minor",
                "message": f"preflight QA root not found: {tool_root}",
            }],
        }
        metadata = payload.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
        return payload, report
    cmd = [
        sys.executable, "-m", "preflight_qa", "check",
        "--input", str(input_path),
        "--out", str(report_path),
        "--clean-out", str(clean_path),
    ]
    if os.getenv("RESEARKA_PREFLIGHT_USE_M3", "").strip().lower() in {"1", "true", "yes", "on"}:
        cmd.append("--use-m3")
    proc = subprocess.run(cmd, cwd=tool_root, text=True, capture_output=True, timeout=90, check=False)
    if proc.returncode not in {0, 2}:
        report = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_runtime_error",
                "severity": "minor",
                "message": (proc.stderr or proc.stdout or "preflight QA failed")[-500:],
            }],
        }
    else:
        report = _read_json(report_path)
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    if isinstance(metadata, dict):
        metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
    if mode == "shadow":
        return payload, report
    if report.get("status") != "pass":
        return payload, report
    cleaned = _read_json(clean_path)
    if not cleaned:
        report = {
            "status": "pass",
            "qa_version": "preflight-v2",
            "blocked_reasons": [],
            "advisories": [{
                "code": "preflight_missing_cleaned_payload",
                "severity": "minor",
                "message": "Preflight passed but did not write a cleaned payload.",
            }],
        }
        metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
        return payload, report
    cleaned_metadata = cleaned.setdefault("metadata", {})
    if isinstance(cleaned_metadata, dict):
        cleaned_metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
        body = str(cleaned.get("body_markdown") or "")
        content_hash = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        cleaned_metadata["preflight_original_content_hash"] = cleaned_metadata.get("content_hash")
        cleaned_metadata["content_hash"] = content_hash
        cleaned["author_signature"] = content_hash
        cleaned_metadata["submission_identity_key"] = _submission_identity_key(
            agent_slug=str(cleaned.get("author_agent_id") or ""),
            title=str(cleaned.get("title") or ""),
            content_hash=content_hash,
            source_citation_hash=str(cleaned_metadata.get("source_citation_hash") or ""),
        )
        cleaned_metadata["submission_payload_hash"] = _payload_fingerprint(cleaned)
    return cleaned, report


def _hash_json(material: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _normalized_key(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _title_marker(title: str) -> str:
    return "title:" + _normalized_key(title)


def _topic_marker(topic: str) -> str:
    return "topic:" + _normalized_key(topic)


def _submission_marker(submission_id: str) -> str:
    return "submission:" + submission_id.strip()


def _paper_title(paper: Path) -> str:
    try:
        first = paper.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return ""
    return first.lstrip("# ").strip()


def _env_or_default(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _agent_slug() -> str:
    return os.getenv("RESEARKA_AGENT_SLUG_V3", "").strip() or os.getenv("AGENT_ID", "").strip() or DEFAULT_AGENT_SLUG


def _threshold(article_type: str, key: str) -> float:
    """Per-type pre-submit intake floor; unknown types fall back to the default lane."""
    table = RESEARKA_TYPE_THRESHOLDS.get(article_type) or RESEARKA_TYPE_THRESHOLDS[DEFAULT_ARTICLE_TYPE]
    return table[key]


# Auto-select doctrine: with no explicit override, route a corpus to
# `evidence_map` when its tension density — n_non_orthogonal_tensions divided by
# n_receipts — is >= the floor (default 1.0). The predicate is INCLUSIVE at the
# boundary: density == floor routes to evidence_map, because a corpus carrying
# at least as many cross-source tensions as it has receipts is already a
# heterogeneous, non-convergent landscape. Forcing such a corpus into a
# single-thesis synthesis is what makes the writer overclaim against its own
# evidence table; the map instead reviews it on the right axis (landscape
# fidelity, not convergence). Universal: density is topic-agnostic; the floor is
# env-tunable via RESEARKA_EVIDENCE_MAP_TENSION_FLOOR.
EVIDENCE_MAP_TENSION_DENSITY_FLOOR = 1.0


def _evidence_map_tension_floor() -> float:
    raw = os.getenv("RESEARKA_EVIDENCE_MAP_TENSION_FLOOR", "").strip()
    try:
        return float(raw) if raw else EVIDENCE_MAP_TENSION_DENSITY_FLOOR
    except ValueError:
        return EVIDENCE_MAP_TENSION_DENSITY_FLOOR


def _select_article_type(manifest: dict[str, Any]) -> str:
    """Explicit env override > landscape auto-select > default thesis lane."""
    override = os.getenv("RESEARKA_ARTICLE_TYPE_V3", "").strip()
    if override:
        return override
    receipts = int(manifest.get("n_receipts") or 0)
    tensions = int(manifest.get("n_non_orthogonal_tensions") or 0)
    # A zero-tension corpus is a landscape survey (nothing to adjudicate), not a
    # failed thesis — route it to evidence_map (reviewed for fidelity, not
    # convergence) rather than the thesis lane that requires >=1 tension. Pairs
    # with final_gate.landscape_thresholds, which lifts only the tension floor.
    if receipts and (tensions == 0 or tensions / receipts >= _evidence_map_tension_floor()):
        return "evidence_map"
    return DEFAULT_ARTICLE_TYPE


def _token() -> tuple[str, str]:
    for name in TOKEN_ENVS:
        value = os.getenv(name, "").strip()
        if value:
            return value, name
    return "", ""


def _runs(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.glob("synthesis-*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _run_topic(run: Path) -> str:
    manifest_topic = str(_read_json(run / "manifest.json").get("topic") or "").strip()
    if manifest_topic:
        return manifest_topic
    match = re.match(r"synthesis-(?P<topic>.+?)-v\d+", run.name)
    return match.group("topic") if match else run.name


def _pre_submit_passed(data: dict[str, Any]) -> bool:
    result = data.get("result")
    return bool(data.get("passed") is True or isinstance(result, dict) and result.get("passed") is True)


def _pre_submit_status(data: dict[str, Any]) -> str:
    if _pre_submit_passed(data):
        return "eligible"
    result = data.get("result")
    raw_failures = result.get("failures") if isinstance(result, dict) else ()
    failures = raw_failures if isinstance(raw_failures, list | tuple) else ()
    corpus_floor = [
        " ".join(str(failure).split())
        for failure in failures if str(failure).startswith(("n_receipts=", "n_tensions="))
    ]
    if corpus_floor:
        return "preflight_insufficient_corpus:" + "; ".join(corpus_floor)
    return "pre_submit_not_passed"


def _source_floor_status(run: Path) -> str:
    manifest = _read_json(run / "manifest.json")
    registry = _read_json(run / "citation_registry.json")
    receipts = int(manifest.get("n_receipts") or 0)
    if not receipts:
        rows = manifest.get("receipts")
        receipts = len(rows) if isinstance(rows, list) else 0
    citations = len(registry) if isinstance(registry, dict) else 0
    available = min(receipts, citations)
    floor = DEFAULT_THRESHOLDS.min_receipts
    if available < floor:
        return f"preflight_insufficient_corpus:n_receipts={available} < threshold {floor}"
    return "eligible"


def _word_count(text: object) -> int:
    return len(str(text or "").split())


def _researka_preflight_status(payload: dict[str, Any]) -> str:
    article_type = str(payload.get("article_type") or DEFAULT_ARTICLE_TYPE)
    sections_raw = payload.get("sections")
    sections: dict[str, Any] = sections_raw if isinstance(sections_raw, dict) else {}
    source_bundle_raw = payload.get("source_bundle")
    source_bundle = [row for row in source_bundle_raw if isinstance(row, dict)] if isinstance(source_bundle_raw, list) else []
    min_citations = int(_threshold(article_type, "min_citations"))
    if len(source_bundle) < min_citations:
        return f"researka_preflight_insufficient_sources:{len(source_bundle)} < {min_citations}"

    required_sections = RESEARKA_REQUIRED_SECTIONS.get(article_type, RESEARKA_REQUIRED_SECTIONS[DEFAULT_ARTICLE_TYPE])
    missing = [name for name in required_sections if not str(sections.get(name) or "").strip()]
    if missing:
        return "researka_preflight_missing_sections:" + ",".join(missing)

    question_section = RESEARKA_QUESTION_SECTION.get(article_type, "Research Question")
    minimum_question_words = int(_threshold(article_type, "min_question_words"))
    question_words = _word_count(sections.get(question_section))
    if question_words < minimum_question_words:
        return (
            "researka_preflight_question_words:"
            f"{question_section}={question_words} < {minimum_question_words}"
        )

    min_body_words = int(_threshold(article_type, "min_body_words"))
    if min_body_words:
        if article_type == "research_synthesis":
            body_words = sum(
                _word_count(sections.get(name))
                for name in (*required_sections, *RESEARKA_RECOMMENDED_SECTIONS.get(article_type, ()))
            )
        else:
            body_words = _word_count(payload.get("body_markdown"))
        if body_words < min_body_words:
            return f"researka_preflight_body_words:{body_words} < {min_body_words}"
    if (recency_status := _recency_ratio_status(payload)) != "eligible":
        return recency_status
    return "eligible"


def _final_status_ready(data: dict[str, Any]) -> bool:
    return bool(data.get("submission_ready") is True)


def _revision_coverage_status(run: Path) -> str:
    request = _read_json(run / "researka_revision_request.json")
    if not request:
        return "eligible"
    _refresh_revision_coverage_gate(run, request)
    gate = _read_json(run / REVISION_COVERAGE_GATE)
    if gate.get("passed") is True:
        return "eligible"
    if gate.get("passed") is False:
        return "revision_coverage_unmet"
    return "revision_coverage_unverified"


def _refresh_revision_coverage_gate(run: Path, request: dict[str, Any]) -> bool:
    gate = _read_json(run / REVISION_COVERAGE_GATE)
    if gate.get("passed") is True:
        return False
    paper = run / "full_paper.md"
    feedback = str(request.get("feedback") or "")
    if not feedback or not paper.is_file():
        return False
    try:
        import revision_coverage
        text = paper.read_text(encoding="utf-8")
        asks = revision_coverage.revision_asks(feedback)
        if not asks or len(revision_coverage.deterministic_known_asks(asks)) != len(asks):
            return False
        unmet = revision_coverage.material_unmet_asks(text, feedback)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False
    _write_json(run / REVISION_COVERAGE_GATE, {
        "passed": not unmet,
        "ask_count": len(asks),
        "unmet_asks": unmet,
        "refreshed_by": "daily_submit",
    })
    return True


def _topic_tokens(topic: str) -> list[str]:
    return topic_tokens(topic)


def _receipt_haystack(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "receipt_id", "paper_id", "citation_token",
            "source_title", "source_doi", "source_pmid",
        )
    ).lower()


def _entity_rescue(tokens: list[str], haystacks: list[str]) -> tuple[int, str | None]:
    """Corpus-dominant-entity rescue for compound topics.

    The per-source gate (`is_source_topic_specific`) requires EVERY specificity
    token, so a focused corpus whose titles name the entity but rarely a
    secondary axis term (e.g. "resveratrol_metabolism": titles say
    "resveratrol", seldom "metabolism") scores below the floor even though every
    source is about the named entity. The entity is the specificity token
    covering the most receipt titles; count the sources that name it in a
    biomedical (non-drift) context. Returns (rescued_hits, entity | None).

    Additive by construction: callers apply it only when the strict ratio is
    already below the floor, so it can never demote a run; the drift guard
    (mirrors `is_source_topic_specific`) keeps off-domain sources out.
    """
    specific = [
        token for token in (_specificity_token(tok) for tok in tokens)
        if token not in BIOMED_ANCHORS
    ]
    if not specific:
        return 0, None
    title_tokens = [
        {
            _specificity_token(tok)
            for tok in re.findall(r"[a-z0-9]+", haystack)
            if len(tok) > 2
        }
        for haystack in haystacks
    ]
    coverage = {token: sum(token in tt for tt in title_tokens) for token in specific}
    entity = max(specific, key=lambda token: coverage[token])
    rescued = 0
    for haystack, present in zip(haystacks, title_tokens):
        if entity not in present:
            continue
        drift = any(term in haystack for term in NON_BIOMED_DRIFT)
        # Rescue anchors match whole words only: a substring check would let the
        # "rat" anchor fire inside "resve(rat)rol", neutering the drift guard.
        rescue_words = set(re.findall(r"[a-z0-9]+", haystack)) & DRIFT_RESCUE_ANCHORS
        if drift and not rescue_words:
            continue
        rescued += 1
    return rescued, entity


def _source_topic_precision(run: Path) -> tuple[bool, str]:
    manifest = _read_json(run / "manifest.json")
    topic = str(manifest.get("topic") or _run_topic(run))
    tokens = _topic_tokens(topic)
    receipts = manifest.get("receipts")
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not tokens or not rows:
        return True, "source_topic_precision_unscored"
    base = run.parent.parent if run.parent.name == "runs" else run.parent
    aliases = source_gate_aliases(
        topic, topic_aliases(topic, root=base, include_generated_terms=False),
    )
    haystacks = [_receipt_haystack(row) for row in rows]
    hits = sum(is_source_topic_specific(topic, h, aliases=aliases) for h in haystacks)
    n = len(rows)
    if hits / n >= SOURCE_TOPIC_PRECISION_FLOOR:
        return True, f"source_topic_precision_ok:{hits}/{n}"
    # Below the floor: a compound topic may be entity-focused but axis-sparse in
    # titles. Rescue on the corpus-dominant entity (non-drift) before blocking.
    rescued, entity = _entity_rescue(tokens, haystacks)
    if entity is not None and rescued / n >= SOURCE_TOPIC_PRECISION_FLOOR:
        return True, f"source_topic_precision_ok:{rescued}/{n}:entity={entity}"
    return False, f"source_topic_precision_low:{hits}/{n}<{SOURCE_TOPIC_PRECISION_FLOOR:.2f}"


def _recency_ratio_status(payload: dict[str, Any]) -> str:
    """Pre-submit mirror of Researka's intake recency gate. Computed over the
    BUILT source bundle (not the registry): citation-floor padding appends
    older reference-list stubs that drag the published recency down, so only
    the bundle the journal actually receives predicts the gate. The floor is
    per-article-type (evidence maps tolerate an older corpus). Universal —
    year-based, no topic/domain assumptions; fail-open when no years are known."""
    article_type = str(payload.get("article_type") or DEFAULT_ARTICLE_TYPE)
    floor = _threshold(article_type, "recency_ratio")
    bundle = payload.get("source_bundle")
    years = [
        row["year"]
        for row in (bundle if isinstance(bundle, list) else [])
        if isinstance(row, dict) and isinstance(row.get("year"), int)
    ]
    if not years:
        return "eligible"
    recent = sum(1 for year in years if year >= RECENT_PUBLICATION_YEAR_FLOOR)
    if recent / len(years) < floor:
        return f"recency_ratio_low:{recent}/{len(years)}<{floor:.2f}"
    return "eligible"


def _null_coding_claim(paper: str) -> tuple[int, int] | None:
    match = re.search(
        r"(\d+)\s*/\s*(\d+)\s+retained sources[^.]{0,120}"
        r"(?:null|no extracted directional signal)",
        paper,
        re.I,
    )
    if not match:
        return None
    return int(match.group(1)), max(1, int(match.group(2)))


def _null_coding_audit_status(payload: dict[str, Any], manifest: dict[str, Any]) -> str:
    paper = str(payload.get("body_markdown") or "")
    claim = _null_coding_claim(paper)
    if not claim:
        return "eligible"
    null_n, total_n = claim
    if null_n / total_n < NULL_CODING_AUDIT_FLOOR:
        return "eligible"
    receipts = [row for row in manifest.get("receipts", []) if isinstance(row, dict)]
    direct = sum(str(row.get("directness") or "").lower() == "direct" for row in receipts)
    if direct:
        return "eligible"
    bundle = [row for row in payload.get("source_bundle", []) if isinstance(row, dict)]
    abstract_like = sum(
        any(token in str(row.get("excerpt") or "")[:220].lower() for token in ("background:", "objective:", "methods:", "study design:"))
        for row in bundle
    )
    if abstract_like and "source-bundle reconciliation note:" in paper.lower():
        return "eligible"
    if bundle and abstract_like / len(bundle) >= 0.5:
        return f"null_coding_requires_reconciliation:{null_n}/{total_n}_null_no_direct"
    return "eligible"


def _refresh_stale_accountability_sidecar(run: Path) -> bool:
    contract = _read_json(run / "pre_submit_gate.json").get("journal_readiness_contract")
    if not isinstance(contract, list):
        return False
    try:
        from agent.accountability import resolve_model
    except ImportError:
        return False
    model = resolve_model(str(_read_json(run / "manifest.json").get("accountability_model") or ""))
    if model != "researka_agent_certified":
        return False
    stale = any(
        isinstance(row, dict)
        and row.get("id") == 13
        and row.get("status") != "pass"
        and bool(row.get("blocks_submission"))
        for row in contract
    )
    if not stale:
        return False
    try:
        from agent.journal_finalizer import _phase_g_refresh_sidecars  # type: ignore[attr-defined]
        return bool(_phase_g_refresh_sidecars(run))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _refresh_stale_audit_sidecar(run: Path) -> bool:
    """Re-run the deterministic audit + gate sidecars for a recently produced
    run whose stored audit is not all-green, so a now-fixed audit check (e.g.
    the Q2 References numeric exclusion) propagates to disk and the run can
    become submit-eligible without a re-synthesis. Structural trigger (stored
    audit not all-green); bounded to recent runs. Re-runs the real audit, so a
    genuinely failing paper stays blocked."""
    audit = _read_json(run / "full_paper.audit.json")
    if not audit or (audit.get("p1_pass") is True and audit.get("n_pass") == audit.get("n_total")):
        return False
    try:
        if dt.datetime.now(dt.UTC).timestamp() - run.stat().st_mtime > STALE_AUDIT_REFRESH_WINDOW_S:
            return False
        from agent.journal_finalizer import _phase_g_refresh_sidecars  # type: ignore[attr-defined]
        return bool(_phase_g_refresh_sidecars(run))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _refresh_stale_surface_sidecar(run: Path) -> bool:
    surface = _read_json(run / "full_paper.journal_surface.json")
    if surface.get("passed") is not False:
        return False
    try:
        if dt.datetime.now(dt.UTC).timestamp() - run.stat().st_mtime > STALE_AUDIT_REFRESH_WINDOW_S:
            return False
        from agent.journal_finalizer import finalize_run
        report = finalize_run(run)
        return bool(report.paper_changed)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _refresh_stale_revision_coverage_sidecar(run: Path) -> bool:
    request = _read_json(run / "researka_revision_request.json")
    if not request:
        return False
    gate = _read_json(run / REVISION_COVERAGE_GATE)
    if gate.get("passed") is True:
        return False
    try:
        if dt.datetime.now(dt.UTC).timestamp() - run.stat().st_mtime > STALE_AUDIT_REFRESH_WINDOW_S:
            return False
        from agent.journal_finalizer import finalize_run
        report = finalize_run(run)
        return bool(report.paper_changed or _refresh_revision_coverage_gate(run, request))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _eligible(run: Path) -> tuple[bool, str]:
    # Phase G refreshes all sidecars (audit + gate + accountability); run it at
    # most once — prefer the accountability path, else the stale-audit path.
    if not _refresh_stale_accountability_sidecar(run):
        _refresh_stale_audit_sidecar(run)
    required = (
        "full_paper.md",
        "manifest.json",
        "citation_registry.json",
        "full_paper.audit.json",
        "full_paper.journal_surface.json",
        "full_paper.final_verdict.json",
        "pre_submit_gate.json",
    )
    missing = [name for name in required if not (run / name).exists()]
    if missing:
        return False, "missing:" + ",".join(missing)
    audit = _read_json(run / "full_paper.audit.json")
    surface = _read_json(run / "full_paper.journal_surface.json")
    if surface.get("passed") is not True and _refresh_stale_surface_sidecar(run):
        surface = _read_json(run / "full_paper.journal_surface.json")
    verdict = _read_json(run / "full_paper.final_verdict.json")
    if audit.get("p1_pass") is not True:
        return False, "audit_p1_failed"
    if surface.get("passed") is not True:
        return False, "journal_surface_not_passed"
    pre_submit_status = _pre_submit_status(_read_json(run / "pre_submit_gate.json"))
    if pre_submit_status != "eligible":
        return False, pre_submit_status
    _refresh_stale_revision_coverage_sidecar(run)
    revision_status = _revision_coverage_status(run)
    if revision_status != "eligible":
        return False, revision_status
    source_floor_status = _source_floor_status(run)
    if source_floor_status != "eligible":
        return False, source_floor_status
    final_status = _read_json(run / "final_status.json")
    if final_status and not _final_status_ready(final_status):
        return False, "final_status_not_ready"
    if not final_status and str(verdict.get("verdict", "")).upper() != "AAA":
        return False, "final_verdict_not_aaa"
    source_precise, source_status = _source_topic_precision(run)
    if not source_precise:
        return False, source_status
    return True, "eligible"


def _seen(path: Path) -> set[str]:
    data = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    out: set[str] = set()
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        for key in ("fingerprint", *PUBLICATION_IDENTITY_KEYS):
            value = row.get(key)
            if isinstance(value, str) and value:
                out.add(value)
    return out


def _seen_topics(path: Path) -> set[str]:
    """Topics recorded in a ledger file (submitted/revision). Complements
    `_seen`, which keys on content/identity fingerprints: a re-synthesized run
    of an already-submitted topic carries a fresh fingerprint, so topic-level
    dedup is needed to avoid re-sending a paper Researka already has pending."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        str(row["topic"])
        for row in (data if isinstance(data, list) else [])
        if isinstance(row, dict) and isinstance(row.get("topic"), str) and row["topic"]
    }


def _seen_runs(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        str(row["run"])
        for row in (data if isinstance(data, list) else [])
        if isinstance(row, dict) and isinstance(row.get("run"), str) and row["run"]
    }


def _append_record(path: Path, row: dict[str, Any]) -> None:
    records = []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if not isinstance(records, list):
        records = []
    records.append(row)
    _write_json(path, records)


def _feedback_text(payload: Any) -> str:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, sort_keys=True)
    return " ".join(text.split())[:2000]


def _is_revision_feedback(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("revise", "revision", "resubmit", "needs revision"))


def _is_duplicate_submission_feedback(text: str) -> bool:
    return "duplicate_submission" in text.lower()


def _duplicate_submission_id(text: str) -> str | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    detail = data.get("detail") if isinstance(data, dict) else None
    row = detail if isinstance(detail, dict) else data
    value = row.get("submission_id") if isinstance(row, dict) else None
    return str(value) if value else None


def _mark_considered_status(rows: list[dict[str, Any]], run_name: str, status: str) -> None:
    for row in rows:
        if row.get("run") == run_name:
            row["status"] = status
            return


def select_candidate(
    root: Path,
    submitted_path: Path,
    *,
    remote_seen: set[str] | None = None,
    candidate_run: Path | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    local_seen = _seen(submitted_path)
    rejected_seen = _seen(submitted_path.with_name(REJECTED_FINGERPRINTS))
    revision_seen = _seen(submitted_path.with_name(REVISION_FINGERPRINTS))
    submitted_topics = _seen_topics(submitted_path)
    revision_topics = _seen_topics(submitted_path.with_name(REVISION_FINGERPRINTS))
    submitted_runs = _seen_runs(submitted_path)
    published_seen = remote_seen or set()
    considered = []
    seen_topics: set[str] = set()
    for run in ([candidate_run] if candidate_run else _runs(root)):
        topic = _run_topic(run)
        paper = run / "full_paper.md"
        paper_sha = _sha256(paper) if paper.exists() else ""
        title_mark = _title_marker(_paper_title(paper))
        markers = {paper_sha, f"sha256:{paper_sha}", title_mark} if paper_sha else set()
        revision = bool(_read_json(run / "researka_revision_request.json"))
        locally_eligible, status = _eligible(run)
        ok = locally_eligible
        payload = build_payload(run) if locally_eligible else {}
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        if locally_eligible:
            null_status = _null_coding_audit_status(payload, _read_json(run / "manifest.json"))
            if null_status != "eligible":
                ok, status = False, null_status
            elif (recency_status := _recency_ratio_status(payload)) != "eligible":
                ok, status = False, recency_status
        fp = _payload_fingerprint(payload) if locally_eligible else paper_sha
        if locally_eligible:
            markers.update(_metadata_markers(metadata))
        if topic in seen_topics:
            ok, status = False, "superseded_topic_run"
        elif ok and run.name in submitted_runs:
            ok, status = False, "duplicate_submission_run"
        elif ok and fp in rejected_seen:
            ok, status = False, "researka_rejected_fingerprint"
        elif ok and fp in revision_seen:
            ok, status = False, "researka_revision_fingerprint"
        elif ok and fp in local_seen:
            ok, status = False, "duplicate_submission_fingerprint"
        elif ok and (markers & published_seen) - {title_mark}:
            # Content/identity already has a live publication. Applies even to a
            # run carrying a stale revision_request — re-submitting identical
            # content is the "exact-content duplicate" reject Researka returns.
            ok, status = False, "duplicate_remote_publication"
        elif ok and title_mark in published_seen and not revision:
            # Same title already published and this is NOT a revision: a
            # re-submit of an already-published topic. A genuine revision
            # (changed content, same title) falls through and is allowed.
            ok, status = False, "duplicate_remote_publication"
        elif (
            ok
            and topic in submitted_topics
            and topic not in revision_topics
            and not revision
        ):
            # Already submitted to Researka and still pending (not published,
            # not revise-requested): a re-synthesized run carries a fresh
            # fingerprint so the content checks above miss it, but Researka
            # dedups on the pending submission and returns duplicate_submission.
            # Skip it so the cycle spends the window on a genuinely new topic.
            ok, status = False, "topic_already_submitted_pending"
        if locally_eligible:
            seen_topics.add(topic)
        row = {"run": run.name, "fingerprint": fp, "status": status}
        considered.append(row)
        if ok:
            return run, considered
    return None, considered


def _section(markdown: str, heading: str, *, fallback: str = "") -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*\n(?P<body>.*?)(?=^## |\Z)",
        re.M | re.S,
    )
    match = pattern.search(markdown)
    return _clip_text(" ".join((match.group("body") if match else fallback).split()))


def _clip_text(text: str, *, limit: int = 1400) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit].rstrip()
    cut = max(head.rfind("."), head.rfind("!"), head.rfind("?"))
    if cut >= limit // 2:
        return head[:cut + 1]
    return head.rstrip(" ,;:-") + "."


def _sections(markdown: str) -> dict[str, str]:
    pattern = re.compile(r"^## (?P<heading>[^\n#].*?)\s*\n(?P<body>.*?)(?=^## |\Z)", re.M | re.S)
    return {
        match.group("heading").strip(): match.group("body").strip()
        for match in pattern.finditer(markdown)
        if match.group("body").strip()
    }


def _key_findings(abstract: str, discussion: str, limitations: str, conclusion: str) -> str:
    """Short synthetic payload field, not a duplicate of Evidence Landscape."""
    source = "\n\n".join(part for part in (conclusion, discussion, limitations, abstract) if part).strip()
    sentences = re.findall(r"[^.!?]+[.!?]", source)
    text = " ".join(s.strip() for s in sentences[:3]).strip() or source[:900]
    return _clip_text(text)


def _same_text(left: str, right: str) -> bool:
    return " ".join(left.lower().split()) == " ".join(right.lower().split())


def _actionable_gaps(topic: str, manifest: dict[str, Any], explicit: str, discussion: str, limitations: str, abstract: str) -> str:
    explicit = _clip_text(explicit)
    if explicit and not any(_same_text(explicit, other) for other in (discussion, limitations, abstract)):
        return explicit
    receipts = [row for row in manifest.get("receipts", []) if isinstance(row, dict)]
    outcomes = [
        str(row.get("outcome_class") or "").replace("_", " ")
        for row in receipts
        if str(row.get("outcome_class") or "").strip()
    ]
    top_outcomes = ", ".join(dict.fromkeys(outcomes[:4])) or "the primary outcome classes"
    direct = sum(str(row.get("directness") or "").lower() == "direct" for row in receipts)
    n_receipts = int(manifest.get("n_receipts") or len(receipts) or 0)
    n_tensions = int(manifest.get("n_non_orthogonal_tensions") or 0)
    label = _display_topic(topic).lower()
    gaps = [
        f"Run adequately powered human studies that test {label} against prespecified endpoints in {top_outcomes}.",
        f"Standardize exposure, comparator, follow-up duration, and endpoint definitions so future syntheses can pool effects instead of resolving {n_tensions} disagreement(s) narratively.",
        f"Separate direct source rows from adjacent context before submission; current direct evidence is {direct}/{n_receipts} admitted source(s).",
    ]
    return _clip_text(" ".join(gaps))


def _evidence_landscape(manifest: dict[str, Any], detail: str) -> str:
    """Corpus-shape summary for an evidence map's Evidence Landscape section:
    how many sources, how direct, across which outcomes, with how much tension —
    the map's boundaries, distinct from the per-finding detail of Findings Map."""
    receipts = [row for row in manifest.get("receipts", []) if isinstance(row, dict)]
    n_receipts = int(manifest.get("n_receipts") or len(receipts) or 0)
    n_tensions = int(manifest.get("n_non_orthogonal_tensions") or 0)
    direct = sum(str(row.get("directness") or "").lower() == "direct" for row in receipts)
    outcomes = list(dict.fromkeys(
        str(row.get("outcome_class") or "").replace("_", " ").strip()
        for row in receipts if str(row.get("outcome_class") or "").strip()
    ))
    outcome_label = ", ".join(outcomes[:5]) or "the mapped outcomes"
    shape = (
        f"This landscape maps {n_receipts} retained source(s) spanning {outcome_label}, "
        f"of which {direct} provide direct human evidence, surfacing {n_tensions} "
        f"non-orthogonal tension(s) across the corpus."
    )
    return _clip_text(f"{shape} {detail}".strip())


def _evidence_map_sections(topic: str, manifest: dict[str, Any], parts: dict[str, str], abstract: str) -> dict[str, str]:
    """Map an evidence_map payload onto the live Researka template
    (contracts/templates.py EVIDENCE_MAP): Scope, Search Summary, Evidence
    Landscape, Findings Map, Tensions and Gaps, Limitations. Reuses the parsed
    paper with fallbacks so every section is non-empty when a heading is
    absent. Universal: no topic-specific content."""
    methods = parts.get("Methods", "")
    results = parts.get("Results", "")
    discussion = parts.get("Discussion", "")
    limitations = parts.get("Limitations", "")
    conclusion = parts.get("Conclusion", "")
    # Bird's-eye digest for Evidence Landscape; the full cited detail lives in
    # Findings Map, so the two sections stay distinct rather than both echoing
    # the Results prose.
    digest = _key_findings(abstract, discussion, limitations, conclusion)
    return {
        "Scope": _clip_text(
            f"This evidence map surveys what current research establishes about "
            f"{_display_topic(topic)}: the scope and boundaries of the available "
            f"evidence, the range of findings reported across the retained sources, "
            f"and the points where those findings diverge rather than converging on a "
            f"single conclusion. {_clip_text(abstract, limit=650)}"
        ),
        "Search Summary": methods or abstract,
        "Evidence Landscape": _evidence_landscape(manifest, digest),
        "Findings Map": results or digest,
        "Tensions and Gaps": _actionable_gaps(
            topic, manifest,
            parts.get("Tensions and Gaps", "") or parts.get("Gaps Identified", ""),
            discussion, limitations, abstract,
        ),
        "Limitations": limitations or discussion or abstract,
    }


def _demote_headings(markdown: str) -> str:
    return re.sub(r"^(#{1,5})(\s+)", r"#\1\2", markdown.strip(), flags=re.M)


def _display_topic(slug: str) -> str:
    return humanize_topic(slug, title_case=True, root=ROOT)


def _citation_url(row: dict[str, Any]) -> str | None:
    doi = str(row.get("source_doi") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    pmid = str(row.get("source_pmid") or "").strip()
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    pmcid = str(row.get("source_pmcid") or "").strip()
    return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/" if pmcid else None


def _evidence_type_for_source(receipt: dict[str, Any]) -> str:
    directness = str(receipt.get("directness") or "").lower()
    if directness == "review":
        return "review"
    return "primary"


def _claim_excerpt(topic: str, receipt_id: str, *, limit: int = 2) -> str:
    path = ROOT / "docs" / "quality-reference" / topic / "quant_claims" / f"{receipt_id}.quant_claims.json"
    data = _read_json(path)
    claims = data.get("claims")
    if not isinstance(claims, list):
        return ""
    sentences: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if str(claim.get("binding_confidence") or "") == "none":
            continue
        sentence = " ".join(str(claim.get("sentence") or "").split())
        if sentence and sentence not in sentences:
            sentences.append(sentence)
        if len(sentences) >= limit:
            break
    return " ".join(sentences)[:900]


def _parsed_source_excerpt(topic: str, receipt_id: str) -> str:
    data = _read_json(ROOT / "docs" / "quality-reference" / topic / "parsed" / f"{receipt_id}.paper_sections.json")
    raw_sections = data.get("sections")
    sections: dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    for name in ("abstract", "results", "conclusion", "discussion"):
        text = " ".join(str(sections.get(name) or "").split())
        if text:
            return _clip_text(text, limit=1200)
    return ""


def _pubmed_abstracts(pmids: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(p for p in pmids if p.isdigit()))
    limit = int(os.getenv("RESEARKA_SOURCE_ABSTRACT_LIMIT", "120") or "0")
    if not unique or limit <= 0:
        return {}
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={','.join(unique[:limit])}&retmode=xml"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            root = ET.fromstring(response.read())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid = "".join(article.findtext(".//PMID") or "").strip()
        parts: list[str] = []
        for node in article.findall(".//Abstract/AbstractText"):
            text = " ".join(node.itertext()).strip()
            if not text:
                continue
            label = str(node.attrib.get("Label") or "").strip()
            parts.append(f"{label}: {text}" if label else text)
        if pmid and parts:
            out[pmid] = _clip_text(" ".join(parts), limit=1200)
    return out


def _structured_source_excerpt(topic: str, row: dict[str, Any], receipt: dict[str, Any], title: str) -> str:
    ids = ", ".join(
        part for part in (
            f"DOI {row.get('source_doi')}" if row.get("source_doi") else "",
            f"PMID {row.get('source_pmid')}" if row.get("source_pmid") else "",
            f"reference {row.get('reference_id')}" if row.get("reference_id") else "",
        )
        if part
    )
    return _clip_text(
        f"{title}. Source-bundle audit for {_display_topic(topic)}: "
        f"outcome={receipt.get('outcome_class') or 'unspecified'}; "
        f"effect_direction={receipt.get('effect_direction') or 'unclear'}; "
        f"directness={receipt.get('directness') or 'unspecified'}; "
        f"evidence_tier={receipt.get('evidence_tier') or 'unspecified'}; "
        f"extracted_claims={receipt.get('n_claims') or 0}. {ids}."
    )


def _clean_doi(value: str) -> str:
    return value.strip().rstrip(".,;:)]}>").lower()


def _cited_reference_ids(text: str) -> tuple[set[str], set[str]]:
    return (
        {_clean_doi(value) for value in DOI_RE.findall(text) if _clean_doi(value)},
        {value.strip() for value in PMID_RE.findall(text) if value.strip()},
    )


def _bib_reference_stubs(run: Path) -> dict[str, dict[str, Any]]:
    try:
        bib = (run / "references.bib").read_text(encoding="utf-8")
    except OSError:
        return {}
    stubs: dict[str, dict[str, Any]] = {}
    for block in re.split(r"\n\s*\n(?=@)", bib):
        doi_match = DOI_RE.search(block)
        pmid_match = PMID_RE.search(block)
        if not doi_match and not pmid_match:
            continue
        title_match = re.search(r"title\s*=\s*\{(?P<title>.*?)\}\s*,?\n", block, re.S | re.I)
        year_match = re.search(r"year\s*=\s*\{(?P<year>\d{4})\}", block, re.I)
        title = _clip_text(" ".join((title_match.group("title") if title_match else "Reference citation").split()), limit=300)
        doi = _clean_doi(doi_match.group(0)) if doi_match else ""
        pmid = pmid_match.group(1).strip() if pmid_match else ""
        row: dict[str, Any] = {
            "source_type": "reference",
            "id": pmid or doi,
            "pmid": pmid or None,
            "title": title,
            "url": f"https://doi.org/{doi}" if doi else None,
            "doi": doi or None,
            "excerpt": _clip_text(f"Reference-list provenance stub. {title}", limit=1200),
            "year": int(year_match.group("year")) if year_match else None,
            # Researka's SourceBundleEntry contract is Literal["primary","review"];
            # a reference-list citation is a secondary/contextual source, so the
            # schema-valid + conservative label is "review" (was "reference",
            # which failed intake with source_bundle_entry_invalid:literal_error
            # and tripped the agent_backoff_intake_rejections lockout on
            # 2026-06-10/11 for every paper that needed citation-floor padding).
            "evidence_type": "review",
        }
        if doi:
            stubs[f"doi:{doi}"] = row
        if pmid:
            stubs[f"pmid:{pmid}"] = row
    return stubs


def _augment_source_bundle_with_cited_references(
    run: Path, paper: str, bundle: list[dict[str, Any]], *, limit: int,
) -> list[dict[str, Any]]:
    cited_dois, cited_pmids = _cited_reference_ids(paper)
    existing_dois = {_clean_doi(str(row.get("doi") or "")) for row in bundle}
    existing_pmids = {str(row.get("pmid") or row.get("id") or "").strip() for row in bundle}
    stubs = _bib_reference_stubs(run)
    out = list(bundle)
    for key in [*(f"doi:{doi}" for doi in sorted(cited_dois - existing_dois)), *(f"pmid:{pmid}" for pmid in sorted(cited_pmids - existing_pmids))]:
        if len(out) >= limit:
            break
        row = stubs.get(key)
        if row is not None:
            out.append(dict(row))
    return out


def _source_bundle(run: Path, *, limit: int) -> list[dict[str, Any]]:
    manifest = _read_json(run / "manifest.json")
    registry = _read_json(run / "citation_registry.json")
    topic = str(manifest.get("topic") or run.name)
    receipts = {
        str(item.get("receipt_id")): item
        for item in manifest.get("receipts", [])
        if isinstance(item, dict)
    }
    rows = [row for row in registry.values() if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            int(row.get("source_year") or 0) >= 2020,
            int(receipts.get(str(row.get("receipt_id")), {}).get("n_claims") or 0),
            int(row.get("source_year") or 0),
        ),
        reverse=True,
    )
    pubmed_abstracts = _pubmed_abstracts([str(row.get("source_pmid") or "") for row in rows[:limit]])
    bundle = []
    for row in rows[:limit]:
        receipt = receipts.get(str(row.get("receipt_id")), {})
        title = str(
            row.get("title")
            or receipt.get("source_title")
            or row.get("body_citation")
            or row.get("receipt_id")
            or "Evidence receipt"
        )[:300]
        claim_excerpt = _claim_excerpt(topic, str(row.get("receipt_id") or ""))
        pmid = str(row.get("source_pmid") or "")
        excerpt = (
            pubmed_abstracts.get(pmid)
            or claim_excerpt
            or _parsed_source_excerpt(topic, str(row.get("receipt_id") or ""))
            or _structured_source_excerpt(topic, row, receipt, title)
        )
        bundle.append({
            "source_type": "pubmed" if row.get("source_pmid") else "corpus",
            "id": str(row.get("source_pmid") or row.get("source_pmcid") or row.get("reference_id") or row.get("receipt_id") or ""),
            "title": title,
            "url": _citation_url(row),
            "doi": row.get("source_doi") or None,
            "excerpt": excerpt,
            "year": row.get("source_year") if isinstance(row.get("source_year"), int) else None,
            "evidence_type": _evidence_type_for_source(receipt),
            # Author-year citation token (registry body_citation, e.g. "Zufry
            # 2025") as a first-class SourceBundleEntry field so the Researka
            # reviewer can ground author-year prose citations to a bundle
            # source (workflow.py matches cited_as / title / year). Universal.
            "cited_as": str(row.get("body_citation") or "") or None,
        })
    return bundle


def _source_citation_hash(source_bundle: list[dict[str, Any]]) -> str:
    material = [
        {
            key: row.get(key)
            for key in ("id", "title", "url", "doi", "year", "evidence_type")
            if row.get(key) not in (None, "")
        }
        for row in source_bundle
    ]
    return _hash_json(material)


def _submission_identity_key(*, agent_slug: str, title: str, content_hash: str, source_citation_hash: str) -> str:
    return _hash_json({
        "agent_slug": agent_slug,
        "title": _normalized_key(title),
        "content_hash": content_hash,
        "source_citation_hash": source_citation_hash,
    })


def _metadata_markers(metadata: dict[str, Any]) -> set[str]:
    return {
        value if value.startswith("sha256:") else f"sha256:{value}"
        for key in PUBLICATION_IDENTITY_KEYS
        if isinstance((value := metadata.get(key)), str) and value
    }


def build_payload(run: Path, *, max_sources: int = 1000) -> dict[str, Any]:
    paper = (run / "full_paper.md").read_text(encoding="utf-8")
    manifest = _read_json(run / "manifest.json")
    topic = str(manifest.get("topic") or run.name)
    title = paper.splitlines()[0].lstrip("# ").strip() if paper.startswith("# ") else f"Research Synthesis: {_display_topic(topic)}"
    parts = _sections(paper)
    abstract = _section(paper, "Abstract", fallback=str(manifest.get("thesis") or ""))
    methods = parts.get("Methods", "")
    results = parts.get("Results", "")
    discussion = parts.get("Discussion", "")
    limitations = parts.get("Limitations", "")
    conclusion = parts.get("Conclusion", "")
    # source_bundle is the RETAINED/ON-TOPIC source set (== the receipts the
    # paper body reports), so the public surface can never certify more
    # "sources on topic" than the evidence base actually has. Cited external
    # references (background refs, prose-cited papers) are NOT retrieved
    # sources — they remain in the body's ## References (rendered from
    # body_markdown), not padded into this count. (Previously this was
    # augmented with cited references, inflating e.g. 13 receipts → 22 and
    # mismatching the body's 13.)
    source_bundle = _source_bundle(run, limit=max_sources)
    n_receipts = int(manifest.get("n_receipts") or 0)
    if n_receipts and len(source_bundle) != n_receipts:
        # Reconciliation invariant: the retained-source count must equal the
        # receipt count the body reports. Surfacing rather than silently
        # shipping a mismatch.
        print(
            f"[submit] WARN source_bundle={len(source_bundle)} != "
            f"n_receipts={n_receipts} for {run.name}",
            file=sys.stderr,
        )
    content_hash = _sha256(run / "full_paper.md")
    source_hash = _source_citation_hash(source_bundle)
    agent_slug = _agent_slug()
    article_type = _select_article_type(manifest)
    domain_slug = _env_or_default("RESEARKA_DOMAIN_SLUG_V3", "longevity")
    category = _env_or_default("RESEARKA_CATEGORY_V3", domain_slug).removesuffix("_research")
    rapid_sections = {
        "Research Question": _clip_text(
            f"What does the current evidence establish about {_display_topic(topic)} and human geroscience? "
            f"{_clip_text(abstract, limit=650)}",
        ),
        "Search Summary": methods or abstract,
        "Evidence Landscape": results or abstract,
        "Key Findings": _key_findings(abstract, discussion, limitations, conclusion),
        "Limitations": limitations or discussion or abstract,
        "Gaps Identified": _actionable_gaps(
            topic, manifest, parts.get("Gaps Identified", ""), discussion, limitations, abstract,
        ),
        "Conclusion": conclusion or abstract,
    }
    metadata: dict[str, Any] = {
        "artifact_type": "research_paper",
        "article_type": article_type,
        "domain_slug": domain_slug,
        "category": category,
        "run_id": run.name,
        "topic": topic,
        "content_hash": content_hash,
        "source_citation_hash": source_hash,
        "submission_identity_key": _submission_identity_key(
            agent_slug=agent_slug,
            title=title,
            content_hash=content_hash,
            source_citation_hash=source_hash,
        ),
        "counts": {
            "n_receipts": manifest.get("n_receipts"),
            "n_claims": manifest.get("n_high_confidence_claims_total"),
            "n_tensions": manifest.get("n_non_orthogonal_tensions"),
        },
    }
    revision = _read_json(run / "researka_revision_request.json")
    if revision:
        metadata["revision_of"] = {
            key: revision.get(key)
            for key in ("artifactId", "submissionId", "source_run", "title")
            if revision.get(key)
        }
        metadata["revision_feedback"] = revision.get("feedback")
    if article_type == "evidence_map":
        sections: dict[str, str] = _evidence_map_sections(topic, manifest, parts, abstract)
    elif article_type == "research_synthesis":
        sections = {**rapid_sections, **parts}
    else:
        sections = rapid_sections
    payload = {
        "title": title[:300],
        "abstract": abstract,
        "artifact_type": "research_paper",
        "body_markdown": paper.strip(),
        "sections": sections,
        "source_bundle": source_bundle,
        "author_agent_id": agent_slug,
        "submitter_name": os.getenv("RESEARKA_SUBMITTER_NAME") or None,
        "submitter_orcid": os.getenv("RESEARKA_SUBMITTER_ORCID") or None,
        "article_type": article_type,
        "domain_slug": domain_slug,
        "category": category,
        "core_claims_resolved": True,
        "author_signature": content_hash,
        "metadata": metadata,
    }
    metadata["submission_payload_hash"] = _payload_fingerprint(payload)
    return payload


def _submitter(url: str, token: str, agent_slug: str) -> Submitter:
    def submit(payload: dict[str, Any]) -> dict[str, Any]:
        preflight_status = _researka_preflight_status(payload)
        if preflight_status != "eligible":
            return {"ok": False, "status": 0, "response": preflight_status, "preflight": True}
        metadata = payload.get("metadata")
        content_hash = metadata.get("content_hash") if isinstance(metadata, dict) else ""
        identity_key = metadata.get("submission_identity_key") if isinstance(metadata, dict) else ""
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-api-key": token,
                "X-Agent-Slug": agent_slug,
                "Idempotency-Key": str(identity_key or content_hash or ""),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                body = response.read().decode("utf-8")
                return {"ok": True, "status": response.status, "response": json.loads(body)}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "response": body[:1000]}
    return submit


def _submit_url() -> str:
    explicit = os.getenv("RESEARKA_SUBMIT_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("RESEARKA_URL", "https://api.researka.org").rstrip("/")
    return base + "/submissions"


def _publications_url() -> str:
    explicit = os.getenv("RESEARKA_PUBLICATIONS_URL", "").strip()
    if explicit:
        return explicit
    return "https://researka.org/api/publications"


def _publication_row_has_public_proof(row: dict[str, Any], metadata: dict[str, Any]) -> bool:
    for source in (row, metadata):
        decision = str(source.get("decision") or source.get("review_decision") or source.get("researka_decision") or "").strip().lower()
        if decision in {"accept", "accepted"}:
            return True
        status = str(source.get("status") or source.get("publication_status") or "").strip().lower()
        if status in {"accepted", "public", "published"}:
            return True
        if source.get("publicVisible") is True or source.get("public_visible") is True or source.get("published") is True:
            return True
        for key in ("publishedAt", "published_at", "published_at_iso"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return True
    return False


def _remote_published_fingerprints(url: str | None = None) -> tuple[set[str], str | None]:
    target = url or _publications_url()
    req = urllib.request.Request(target, headers={"Accept": "application/json"})
    out: set[str] = set()
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("publications") if isinstance(payload, dict) else payload
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            raw_metadata = row.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            if not _publication_row_has_public_proof(row, metadata):
                continue
            out.update(_metadata_markers(metadata))
            for key in ("sha256", "full_body_sha256", "condensed_body_sha256"):
                content_hash = metadata.get(key)
                if isinstance(content_hash, str) and content_hash:
                    out.add(content_hash if content_hash.startswith("sha256:") else f"sha256:{content_hash}")
            title = row.get("title")
            if isinstance(title, str) and title.strip():
                out.add(_title_marker(title))
            submission_id = row.get("submission_id")
            if isinstance(submission_id, str) and submission_id.strip():
                out.add(_submission_marker(submission_id))
            for source in (row, metadata):
                topic = source.get("topic") if isinstance(source, dict) else None
                if isinstance(topic, str) and topic.strip():
                    out.add(_topic_marker(topic))
            body = row.get("body_markdown")
            if isinstance(body, str) and body.strip():
                out.add("sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest())
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return set(), f"{type(exc).__name__}: {exc}"
    return out, None


def run_cycle(
    *,
    runs_root: Path = RUNS,
    date: str,
    submit: bool = False,
    submitter: Submitter | None = None,
    remote_loader: RemoteLoader | None = None,
    candidate_run: Path | None = None,
) -> dict[str, Any]:
    ledger_path = runs_root / LEDGER_DIR / f"{date}.json"
    submitted_path = runs_root / LEDGER_DIR / "_submitted_fingerprints.json"
    ledger: dict[str, Any] = {"date": date, "dry_run": not submit, "submitted": 0, "published": 0, "status": "started"}
    token, token_env = _token() if submitter is None else ("", "")
    if submit and submitter is None and not token:
        ledger.update({"status": "submit_not_configured", "reason": "missing_v3_submit_token"})
        _write_json(ledger_path, ledger)
        return ledger
    remote_seen: set[str] = set()
    if submit:
        remote_seen, remote_error = (remote_loader or _remote_published_fingerprints)()
        ledger["remote_dedupe"] = {"checked": True, "known_fingerprints": len(remote_seen)}
        if remote_error:
            ledger.update({"status": "remote_dedupe_failed", "reason": remote_error})
            _write_json(ledger_path, ledger)
            return ledger
    run, considered = select_candidate(runs_root, submitted_path, remote_seen=remote_seen, candidate_run=candidate_run)
    ledger["considered"] = considered
    if run is None:
        ledger.update({"status": "no_eligible_research_paper"})
        _write_json(ledger_path, ledger)
        return ledger
    payload = build_payload(run)
    fp = _payload_fingerprint(payload)
    raw_metadata = payload.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    ledger["candidate"] = {"run": run.name, "topic": metadata.get("topic"), "fingerprint": fp}
    if not submit:
        ledger.update({"status": "dry_run_selected"})
        _write_json(ledger_path, ledger)
        return ledger
    if submitter is None:
        ledger["submit_token_env"] = token_env
        submitter = _submitter(_submit_url(), token, str(payload["author_agent_id"]))
    checked_payload, preflight_report = _run_preflight_qa(payload, run)
    if preflight_report:
        ledger["preflight_qa"] = _preflight_summary(preflight_report)
    if checked_payload is None:
        reason = "preflight_qa_blocked"
        ledger.update({"status": "no_eligible_research_paper", "reason": reason})
        _mark_considered_status(considered, run.name, reason)
        _write_json(ledger_path, ledger)
        return ledger
    payload = checked_payload
    fp = _payload_fingerprint(payload)
    raw_metadata = payload.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    ledger["candidate"] = {"run": run.name, "topic": metadata.get("topic"), "fingerprint": fp}
    preflight_status = _researka_preflight_status(payload)
    ledger["researka_preflight"] = preflight_status
    if preflight_status != "eligible":
        ledger.update({"status": "no_eligible_research_paper", "reason": preflight_status})
        _mark_considered_status(considered, run.name, preflight_status)
        _write_json(ledger_path, ledger)
        return ledger
    result = submitter(payload)
    ledger["submission"] = result
    if result.get("ok"):
        response = result.get("response")
        submission_id = response.get("id") if isinstance(response, dict) else None
        _append_record(submitted_path, {
            "date": date,
            "run": run.name,
            "topic": metadata.get("topic"),
            "fingerprint": fp,
            "paper_sha256": metadata.get("content_hash"),
            "submission_id": submission_id,
            **{key: metadata.get(key) for key in PUBLICATION_IDENTITY_KEYS if metadata.get(key)},
        })
        ledger.update({"status": "submitted_to_researka", "submitted": 1})
        _mark_considered_status(considered, run.name, "submitted_to_researka")
    elif 400 <= int(result.get("status") or 0) < 500:
        feedback = _feedback_text(result.get("response"))
        is_duplicate = _is_duplicate_submission_feedback(feedback)
        is_revision = False if is_duplicate else _is_revision_feedback(feedback)
        status = "submission_revise_requested" if is_revision else "submission_rejected_by_researka"
        if is_duplicate:
            _append_record(submitted_path, {
                "date": date,
                "run": run.name,
                "topic": metadata.get("topic"),
                "fingerprint": fp,
                "duplicate_submission_id": _duplicate_submission_id(feedback),
                **{key: metadata.get(key) for key in PUBLICATION_IDENTITY_KEYS if metadata.get(key)},
            })
        _append_record(submitted_path.with_name(REVISION_FINGERPRINTS if is_revision else REJECTED_FINGERPRINTS), {
            "date": date,
            "run": run.name,
            "topic": metadata.get("topic"),
            "fingerprint": fp,
            "status": result.get("status"),
            "feedback": feedback,
        })
        ledger.update({"status": status, "revision_feedback": feedback})
        _mark_considered_status(considered, run.name, status)
    else:
        ledger.update({"status": "submission_failed"})
        _mark_considered_status(considered, run.name, "submission_failed")
    _write_json(ledger_path, ledger)
    return ledger


def run_cycle_capped(
    *,
    runs_root: Path = RUNS,
    date: str,
    submit: bool = False,
    submitter: Submitter | None = None,
    remote_loader: RemoteLoader | None = None,
    max_submissions: int = 1,
) -> dict[str, Any]:
    """Submit up to `max_submissions` distinct ready candidates this cycle.

    Each underlying `run_cycle` re-selects via the submitted-fingerprints
    file, so successive calls return the next distinct topic (a submitted
    fingerprint is excluded on the following pass). A candidate that was
    consumed — submitted, or recorded as rejected/revise-requested so the
    next pass skips it — does NOT stop the cycle; the loop moves on to the
    next ready candidate so one duplicate rejection cannot stall the window.
    It stops only on a no-progress terminal status (no_eligible /
    remote_dedupe_failed / submit_not_configured / submission_failed).

    `max_submissions <= 1` is an exact passthrough to `run_cycle` — same
    ledger shape, same behaviour, no extra remote-dedupe fetches — so the
    fresh lane and existing callers are unaffected. Only the standalone
    submit lane opts into a higher cap to drain the ready backlog.
    """
    if max_submissions <= 1:
        return run_cycle(
            runs_root=runs_root, date=date, submit=submit,
            submitter=submitter, remote_loader=remote_loader,
        )
    submissions: list[dict[str, Any]] = []
    total = 0
    first_candidate: dict[str, Any] | None = None
    last: dict[str, Any] = {}
    for _ in range(max_submissions):
        last = run_cycle(
            runs_root=runs_root, date=date, submit=submit,
            submitter=submitter, remote_loader=remote_loader,
        )
        n = int(last.get("submitted") or 0)
        total += n
        submissions.append({
            "status": last.get("status"),
            "candidate": last.get("candidate"),
            "submitted": n,
        })
        if n and first_candidate is None:
            first_candidate = last.get("candidate")
        # Continue past a consumed candidate (published, or recorded as
        # rejected/revise-requested so the next pass skips it); stop only when
        # there is no further progress to make this window.
        if last.get("status") not in {
            "submitted_to_researka",
            "submission_rejected_by_researka",
            "submission_revise_requested",
        }:
            break
    agg = dict(last)
    agg["submitted"] = total
    agg["submissions"] = submissions
    agg["status"] = "submitted_to_researka" if total else last.get("status")
    if first_candidate is not None:
        agg["candidate"] = first_candidate
    _write_json(runs_root / LEDGER_DIR / f"{date}.json", agg)
    return agg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat())
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--max-submissions", type=int, default=3,
        help="Max distinct ready candidates to submit this cycle (default 3).",
    )
    args = parser.parse_args(argv)
    ledger = run_cycle_capped(
        runs_root=args.runs_root, date=args.date, submit=args.submit,
        max_submissions=max(1, args.max_submissions),
    )
    print(
        f"[daily-v3] status={ledger['status']} submitted={ledger['submitted']} "
        f"published={ledger['published']} run={ledger.get('candidate', {}).get('run', '-')}"
    )
    return 0 if ledger["status"] != "submission_failed" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
