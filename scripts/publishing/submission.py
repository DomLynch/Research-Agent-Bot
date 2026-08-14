"""Daily v3 research-paper submit bridge.

Safe by default: select one ready run, write a ledger, and only call
Researka when `--submit` is explicit. A successful POST is recorded as
submitted_to_researka, not published.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
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
from collections.abc import Callable, Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from source_topic_specificity import (  # noqa: E402
    BIOMED_ANCHORS, DRIFT_RESCUE_ANCHORS, NON_BIOMED_DRIFT,
    _specificity_token, is_source_topic_specific, source_gate_aliases,
    topic_aliases, topic_tokens,
)
from agent.final_gate import DEFAULT_THRESHOLDS  # noqa: E402
from agent.deterministic_anchors import build_source_bounded_conclusion  # noqa: E402
from agent.evidence_lanes import derive_receipt_lane  # noqa: E402
from agent import publication_evidence as _publication_evidence, revision_claim_trace as _revision_claim_trace  # noqa: E402
from agent.publishing.io import (  # noqa: E402
    CorruptJsonState,
    read_json as _read_json_state,
    update_json_list as _update_json_list,
    write_json as _write_json,
)
from agent.publishing.policy import (  # noqa: E402
    CandidateDecision,
    PublicationSurface,
    decision_from_status,
    publication_surface,
)
from agent.revision_contract import gate_report as _revision_gate_report, needs_coverage as _revision_needs_coverage  # noqa: E402
from agent.revision_evidence import load_revision_evidence  # noqa: E402
from agent.revision_quality import resolved_effect_direction, role_outcome_display  # noqa: E402
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
TRANSIENT_SUBMISSION_STATUSES = frozenset({408, 425, 429})
TRUSTED_SUBMISSION_HOSTS = frozenset({"api.researka.org", "researka.org"})
TOKEN_ENVS = (
    "RESEARKA_API_KEY_V3",
    "RESEARKA_API_TOKEN_V3",
    "RESEARKA_AGENT_TOKEN_V3",
    "RESEARKA_V2_API_KEY",
)
DEFAULT_AGENT_SLUG = "agent-v3-full-paper"
DEFAULT_ARTICLE_TYPE = "research_synthesis"
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
PUBLIC_BLOCKED_TITLE_PREFIXES = (
    "adjacent evidence brief:", "evidence brief:", "evidence map:",
    "hypothesis-generating brief:", "mechanistic evidence brief:",
    "mechanistic evidence map:", "thin-corpus evidence brief:",
)
NULL_CODING_AUDIT_FLOOR = 0.90
# Mirror of Researka's intake recency floor year (contracts/submissions.py
# RECENT_PUBLICATION_YEAR_FLOOR). The per-type recency *ratio* lives in
# RESEARKA_TYPE_THRESHOLDS below. Checking recency pre-submit stops the bot
# wasting a synthesis cycle — and tripping the intake backoff — on a corpus
# whose published source bundle is too old to clear the gate.
RECENT_PUBLICATION_YEAR_FLOOR = 2020
# Pre-submit intake floors mirror Researka's full research-synthesis contract.
RESEARKA_TYPE_THRESHOLDS: dict[str, dict[str, float]] = {
    "research_synthesis": {"min_citations": 12, "recency_ratio": 0.50, "min_question_words": 75, "min_body_words": 2000},
}
PUBLICATION_IDENTITY_KEYS = (
    "submission_identity_key",
    "submission_payload_hash",
    "content_hash",
    "source_citation_hash",
    "author_signature",
)
_READ_ERROR = "_v3_read_error"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return _read_json_state(path)
    except CorruptJsonState as exc:
        return {_READ_ERROR: str(exc)}


def _run_artifact_error(run: Path) -> str:
    paper = run / "full_paper.md"
    try:
        if paper.is_file():
            paper.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "run_artifact_invalid:full_paper.md"
    for path in sorted(run.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return f"run_artifact_invalid:{path.name}"
    return ""
RESEARKA_REQUIRED_SECTIONS = {
    "research_synthesis": (
        "Abstract",
        "Introduction",
        "Methods",
        "Results",
        "Discussion",
        "Limitations",
        "Conclusion",
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
_PUBLIC_CLAIM_SECTIONS = frozenset({"abstract", "key findings", "findings", "results", "conclusion"})
_CLAIM_MARKERS = ("support", "suggest", "risk", "increase", "decrease", "null", "evidence")
_GENERIC_EVIDENCE_WORDS = frozenset({
    "about", "across", "adults", "after", "among", "associated", "before", "bundle", "cohort", "compared", "evidence",
    "finding", "findings", "group", "groups", "intervention", "patients", "reported", "results",
    "receiving", "review", "significant", "significantly", "source", "studies", "study", "support",
    "supports", "suggests", "therapy", "treated", "treatment", "trial", "trials",
})
_RESEARKA_GENERIC_EVIDENCE_WORDS = frozenset({
    "about", "across", "evidence", "finding", "findings", "reported", "results",
    "review", "source", "studies", "study", "support", "supports", "suggests", "trial",
})
_CORPUS_ACCOUNTING_MARKERS = (
    "reference papers", "included sources", "evidence tiers", "directness is",
    "effect directions are", "cross-source tensions", "population summaries",
    "receipt-level direction coded",
)
_EMPIRICAL_CLAIM_RE = re.compile(
    r"\b(?:achiev(?:e[ds]?|ing)|associat(?:ed|ion)|benefit|decreas(?:e[sd]?|ing)|"
    r"conferr(?:ed|ing|s)|demonstrat(?:e[ds]?|ing)|differ(?:ed|ence|ences)|experienc(?:ed|es|ing)|"
    r"found|harm|higher|"
    r"improv(?:e[sd]?|ement|ing)|increas(?:e[sd]?|ing)|lower|null (?:effect|finding|result|signal)|"
    r"observed|prevent(?:ed|ing|s)|prolong(?:ed|ing|s)|protect(?:ed|ing|ion|ive|s)|"
    r"reduc(?:e[sd]?|ing|tion)|report(?:ed|s)|"
    r"produc(?:e[ds]?|ing)|show(?:ed|s)|worsen(?:ed|ing|s)|yield(?:ed|ing|s))\b",
    re.I,
)
_INCREASE_RE = re.compile(r"\b(?:elevat(?:e[ds]?|ion)|greater|higher|increas(?:e[ds]?|ing)|rose|rising)\b", re.I)
_DECREASE_RE = re.compile(r"\b(?:decreas(?:e[ds]?|ing)|declin(?:e[ds]?|ing)|fell|lower(?:ed|ing|s)?|reduc(?:e[ds]?|ing|tion))\b", re.I)
_NULL_RE = re.compile(
    r"\b(?:did not (?:achieve|change|confer|decrease|demonstrate|differ|experience|improve|increase|"
    r"prevent|produce|protect|reduce|show|worsen)|no (?:(?:statistically )?significant )?"
    r"(?:association|benefit|change|difference|effect|improvement|increase|reduction)|"
    r"not (?:associated|linked|related)|unchanged|"
    r"non[- ]?significant|null (?:effect|finding|result|signal)|similar)\b",
    re.I,
)
_BENEFIT_RE = re.compile(r"\b(?:benefit|beneficial|improv(?:e[ds]?|ement|ing)|protect(?:ed|ing|ion|ive)|remission|recovery)\b", re.I)
_HARM_RE = re.compile(r"\b(?:adverse|complication|deteriorat(?:e[ds]?|ion|ing)|harm|toxicity|worsen(?:ed|ing|s))\b", re.I)
_BUNDLE_REFERENCE_RE = re.compile(r"\[bundle:(\d+)\]", re.I)
_NUMERIC_CITATION_RE = re.compile(r"\[((?:\d+[\s,;-]*)+)\]")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
_PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d+)\b", re.I)
_QUANTITY_RE = re.compile(
    r"(?<![\w./])(?P<number>[+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+))(?:\s*-\s*|\s*)"
    r"(?P<unit>(?:%|percent(?:age)?(?:\s+points?)?|pp|mmol|mol|mmhg|bpm|hz|"
    r"mg|kg|ug|µg|μg|ng|ml|km|cm|mm|g|l|m|seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    r"(?:/[A-Za-zµμ]+)?)?(?![A-Za-z])",
    re.I,
)
_BUNDLE_COUNT_RE = re.compile(
    r"^\s*(?:sources?|papers?|studies|findings|receipts|claims)\b", re.I,
)
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


@contextlib.contextmanager
def submission_lock(runs_root: Path) -> Iterator[None]:
    """Serialize candidate recheck, remote submission, and shared ledger writes."""
    ledger_dir = runs_root / LEDGER_DIR
    ledger_dir.mkdir(parents=True, exist_ok=True)
    with (ledger_dir / ".submit.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _write_daily_submit_cycle_ledger(runs_root: Path, date: str, ledger: dict[str, Any]) -> None:
    payload = dict(ledger)
    payload["lane"] = "daily-submit"
    payload["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    with submission_lock(runs_root):
        _write_json(runs_root / CYCLE_LEDGER_DIR / f"{date}-daily-submit.json", payload)


def _default_cycle_date() -> str:
    return dt.datetime.now().astimezone().date().isoformat()


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    material = {
        key: payload.get(key)
        for key in ("title", "abstract", "artifact_type", "article_type", "author_agent_id", "body_markdown", "sections", "source_bundle", "parent_submission_id")
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


def _preflight_failure(
    payload: dict[str, Any], mode: str, code: str, message: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    report = {
        "status": "blocked", "qa_version": "preflight-v2",
        "blocked_reasons": [code],
        "advisories": [{"code": code, "severity": "major", "message": message}],
    }
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
    return (payload if mode == "shadow" else None), report


def _run_preflight_qa(payload: dict[str, Any], run: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mode = _preflight_mode()
    if mode == "off":
        return payload, None
    tool_root = Path(os.getenv("RESEARKA_PREFLIGHT_QA_ROOT", ROOT.parent / "researka-preflight-qa"))
    input_path = (run / "researka_preflight_input.json").resolve()
    report_path = (run / "researka_preflight_report.json").resolve()
    clean_path = (run / "researka_preflight_cleaned_payload.json").resolve()
    _write_json(input_path, payload)
    for stale_path in (report_path, clean_path):
        with contextlib.suppress(OSError):
            stale_path.unlink()
    if not tool_root.is_dir():
        return _preflight_failure(
            payload, mode, "preflight_tool_missing",
            f"preflight QA root not found: {tool_root}",
        )
    cmd = [
        sys.executable, "-m", "preflight_qa", "check",
        "--input", str(input_path),
        "--out", str(report_path),
        "--clean-out", str(clean_path),
    ]
    if os.getenv("RESEARKA_PREFLIGHT_USE_M3", "").strip().lower() in {"1", "true", "yes", "on"}:
        cmd.append("--use-m3")
    try:
        proc = subprocess.run(cmd, cwd=tool_root, text=True, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return _preflight_failure(
            payload, mode, "preflight_runtime_error", f"{type(exc).__name__}: {exc}",
        )
    runtime_error = proc.returncode not in {0, 2}
    if runtime_error:
        return _preflight_failure(
            payload, mode, "preflight_runtime_error",
            (proc.stderr or proc.stdout or "preflight QA failed")[-500:],
        )
    report = _read_json(report_path)
    if not report:
        return _preflight_failure(
            payload, mode, "preflight_report_missing",
            "Preflight did not write a valid report.",
        )
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    if isinstance(metadata, dict):
        metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
    if mode == "shadow":
        return payload, report
    if report.get("status") != "pass":
        return None, report
    cleaned = _read_json(clean_path)
    if not cleaned:
        return _preflight_failure(
            payload, mode, "preflight_missing_cleaned_payload",
            "Preflight passed but did not write a cleaned payload.",
        )
    cleaned_metadata = cleaned.setdefault("metadata", {})
    if isinstance(cleaned_metadata, dict):
        cleaned_metadata["preflight_qa"] = _preflight_summary(report) | {"mode": mode}
        body = str(cleaned.get("body_markdown") or "")
        content_hash = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        cleaned_metadata["preflight_original_content_hash"] = cleaned_metadata.get("content_hash")
        cleaned_metadata["content_hash"] = content_hash
        cleaned["author_signature"] = content_hash
        raw_bundle = cleaned.get("source_bundle")
        source_bundle = [row for row in raw_bundle if isinstance(row, dict)] if isinstance(raw_bundle, list) else []
        source_hash = _source_citation_hash(source_bundle)
        cleaned_metadata["source_citation_hash"] = source_hash
        cleaned_metadata["submission_identity_key"] = _submission_identity_key(
            agent_slug=str(cleaned.get("author_agent_id") or ""),
            title=str(cleaned.get("title") or ""),
            content_hash=content_hash,
            source_citation_hash=source_hash,
            revision_parent=str(
                (cleaned_metadata.get("revision_of") or {}).get("submissionId")
                or (cleaned_metadata.get("revision_of") or {}).get("artifactId")
                or ""
            ) if isinstance(cleaned_metadata.get("revision_of"), dict) else "",
        )
        cleaned["core_claims_resolved"] = _researka_core_claim_trace_status(cleaned, source_bundle) == "eligible"
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
        if isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", value.strip())
    ))


def _submission_id_from_response(response: object) -> str | None:
    ids = _submission_ids_from_response(response)
    return ids[0] if ids else None


def _paper_title(paper: Path) -> str:
    try:
        first = paper.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeDecodeError, IndexError):
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


def _token() -> tuple[str, str]:
    for name in TOKEN_ENVS:
        value = os.getenv(name, "").strip()
        if value:
            return value, name
    return "", ""


def _runs(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.glob("synthesis-*") if p.is_dir()),
        key=lambda p: p.name.rsplit("-DAILY-", 1)[-1] if "-DAILY-" in p.name else f"{p.stat().st_mtime:020.6f}",
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
    return (
        "public_research_surface_compact_review"
        if publication_surface(review_type) is PublicationSurface.INTERNAL_COMPACT
        else "eligible"
    )


def _word_count(text: object) -> int: return len(str(text or "").split())


def _empirical_claim(text: str) -> bool:
    return bool(_EMPIRICAL_CLAIM_RE.search(text))


def _corpus_accounting_only(text: str) -> bool:
    return any(marker in text.lower() for marker in _CORPUS_ACCOUNTING_MARKERS) and not _empirical_claim(text)


def _claim_candidates(text: str) -> list[str]:
    return [
        clean for line in text.splitlines()
        for sentence in _revision_claim_trace._sentences(line)
        if len(clean := sentence.strip(" -*")) >= 80
        and (
            any(marker in clean.lower() for marker in _CLAIM_MARKERS)
            or _empirical_claim(clean)
        )
        and not (clean.lower().startswith("outcome-class note:") and not _empirical_claim(clean))
        and "receipt-level direction is the coded finding" not in clean.lower()
        and not _corpus_accounting_only(clean)
        and bool(
            _BUNDLE_REFERENCE_RE.search(clean)
            or _DOI_RE.search(clean)
            or _PMID_RE.search(clean)
            or _empirical_claim(clean)
        )
    ][:30]


def _evidence_words(text: object) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(word) >= 5 and word not in _GENERIC_EVIDENCE_WORDS}


def _direction_labels(text: str) -> set[str]:
    if _NULL_RE.search(text):
        return {"null"}
    labels = {
        name for name, pattern in (
            ("up", _INCREASE_RE), ("down", _DECREASE_RE),
        ) if pattern.search(text)
    }
    if _BENEFIT_RE.search(text):
        labels.add("benefit")
    if _HARM_RE.search(text) and "down" not in labels:
        labels.add("harm")
    return labels


def _directions_compatible(claim: str, evidence: str) -> bool:
    claim_labels = _direction_labels(claim)
    evidence_labels = _direction_labels(evidence)
    for axis in ({"up", "down", "null"}, {"benefit", "harm", "null"}):
        claim_axis = claim_labels & axis
        evidence_axis = evidence_labels & axis
        if claim_axis and evidence_axis and claim_axis.isdisjoint(evidence_axis):
            return False
    return True


def _quantities_match(claim_quantities: set[tuple[str, str]], evidence: str) -> bool:
    evidence_quantities = _quantity_tokens(evidence)
    return all(token in evidence_quantities or token[0].startswith("-") and "down" in _direction_labels(evidence) and (token[0][1:], token[1]) in evidence_quantities for token in claim_quantities)


def _structured_source_fields(claim: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for segment in claim.split(";"):
        if match := re.search(r"\b(outcome|direction|directness|tier)=(.*)", segment, re.I):
            key, value = match.groups()
            fields[key.lower()] = value.strip().rstrip(".)") if key.lower() == "tier" else value.strip()
    return fields


def _structured_source_summary_aligns(claim: str, source: dict[str, Any], quantities: set[tuple[str, str]]) -> bool:
    fields = _structured_source_fields(claim)
    expected = (
        ("outcome", role_outcome_display(source)),
        ("direction", resolved_effect_direction(source)),
        ("directness", str(source.get("directness") or "")),
        ("tier", str(source.get("evidence_tier") or "")),
    )
    return (
        bool(quantities) and bool(re.search(r"\brepresentative (?:non-significant )?statistic\b", claim, re.I))
        and _normalized_key(claim.split(" [bundle:", 1)[0]) == _normalized_key(str(source.get("cited_as") or ""))
        and all(value and _normalized_key(fields.get(key, "")) == _normalized_key(value) for key, value in expected)
        and any(_quantities_match(quantities, str(source.get(key) or "")) for key in ("quote", "evidence_span", "excerpt"))
    )


def _evidence_aligns(claim: str, source: dict[str, Any]) -> bool:
    label_words = _evidence_words(source.get("cited_as"))
    claim_words = _evidence_words(claim) - label_words
    if (match := re.fullmatch(r"(?:This paper|The conclusion) synthesizes evidence on (?P<topic>.+?) across the retained source corpus and high-confidence extracted claim set(?:, while remaining bounded by source directness and endpoint fit)?(?: \[bundle:\d+\])?[.!?]?", " ".join(claim.split()), re.I)) and is_source_topic_specific(match.group("topic"), str(source.get("title") or "")):
        return True
    required = min(4, max(3, (len(claim_words) + 4) // 5))
    claim_text = claim.lower().split(" reports: ", 1)[-1].split(" [exact source:", 1)[0]
    claim_quantities = _quantity_tokens(claim, [source])
    structured_fields = _structured_source_fields(claim)
    expected_fields = {
        "outcome": role_outcome_display(source),
        "direction": resolved_effect_direction(source),
        "directness": str(source.get("directness") or ""),
        "tier": str(source.get("evidence_tier") or ""),
    }
    if any(not expected_fields[key] or _normalized_key(value) != _normalized_key(expected_fields[key])
           for key, value in structured_fields.items()):
        return False
    if _structured_source_summary_aligns(claim, source, claim_quantities):
        return True
    for key in ("quote", "evidence_span", "excerpt"):
        evidence = " ".join(str(source.get(key) or "").lower().split()).replace("−", "-").replace("–", "-").replace("—", "-")
        if len(evidence) < 20:
            continue
        for sentence in _revision_claim_trace._sentences(evidence):
            passages = re.split(r";\s*|,\s*(?=[a-z])|\s+and\s+(?=[^,;.]{0,80}(?:[+-]?\d|\.\d)|[^,;.]{0,60}\b(?:did not|had no|no (?:statistically )?significant|remained unchanged))", sentence, flags=re.I)
            direction_conflict = not _directions_compatible(claim, sentence)
            distinct_null = any(_NULL_RE.search(part) and bool(_evidence_words(part) - claim_words - {"change", "control", "controls", "difference", "effect", "effects", "individuals", "observed", "overall", "participant", "participants", "population", "populations", "same", "sample", "subject", "subjects", "these", "those"}) for part in passages)
            if len(sentence) >= 20 and claim_text and (sentence in claim_text or claim_text in sentence) and (not claim_quantities or _quantities_match(claim_quantities, sentence)) and (not direction_conflict or distinct_null):
                return True
            for passage in passages:
                if not passage or not _directions_compatible(claim, passage) or direction_conflict and not distinct_null:
                    continue
                overlap = len(claim_words & (_evidence_words(passage) - label_words))
                quantity_match = _quantities_match(claim_quantities, passage)
                if len(passage) >= 20 and claim_text and (passage in claim_text or claim_text in passage) and (not claim_quantities or quantity_match):
                    return True
                if overlap >= (2 if claim_quantities else required) and (not claim_quantities or quantity_match):
                    return True
    return False


def _citation_indexes(text: str, bundle: list[dict[str, Any]]) -> set[int]:
    lower = text.lower()
    indexes = {int(value) - 1 for value in _BUNDLE_REFERENCE_RE.findall(text)}
    indexes.update(
        int(value) - 1 for group in _NUMERIC_CITATION_RE.findall(text)
        for value in re.findall(r"\d+", group)
    )
    pmids = set(_PMID_RE.findall(text))
    dois = {value.lower().rstrip(".,") for value in _DOI_RE.findall(text)}
    for index, row in enumerate(bundle):
        cited_as = str(row.get("cited_as") or "").strip().lower()
        pmid = re.sub(r"\D", "", str(row.get("pmid") or ""))
        doi = str(row.get("doi") or "").strip().lower().rstrip(".,")
        spans = (str(row.get("quote") or "").strip(), str(row.get("evidence_span") or "").strip())
        if (
            cited_as and len(cited_as) >= 4 and cited_as in lower
            or pmid and pmid in pmids
            or doi and doi in dois
            or any(len(span) >= 8 and span.lower() in lower for span in spans)
        ):
            indexes.add(index)
    return {index for index in indexes if 0 <= index < len(bundle)}


def _claim_trace_counts(
    text: str, bundle: list[dict[str, Any]],
) -> tuple[int, int, int]:
    claims = _claim_candidates(text)
    indexes = [_citation_indexes(claim, bundle) for claim in claims]
    return len(claims), sum(bool(values) for values in indexes), sum(
        any(_evidence_aligns(claim, bundle[index]) for index in values)
        for claim, values in zip(claims, indexes, strict=True))


def _researka_claim_candidates(text: str) -> list[str]:
    candidates = [
        clean for line in text.splitlines()
        if len(clean := line.strip(" -*")) >= 80
        and any(marker in clean.lower() for marker in _CLAIM_MARKERS)
    ]
    return (candidates or [
        part.strip() for part in re.split(r"\n+|(?<=[.!?])\s+", text)
        if len(part.strip()) >= 80
    ])[:30]


def _researka_evidence_words(text: object) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(word) >= 5 and word not in _RESEARKA_GENERIC_EVIDENCE_WORDS}


def _researka_evidence_aligns(claim: str, source: dict[str, Any]) -> bool:
    claim_words = _researka_evidence_words(claim)
    required = min(4, max(2, (len(claim_words) + 4) // 5))
    for key in ("quote", "evidence_span", "excerpt"):
        evidence = " ".join(str(source.get(key) or "").lower().split())
        if len(evidence) >= 20 and (
            evidence in claim.lower() or claim.lower() in evidence
            or len(claim_words & _researka_evidence_words(evidence)) >= required
        ):
            return True
    return False


def _attach_aligned_claim_references(paper: str, bundle: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    section = ""
    for line in paper.splitlines():
        if heading := re.match(r"^##\s+(.+?)\s*$", line):
            section = heading.group(1).strip().lower()
        if section in _PUBLIC_CLAIM_SECTIONS and not line.lstrip().startswith(("#", "|", "```")):
            sentences: list[str] = []
            for sentence in _revision_claim_trace._sentences(line):
                clean = sentence.strip(" -*")
                candidate = bool(_claim_candidates(clean)) or section in {"abstract", "conclusion"} and len(clean) >= 80 and any(marker in clean.lower() for marker in _CLAIM_MARKERS)
                if candidate and not _citation_indexes(clean, bundle):
                    aligned = [index for index, row in enumerate(bundle) if _evidence_aligns(clean, row)]
                    if aligned:
                        def rank(index: int) -> tuple[int, bool, bool, int]:
                            row = bundle[index]
                            return (
                                max(
                                    (len(_evidence_words(clean) & _evidence_words(row.get(key)))
                                     for key in ("quote", "evidence_span", "excerpt")),
                                    default=0,
                                ),
                                str(row.get("directness") or "").lower().startswith("direct"),
                                str(row.get("evidence_tier") or "").upper().startswith("A"),
                                -index,
                            )
                        index = max(aligned, key=rank)
                        terminal = re.search(r"""[.!?](?:["')\]]|\*{1,2}|_{1,2})*$""", sentence)
                        sentence = (
                            f"{sentence[:terminal.start()]} [bundle:{index + 1}]{sentence[terminal.start():]}"
                            if terminal else f"{sentence} [bundle:{index + 1}]"
                        )
                sentences.append(sentence)
            line = " ".join(sentences)
        lines.append(line)
    return "\n".join(lines)


def _researka_claim_trace_status(
    payload: dict[str, Any], source_bundle: list[dict[str, Any]],
) -> str:
    sections_raw = payload.get("sections")
    sections = sections_raw if isinstance(sections_raw, dict) else {}
    major = [
        str(value) for name, value in sections.items()
        if str(name).strip().lower() in {"key findings", "findings", "results", "conclusion"}
    ]
    prose = "\n".join([str(payload.get("abstract") or ""), *major])
    prose = "\n".join(line for line in prose.splitlines() if not line.lstrip().startswith("|"))
    checks = [_claim_trace_counts(prose, source_bundle)]
    claims = _researka_claim_candidates(prose)
    indexes = [_citation_indexes(claim, source_bundle) for claim in claims]
    checks.append((len(claims), sum(bool(values) for values in indexes), sum(
        any(_researka_evidence_aligns(claim, source_bundle[index]) for index in values)
        for claim, values in zip(claims, indexes, strict=True)
    )))
    for count, cited, aligned in checks:
        required = (count * 4 + 4) // 5 if count else 0
        if count and aligned < required:
            return (f"researka_claim_trace_insufficient:cited={cited}/{count},"
                    f"aligned={aligned}/{count},required={required}")
    return "eligible"


def _researka_core_claim_trace_status(
    payload: dict[str, Any], source_bundle: list[dict[str, Any]],
) -> str:
    sections = {heading.strip().lower(): value for heading, value in _sections(str(payload.get("body_markdown") or "")).items()}
    decisive = "\n".join(map(str, (payload.get("title") or "", payload.get("abstract") or "", sections.get("conclusion") or "")))
    if re.search(r"(?:\b(?:todo|tbd|unresolved|placeholder)\b|\[(?:to fill|insert|pending)[^]]*\]|\?\?\?)", decisive, re.I):
        return "researka_core_claims_unresolved:placeholder_token"
    claims: list[str] = []
    for name in ("abstract", "conclusion"):
        text = re.sub(r"^#{1,6}\s+(.+?)\s*$", r"\1.", sections.get(name, ""), flags=re.M)
        section_claims = [
            sentence.strip() for sentence in _revision_claim_trace._sentences(text)
            if sentence.strip() and (bool(_claim_candidates(sentence)) or _empirical_claim(sentence) or (_corpus_accounting_only(sentence) and bool(re.search(r"\d", sentence))) or "synthesizes evidence on" in sentence.lower())
        ]
        if not section_claims:
            return f"researka_core_claims_unresolved:{name}_claims=0"
        claims.extend(section_claims)
    indexes = [_citation_indexes(claim, source_bundle) for claim in claims]
    cited = sum(bool(values) for values in indexes)
    aligned = sum(any(_evidence_aligns(claim, source_bundle[index]) for index in values)
                  for claim, values in zip(claims, indexes, strict=True))
    if aligned == len(claims):
        return "eligible"
    return f"researka_core_claims_unresolved:cited={cited}/{len(claims)},aligned={aligned}/{len(claims)}"


def _quantity_tokens(text: str, sources: list[dict[str, Any]] | None = None) -> set[tuple[str, str]]:
    text = text.translate(str.maketrans("‐‑‒–—−", "------"))
    cleaned = _BUNDLE_REFERENCE_RE.sub(
        " ", _DOI_RE.sub(" ", _PMID_RE.sub(" ", _NUMERIC_CITATION_RE.sub(" ", text))),
    )
    cleaned = re.sub(
        r"\b(?:[A-Za-z][A-Za-z0-9]*-\d+[A-Za-z0-9-]*|\d+-[A-Za-z][A-Za-z0-9-]*)\b",
        lambda match: match.group()
        if (quantity := _QUANTITY_RE.match(match.group())) and quantity.group("unit")
        else " ",
        cleaned,
    )
    cleaned = re.sub(r"(%|percent(?:age)?|pp)\s*=\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))", r"\2\1", cleaned, flags=re.I)
    cleaned = re.sub(r"\btype\s+[12]\s+diabet(?:es|ic)\b|(?<=[A-Za-z])-\d+\b", " ", cleaned, flags=re.I)
    for source in sources or []:
        for field in ("doi", "cited_as"):
            value = str(source.get(field) or "").strip()
            if value:
                cleaned = re.sub(re.escape(value), " ", cleaned, flags=re.I)
    tokens: set[tuple[str, str]] = set()
    for match in _QUANTITY_RE.finditer(cleaned):
        raw_number = match.group("number").replace(",", "")
        raw_unit = (match.group("unit") or "").strip().lower()
        if not raw_unit and _BUNDLE_COUNT_RE.match(cleaned[match.end():]):
            continue
        try:
            decimal_value = Decimal(raw_number)
            number = format(decimal_value.normalize(), "f")
            number = f"+{number}" if raw_number.startswith("+") else number
        except InvalidOperation:
            continue
        if not raw_unit and decimal_value == int(decimal_value) and 1900 <= int(decimal_value) <= 2100:
            continue
        unit = raw_unit.replace("μ", "u").replace("µ", "u")
        if unit.startswith("percent"):
            unit = "pp" if "point" in unit else "%"
        elif unit.endswith("s") and unit != "mmhg":
            unit = unit[:-1]
        tokens.add((number, unit))
    return tokens


def _quantitative_claim_candidates(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"\n+|(?<=[.!?])\s+", text)
        if len(part.strip()) >= 40 and _quantity_tokens(part)
        and not _corpus_accounting_only(part)
    ][:30]


