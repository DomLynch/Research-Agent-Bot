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
import urllib.parse
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
from agent.outcome_class_remap import unique_outcome_displays  # noqa: E402
from agent import publication_evidence as _publication_evidence  # noqa: E402
from agent.review_type import (  # noqa: E402
    COMPACT_REVIEW_TYPES,
    parse_review_type,
)
from agent.topic_display import humanize_topic  # noqa: E402
from citation_registry import (  # noqa: E402
    _body_citation_from_metadata,
    _title_citation_from_metadata,
)

RUNS = ROOT / "runs"
LEDGER_DIR = "_daily_research_paper_ledger"
CYCLE_LEDGER_DIR = "_daily_research_paper_cycle_ledger"
# Re-audit window for stale-audit self-heal: only recently produced runs are
# re-audited at submit time so a now-fixed audit check propagates without a
# re-synthesis. Bounds cost — historical runs are not re-audited every cycle.
STALE_AUDIT_REFRESH_WINDOW_S = 48 * 3600
MAX_SUBMIT_SELF_HEAL_CANDIDATES = 1
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
PUBLIC_RESEARCH_MIN_DIRECT_RECEIPTS = 4
SOURCE_BUNDLE_TOPIC_TOLERANCE_MIN_ROWS = 12
SOURCE_BUNDLE_TOPIC_TOLERANCE_MAX_MISSES = 2
SOURCE_BUNDLE_TOPIC_TOLERANCE_RATIO = 0.05
SOURCE_BUNDLE_INDIRECT_TOLERANCE_MIN_DIRECT = PUBLIC_RESEARCH_MIN_DIRECT_RECEIPTS
SOURCE_BUNDLE_INDIRECT_TOLERANCE_MAX_MISSES = 3
SOURCE_BUNDLE_INDIRECT_TOLERANCE_RATIO = 0.15
SOURCE_BUNDLE_MAPPING_TOLERANCE_MIN_ROWS = 20
SOURCE_BUNDLE_MAPPING_TOLERANCE_MAX_MISSING_CITATIONS = 3
SOURCE_BUNDLE_MAPPING_TOLERANCE_RATIO = 0.10
PUBLIC_BLOCKED_TITLE_PREFIXES = ("hypothesis-generating brief:",)
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
SUBMISSION_REQUIRED_FILES = (
    "full_paper.md",
    "manifest.json",
    "citation_registry.json",
    "full_paper.audit.json",
    "full_paper.journal_surface.json",
    "full_paper.final_verdict.json",
    "pre_submit_gate.json",
)
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


