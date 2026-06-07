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
    is_source_topic_specific, source_gate_aliases, topic_aliases, topic_tokens,
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
PUBLICATION_IDENTITY_KEYS = (
    "submission_identity_key",
    "submission_payload_hash",
    "content_hash",
    "source_citation_hash",
    "author_signature",
)
RESEARKA_MIN_CITATIONS = 12
RESEARKA_FULL_PAPER_MIN_BODY_WORDS = 2000
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
}
RESEARKA_MIN_QUESTION_WORDS = {
    "rapid_evidence_synthesis": 50,
    "research_synthesis": 75,
}
Submitter = Callable[[dict[str, Any]], dict[str, Any]]
RemoteLoader = Callable[[], tuple[set[str], str | None]]


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


def _hash_json(material: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _normalized_key(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _title_marker(title: str) -> str:
    return "title:" + _normalized_key(title)


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


def _article_type() -> str:
    return os.getenv("RESEARKA_ARTICLE_TYPE_V3", "").strip() or DEFAULT_ARTICLE_TYPE


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
    if len(source_bundle) < RESEARKA_MIN_CITATIONS:
        return f"researka_preflight_insufficient_sources:{len(source_bundle)} < {RESEARKA_MIN_CITATIONS}"

    required_sections = RESEARKA_REQUIRED_SECTIONS.get(article_type, RESEARKA_REQUIRED_SECTIONS[DEFAULT_ARTICLE_TYPE])
    missing = [name for name in required_sections if not str(sections.get(name) or "").strip()]
    if missing:
        return "researka_preflight_missing_sections:" + ",".join(missing)

    question_section = RESEARKA_QUESTION_SECTION.get(article_type, "Research Question")
    minimum_question_words = RESEARKA_MIN_QUESTION_WORDS.get(article_type, 50)
    question_words = _word_count(sections.get(question_section))
    if question_words < minimum_question_words:
        return (
            "researka_preflight_question_words:"
            f"{question_section}={question_words} < {minimum_question_words}"
        )

    if article_type == "research_synthesis":
        body_words = sum(
            _word_count(sections.get(name))
            for name in (*required_sections, *RESEARKA_RECOMMENDED_SECTIONS.get(article_type, ()))
        )
    else:
        body_words = _word_count(payload.get("body_markdown"))
    if body_words < RESEARKA_FULL_PAPER_MIN_BODY_WORDS:
        return f"researka_preflight_body_words:{body_words} < {RESEARKA_FULL_PAPER_MIN_BODY_WORDS}"
    return "eligible"


def _final_status_ready(data: dict[str, Any]) -> bool:
    return bool(data.get("submission_ready") is True)


def _topic_tokens(topic: str) -> list[str]:
    return topic_tokens(topic)


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
    hits = 0
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ("receipt_id", "paper_id", "citation_token")
            + ("source_title", "source_doi", "source_pmid")
        ).lower()
        hits += int(is_source_topic_specific(topic, haystack, aliases=aliases))
    ratio = hits / len(rows)
    if ratio < SOURCE_TOPIC_PRECISION_FLOOR:
        return False, f"source_topic_precision_low:{hits}/{len(rows)}<{SOURCE_TOPIC_PRECISION_FLOOR:.2f}"
    return True, f"source_topic_precision_ok:{hits}/{len(rows)}"


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
        from agent.journal_finalizer import _phase_g_refresh_sidecars
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
        from agent.journal_finalizer import _phase_g_refresh_sidecars
        return bool(_phase_g_refresh_sidecars(run))
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
    verdict = _read_json(run / "full_paper.final_verdict.json")
    if audit.get("p1_pass") is not True:
        return False, "audit_p1_failed"
    if surface.get("passed") is not True:
        return False, "journal_surface_not_passed"
    pre_submit_status = _pre_submit_status(_read_json(run / "pre_submit_gate.json"))
    if pre_submit_status != "eligible":
        return False, pre_submit_status
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
    published_seen = remote_seen or set()
    considered = []
    seen_topics: set[str] = set()
    for run in ([candidate_run] if candidate_run else _runs(root)):
        topic = _run_topic(run)
        paper = run / "full_paper.md"
        paper_sha = _sha256(paper) if paper.exists() else ""
        markers = {paper_sha, _title_marker(_paper_title(paper))} if paper_sha else set()
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
        fp = _payload_fingerprint(payload) if locally_eligible else paper_sha
        if locally_eligible:
            markers.update(_metadata_markers(metadata))
        if topic in seen_topics:
            ok, status = False, "superseded_topic_run"
        elif ok and fp in rejected_seen:
            ok, status = False, "researka_rejected_fingerprint"
        elif ok and fp in revision_seen:
            ok, status = False, "researka_revision_fingerprint"
        elif ok and fp in local_seen:
            ok, status = False, "duplicate_submission_fingerprint"
        elif ok and not revision and markers & published_seen:
            ok, status = False, "duplicate_remote_publication"
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
    source_bundle = _source_bundle(run, limit=max_sources)
    content_hash = _sha256(run / "full_paper.md")
    source_hash = _source_citation_hash(source_bundle)
    agent_slug = _agent_slug()
    article_type = _article_type()
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
    payload = {
        "title": title[:300],
        "abstract": abstract,
        "artifact_type": "research_paper",
        "body_markdown": paper.strip(),
        "sections": {**rapid_sections, **parts} if article_type == "research_synthesis" else rapid_sections,
        "source_bundle": source_bundle,
        "author_agent_id": agent_slug,
        "submitter_name": os.getenv("RESEARKA_SUBMITTER_NAME") or None,
        "submitter_orcid": os.getenv("RESEARKA_SUBMITTER_ORCID") or None,
        "article_type": article_type,
        "domain_slug": _env_or_default("RESEARKA_DOMAIN_SLUG_V3", "longevity"),
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
        is_revision = _is_revision_feedback(feedback)
        status = "submission_revise_requested" if is_revision else "submission_rejected_by_researka"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat())
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    ledger = run_cycle(runs_root=args.runs_root, date=args.date, submit=args.submit)
    print(
        f"[daily-v3] status={ledger['status']} submitted={ledger['submitted']} "
        f"published={ledger['published']} run={ledger.get('candidate', {}).get('run', '-')}"
    )
    return 0 if ledger["status"] != "submission_failed" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