def _quantities_agree(claim: str, sources: list[dict[str, Any]]) -> bool:
    claim_tokens = _quantity_tokens(claim, sources)
    evidence = " ".join(str(source.get(field) or "") for source in sources for field in (
        "quote", "evidence_span", "excerpt", "effect"))
    return _quantities_match(claim_tokens, evidence)


def _researka_quantitative_trace_status(
    payload: dict[str, Any], source_bundle: list[dict[str, Any]],
) -> str:
    sections_raw = payload.get("sections")
    sections = sections_raw if isinstance(sections_raw, dict) else {}
    conclusion = "\n".join(
        str(value) for name, value in sections.items()
        if str(name).strip().lower() == "conclusion"
    )
    claims = _quantitative_claim_candidates(
        "\n".join((str(payload.get("abstract") or ""), conclusion)),
    )
    aligned = 0
    for claim in claims:
        sources = [
            source_bundle[index] for index in _citation_indexes(claim, source_bundle)
            if _evidence_aligns(claim, source_bundle[index])
        ]
        aligned += bool(sources) and _quantities_agree(claim, sources)
    return (
        "eligible" if aligned == len(claims)
        else f"researka_quantitative_trace_insufficient:aligned={aligned}/{len(claims)}"
    )


def _researka_preflight_status(payload: dict[str, Any], *, enforce_recency: bool = True) -> str:
    article_type = str(payload.get("article_type") or DEFAULT_ARTICLE_TYPE)
    if article_type != DEFAULT_ARTICLE_TYPE:
        return "public_surface_not_full_research"
    sections_raw = payload.get("sections")
    sections: dict[str, Any] = sections_raw if isinstance(sections_raw, dict) else {}
    source_bundle_raw = payload.get("source_bundle")
    source_bundle = [row for row in source_bundle_raw if isinstance(row, dict)] if isinstance(source_bundle_raw, list) else []
    min_citations = int(_threshold(article_type, "min_citations"))
    if len(source_bundle) < min_citations:
        return f"researka_preflight_insufficient_sources:{len(source_bundle)} < {min_citations}"
    for check in (_public_grade_surface_status, _source_bundle_reconciliation_status, _source_bundle_topic_status):
        if (status := check(payload)) != "eligible":
            return status
    direct = sum(_row_context(row) == "direct" for row in source_bundle)
    if direct < PUBLIC_RESEARCH_MIN_DIRECT_RECEIPTS:
        return f"public_surface_direct_receipts_below_floor:{direct} < {PUBLIC_RESEARCH_MIN_DIRECT_RECEIPTS}"

    required_sections = RESEARKA_REQUIRED_SECTIONS.get(article_type, RESEARKA_REQUIRED_SECTIONS[DEFAULT_ARTICLE_TYPE])
    missing = [name for name in required_sections if not str(sections.get(name) or "").strip()]
    if missing:
        return "researka_preflight_missing_sections:" + ",".join(missing)

    minimum_question_words = int(_threshold(article_type, "min_question_words"))
    question_words = _word_count(sections.get("Abstract"))
    if question_words < minimum_question_words:
        return f"researka_preflight_question_words:Abstract={question_words} < {minimum_question_words}"

    min_body_words = int(_threshold(article_type, "min_body_words"))
    if min_body_words:
        body_words = sum(_word_count(sections.get(name)) for name in (
            *required_sections, *RESEARKA_RECOMMENDED_SECTIONS.get(article_type, ())))
        if body_words < min_body_words:
            return f"researka_preflight_body_words:{body_words} < {min_body_words}"
    if (claim_trace_status := _researka_claim_trace_status(payload, source_bundle)) != "eligible":
        return claim_trace_status
    if (core_status := _researka_core_claim_trace_status(payload, source_bundle)) != "eligible":
        return core_status
    if (quantity_status := _researka_quantitative_trace_status(payload, source_bundle)) != "eligible":
        return quantity_status
    if enforce_recency and (recency_status := _recency_ratio_status(payload)) != "eligible":
        return recency_status
    if (doi_status := _doi_existence_status(payload)) != "eligible":
        return doi_status
    if (domain_frame_status := _domain_frame_status(payload)) != "eligible":
        return domain_frame_status
    return "eligible"


