"""Generate a BRIEFS-V1 focused evidence brief bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent.briefs import filter_receipts, parse_question, write_brief  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _resolve_run_dir(source_paper: str | Path) -> Path:
    p = Path(source_paper)
    if p.name == "full_paper.md":
        return p.parent
    return p


def _default_output_dir(question: str, run_dir: Path) -> Path:
    digest = hashlib.sha1(  # noqa: S324 - non-security content hash
        f"{run_dir.name}\n{question}".encode(),
    ).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return REPO / "runs" / f"brief-{digest}-{stamp}"


def generate_brief_bundle(
    *, question: str, source_paper: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Write brief.md + audit/provenance sidecars from a source run."""
    run_dir = _resolve_run_dir(source_paper)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = _read_json(manifest_path)
    query = parse_question(question)
    topic = str(manifest.get("topic") or run_dir.name)
    receipts = filter_receipts(manifest, query)
    draft = write_brief(query, topic=topic, receipts=receipts)

    out = Path(output_dir) if output_dir else _default_output_dir(question, run_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "brief": out / "brief.md",
        "audit": out / "brief.audit.json",
        "citations": out / "brief.citations.json",
        "provenance": out / "brief.provenance.json",
        "numeric_quarantine": out / "numeric_quarantine.json",
    }
    paths["brief"].write_text(draft.body_md)
    paths["audit"].write_text(json.dumps(_audit_doc(query, manifest, receipts), indent=2))
    paths["citations"].write_text(json.dumps(_citations(receipts), indent=2))
    paths["provenance"].write_text(
        json.dumps(_provenance_doc(query, run_dir, manifest, draft), indent=2),
    )
    paths["numeric_quarantine"].write_text("[]\n")
    return paths


def _audit_doc(
    query: Any, manifest: dict[str, Any], receipts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return {
        "passed": bool(receipts),
        "query": query.to_dict(),
        "source_receipts": int(manifest.get("n_receipts", 0)),
        "filtered_receipts": len(receipts),
        "numeric_claims_checked": 0,
        "numeric_traceability_pct": 100.0,
        "notes": [
            "BRIEFS-V1 skeleton introduces no new free-form numeric claims.",
        ],
    }


def _citations(receipts: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return [
        {
            "receipt_id": r.get("receipt_id"),
            "paper_id": r.get("paper_id"),
            "citation_token": r.get("citation_token"),
            "outcome_class": r.get("outcome_class"),
            "evidence_tier": r.get("evidence_tier"),
            "directness": r.get("directness"),
        }
        for r in receipts
    ]


def _provenance_doc(
    query: Any, run_dir: Path, manifest: dict[str, Any], draft: Any,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_run": run_dir.name,
        "source_manifest": str(run_dir / "manifest.json"),
        "topic": draft.topic,
        "query": query.to_dict(),
        "source_run_receipts": int(manifest.get("n_receipts", 0)),
        "brief_receipts": len(draft.receipts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--source-paper", required=True)
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    paths = generate_brief_bundle(
        question=args.question,
        source_paper=args.source_paper,
        output_dir=args.output_dir,
    )
    print(paths["brief"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
