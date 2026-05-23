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
TOKEN_ENVS = (
    "RESEARKA_API_KEY_V3",
    "RESEARKA_API_TOKEN_V3",
    "RESEARKA_AGENT_TOKEN_V3",
    "RESEARKA_V2_API_KEY",
)
Submitter = Callable[[dict[str, Any]], dict[str, Any]]


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


def _pre_submit_passed(data: dict[str, Any]) -> bool:
    result = data.get("result")
    return bool(data.get("passed") is True or isinstance(result, dict) and result.get("passed") is True)


def _eligible(run: Path) -> tuple[bool, str]:
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
    if not (audit.get("p1_pass") is True and audit.get("n_pass") == audit.get("n_total")):
        return False, "audit_not_all_green"
    if surface.get("passed") is not True:
        return False, "journal_surface_not_passed"
    if str(verdict.get("verdict", "")).upper() != "AAA":
        return False, "final_verdict_not_aaa"
    if not _pre_submit_passed(_read_json(run / "pre_submit_gate.json")):
        return False, "pre_submit_not_passed"
    return True, "eligible"


def _seen(path: Path) -> set[str]:
    data = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {str(row.get("fingerprint")) for row in data if isinstance(row, dict)}


def select_candidate(root: Path, submitted_path: Path) -> tuple[Path | None, list[dict[str, Any]]]:
    seen = _seen(submitted_path)
    considered = []
    for run in _runs(root):
        paper = run / "full_paper.md"
        fp = _sha256(paper) if paper.exists() else ""
        ok, status = _eligible(run)
        if ok and fp in seen:
            ok, status = False, "duplicate_submission_fingerprint"
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
    rows.sort(key=lambda row: int(receipts.get(str(row.get("receipt_id")), {}).get("n_claims") or 0), reverse=True)
    bundle = []
    for row in rows[:limit]:
        receipt = receipts.get(str(row.get("receipt_id")), {})
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
        })
    return bundle


def build_payload(run: Path, *, max_sources: int = 40) -> dict[str, Any]:
    paper = (run / "full_paper.md").read_text(encoding="utf-8")
    manifest = _read_json(run / "manifest.json")
    topic = str(manifest.get("topic") or run.name)
    title = paper.splitlines()[0].lstrip("# ").strip() if paper.startswith("# ") else f"Research Synthesis: {_display_topic(topic)}"
    return {
        "domain_slug": os.getenv("RESEARKA_DOMAIN_SLUG_V3", "longevity"),
        "author_agent_slug": os.getenv("RESEARKA_AGENT_SLUG_V3", os.getenv("AGENT_ID", "agent-v3-full-paper")),
        "object_type": "proposal",
        "title": title[:300],
        "abstract": _section(paper, "Abstract", fallback=str(manifest.get("thesis") or "")),
        "body_markdown": paper,
        "source_bundle": _source_bundle(run, limit=max_sources),
        "article_type": "evidence_synthesis",
        "research_mode": "source_grounded_synthesis",
        "tags": ["research_paper", "agent-v3"],
        "metadata": {
            "artifact_type": "research_paper",
            "run_id": run.name,
            "topic": topic,
            "content_hash": _sha256(run / "full_paper.md"),
            "counts": {
                "n_receipts": manifest.get("n_receipts"),
                "n_claims": manifest.get("n_high_confidence_claims_total"),
                "n_tensions": manifest.get("n_non_orthogonal_tensions"),
            },
        },
        "auto_enqueue_follow_up": True,
    }


def _submitter(url: str, token: str, agent_slug: str) -> Submitter:
    def submit(payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Agent-Slug": agent_slug,
                "X-Agent-Key": token,
                "Idempotency-Key": str(payload.get("metadata", {}).get("content_hash") or ""),
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
    explicit = os.getenv("RESEARKA_RESEARCH_OBJECTS_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("RESEARKA_URL", "https://api.researka.org").rstrip("/")
    return base + "/v1/research-objects"


def run_cycle(
    *,
    runs_root: Path = RUNS,
    date: str,
    submit: bool = False,
    submitter: Submitter | None = None,
) -> dict[str, Any]:
    ledger_path = runs_root / LEDGER_DIR / f"{date}.json"
    submitted_path = runs_root / LEDGER_DIR / "_submitted_fingerprints.json"
    ledger: dict[str, Any] = {"date": date, "dry_run": not submit, "submitted": 0, "published": 0, "status": "started"}
    run, considered = select_candidate(runs_root, submitted_path)
    ledger["considered"] = considered
    if run is None:
        ledger.update({"status": "no_eligible_research_paper"})
        _write_json(ledger_path, ledger)
        return ledger
    payload = build_payload(run)
    fp = payload["metadata"]["content_hash"]
    ledger["candidate"] = {"run": run.name, "topic": payload["metadata"]["topic"], "fingerprint": fp}
    if not submit:
        ledger.update({"status": "dry_run_selected"})
        _write_json(ledger_path, ledger)
        return ledger
    token, token_env = _token()
    if submitter is None:
        if not token:
            ledger.update({"status": "submit_not_configured", "reason": "missing_v3_submit_token", "accepted_env_vars": list(TOKEN_ENVS)})
            _write_json(ledger_path, ledger)
            return ledger
        ledger["submit_token_env"] = token_env
        submitter = _submitter(_submit_url(), token, payload["author_agent_slug"])
    result = submitter(payload)
    ledger["submission"] = result
    if result.get("ok"):
        records = []
        try:
            records = json.loads(submitted_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        if not isinstance(records, list):
            records = []
        records.append({"date": date, "run": run.name, "topic": payload["metadata"]["topic"], "fingerprint": fp})
        _write_json(submitted_path, records)
        ledger.update({"status": "submitted_to_researka", "submitted": 1})
    else:
        ledger.update({"status": "submission_failed"})
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