def _final_status_ready(data: dict[str, Any]) -> bool:
    return data.get("researka_publish_ready" if "researka_publish_ready" in data else "submission_ready") is True


def _inside_refresh_window(run: Path) -> bool:
    try:
        age = dt.datetime.now(dt.UTC).timestamp() - run.stat().st_mtime
    except OSError:
        return False
    return age <= STALE_AUDIT_REFRESH_WINDOW_S


def _needs_submit_self_heal(run: Path, *, inside_refresh: bool | None = None) -> bool:
    if not (_inside_refresh_window(run) if inside_refresh is None else inside_refresh):
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


def _static_ineligible_status(
    run: Path, *, allow_recent_repair: bool = True, inside_refresh: bool | None = None,
) -> str | None:
    missing = [name for name in SUBMISSION_REQUIRED_FILES if not (run / name).exists()]
    if missing:
        return "missing:" + ",".join(missing)
    repairable = allow_recent_repair and _needs_submit_self_heal(run, inside_refresh=inside_refresh)
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
    if request and _revision_needs_coverage(request):
        refreshed = _refresh_revision_coverage_gate(run, request)
        gate = _read_json(run / REVISION_COVERAGE_GATE)
        if not refreshed and gate.get("passed") is not False:
            return "revision_coverage_unverified"
        if gate.get("passed") is False:
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
    if not request or not _revision_needs_coverage(request):
        return "eligible"
    refreshed = _refresh_revision_coverage_gate(run, request)
    gate = _read_json(run / REVISION_COVERAGE_GATE)
    if refreshed and gate.get("passed") is True:
        return "eligible"
    if gate.get("passed") is False:
        return "revision_coverage_unmet"
    return "revision_coverage_unverified"


