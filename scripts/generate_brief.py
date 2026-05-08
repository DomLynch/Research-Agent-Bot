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

BRIEF_FILES = (
    "brief",
    "audit",
    "citations",
    "provenance",
    "numeric_quarantine",
)


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
    _assert_citation_whitelist(draft.body_md, run_dir, manifest, receipts)

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
    paths["numeric_quarantine"].write_text(
        json.dumps(_numeric_quarantine_doc(run_dir), indent=2) + "\n",
    )
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


def _receipt_id(receipt: dict[str, Any]) -> str:
    return str(receipt.get("receipt_id") or receipt.get("paper_id") or "")


def _citation_token(receipt: dict[str, Any]) -> str:
    return str(receipt.get("citation_token") or "").strip()


def _assert_citation_whitelist(
    body_md: str,
    run_dir: Path,
    manifest: dict[str, Any],
    receipts: tuple[dict[str, Any], ...],
) -> None:
    allowed = {_citation_token(r) for r in receipts if _citation_token(r)}
    all_tokens = {
        _citation_token(r) for r in manifest.get("receipts", [])
        if isinstance(r, dict) and _citation_token(r)
    }
    all_tokens |= _citation_registry_tokens(run_dir)
    leaked = sorted(token for token in all_tokens - allowed if token in body_md)
    if leaked:
        raise RuntimeError(
            "brief cites receipt(s) outside filtered whitelist: "
            + ", ".join(leaked)
        )


def _citation_registry_tokens(run_dir: Path) -> set[str]:
    registry = run_dir / "citation_registry.json"
    if not registry.exists():
        return set()
    data = _read_json(registry)
    if not isinstance(data, dict):
        return set()
    return {str(token) for token in data if str(token).strip()}


def _provenance_doc(
    query: Any, run_dir: Path, manifest: dict[str, Any], draft: Any,
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    registry_path = run_dir / "citation_registry.json"
    return {
        "schema": "researka.brief_provenance.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_run": run_dir.name,
        "source_manifest": "manifest.json",
        "source_manifest_sha256": _sha256_file(manifest_path),
        "source_citation_registry": (
            "citation_registry.json" if registry_path.exists() else None
        ),
        "source_citation_registry_sha256": (
            _sha256_file(registry_path) if registry_path.exists() else None
        ),
        "topic": draft.topic,
        "query": query.to_dict(),
        "source_run_receipts": int(manifest.get("n_receipts", 0)),
        "brief_receipts": len(draft.receipts),
        "brief_receipt_ids": [_receipt_id(r) for r in draft.receipts],
        "citation_whitelist": [
            token for r in draft.receipts if (token := _citation_token(r))
        ],
    }


def _numeric_quarantine_doc(run_dir: Path) -> Any:
    source = next(
        (
            run_dir / name for name in (
                "numeric_quarantine.json",
                "numeric_claim_quarantine.json",
            )
            if (run_dir / name).exists()
        ),
        run_dir / "numeric_quarantine.json",
    )
    items: list[Any] = []
    if not source.exists():
        return []
    data = json.loads(source.read_text())
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    else:
        raise ValueError(f"malformed numeric quarantine: {source}")
    return {
        "schema": "researka.brief_numeric_quarantine.v1",
        "source_numeric_quarantine": source.name,
        "source_numeric_quarantine_sha256": _sha256_file(source),
        "items": items,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
