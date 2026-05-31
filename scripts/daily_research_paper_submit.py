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
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
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


def _final_status_ready(data: dict[str, Any]) -> bool:
    return bool(data.get("submission_ready") is True)


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
    if not _pre_submit_passed(_read_json(run / "pre_submit_gate.json")):
        return False, "pre_submit_not_passed"
    final_status = _read_json(run / "final_status.json")
    if final_status and not _final_status_ready(final_status):
        return False, "final_status_not_ready"
    if not final_status and str(verdict.get("verdict", "")).upper() != "AAA":
        return False, "final_verdict_not_aaa"
    return True, "eligible"


def _seen(path: Path) -> set[str]:
    data = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {str(row.get("fingerprint")) for row in data if isinstance(row, dict)}


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
        fp = _sha256(paper) if paper.exists() else ""
        markers = {fp, _title_marker(_paper_title(paper))} if fp else set()
        locally_eligible, status = _eligible(run)
        ok = locally_eligible
        if topic in seen_topics:
            ok, status = False, "superseded_topic_run"
        elif ok and fp in rejected_seen:
            ok, status = False, "researka_rejected_fingerprint"
        elif ok and fp in revision_seen:
            ok, status = False, "researka_revision_fingerprint"
        elif ok and fp in local_seen:
            ok, status = False, "duplicate_submission_fingerprint"
        elif ok and markers & published_seen:
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
    return " ".join((match.group("body") if match else fallback).split())[:1400]


def _sections(markdown: str) -> dict[str, str]:
    pattern = re.compile(r"^## (?P<heading>[^\n#].*?)\s*\n(?P<body>.*?)(?=^## |\Z)", re.M | re.S)
    return {
        match.group("heading").strip(): match.group("body").strip()
        for match in pattern.finditer(markdown)
        if match.group("body").strip()
    }


def _demote_headings(markdown: str) -> str:
    return re.sub(r"^(#{1,5})(\s+)", r"#\1\2", markdown.strip(), flags=re.M)


def _display_topic(slug: str) -> str:
    return slug.replace("_", " ").strip().title() or "Research Synthesis"


def _citation_url(row: dict[str, Any]) -> str | None:
    doi = str(row.get("source_doi") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    pmid = str(row.get("source_pmid") or "").strip()
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    pmcid = str(row.get("source_pmcid") or "").strip()
    return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/" if pmcid else None


def _source_bundle(run: Path, *, limit: int) -> list[dict[str, Any]]:
    manifest = _read_json(run / "manifest.json")
    registry = _read_json(run / "citation_registry.json")
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
    bundle = []
    for row in rows[:limit]:
        receipt = receipts.get(str(row.get("receipt_id")), {})
        directness = str(receipt.get("directness") or "").lower()
        title = str(row.get("title") or row.get("body_citation") or row.get("receipt_id") or "Evidence receipt")[:300]
        excerpt = (
            f"{row.get('body_citation') or title} is registered as {row.get('reference_id') or 'a source'} "
            f"for outcome {receipt.get('outcome_class') or 'unspecified'} with "
            f"{receipt.get('n_claims') or 0} extracted claim(s), "
            f"{receipt.get('effect_direction') or 'unclear'} direction, and "
            f"{receipt.get('directness') or 'unspecified'} directness."
        )
        bundle.append({
            "source_type": "pubmed" if row.get("source_pmid") else "corpus",
            "id": str(row.get("source_pmid") or row.get("source_pmcid") or row.get("reference_id") or row.get("receipt_id") or ""),
            "title": title,
            "url": _citation_url(row),
            "doi": row.get("source_doi") or None,
            "excerpt": excerpt,
            "year": row.get("source_year") if isinstance(row.get("source_year"), int) else None,
            "evidence_type": "primary" if directness == "direct" else "review",
        })
    return bundle


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
    metadata: dict[str, Any] = {
        "artifact_type": "research_paper",
        "run_id": run.name,
        "topic": topic,
        "content_hash": _sha256(run / "full_paper.md"),
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
    return {
        "title": title[:300],
        "abstract": abstract,
        "sections": {
            "Research Question": f"What does the current evidence establish about {_display_topic(topic)} and human geroscience? {abstract}",
            "Search Summary": methods or abstract,
            "Evidence Landscape": results or abstract,
            "Key Findings": results or discussion or abstract,
            "Limitations": limitations or discussion or abstract,
            "Gaps Identified": discussion or limitations or abstract,
            "Conclusion": conclusion or abstract,
            "Full Manuscript": _demote_headings(paper),
        },
        "source_bundle": _source_bundle(run, limit=max_sources),
        "author_agent_id": os.getenv("RESEARKA_AGENT_SLUG_V3", os.getenv("AGENT_ID", "agent-v3-full-paper")),
        "submitter_name": os.getenv("RESEARKA_SUBMITTER_NAME") or None,
        "submitter_orcid": os.getenv("RESEARKA_SUBMITTER_ORCID") or None,
        "article_type": "rapid_evidence_synthesis",
        "domain_slug": os.getenv("RESEARKA_DOMAIN_SLUG_V3", "longevity"),
        "core_claims_resolved": True,
        "author_signature": _sha256(run / "full_paper.md"),
        "metadata": metadata,
    }


def _submitter(url: str, token: str, agent_slug: str) -> Submitter:
    def submit(payload: dict[str, Any]) -> dict[str, Any]:
        metadata = payload.get("metadata")
        content_hash = metadata.get("content_hash") if isinstance(metadata, dict) else ""
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-api-key": token,
                "X-Agent-Slug": agent_slug,
                "Idempotency-Key": str(content_hash or ""),
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
    base = os.getenv("RESEARKA_URL", "https://api.researka.org").rstrip("/")
    return base + "/publications"


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
            for key in ("content_hash", "sha256", "full_body_sha256", "condensed_body_sha256"):
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
    fp = payload["metadata"]["content_hash"]
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
    result = submitter(payload)
    ledger["submission"] = result
    if result.get("ok"):
        _append_record(submitted_path, {"date": date, "run": run.name, "topic": metadata.get("topic"), "fingerprint": fp})
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