def _refresh_revision_coverage_gate(run: Path, request: dict[str, Any]) -> bool:
    try:
        import revision_coverage
        report = _revision_gate_report(
            run, revision_coverage, refreshed_by="daily_submit",
            payload_satisfied=lambda ask: payload_revision_ask_satisfied(run, ask),
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False
    if report is None:
        return False
    _write_json(run / REVISION_COVERAGE_GATE, report)
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
    if not _inside_refresh_window(run):
        return False
    audit = _read_json(run / "full_paper.audit.json")
    if not audit or (audit.get("p1_pass") is True and audit.get("n_pass") == audit.get("n_total")):
        return False
    try:
        from agent.journal_finalizer import _phase_g_refresh_sidecars  # type: ignore[attr-defined]
        return bool(_phase_g_refresh_sidecars(run))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _refresh_stale_surface_sidecar(run: Path) -> bool:
    if not _inside_refresh_window(run):
        return False
    surface = _read_json(run / "full_paper.journal_surface.json")
    if surface.get("passed") is not False:
        return False
    try:
        from agent.journal_finalizer import finalize_run
        report = finalize_run(run)
        return bool(report.paper_changed)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _refresh_stale_revision_coverage_sidecar(run: Path) -> bool:
    if not _inside_refresh_window(run):
        return False
    request = _read_json(run / "researka_revision_request.json")
    if not request:
        return False
    gate = _read_json(run / REVISION_COVERAGE_GATE)
    if gate.get("passed") is True:
        return False
    try:
        from agent.journal_finalizer import finalize_run
        report = finalize_run(run)
        refreshed = _refresh_revision_coverage_gate(run, request)
        return bool(report.paper_changed or refreshed)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _eligibility_status(run: Path) -> tuple[bool, str]:
    # Phase G refreshes all sidecars (audit + gate + accountability); run it at
    # most once — prefer the accountability path, else the stale-audit path.
    recent = _inside_refresh_window(run)
    if recent and not _refresh_stale_accountability_sidecar(run):
        _refresh_stale_audit_sidecar(run)
    missing = [name for name in SUBMISSION_REQUIRED_FILES if not (run / name).exists()]
    if missing:
        return False, "missing:" + ",".join(missing)
    audit = _read_json(run / "full_paper.audit.json")
    surface = _read_json(run / "full_paper.journal_surface.json")
    if recent and surface.get("passed") is not True and _refresh_stale_surface_sidecar(run):
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
    if recent:
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


def _candidate_decision(run: Path) -> CandidateDecision:
    _ok, status = _eligibility_status(run)
    review_type = str(_read_json(run / "manifest.json").get("review_type") or "")
    return decision_from_status(
        run.name,
        review_type=review_type,
        status=status,
    )


def _eligible(run: Path) -> tuple[bool, str]:
    decision = _candidate_decision(run)
    return decision.publishable, decision.blocker_code or "eligible"


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


def _seen_field(path: Path, key: str, *, latest_active: bool = False) -> set[str]:
    rows = _ledger_rows(path)
    if latest_active:
        rows = list({str(row[key]): row for row in rows if isinstance(row.get(key), str) and row[key]}.values())
    return {str(row[key]) for row in rows if isinstance(row.get(key), str) and row[key]
            and (not latest_active or str(row.get("decision") or "").strip().lower() != "reject")}


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
    _update_json_list(path, lambda records: records.append(row))


def _feedback_text(payload: Any) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
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
    candidate_inside_refresh: bool | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    local_seen = _seen(submitted_path)
    rejected_seen = _seen(submitted_path.with_name(REJECTED_FINGERPRINTS))
    revision_seen = _seen(submitted_path.with_name(REVISION_FINGERPRINTS))
    submitted_topics = _seen_field(submitted_path, "topic", latest_active=True)
    revision_topics = _seen_field(submitted_path.with_name(REVISION_FINGERPRINTS), "topic")
    published_seen = remote_seen or set()
    considered = []
    seen_topics: set[str] = set()
    blocked_topics = skip_topics or set()
    repair_attempts = 0
    explicit_candidate = candidate_run is not None
    for run in ([candidate_run] if candidate_run else _runs(root)):
        if artifact_error := _run_artifact_error(run):
            considered.append({
                "run": run.name,
                "topic": _run_topic(run),
                "fingerprint": "",
                "status": artifact_error,
            })
            continue
        inside_refresh = (
            candidate_inside_refresh
            if explicit_candidate and candidate_inside_refresh is not None
            else _inside_refresh_window(run)
        )
        topic = _run_topic(run)
        paper = run / "full_paper.md"
        paper_sha = _sha256(paper) if paper.exists() else ""
        title_marks = _title_markers(_paper_title(paper))
        markers = {paper_sha, f"sha256:{paper_sha}", *title_marks} if paper_sha else set(title_marks)
        revision = bool(_read_json(run / "researka_revision_request.json"))
        if topic in blocked_topics:
            considered.append({"run": run.name, "topic": topic, "fingerprint": paper_sha, "status": "topic_already_consumed_this_window"})
            continue
        if topic in seen_topics:
            considered.append({"run": run.name, "topic": topic, "fingerprint": paper_sha, "status": "superseded_topic_run"})
            continue
        needs_repair = _needs_submit_self_heal(run, inside_refresh=inside_refresh)
        allow_repair = repair_attempts < MAX_SUBMIT_SELF_HEAL_CANDIDATES
        if static_status := _static_ineligible_status(
            run, allow_recent_repair=allow_repair, inside_refresh=inside_refresh,
        ):
            considered.append({"run": run.name, "topic": topic, "fingerprint": paper_sha, "status": static_status})
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
        row = {"run": run.name, "topic": topic, "fingerprint": fp, "status": status}
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
    if derive_receipt_lane(receipt) == "animal_preclinical":
        return "context"
    if directness == "direct":
        return "direct"
    if directness == "mechanistic":
        return "mechanistic"
    if "context" in outcome or directness in {"protocol", "review"}:
        return "context"
    return "adjacent"


def _claim_excerpt(quant_dir: Path, receipt_id: str, *, limit: int = 2) -> str:
    path = quant_dir / f"{receipt_id}.quant_claims.json"
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


def _receipt_evidence_excerpt(receipt: dict[str, Any], source_text: str) -> str:
    source = re.split(r"\bsource excerpts:\s*", str(receipt.get("thesis_text") or ""), maxsplit=1, flags=re.I)
    if len(source) != 2:
        return ""
    spans: list[tuple[int, int]] = []
    for excerpt in (part.strip() for part in source[1].split(" | ")):
        candidate = excerpt.removesuffix("…").rstrip()
        if not candidate:
            continue
        if (start := source_text.find(candidate)) >= 0:
            spans.append((start, start + len(candidate)))
            continue
        candidate_words = _evidence_words(candidate)
        if len(candidate_words) < 5:
            continue
        candidate_quantities = _quantity_tokens(candidate)
        matches: list[tuple[float, int, int, int]] = []
        for sentence in re.split(r"(?<=[.!?])\s+", source_text):
            sentence_words = _evidence_words(sentence)
            overlap = len(candidate_words & sentence_words)
            coverage = overlap / len(candidate_words)
            if coverage < 0.8 or (
                candidate_quantities
                and not candidate_quantities.issubset(_quantity_tokens(sentence))
            ):
                continue
            sentence_start = source_text.find(sentence)
            if sentence_start >= 0:
                matches.append((coverage, overlap, sentence_start, len(sentence)))
        if matches:
            _coverage, _overlap, start, length = max(matches)
            spans.append((start, start + length))
    if not spans:
        return ""
    start, end = min(value[0] for value in spans), max(value[1] for value in spans)
    if end - start > 12_000:
        start, end = spans[0]
    return source_text[start:end]


def _parsed_source_excerpt(parsed_dir: Path, receipt_id: str) -> str:
    data = _read_json(parsed_dir / f"{receipt_id}.paper_sections.json")
    raw_sections = data.get("sections")
    sections: dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    for name in ("abstract", "results", "conclusion", "discussion"):
        text = " ".join(str(sections.get(name) or "").split())
        if text:
            return _clip_text(text, limit=1200)
    return ""


def _parsed_source_text(parsed_dir: Path, receipt_id: str) -> str:
    data = _read_json(parsed_dir / f"{receipt_id}.paper_sections.json")
    sections = data.get("sections")
    if not isinstance(sections, dict):
        return ""
    return " ".join(
        " ".join(value.split()) for value in sections.values()
        if isinstance(value, str) and value.strip()
    )


def _pubmed_abstracts(pmids: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(p for p in pmids if p.isdigit()))
    limit = int(os.getenv("RESEARKA_SOURCE_ABSTRACT_LIMIT", "120") or "0")
    if not unique or limit <= 0:
        return {}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi" f"?db=pubmed&id={','.join(unique[:limit])}&retmode=xml"
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


def _source_bundle(run: Path, *, limit: int) -> list[dict[str, Any]]:
    manifest = _read_json(run / "manifest.json")
    topic = str(manifest.get("topic") or run.name)
    corpus = ROOT / "docs" / "quality-reference" / topic
    evidence = load_revision_evidence(
        run, quant_dir=corpus / "quant_claims", parsed_dir=corpus / "parsed",
        expected_topic=topic,
    )
    snapshot = evidence.mode == "snapshot" and not evidence.errors
    quant_dir = evidence.quant_dir if snapshot else corpus / "quant_claims"
    parsed_dir = evidence.parsed_dir if snapshot else corpus / "parsed"
    registry_path = evidence.citation_registry if snapshot else run / "citation_registry.json"
    registry = _read_json(registry_path) if registry_path else {}
    receipts = {
        str(item.get("receipt_id")): item
        for item in manifest.get("receipts", [])
        if isinstance(item, dict)
    }
    rows = _publication_evidence.ordered_source_rows(
        _publication_evidence.source_rows(registry, receipts), receipts,
    )
    pubmed_abstracts = _pubmed_abstracts([str(row.get("source_pmid") or "") for row in rows[:limit]])
    rob_ratings = _publication_evidence.risk_of_bias_ratings(run)
    bundle = []
    for row in rows[:limit]:
        receipt = receipts.get(str(row.get("receipt_id")), {})
        title = str(row.get("title") or receipt.get("source_title") or "Evidence receipt")[:300]
        claim_excerpt = _claim_excerpt(quant_dir, str(row.get("receipt_id") or ""))
        pmid = str(row.get("source_pmid") or "")
        pubmed_excerpt = pubmed_abstracts.get(pmid)
        receipt_id = str(row.get("receipt_id") or "")
        parsed_excerpt = _parsed_source_excerpt(parsed_dir, receipt_id)
        receipt_excerpt = _receipt_evidence_excerpt(
            receipt, _parsed_source_text(parsed_dir, receipt_id),
        )
        excerpt = receipt_excerpt if len(receipt_excerpt.split()) >= 12 else (
            parsed_excerpt or pubmed_excerpt or ""
        )
        quote = _publication_evidence.exact_source_quote(claim_excerpt, excerpt)
        cited_as = str(row.get("body_citation") or "")
        rob = _publication_evidence.risk_of_bias_rating(rob_ratings, cited_as, receipt.get("citation_token"), receipt_id)
        url = _citation_url(row) or _publication_evidence.parsed_source_url(
            ROOT, topic, receipt_id, parsed_dir=parsed_dir,
        )
        identity_text = " ".join(str(value or "") for value in (url, title))
        registry_id = next((
            str(row.get(key) or "").strip()
            for key in ("registry_id", "canonical_trial_id", "trial_id", "nct")
            if str(row.get(key) or "").strip()
        ), None) or next(iter(re.findall(r"\b(?:NCT\d{8}|ISRCTN\d{8}|ACTRN\d{14})\b", identity_text, re.I)), None)
        openalex_id = str(row.get("source_openalex_id") or row.get("openalex_id") or "").strip() or None
        if not openalex_id and (match := re.search(r"(?:https?://openalex\.org/)?\b(W\d+)\b", identity_text, re.I)):
            openalex_id = match.group(1).upper()
        source = {
            "source_type": "pubmed" if row.get("source_pmid") else "corpus",
            "id": str(row.get("source_pmid") or row.get("source_pmcid") or row.get("reference_id") or row.get("receipt_id") or ""),
            "title": title,
            "url": url,
            "doi": _clean_doi(row.get("source_doi")) or None,
            "pmid": str(row.get("source_pmid") or "") or None,
            "openalex_id": openalex_id,
            "registry_id": registry_id.upper() if registry_id else None,
            "excerpt": excerpt,
            "quote": quote,
            "year": row.get("source_year") if isinstance(row.get("source_year"), int) else None,
            "evidence_type": _evidence_type_for_source(receipt),
            "evidence_context": _source_context_for_receipt(receipt),
            "outcome_class": receipt.get("outcome_class") or None,
            "effect_direction": resolved_effect_direction(receipt),
            "directness": receipt.get("directness") or None,
            "evidence_tier": receipt.get("evidence_tier") or None,
            # Author-year citation token (registry body_citation, e.g. "Zufry
            # 2025") as a first-class SourceBundleEntry field so the Researka
            # reviewer can ground author-year prose citations to a bundle
            # source (workflow.py matches cited_as / title / year). Universal.
            "cited_as": cited_as or None,
            "risk_of_bias": rob if _source_context_for_receipt(receipt) == "direct" else None,
        }
        source.update(_publication_evidence.source_proof_fields(
            source,
            origin="full_text",
            evidence=evidence if snapshot else None,
            topic=topic,
            receipt_id=receipt_id,
        ))
        bundle.append(source)
    return bundle


def _row_context(row: dict[str, Any]) -> str:
    context = str(row.get("evidence_context") or row.get("directness") or "").lower()
    if context in SOURCE_CONTEXTS:
        return context
    evidence_type = str(row.get("evidence_type") or "").lower()
    if evidence_type == "review":
        return "context"
    return "adjacent" if evidence_type == "primary" else ""


def _has_stable_source_locator(row: dict[str, Any]) -> bool:
    doi = _clean_doi(row.get("doi"))
    url = urllib.parse.urlparse(str(row.get("url") or "").strip())
    pmid = str(row.get("pmid") or (row.get("id") if row.get("source_type") == "pubmed" else "")).strip()
    return bool(re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.I) or pmid.isdigit() or url.scheme in {"http", "https"} and url.netloc)