def _write_daily_submit_cycle_ledger(runs_root: Path, date: str, ledger: dict[str, Any]) -> None:
    payload = dict(ledger)
    payload["lane"] = "daily-submit"
    payload["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    _write_json(runs_root / CYCLE_LEDGER_DIR / f"{date}-daily-submit.json", payload)


def _default_cycle_date() -> str:
    return dt.datetime.now().astimezone().date().isoformat()


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
    for stale_path in (report_path, clean_path):
        try:
            stale_path.unlink()
        except OSError:
            pass
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
    runtime_error = proc.returncode not in {0, 2}
    if runtime_error:
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
    if mode == "shadow" or runtime_error:
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


def _title_markers(title: str) -> set[str]:
    raw = str(title or "").strip()
    if not raw:
        return set()
    variants = {raw}
    no_suffix = re.sub(r"\s+[—-]\s+full paper\s*$", "", raw, flags=re.I).strip()
    if no_suffix:
        variants.add(no_suffix)
    for value in list(variants):
        if ":" in value:
            tail = value.split(":", 1)[1].strip()
            if tail:
                variants.add(tail)
    return {_title_marker(value) for value in variants if value}


def _topic_marker(topic: str) -> str:
    return "topic:" + _normalized_key(topic)


def _submission_marker(submission_id: str) -> str:
    return "submission:" + submission_id.strip()


def _submission_ids_from_response(response: object) -> list[str]:
    if not isinstance(response, dict):
        return []
    submission = response.get("submission")
    job = response.get("job")
    values = [
        response.get("id"),
        response.get("submission_id"),
        submission.get("id") if isinstance(submission, dict) else None,
        job.get("target_object_id") if isinstance(job, dict) else None,
    ]
    return list(dict.fromkeys(
        value.strip() for value in values
        if isinstance(value, str) and value.strip()
    ))


def _submission_id_from_response(response: object) -> str | None:
    ids = _submission_ids_from_response(response)
    return ids[0] if ids else None


def _paper_title(paper: Path) -> str:
    try:
        first = paper.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return ""
    return first.lstrip("# ").strip()


def _env_or_default(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _clean_doi(value: object) -> str:
    return str(value or "").strip().rstrip(".,;")


_DOI_TEXT_RE = re.compile(r"(?i)(\bDOI:\s*)(10\.\d{4,9}/\S+)")


def _clean_doi_text(text: str) -> str:
    return _DOI_TEXT_RE.sub(lambda match: match.group(1) + _clean_doi(match.group(2)), text)


_BACKGROUND_REFERENCES_RE = re.compile(
    r"(?ims)^###\s+Background References\b.*?(?=^#{1,3}\s+\S|\Z)"
)


def _strip_background_references(text: str) -> str:
    return _BACKGROUND_REFERENCES_RE.sub("", text)


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


def _public_research_surface_status(run: Path) -> str:
    manifest = _read_json(run / "manifest.json")
    review_type = str(manifest.get("review_type") or "").strip()
    if review_type:
        try:
            if parse_review_type(review_type) in COMPACT_REVIEW_TYPES:
                return "public_research_surface_compact_review"
        except ValueError:
            return "public_research_surface_compact_review"
    return "eligible"


def _word_count(text: object) -> int:
    return len(str(text or "").split())


def _title_anchor_terms(title: object) -> tuple[str, ...]:
    subject = str(title or "").strip()
    if ":" in subject:
        subject = subject.split(":", 1)[1]
    subject = re.split(r"\s+[—–-]\s+|\s+--\s+", subject, maxsplit=1)[0]
    words = re.findall(r"[a-z0-9]+", subject.lower())
    words = [
        word for word in words
        if word not in {"full", "paper", "brief", "research", "synthesis", "hypothesis", "generating", "evidence", "adjacent"}
    ]
    terms = [" ".join(words)] if words else []
    terms.extend(word for word in words if len(word) >= 4 or any(ch.isdigit() for ch in word))
    return tuple(dict.fromkeys(term for term in terms if term))


def _findings_map_topic_anchor_status(payload: dict[str, Any]) -> str:
    if str(payload.get("article_type") or DEFAULT_ARTICLE_TYPE) != "evidence_map":
        return "eligible"
    sections_raw = payload.get("sections")
    sections = sections_raw if isinstance(sections_raw, dict) else {}
    findings = str(sections.get("Findings Map") or "")
    terms = _title_anchor_terms(payload.get("title"))
    if not findings.strip() or not terms:
        return "eligible"
    rows: list[str] = []
    for line in findings.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not cells[0] or set(cells[0]) <= {"-", ":"}:
            continue
        first = _normalized_key(cells[0])
        if first in {"evidence domain", "outcome class", "source context"}:
            continue
        rows.append(first)
    if not rows:
        return "eligible"
    weak = [row for row in rows if not any(term in row for term in terms)]
    if weak and len(weak) / len(rows) >= 0.5:
        return f"evidence_map_topic_anchor_low:{len(weak)}/{len(rows)}"
    return "eligible"


def _topic_anchored_title(title: str, topic: str) -> str:
    display = _display_topic(topic)
    match = re.match(r"(?P<prefix>.*?:\s*)(?P<subject>.*?)(?P<suffix>\s+[—–-]\s+.*)?$", title)
    if match:
        return f"{match.group('prefix')}{display}{match.group('suffix') or ''}"
    return f"Research Synthesis: {display}"


def _anchor_findings_map_rows(findings: str, topic: str) -> str:
    anchor = _display_topic(topic)
    anchor_norm = _normalized_key(anchor)
    out: list[str] = []
    for line in findings.splitlines():
        if not line.strip().startswith("|"):
            out.append(line)
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        first = _normalized_key(cells[0]) if cells else ""
        if not cells or first in {"evidence domain", "outcome class", "source context"} or set(cells[0]) <= {"-", ":"}:
            out.append(line)
            continue
        if not first.startswith(anchor_norm):
            cells[0] = f"{anchor} / {cells[0].split('/', 1)[-1].strip()}"
            line = "| " + " | ".join(cells) + " |"
        out.append(line)
    return "\n".join(out)


def _researka_preflight_status(payload: dict[str, Any], *, enforce_recency: bool = True) -> str:
    article_type = str(payload.get("article_type") or DEFAULT_ARTICLE_TYPE)
    sections_raw = payload.get("sections")
    sections: dict[str, Any] = sections_raw if isinstance(sections_raw, dict) else {}
    source_bundle_raw = payload.get("source_bundle")
    source_bundle = [row for row in source_bundle_raw if isinstance(row, dict)] if isinstance(source_bundle_raw, list) else []
    min_citations = int(_threshold(article_type, "min_citations"))
    if len(source_bundle) < min_citations:
        return f"researka_preflight_insufficient_sources:{len(source_bundle)} < {min_citations}"
    if (surface_status := _public_grade_surface_status(payload)) != "eligible":
        return surface_status
    if (bundle_status := _source_bundle_reconciliation_status(payload)) != "eligible":
        return bundle_status
    if (topic_status := _source_bundle_topic_status(payload)) != "eligible":
        return topic_status

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
    if enforce_recency and (recency_status := _recency_ratio_status(payload)) != "eligible":
        return recency_status
    if (doi_status := _doi_existence_status(payload)) != "eligible":
        return doi_status
    if (anchor_status := _findings_map_topic_anchor_status(payload)) != "eligible":
        return anchor_status
    if (breadth_status := _conclusion_breadth_status(payload)) != "eligible":
        return breadth_status
    if (domain_frame_status := _domain_frame_status(payload)) != "eligible":
        return domain_frame_status
    return "eligible"


def _final_status_ready(data: dict[str, Any]) -> bool:
    return bool(data.get("submission_ready") is True)


def _inside_refresh_window(run: Path) -> bool:
    try:
        age = dt.datetime.now(dt.UTC).timestamp() - run.stat().st_mtime
    except OSError:
        return False
    return age <= STALE_AUDIT_REFRESH_WINDOW_S


def _needs_submit_self_heal(run: Path) -> bool:
    if not _inside_refresh_window(run):
        return False
    audit = _read_json(run / "full_paper.audit.json")
    if audit and audit.get("p1_pass") is not True:
        return True
    surface = _read_json(run / "full_paper.journal_surface.json")
    if surface and surface.get("passed") is not True:
        return True
    if _read_json(run / "researka_revision_request.json"):
        gate = _read_json(run / REVISION_COVERAGE_GATE)
        if gate.get("passed") is False:
            return True
    return False


def _static_ineligible_status(run: Path, *, allow_recent_repair: bool = True) -> str | None:
    missing = [name for name in SUBMISSION_REQUIRED_FILES if not (run / name).exists()]
    if missing:
        return "missing:" + ",".join(missing)
    repairable = allow_recent_repair and _needs_submit_self_heal(run)
    audit = _read_json(run / "full_paper.audit.json")
    if audit and audit.get("p1_pass") is not True:
        if repairable:
            return None
        return "audit_p1_failed"
    surface = _read_json(run / "full_paper.journal_surface.json")
    if surface and surface.get("passed") is not True:
        if repairable:
            return None
        return "journal_surface_not_passed"
    pre_submit_status = _pre_submit_status(_read_json(run / "pre_submit_gate.json"))
    if pre_submit_status != "eligible":
        return pre_submit_status
    public_surface_status = _public_research_surface_status(run)
    if public_surface_status != "eligible":
        return public_surface_status
    request = _read_json(run / "researka_revision_request.json")
    if request:
        gate = _read_json(run / REVISION_COVERAGE_GATE)
        if gate.get("passed") is False:
            if _refresh_revision_coverage_gate(run, request):
                gate = _read_json(run / REVISION_COVERAGE_GATE)
            if gate.get("passed") is not False:
                return None
            if repairable:
                return None
            return "revision_coverage_unmet"
    source_floor_status = _source_floor_status(run)
    if source_floor_status != "eligible":
        return source_floor_status
    final_status = _read_json(run / "final_status.json")
    if final_status and not _final_status_ready(final_status):
        return "final_status_not_ready"
    verdict = _read_json(run / "full_paper.final_verdict.json")
    if not final_status and str(verdict.get("verdict", "")).upper() != "AAA":
        return "final_verdict_not_aaa"
    return None


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
        stale_unmet = gate.get("unmet_asks")
        asks = (
            [str(ask) for ask in stale_unmet if isinstance(ask, str) and ask.strip()]
            if isinstance(stale_unmet, list)
            else revision_coverage.revision_asks(feedback)
        )
        if not asks or len(revision_coverage.deterministic_known_asks(asks)) != len(asks):
            return False
        unmet = revision_coverage.deterministic_unmet_asks(
            text, asks, retained_citations=revision_coverage.retained_citation_labels(
                _read_json(run / "manifest.json"), _read_json(run / "citation_registry.json"),
            ),
        )
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
    if len(specific) > 1 and not any(
        count > 0 for token, count in coverage.items() if token != entity
    ):
        return 0, None
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


def _doi_existence_status(payload: dict[str, Any]) -> str:
    if os.getenv("RESEARKA_DOI_PREFLIGHT_ENABLED", "0").strip() != "1":
        return "eligible"
    bundle = payload.get("source_bundle")
    dois = sorted({
        _clean_doi(row.get("doi")).lower()
        for row in (bundle if isinstance(bundle, list) else [])
        if isinstance(row, dict) and _clean_doi(row.get("doi"))
    })
    if not dois:
        return "eligible"
    try:
        limit = max(1, int(os.getenv("RESEARKA_DOI_CHECK_MAX", "25")))
    except ValueError:
        limit = 25
    try:
        timeout = float(os.getenv("RESEARKA_DOI_CHECK_TIMEOUT_S", "3"))
    except ValueError:
        timeout = 3.0
    base_url = os.getenv("RESEARKA_DOI_RESOLVER_URL", "https://doi.org/api/handles").rstrip("/")
    missing: list[str] = []
    try:
        for doi in dois[:limit]:
            url = f"{base_url}/{urllib.parse.quote(doi, safe='/')}"
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    response.read(1)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    missing.append(doi)
                else:
                    return "eligible"
    except (OSError, urllib.error.URLError, TimeoutError):
        return "eligible"
    if missing:
        return "doi_exists_missing:" + ",".join(missing[:10])
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
        refreshed = _refresh_revision_coverage_gate(run, request)
        return bool(report.paper_changed or refreshed)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _eligible(run: Path) -> tuple[bool, str]:
    # Phase G refreshes all sidecars (audit + gate + accountability); run it at
    # most once — prefer the accountability path, else the stale-audit path.
    if not _refresh_stale_accountability_sidecar(run):
        _refresh_stale_audit_sidecar(run)
    missing = [name for name in SUBMISSION_REQUIRED_FILES if not (run / name).exists()]
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
    public_surface_status = _public_research_surface_status(run)
    if public_surface_status != "eligible":
        return False, public_surface_status
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


def _ledger_rows(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in (data if isinstance(data, list) else []) if isinstance(row, dict)]


def _seen(path: Path) -> set[str]:
    out: set[str] = set()
    for row in _ledger_rows(path):
        for key in ("fingerprint", *PUBLICATION_IDENTITY_KEYS):
            value = row.get(key)
            if isinstance(value, str) and value:
                out.add(value)
    return out


def _seen_field(path: Path, key: str) -> set[str]:
    return {
        str(row[key])
        for row in _ledger_rows(path)
        if isinstance(row.get(key), str) and row[key]
    }


def _submitted_count_for_date(path: Path, date: str) -> int:
    keys: set[str] = set()
    for row in _ledger_rows(path):
        if row.get("date") != date:
            continue
        value = row.get("run") or row.get("fingerprint")
        if isinstance(value, str) and value:
            keys.add(value)
    return len(keys)


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


def _remote_publication_duplicate_status(
    *,
    markers: set[str],
    title_marks: set[str],
    published_seen: set[str],
    revision: bool,
    explicit_candidate: bool,
) -> str | None:
    if (markers & published_seen) - title_marks:
        # Content/identity already has a live publication. Applies even to a run
        # carrying a stale revision_request — re-submitting identical content is
        # the "exact-content duplicate" reject Researka returns.
        return "duplicate_remote_publication"
    if title_marks & published_seen and not (revision and explicit_candidate):
        # Same title already published and this is NOT a revision: a re-submit of
        # an already-published topic. A genuine revision (changed content, same
        # title) falls through only when the revise lane explicitly hands us that
        # candidate. The generic submit sweep must not resurrect stale
        # revision_request files for public papers.
        return "duplicate_remote_publication"
    return None


def select_candidate(
    root: Path,
    submitted_path: Path,
    *,
    remote_seen: set[str] | None = None,
    candidate_run: Path | None = None,
    purpose: str = "resubmit",
    skip_topics: set[str] | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    local_seen = _seen(submitted_path)
    rejected_seen = _seen(submitted_path.with_name(REJECTED_FINGERPRINTS))
    revision_seen = _seen(submitted_path.with_name(REVISION_FINGERPRINTS))
    submitted_topics = _seen_field(submitted_path, "topic")
    revision_topics = _seen_field(submitted_path.with_name(REVISION_FINGERPRINTS), "topic")
    published_seen = remote_seen or set()
    considered = []
    seen_topics: set[str] = set()
    blocked_topics = skip_topics or set()
    repair_attempts = 0
    explicit_candidate = candidate_run is not None
    for run in ([candidate_run] if candidate_run else _runs(root)):
        topic = _run_topic(run)
        paper = run / "full_paper.md"
        paper_sha = _sha256(paper) if paper.exists() else ""
        title_marks = _title_markers(_paper_title(paper))
        markers = {paper_sha, f"sha256:{paper_sha}", *title_marks} if paper_sha else set(title_marks)
        revision = bool(_read_json(run / "researka_revision_request.json"))
        if topic in blocked_topics:
            considered.append({"run": run.name, "fingerprint": paper_sha, "status": "topic_already_consumed_this_window"})
            continue
        if topic in seen_topics:
            considered.append({"run": run.name, "fingerprint": paper_sha, "status": "superseded_topic_run"})
            continue
        needs_repair = _needs_submit_self_heal(run)
        allow_repair = repair_attempts < MAX_SUBMIT_SELF_HEAL_CANDIDATES
        if static_status := _static_ineligible_status(run, allow_recent_repair=allow_repair):
            considered.append({"run": run.name, "fingerprint": paper_sha, "status": static_status})
            continue
        if needs_repair:
            repair_attempts += 1
        locally_eligible, status = _eligible(run)
        ok = locally_eligible
        payload = build_payload(run) if locally_eligible else {}
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        if locally_eligible:
            title_marks.update(_title_markers(str(payload.get("title") or "")))
            markers.update(title_marks)
        if locally_eligible:
            null_status = _null_coding_audit_status(payload, _read_json(run / "manifest.json"))
            if null_status != "eligible":
                ok, status = False, null_status
            elif (anchor_status := _findings_map_topic_anchor_status(payload)) != "eligible":
                ok, status = False, anchor_status
            elif (
                not (purpose == "revision" and revision)
                and (recency_status := _recency_ratio_status(payload)) != "eligible"
            ):
                ok, status = False, recency_status
        fp = _payload_fingerprint(payload) if locally_eligible else paper_sha
        if locally_eligible:
            markers.update(_metadata_markers(metadata))
        if ok and fp in rejected_seen:
            ok, status = False, "researka_rejected_fingerprint"
        elif ok and fp in revision_seen:
            ok, status = False, "researka_revision_fingerprint"
        elif ok and fp in local_seen:
            ok, status = False, "duplicate_submission_fingerprint"
        elif ok and (
            remote_status := _remote_publication_duplicate_status(
                markers=markers,
                title_marks=title_marks,
                published_seen=published_seen,
                revision=revision,
                explicit_candidate=explicit_candidate,
            )
        ):
            ok, status = False, remote_status
        elif ok and revision and not explicit_candidate and topic in submitted_topics:
            ok, status = False, "revision_pending_for_revise_lane"
        elif ok and topic in submitted_topics and topic not in revision_topics and not revision:
            topic_rows = [
                row for row in _ledger_rows(submitted_path)
                if row.get("topic") == topic
            ]
            same_run_rows = [
                row for row in topic_rows
                if row.get("run") == run.name and not row.get("duplicate_submission_id")
            ]
            if same_run_rows and not any(
                fp in {row.get("fingerprint"), row.get("submission_payload_hash")}
                for row in same_run_rows
            ):
                if explicit_candidate:
                    status = "eligible_resubmission_after_payload_change"
                else:
                    ok, status = False, "topic_already_submitted_pending"
            else:
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


def _key_findings(abstract: str, results: str, discussion: str, limitations: str, conclusion: str) -> str:
    """Short synthetic payload field, distinct from Conclusion."""
    conclusion_norm = " ".join(conclusion.lower().split())
    findings: list[str] = []
    for source in (results, discussion, limitations, abstract, conclusion):
        prose = "\n".join(line for line in source.splitlines() if "|" not in line)
        for sentence in re.findall(r"[^.!?]+[.!?]", prose):
            sentence = " ".join(sentence.split())
            if not sentence:
                continue
            if findings or sentence.lower() not in conclusion_norm:
                findings.append(sentence)
            if len(findings) >= 3:
                break
        if len(findings) >= 3:
            break
    source = "\n\n".join(part for part in (results, discussion, limitations, abstract, conclusion) if part).strip()
    text = " ".join(findings).strip() or source[:900]
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
    tension_work = (
        "resolving the pairwise disagreement map"
        if _dense_tension_map(n_tensions, n_receipts)
        else f"resolving {n_tensions} disagreement(s) narratively"
    )
    gaps = [
        f"Run adequately powered human studies that test {label} against prespecified endpoints in {top_outcomes}.",
        f"Standardize exposure, comparator, follow-up duration, and endpoint definitions so future syntheses can pool effects instead of {tension_work}.",
        f"Separate direct source rows from adjacent context before submission; current direct evidence is {direct}/{n_receipts} admitted source(s).",
    ]
    return _clip_text(" ".join(gaps))


def _dense_tension_map(n_tensions: int, n_receipts: int) -> bool:
    return n_tensions > max(50, n_receipts * 3)


def _public_tension_summary(n_tensions: int, n_receipts: int) -> str:
    if n_tensions <= 0:
        return "no load-bearing cross-source disagreements"
    if _dense_tension_map(n_tensions, n_receipts):
        return "a high-density pairwise disagreement map"
    return f"{n_tensions} load-bearing cross-source disagreement(s)"


def _evidence_landscape(manifest: dict[str, Any], detail: str) -> str:
    """Corpus-shape summary for an evidence map's Evidence Landscape section:
    how many sources, how direct, across which outcomes, with how much tension —
    the map's boundaries, distinct from the per-finding detail of Findings Map."""
    receipts = [row for row in manifest.get("receipts", []) if isinstance(row, dict)]
    n_receipts = int(manifest.get("n_receipts") or len(receipts) or 0)
    n_tensions = int(manifest.get("n_non_orthogonal_tensions") or 0)
    direct = sum(str(row.get("directness") or "").lower() == "direct" for row in receipts)
    outcomes = list(unique_outcome_displays(
        str(row.get("outcome_class") or "").strip()
        for row in receipts if str(row.get("outcome_class") or "").strip()
    ))
    outcome_label = ", ".join(outcomes[:5]) or "the mapped outcomes"
    shape = (
        f"This landscape maps {n_receipts} retained source(s) spanning {outcome_label}, "
        f"of which {direct} provide direct human evidence, surfacing "
        f"{_public_tension_summary(n_tensions, n_receipts)} across the corpus."
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
    digest = _key_findings(abstract, results, discussion, limitations, conclusion)
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


def _display_topic(slug: str) -> str:
    return humanize_topic(slug, title_case=True, root=ROOT)


def _citation_url(row: dict[str, Any]) -> str | None:
    doi = _clean_doi(row.get("source_doi"))
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


SOURCE_CONTEXTS = frozenset({"direct", "adjacent", "mechanistic", "context"})


def _source_context_for_receipt(receipt: dict[str, Any]) -> str:
    directness = str(receipt.get("directness") or "").lower()
    outcome = str(receipt.get("outcome_class") or "").lower()
    if directness == "direct":
        return "direct"
    if directness == "mechanistic":
        return "mechanistic"
    if "context" in outcome or directness in {"protocol", "review"}:
        return "context"
    return "adjacent"


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
    ids = " | ".join(
        part for part in (
            f"DOI {_clean_doi(row.get('source_doi'))}" if _clean_doi(row.get("source_doi")) else "",
            f"PMID {row.get('source_pmid')}" if row.get("source_pmid") else "",
            f"reference {row.get('reference_id')}" if row.get("reference_id") else "",
        )
        if part
    )
    identifiers = f" Identifiers: {ids}" if ids else ""
    return _clip_text(
        f"{title}. Source-bundle audit for {_display_topic(topic)}: "
        f"outcome={receipt.get('outcome_class') or 'unspecified'}; "
        f"effect_direction={receipt.get('effect_direction') or 'unclear'}; "
        f"directness={receipt.get('directness') or 'unspecified'}; "
        f"evidence_tier={receipt.get('evidence_tier') or 'unspecified'}; "
        f"extracted_claims={receipt.get('n_claims') or 0}.{identifiers}"
    )


def _source_bundle(run: Path, *, limit: int) -> list[dict[str, Any]]:
    manifest = _read_json(run / "manifest.json")
    registry = _read_json(run / "citation_registry.json")
    topic = str(manifest.get("topic") or run.name)
    receipts = {
        str(item.get("receipt_id")): item
        for item in manifest.get("receipts", [])
        if isinstance(item, dict)
    }
    rows = _publication_evidence.source_rows(registry, receipts)
    rows.sort(
        key=lambda row: (
            int(row.get("source_year") or 0) >= 2020,
            int(receipts.get(str(row.get("receipt_id")), {}).get("n_claims") or 0),
            int(row.get("source_year") or 0),
        ),
        reverse=True,
    )
    pubmed_abstracts = _pubmed_abstracts([str(row.get("source_pmid") or "") for row in rows[:limit]])
    rob_ratings = _publication_evidence.risk_of_bias_ratings(run)
    bundle = []
    for row in rows[:limit]:
        receipt = receipts.get(str(row.get("receipt_id")), {})
        title = str(
            row.get("title")
            or receipt.get("source_title")
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
        receipt_id = str(row.get("receipt_id") or "")
        cited_as = str(row.get("body_citation") or "")
        rob = _publication_evidence.risk_of_bias_rating(rob_ratings, cited_as, receipt.get("citation_token"), receipt_id)
        bundle.append({
            "source_type": "pubmed" if row.get("source_pmid") else "corpus",
            "id": str(row.get("source_pmid") or row.get("source_pmcid") or row.get("reference_id") or row.get("receipt_id") or ""),
            "title": title,
            "url": _citation_url(row) or _publication_evidence.parsed_source_url(ROOT, topic, receipt_id),
            "doi": _clean_doi(row.get("source_doi")) or None,
            "pmid": str(row.get("source_pmid") or "") or None,
            "excerpt": excerpt,
            "quote": claim_excerpt or None,
            "year": row.get("source_year") if isinstance(row.get("source_year"), int) else None,
            "evidence_type": _evidence_type_for_source(receipt),
            "evidence_context": _source_context_for_receipt(receipt),
            "outcome_class": receipt.get("outcome_class") or None,
            "effect_direction": receipt.get("effect_direction") or None,
            "directness": receipt.get("directness") or None,
            "evidence_tier": receipt.get("evidence_tier") or None,
            # Author-year citation token (registry body_citation, e.g. "Zufry
            # 2025") as a first-class SourceBundleEntry field so the Researka
            # reviewer can ground author-year prose citations to a bundle
            # source (workflow.py matches cited_as / title / year). Universal.
            "cited_as": cited_as or None,
            "risk_of_bias": rob if _source_context_for_receipt(receipt) == "direct" else None,
        })
    return bundle


def _row_context(row: dict[str, Any]) -> str:
    context = str(row.get("evidence_context") or row.get("directness") or "").lower()
    if context in SOURCE_CONTEXTS:
        return context
    evidence_type = str(row.get("evidence_type") or "").lower()
    if evidence_type == "review":
        return "context"
    return "adjacent" if evidence_type == "primary" else ""


def _has_source_citation(row: dict[str, Any]) -> bool:
    cited_as = str(row.get("cited_as") or "")
    if re.search(r"\b(?:19|20)\d{2}\b", cited_as):
        return True
    normalized = " ".join(cited_as.lower().split()).rstrip(".")
    title = str(row.get("title") or "").strip()
    title_expected = _title_citation_from_metadata(
        {"title": title}, "n.d.",
    )
    expected = " ".join(str(title_expected or "").lower().split()).rstrip(".")
    matches_expected = bool(expected) and bool(
        normalized == expected or re.fullmatch(rf"{re.escape(expected)}\.[a-z]+", normalized)
    )
    if matches_expected:
        return True
    author = re.sub(r"\s+n\.d(?:\.[a-z]+)?\.?\s*$", "", cited_as, flags=re.I).strip()
    doi = _clean_doi(row.get("doi"))
    url = urllib.parse.urlparse(str(row.get("url") or "").strip())
    stable_locator = bool(
        re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.I)
        or url.scheme in {"http", "https"} and url.netloc
        or row.get("source_type") == "pubmed" and str(row.get("id") or "").strip().isdigit()
    )
    author_expected = _body_citation_from_metadata({
        "title": title, "authors": [author], "year": 9999,
    }) if author and stable_locator else None
    expected = " ".join(str(author_expected or "").lower().split()).rstrip(".")
    if expected and (
        normalized == expected or re.fullmatch(rf"{re.escape(expected)}\.[a-z]+", normalized)
    ):
        return True
    return bool(str(row.get("title") or "").strip() and isinstance(row.get("year"), int))


def _missing_citation_tolerated(bundle: list[dict[str, Any]], missing_citation: int) -> bool:
    if missing_citation <= 0:
        return True
    missing_rows = [row for row in bundle if not _has_source_citation(row)]
    return (
        len(bundle) >= SOURCE_BUNDLE_MAPPING_TOLERANCE_MIN_ROWS
        and missing_citation <= SOURCE_BUNDLE_MAPPING_TOLERANCE_MAX_MISSING_CITATIONS
        and missing_citation / len(bundle) <= SOURCE_BUNDLE_MAPPING_TOLERANCE_RATIO
        and all(_row_context(row) != "direct" for row in missing_rows)
    )


def _source_bundle_reconciliation_status(payload: dict[str, Any]) -> str:
    bundle = [row for row in payload.get("source_bundle", []) if isinstance(row, dict)]
    if not bundle:
        return "eligible"
    missing_context = sum(_row_context(row) not in SOURCE_CONTEXTS for row in bundle)
    if missing_context:
        return f"source_bundle_missing_context:{missing_context}/{len(bundle)}"
    missing_outcome = sum(not str(row.get("outcome_class") or "").strip() for row in bundle)
    missing_citation = sum(not _has_source_citation(row) for row in bundle)
    if missing_outcome or missing_citation:
        if (
            not missing_outcome
            and _missing_citation_tolerated(bundle, missing_citation)
        ):
            return "eligible"
        return f"source_bundle_unmapped_sources:outcome={missing_outcome},citation={missing_citation}"
    return "eligible"


def _public_grade_surface_status(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "").strip().lower()
    if title.startswith(PUBLIC_BLOCKED_TITLE_PREFIXES):
        return "public_surface_hypothesis_generating_brief"
    return "eligible"


def _source_bundle_topic_status(payload: dict[str, Any]) -> str:
    metadata_raw = payload.get("metadata")
    metadata: dict[str, Any] = metadata_raw if isinstance(metadata_raw, dict) else {}
    topic = str(metadata.get("topic") or payload.get("topic") or "").strip()
    bundle = [row for row in payload.get("source_bundle", []) if isinstance(row, dict)]
    if not topic or not bundle:
        return "eligible"
    aliases = source_gate_aliases(topic, topic_aliases(topic, root=ROOT, include_generated_terms=False))
    haystacks = [
        " ".join(
            str(row.get(key) or "")
            for key in ("title", "excerpt", "outcome_class", "evidence_context", "evidence_type", "directness")
        )
        for row in bundle
    ]
    misses: list[tuple[str, str]] = []
    direct_specific = 0
    for idx, (row, haystack) in enumerate(zip(bundle, haystacks), start=1):
        specific = is_source_topic_specific(topic, haystack, aliases=aliases)
        context = _row_context(row)
        if specific and context == "direct":
            direct_specific += 1
        if not specific:
            misses.append((str(idx), context))
    if misses:
        miss_ratio = len(misses) / len(bundle)
        if (
            len(bundle) >= SOURCE_BUNDLE_TOPIC_TOLERANCE_MIN_ROWS
            and len(misses) <= SOURCE_BUNDLE_TOPIC_TOLERANCE_MAX_MISSES
            and (
                len(misses) == 1
                or miss_ratio <= SOURCE_BUNDLE_TOPIC_TOLERANCE_RATIO
            )
        ):
            return "eligible"
        if (
            direct_specific >= SOURCE_BUNDLE_INDIRECT_TOLERANCE_MIN_DIRECT
            and len(misses) <= SOURCE_BUNDLE_INDIRECT_TOLERANCE_MAX_MISSES
            and miss_ratio <= SOURCE_BUNDLE_INDIRECT_TOLERANCE_RATIO
            and sum(context == "direct" for _, context in misses) <= 1
        ):
            return "eligible"
        return f"source_bundle_topic_mismatch:{len(misses)}/{len(bundle)}:rows={','.join(idx for idx, _ in misses[:5])}"
    return "eligible"


def _weak_direct_evidence(payload: dict[str, Any]) -> bool:
    bundle = [row for row in payload.get("source_bundle", []) if isinstance(row, dict)]
    if not bundle:
        return False
    return sum(_row_context(row) == "direct" for row in bundle) <= 1


_UNSUPPORTED_DOMAIN_FRAME_PATTERNS: tuple[tuple[str, str], ...] = (
    ("bounded_geroscience", r"\bbounded\s+geroscience\s+(?:case|hypothesis|rationale)\b"),
    ("geroscience_target", r"\bgeroscience\s+intervention\s+target\b"),
    ("anti_aging_claim", r"\b(?:unqualified|generalized|global)\s+anti-aging\s+(?:claim|conclusion)\b"),
    ("longevity_treatment", r"\bsettled\s+longevity\s+treatment\b"),
    ("healthspan_benefit", r"\bdurable\s+healthspan\s+benefit\b"),
    ("standalone_aging_proof", r"\bstandalone\s+anti-aging\s+or\s+longevity\s+proof\b"),
    ("geroprotection", r"\bgeroprotection\b"),
)


_DOMAIN_FRAME_TEMPLATE_REPAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "bounded_geroscience",
        r"\bbounded\s+geroscience\s+(?:case|hypothesis|rationale)\b",
        "bounded evidence hypothesis",
    ),
    (
        "geroscience_target",
        r"\bgeroscience\s+intervention\s+target\b",
        "biomedical intervention hypothesis",
    ),
    (
        "anti_aging_claim",
        r"\b(?:unqualified|generalized|global)\s+anti-aging\s+claim\b",
        "over-broad aging-related claim",
    ),
    (
        "anti_aging_claim",
        r"\b(?:unqualified|generalized|global)\s+anti-aging\s+conclusion\b",
        "over-broad aging-related conclusion",
    ),
    (
        "longevity_treatment",
        r"\bsettled\s+longevity\s+treatment\b",
        "settled clinical treatment",
    ),
    (
        "healthspan_benefit",
        r"\bdurable\s+healthspan\s+benefit\b",
        "durable clinical benefit",
    ),
    (
        "standalone_aging_proof",
        r"\bstandalone\s+anti-aging\s+or\s+longevity\s+proof\b",
        "standalone proof of durable clinical benefit",
    ),
    ("geroprotection", r"\bgeroprotection\b", "endpoint-specific protective effects"),
)


def _repair_domain_frame_template_text(text: str) -> tuple[str, list[str]]:
    repaired = text
    codes: list[str] = []
    for code, pattern, replacement in _DOMAIN_FRAME_TEMPLATE_REPAIRS:
        repaired_next, count = re.subn(pattern, replacement, repaired, flags=re.I)
        if count:
            codes.append(code)
            repaired = repaired_next
    return repaired, list(dict.fromkeys(codes))


def _repair_domain_frame_template_file(run: Path) -> list[str]:
    paper = run / "full_paper.md"
    try:
        text = paper.read_text(encoding="utf-8")
    except OSError:
        return []
    repaired, codes = _repair_domain_frame_template_text(text)
    if codes and repaired != text:
        paper.write_text(repaired, encoding="utf-8")
    return codes


def _domain_frame_status(payload: dict[str, Any]) -> str:
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("title", "abstract", "body_markdown")
    )
    sections = payload.get("sections")
    if isinstance(sections, dict):
        text += " " + " ".join(str(value or "") for value in sections.values())
    for code, pattern in _UNSUPPORTED_DOMAIN_FRAME_PATTERNS:
        if re.search(pattern, text, flags=re.I):
            return f"domain_frame_template_leak:{code}"
    return "eligible"


def _bounded_title(title: str, topic: str, payload: dict[str, Any]) -> str:
    if not _weak_direct_evidence(payload):
        return title
    if re.match(r"^(Adjacent Evidence Brief|Hypothesis-Generating Brief|Mechanistic Evidence Brief):", title):
        return title
    prefix = "Hypothesis-Generating Brief" if any(_row_context(row) == "direct" for row in payload.get("source_bundle", [])) else "Adjacent Evidence Brief"
    suffix = " — full paper" if "full paper" in title.lower() else ""
    return f"{prefix}: {_display_topic(topic)}{suffix}"


def _conclusion_breadth_status(payload: dict[str, Any]) -> str:
    if not _weak_direct_evidence(payload):
        return "eligible"
    title = str(payload.get("title") or "").lower()
    body = str(payload.get("body_markdown") or "")
    sections = payload.get("sections")
    section_map = sections if isinstance(sections, dict) else {}
    conclusion = str(section_map.get("Conclusion") or _section(body, "Conclusion") or "")
    title_bounded = any(token in title for token in ("adjacent", "hypothesis-generating", "mechanistic"))
    conclusion_lower = conclusion.lower()
    conclusion_bounded = any(token in conclusion_lower for token in (
        "adjacent", "hypothesis-generating", "mechanistic", "bounded",
        "does not support", "cannot support", "insufficient", "limited",
    ))
    overbroad = any(token in conclusion_lower for token in (
        "establishes", "demonstrates", "proves", "supports clinical",
        "supports causal",
    ))
    if not title_bounded or not conclusion_bounded or overbroad:
        return "conclusion_breadth_unbounded_low_direct_evidence"
    return "eligible"


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
    paper = _strip_background_references(_clean_doi_text((run / "full_paper.md").read_text(encoding="utf-8")))
    manifest = _read_json(run / "manifest.json")
    topic = str(manifest.get("topic") or run.name)
    title = paper.splitlines()[0].lstrip("# ").strip() if paper.startswith("# ") else f"Research Synthesis: {_display_topic(topic)}"
    # Preserve the agent's existing source URLs, source-level appraisals, and
    # exact body-to-bundle links instead of dropping them at the API boundary.
    source_bundle = _source_bundle(run, limit=max_sources)
    paper = _publication_evidence.attach_bundle_references(paper, source_bundle)
    _publication_evidence.attach_evidence_spans(paper, source_bundle)
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
    body_markdown = paper.strip()
    content_hash = "sha256:" + hashlib.sha256(body_markdown.encode("utf-8")).hexdigest()
    source_hash = _source_citation_hash(source_bundle)
    agent_slug = _agent_slug()
    article_type = _select_article_type(manifest)
    if article_type == "evidence_map":
        title = _topic_anchored_title(title, topic)
    title = _bounded_title(title, topic, {"source_bundle": source_bundle})
    domain_slug = _env_or_default("RESEARKA_DOMAIN_SLUG_V3", "longevity")
    category = _env_or_default("RESEARKA_CATEGORY_V3", domain_slug).removesuffix("_research")
    rapid_sections = {
        "Research Question": _clip_text(
            f"What does the retained source corpus establish about {_display_topic(topic)}? "
            f"{_clip_text(abstract, limit=650)}",
        ),
        "Search Summary": methods or abstract,
        "Evidence Landscape": results or abstract,
        "Key Findings": _key_findings(abstract, results, discussion, limitations, conclusion),
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
        sections["Findings Map"] = _anchor_findings_map_rows(sections.get("Findings Map", ""), topic)
    elif article_type == "research_synthesis":
        sections = {**rapid_sections, **parts}
    else:
        sections = rapid_sections
    payload = {
        "title": title[:300],
        "abstract": abstract,
        "artifact_type": "research_paper",
        "body_markdown": body_markdown,
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


def _submitter(url: str, token: str, agent_slug: str, *, purpose: str = "resubmit") -> Submitter:
    def submit(payload: dict[str, Any]) -> dict[str, Any]:
        preflight_status = _researka_preflight_status(payload, enforce_recency=purpose != "revision")
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


def _retraction_gate_status(run: Path) -> tuple[str, list[str]]:
    import retraction_check
    try:
        retracted = retraction_check.retracted_cited_sources(run, strict=True)
    except retraction_check.RetractionCheckUnavailable:
        return "retraction_check_unavailable", []
    return ("retracted_source_cited", retracted) if retracted else ("eligible", [])


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
                out.update(_title_markers(title))
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
    skip_topics: set[str] | None = None,
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
    purpose = (
        "revision"
        if candidate_run is not None and _read_json(candidate_run / "researka_revision_request.json")
        else "resubmit"
    )
    run, considered = select_candidate(
        runs_root,
        submitted_path,
        remote_seen=remote_seen,
        candidate_run=candidate_run,
        purpose=purpose,
        skip_topics=skip_topics,
    )
    ledger["considered"] = considered
    if run is None:
        ledger.update({"status": "no_eligible_research_paper"})
        _write_json(ledger_path, ledger)
        return ledger
    domain_frame_repairs = _repair_domain_frame_template_file(run) if submit else []
    if domain_frame_repairs:
        ledger["domain_frame_repairs"] = {"run": run.name, "codes": domain_frame_repairs}
    payload = build_payload(run)
    fp = _payload_fingerprint(payload)
    raw_metadata = payload.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    ledger["candidate"] = {"run": run.name, "topic": metadata.get("topic"), "fingerprint": fp}
    if not submit:
        ledger.update({"status": "dry_run_selected"})
        _write_json(ledger_path, ledger)
        return ledger
    retraction_status, retracted = _retraction_gate_status(run)
    ledger["retraction_check"] = {
        "status": retraction_status,
        "retracted_dois": retracted,
    }
    if retraction_status != "eligible":
        ledger.update({"status": "no_eligible_research_paper", "reason": retraction_status})
        _mark_considered_status(considered, run.name, retraction_status)
        _write_json(ledger_path, ledger)
        return ledger
    if submitter is None:
        ledger["submit_token_env"] = token_env
        submitter = _submitter(_submit_url(), token, str(payload["author_agent_id"]), purpose=purpose)
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
    preflight_status = _researka_preflight_status(payload, enforce_recency=purpose != "revision")
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
        submission_id = _submission_id_from_response(response)
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
    fingerprint is excluded on the following pass). A candidate-specific
    blocker — submitted, rejected/revise-requested, or selected then blocked by
    preflight — does NOT stop the cycle; the loop moves on to the next ready
    candidate. It stops only on a no-candidate/no-progress terminal status.

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
    consumed_topics: set[str] = set()
    total = 0
    first_candidate: dict[str, Any] | None = None
    first_repairs: dict[str, Any] | None = None
    last: dict[str, Any] = {}
    for _ in range(max_submissions):
        last = run_cycle(
            runs_root=runs_root, date=date, submit=submit,
            submitter=submitter, remote_loader=remote_loader,
            skip_topics=consumed_topics,
        )
        n = int(last.get("submitted") or 0)
        total += n
        submissions.append({
            "status": last.get("status"),
            "reason": last.get("reason"),
            "candidate": last.get("candidate"),
            "submitted": n,
            "published": int(last.get("published") or 0),
            "submission_markers": sorted(
                _submission_marker(value)
                for value in _submission_ids_from_response(
                    last.get("submission", {}).get("response")
                    if isinstance(last.get("submission"), dict) else {},
                )
            ),
            "domain_frame_repairs": last.get("domain_frame_repairs"),
        })
        if n and first_candidate is None:
            first_candidate = last.get("candidate")
            repairs = last.get("domain_frame_repairs")
            first_repairs = repairs if isinstance(repairs, dict) else None
        candidate = last.get("candidate")
        topic = candidate.get("topic") if isinstance(candidate, dict) else None
        status = last.get("status")
        candidate_blocked = bool(topic and status == "no_eligible_research_paper" and last.get("reason"))
        if topic and (candidate_blocked or status in {
            "submitted_to_researka",
            "submission_rejected_by_researka",
            "submission_revise_requested",
        }):
            consumed_topics.add(str(topic))
        # Continue past a consumed candidate (published, or recorded as
        # rejected/revise-requested so the next pass skips it); stop only when
        # there is no further progress to make this window.
        if not candidate_blocked and status not in {
            "submitted_to_researka",
            "submission_rejected_by_researka",
            "submission_revise_requested",
        }:
            break
    agg = dict(last)
    agg["submitted"] = total
    agg["submissions"] = submissions
    agg["status"] = "submitted_to_researka" if total else last.get("status")
    if total:
        agg.pop("reason", None)
        agg.pop("researka_preflight", None)
        agg.pop("domain_frame_repairs", None)
        if first_repairs is not None:
            agg["domain_frame_repairs"] = first_repairs
    if first_candidate is not None:
        agg["candidate"] = first_candidate
    ledger_path = runs_root / LEDGER_DIR / f"{date}.json"
    previous = _read_json(ledger_path)
    durable_submitted = _submitted_count_for_date(runs_root / LEDGER_DIR / "_submitted_fingerprints.json", date)
    agg["latest_status"] = last.get("status")
    day_summary = {
        "submitted": max(durable_submitted, int(previous.get("submitted") or 0)),
        "published": max(int(agg.get("published") or 0), int(previous.get("published") or 0)),
    }
    if day_summary["submitted"] or day_summary["published"]:
        agg["day_summary"] = day_summary
    _write_json(ledger_path, agg)
    return agg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=_default_cycle_date())
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
    _write_daily_submit_cycle_ledger(args.runs_root, args.date, ledger)
    print(
        f"[daily-v3] status={ledger['status']} submitted={ledger['submitted']} "
        f"published={ledger['published']} run={ledger.get('candidate', {}).get('run', '-')}"
    )
    return 0 if ledger["status"] != "submission_failed" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