def _has_registered_source_locator(row: dict[str, Any]) -> bool:
    return bool(
        re.fullmatch(r"10\.\d{4,9}/\S+", _clean_doi(row.get("doi")), flags=re.I)
        or re.fullmatch(r"\d{4,12}", str(row.get("pmid") or ""))
        or re.fullmatch(r"(?:https?://openalex\.org/)?W\d+", str(row.get("openalex_id") or ""), re.I)
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9._/-]{3,127}", str(row.get("registry_id") or ""))
    )


def _has_authoritative_excerpt(row: dict[str, Any]) -> bool:
    excerpt = _publication_evidence.verified_source_span(row)
    return bool(excerpt) and " is registered as " not in excerpt.lower() and "source-bundle audit for " not in excerpt.lower()


def _source_evidence_span(row: dict[str, Any]) -> str:
    text = _publication_evidence.verified_source_span(row)
    if not text or any(token in text.lower() for token in (
        "placeholder", "evidence pending", "source excerpt unavailable",
        "validated source-owned result trace", "source-bundle audit for",
    )):
        return ""
    return text if len(text) <= 600 else text[:600].rsplit(" ", 1)[0]


def _asks_source_evidence_span(ask: str) -> bool:
    lower = " ".join(ask.lower().split())
    return (
        ("evidence span" in lower or "evidence_span" in lower)
        and any(token in lower for token in ("source", "bundle"))
        and any(token in lower for token in ("load bearing", "placeholder", "substantive", "audit"))
    )


def _source_evidence_span_ask_satisfied(payload: dict[str, Any], ask: str) -> bool:
    if not _asks_source_evidence_span(ask):
        return False
    direct = [
        row for row in payload.get("source_bundle", [])
        if isinstance(row, dict) and str(row.get("directness") or "").lower() == "direct"
    ]
    return bool(direct) and all(
        _has_stable_source_locator(row) and bool(_source_evidence_span(row))
        for row in direct
    )


def authoritative_doi_repair_satisfied(run: Path, ask: str) -> bool:
    requested = {_clean_doi(match.group()).lower() for match in re.finditer(r"10\.\d{4,9}/[^\s,;]+", ask, re.I)}
    matched = [row for row in build_payload(run).get("source_bundle", []) if isinstance(row, dict) and _clean_doi(row.get("doi")).lower() in requested] if requested else []
    return "evidence text" in ask.lower() and "authoritative abstract" in ask.lower() and bool(requested) and len(matched) == len(requested) and all(_has_stable_source_locator(row) and _has_authoritative_excerpt(row) for row in matched)


def payload_revision_ask_satisfied(run: Path, ask: str) -> bool:
    return (
        authoritative_doi_repair_satisfied(run, ask)
        or _asks_source_evidence_span(ask)
        and _source_evidence_span_ask_satisfied(build_payload(run), ask)
    )


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
    author_expected = _body_citation_from_metadata({
        "title": title, "authors": [author], "year": 9999,
    }) if author and _has_stable_source_locator(row) else None
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
    unregistered_primary = sum(
        str(row.get("evidence_type") or "").lower() == "primary"
        and not _has_registered_source_locator(row)
        for row in bundle
    )
    if unregistered_primary:
        return f"source_bundle_unregistered_primary_sources:{unregistered_primary}/{len(bundle)}"
    unverified_direct = sum(
        _row_context(row) == "direct"
        and (not _has_authoritative_excerpt(row) or not _has_stable_source_locator(row))
        for row in bundle
    )
    if unverified_direct:
        return f"source_bundle_unverified_direct_sources:{unverified_direct}/{len(bundle)}"
    unverified_source_proof = sum(
        any(str(row.get(key) or "").strip() for key in ("excerpt", "quote", "evidence_span"))
        and not _publication_evidence.source_proof_is_valid(row)
        for row in bundle
    )
    if unverified_source_proof:
        return f"source_bundle_unverified_source_proof:{unverified_source_proof}/{len(bundle)}"
    missing_outcome = sum(not str(row.get("outcome_class") or "").strip() for row in bundle)
    missing_citation = sum(not _has_source_citation(row) for row in bundle)
    if missing_outcome or missing_citation:
        if not missing_outcome and _missing_citation_tolerated(bundle, missing_citation):
            return "eligible"
        return f"source_bundle_unmapped_sources:outcome={missing_outcome},citation={missing_citation}"
    return "eligible"


def _public_grade_surface_status(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "").strip().lower()
    if title.startswith(PUBLIC_BLOCKED_TITLE_PREFIXES):
        return "public_surface_compact_review"
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
            and all(context != "direct" for _, context in misses)
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
            and all(context != "direct" for _, context in misses)
        ):
            return "eligible"
        return f"source_bundle_topic_mismatch:{len(misses)}/{len(bundle)}:rows={','.join(idx for idx, _ in misses[:5])}"
    return "eligible"


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
    sections = payload.get("sections")
    values = [payload.get(key) for key in ("title", "abstract", "body_markdown")]
    if isinstance(sections, dict):
        values.extend(sections.values())
    text = " ".join(map(str, filter(None, values)))
    for code, pattern in _UNSUPPORTED_DOMAIN_FRAME_PATTERNS:
        if re.search(pattern, text, flags=re.I):
            return f"domain_frame_template_leak:{code}"
    return "eligible"


def _source_citation_hash(source_bundle: list[dict[str, Any]]) -> str:
    return _hash_json(source_bundle)


def _submission_identity_key(
    *,
    agent_slug: str,
    title: str,
    content_hash: str,
    source_citation_hash: str,
    revision_parent: str = "",
) -> str:
    material = {
        "agent_slug": agent_slug,
        "title": _normalized_key(title),
        "content_hash": content_hash,
        "source_citation_hash": source_citation_hash,
    }
    if revision_parent:
        material["revision_parent"] = revision_parent
    return _hash_json(material)


def _metadata_markers(metadata: dict[str, Any]) -> set[str]:
    return {
        value if value.startswith("sha256:") else f"sha256:{value}"
        for key in PUBLICATION_IDENTITY_KEYS
        if isinstance((value := metadata.get(key)), str) and value
    }


def _trim_submission_boilerplate(paper: str) -> str:
    for pattern in (
        r"(?m)^\*\*Outcome-class note:\*\*[^\n]*\n?",
        r"(?m)^[^\n]+ remains a separate Results slice[^\n]*Source-level findings are:\s*\n?",
        r"(?m)^Direction reconciliation: receipt-level null or unclear coding is conservative claim-level coding\.[^\n]*\n?",
        r"(?m)^### Bounded conclusion\s*\n(?=(?:The closing interpretation|Interpretation also depends|The practical takeaway|This boundary makes|The current corpus is non-supportive|Evidence for this outcome class))",
        r"(?m)^The closing interpretation must remain inside the scope of the retained source record\.[^\n]*\n?",
        r"(?m)^Interpretation also depends on fit\.[^\n]*\n?",
        r"(?m)^The practical takeaway is therefore a method for reading the synthesis,[^\n]*\n?",
        r"(?m)^This boundary makes the conclusion revisable without making it vague\.[^\n]*\n?",
        r"(?m)^The current corpus is non-supportive for clinical efficacy or general health-intervention claims;[^\n]*\n?",
        r"(?m)^Evidence scope: A subset of the retained sources is indirect,[^\n]*\n?",
        r"(?m)^The evidence profile separates direct interventional hard-endpoint evidence[^\n]*\n?",
        r"(?m)^Positive study-level signals are not the dominant direction[^\n]*\n?",
        r"(?m)^The conclusion is that [^\n]+ remains a bounded evidence case:[^\n]*\n?",
        r"(?m)^Evidence for this outcome class is represented in the structured results table,[^\n]*\n?",
    ):
        paper = re.sub(pattern, "", paper)
    return re.sub(r"\n{3,}", "\n\n", paper)


def _restore_source_bounded_conclusion(
    paper: str, source_bundle: list[dict[str, Any]],
) -> str:
    match = re.search(r"(?ms)(^## Conclusion\s*\n)(.*?)(?=^## |\Z)", paper)
    if not match or (words := _word_count(match.group(2))) >= 250:
        return paper
    anchor = build_source_bounded_conclusion(source_bundle, minimum_words=250 - words)
    if not anchor:
        return paper
    body = match.group(2).rstrip()
    replacement = f"{match.group(1)}{body}\n\n{anchor}\n\n"
    return paper[:match.start()] + replacement + paper[match.end():].lstrip()


def build_payload(run: Path, *, max_sources: int = 1000) -> dict[str, Any]:
    paper = _strip_background_references(_clean_doi_text((run / "full_paper.md").read_text(encoding="utf-8")))
    paper = paper.replace("The paper therefore reports a source-directness and outcome-class map rather than a pooled effect.", "This is a source-directness and outcome-class map rather than a pooled effect.").replace("Indirect clinical material, reviews, protocols, and mechanistic work can clarify context and plausibility", "Indirect clinical evidence, reviews, protocols, and mechanistic work can clarify context and plausibility").replace("changing the evidence tier", "changing the source tier")
    paper = re.sub(r"\A(# [^\n]+?)\s+[—-]\s+full paper\s*$", r"\1", paper, count=1, flags=re.I | re.M)
    paper = _trim_submission_boilerplate(paper)
    manifest = _read_json(run / "manifest.json")
    topic = str(manifest.get("topic") or run.name)
    # Preserve the agent's existing source URLs, source-level appraisals, and
    # exact body-to-bundle links instead of dropping them at the API boundary.
    source_bundle = _source_bundle(run, limit=max_sources)
    for row in source_bundle:
        if span := _source_evidence_span(row):
            row["evidence_span"] = span
    paper = _restore_source_bounded_conclusion(paper, source_bundle)
    paper = _publication_evidence.attach_bundle_references(paper, source_bundle)
    paper = _attach_aligned_claim_references(paper, source_bundle)
    paper = re.sub(r"(?ims)(\A# [^\n]+|^## (?:Abstract|Conclusion)\b.*?(?=^## |\Z))", lambda block: re.sub(r"\bunresolved\b", lambda word: "Unsettled" if word.group()[0].isupper() else "unsettled", block.group()), paper)
    title = paper.splitlines()[0].lstrip("# ").strip() if paper.startswith("# ") else f"Research Synthesis: {_display_topic(topic)}"
    _publication_evidence.attach_evidence_spans(paper, source_bundle)
    sections = _sections(paper)
    abstract = sections.get("Abstract") or str(manifest.get("thesis") or "")
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
    revision = _read_json(run / "researka_revision_request.json")
    revision_parent = str(revision.get("submissionId") or revision.get("artifactId") or "")
    article_type = DEFAULT_ARTICLE_TYPE
    domain_slug = _env_or_default("RESEARKA_DOMAIN_SLUG_V3", "longevity")
    category = _env_or_default("RESEARKA_CATEGORY_V3", domain_slug).removesuffix("_research")
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
            revision_parent=revision_parent,
        ),
        "counts": {
            "n_receipts": manifest.get("n_receipts"),
            "n_claims": manifest.get("n_high_confidence_claims_total"),
            "n_tensions": manifest.get("n_non_orthogonal_tensions"),
        },
    }
    if revision:
        metadata["revision_of"] = {
            key: revision.get(key)
            for key in ("artifactId", "submissionId", "source_run", "title")
            if revision.get(key)
        }
        metadata["revision_feedback"] = revision.get("feedback")
    payload = {
        "title": title[:300],
        "abstract": abstract,
        "artifact_type": "research_paper",
        "body_markdown": body_markdown,
        "sections": sections,
        "source_bundle": source_bundle,
        "author_agent_id": agent_slug,
        "article_type": article_type,
        "domain_slug": domain_slug,
        "category": category,
        "core_claims_resolved": False,
        "author_signature": content_hash,
        "metadata": metadata,
    } | ({"parent_submission_id": revision_parent} if revision.get("submissionId") else {})
    payload["core_claims_resolved"] = _researka_core_claim_trace_status(payload, source_bundle) == "eligible"
    metadata["submission_payload_hash"] = _payload_fingerprint(payload)
    return payload


def _trusted_submission_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname in TRUSTED_SUBMISSION_HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
        )
    except ValueError:
        return False


def _submitter(url: str, token: str, agent_slug: str, *, purpose: str = "resubmit") -> Submitter:
    def submit(payload: dict[str, Any]) -> dict[str, Any]:
        if not _trusted_submission_url(url):
            return {"ok": False, "status": 0, "response": "untrusted_submission_url", "preflight": True}
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
                result = json.loads(body)
                if not 200 <= response.status < 300 or _submission_id_from_response(result) is None:
                    return {
                        "ok": False, "status": response.status, "response": result,
                        "retryable": True, "unknown_submission": True,
                    }
                return {"ok": True, "status": response.status, "response": result}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "status": exc.code, "response": body[:1000]}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {
                "ok": False, "status": 0,
                "response": f"{type(exc).__name__}: {exc}", "retryable": True,
            }
    return submit


def _submit_url() -> str:
    explicit = os.getenv("RESEARKA_SUBMIT_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("RESEARKA_URL", "https://api.researka.org").rstrip("/")
    return base + "/submissions"


def _retraction_gate_status(run: Path) -> tuple[str, list[str]]:
    from agent import retraction_check
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
    publication = row.get("publication")
    publication = publication if isinstance(publication, dict) else {}
    for source in (row, metadata, publication):
        status = str(source.get("status") or source.get("publication_status") or "").strip().lower()
        if status in {"public", "published"}:
            return True
        if source.get("publicVisible") is True or source.get("public_visible") is True or source.get("published") is True:
            return True
        for key in ("publishedAt", "published_at", "published_at_iso"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return True
        keys = ("publication_id", "publicationId", "public_url")
        if any(isinstance(source.get(key), str) and source[key].strip() for key in keys):
            return True
        if source is publication and isinstance(source.get("url"), str) and source["url"].strip():
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


def _run_cycle_unlocked(
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
    candidate_inside_refresh = _inside_refresh_window(candidate_run) if candidate_run is not None else None
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
        candidate_inside_refresh=candidate_inside_refresh,
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
    try:
        result = submitter(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = {
            "ok": False, "status": 0,
            "response": f"{type(exc).__name__}: {exc}", "retryable": True,
        }
    if not isinstance(result, dict):
        result = {"ok": False, "status": 0, "response": "malformed submitter response", "retryable": True}
    try:
        status_code = int(result.get("status") or 0)
    except (TypeError, ValueError):
        status_code = 0
        result["retryable"] = True
    submission_id = _submission_id_from_response(result.get("response")) if result.get("ok") else None
    if result.get("ok") and (not 200 <= status_code < 300 or submission_id is None):
        result = {
            **result, "ok": False, "retryable": True, "unknown_submission": True,
        }
    ledger["submission"] = result
    if result.get("ok"):
        assert submission_id is not None
        _append_record(submitted_path, {
            "date": date,
            "submitted_at": dt.datetime.now(dt.UTC).isoformat(),
            "run": run.name,
            "topic": metadata.get("topic"),
            "fingerprint": fp,
            "paper_sha256": metadata.get("content_hash"),
            "submission_id": submission_id,
            "status": "submitted_to_researka",
            "http_status": status_code,
            **{key: metadata.get(key) for key in PUBLICATION_IDENTITY_KEYS if metadata.get(key)},
        })
        ledger.update({"status": "submitted_to_researka", "submitted": 1})
        _mark_considered_status(considered, run.name, "submitted_to_researka")
    elif 400 <= status_code < 500 and status_code not in TRANSIENT_SUBMISSION_STATUSES:
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
        retryable = bool(result.get("retryable")) or status_code in TRANSIENT_SUBMISSION_STATUSES or status_code >= 500
        ledger.update({"status": "submission_failed", "retryable": retryable})
        _mark_considered_status(considered, run.name, "submission_failed")
    _write_json(ledger_path, ledger)
    return ledger


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
    with submission_lock(runs_root):
        return _run_cycle_unlocked(
            runs_root=runs_root, date=date, submit=submit, submitter=submitter,
            remote_loader=remote_loader, candidate_run=candidate_run,
            skip_topics=skip_topics,
        )


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
    with submission_lock(runs_root):
        ledger_path = runs_root / LEDGER_DIR / f"{date}.json"
        previous = _read_json(ledger_path)
        durable_submitted = _submitted_count_for_date(
            runs_root / LEDGER_DIR / "_submitted_fingerprints.json", date,
        )
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
    if ledger["status"] == "submission_failed":
        return 2
    return 3 if args.submit and not int(ledger.get("submitted") or 0) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
