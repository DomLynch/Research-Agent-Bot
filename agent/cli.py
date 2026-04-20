from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from agent.drafter import RapidEvidenceDrafter
from agent.planner import QueryPlanner
from agent.provider import MimoClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.submit import submit


def _slug(value: str) -> str:
    return "-".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in value).split() if part)[:80]


def _run_stem(started_at: str, topic: str) -> str:
    stamp = started_at.replace("+00:00", "Z").replace(":", "-")
    return f"{stamp}-{_slug(topic)}"


def _write_json(run_dir: Path, payload: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{_run_stem(payload['started_at'], payload['topic'])}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_markdown(run_dir: Path, *, started_at: str, topic: str, markdown: str) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{_run_stem(started_at, topic)}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def _payload_to_markdown(payload: dict, *, topic: str, criteria: str) -> str:
    lines = [
        f"# {payload['title']}",
        "",
        f"- Topic: {topic}",
        f"- Domain: {payload['domain_slug']}",
    ]
    if criteria.strip():
        lines.append(f"- Criteria: {criteria.strip()}")
    lines.extend(["", "## Abstract", "", payload["abstract"], ""])
    for heading, body in payload.get("sections", {}).items():
        lines.extend([f"## {heading}", "", body, ""])
    if payload.get("source_bundle"):
        lines.extend(["## Sources", ""])
        for i, item in enumerate(payload["source_bundle"], start=1):
            title = item.get("title", "Untitled")
            year = item.get("year", "unknown")
            url = item.get("url")
            etype = item.get("evidence_type", "unknown")
            src = item.get("source_type", "")
            url_str = f" — {url}" if url else ""
            src_str = f", {src}" if src else ""
            lines.append(f"[{i}] {title} ({year}), {etype}{src_str}{url_str}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Research Agent Bot")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--criteria", default="")
    parser.add_argument("--per-source-limit", type=int, default=15)
    parser.add_argument("--run-dir", default="runs")
    return parser


def run_agent(
    *,
    topic: str,
    domain: str,
    criteria: str = "",
    per_source_limit: int = 15,
    run_dir: str = "runs",
) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    plan = QueryPlanner().build(topic=topic, domain_slug=domain, criteria=criteria)
    queries = plan.primary_queries()
    run_log = {
        "started_at": started_at,
        "topic": topic,
        "domain_slug": domain,
        "criteria": criteria,
        "queries": queries,
        "scope_signals": plan.scope_signals(),
        "evidence_retrieved": 0,
        "evidence_selected": 0,
        "source_errors": [],
    }
    evidence: list[dict] = []
    sources = (("pubmed", PubMedClient()), ("openalex", OpenAlexClient()))
    for query in queries:
        for source_name, client in sources:
            try:
                evidence.extend(client.search(query, limit=per_source_limit))
            except Exception as exc:
                run_log["source_errors"].append(f"{source_name}:{query}:{exc}")
    run_log["evidence_retrieved"] = len(evidence)
    year_min = int(plan.scope.get("year_min", 0) or 0)
    if year_min:
        evidence = [e for e in evidence if isinstance(e.get("year"), int) and e["year"] >= year_min]
    all_evidence = list(evidence)
    evidence = plan.filter_evidence(evidence)
    run_log["evidence_selected"] = len(evidence)
    try:
        artifact, raw_output = RapidEvidenceDrafter(provider=MimoClient.from_env()).draft(
            topic=topic,
            domain_slug=domain,
            criteria=criteria,
            queries=queries,
            evidence=all_evidence,
        )
        if raw_output:
            run_dir_p = Path(run_dir)
            run_dir_p.mkdir(parents=True, exist_ok=True)
            stem = _run_stem(started_at, topic)
            (run_dir_p / f"{stem}.raw.json").write_text(json.dumps(raw_output, indent=2), encoding="utf-8")
        run_log.update(artifact)
        if not artifact.get("error"):
            markdown = _payload_to_markdown(artifact, topic=topic, criteria=criteria)
            markdown_path = _write_markdown(Path(run_dir), started_at=started_at, topic=topic, markdown=markdown)
            run_log["markdown"] = markdown
            run_log["markdown_file"] = markdown_path.name
            import os as _os
            if _os.getenv("RESEARKA_URL"):
                try:
                    run_log["submission"] = submit(artifact)
                except Exception as exc:
                    run_log["submission_error"] = str(exc)
    except Exception as exc:
        run_log["error"] = str(exc)
    run_log["run_log"] = str(_write_json(Path(run_dir), run_log))
    return run_log


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_log = run_agent(
        topic=args.topic,
        domain=args.domain,
        criteria=args.criteria,
        per_source_limit=args.per_source_limit,
        run_dir=args.run_dir,
    )
    if run_log.get("error"):
        print(json.dumps({"error": run_log["error"], "run_log": run_log["run_log"]}))
        return 1
    print(
        json.dumps(
            {
                "model": run_log.get("model"),
                "estimated_cost_usd": run_log.get("estimated_cost_usd", 0.0),
                "markdown_file": run_log.get("markdown_file"),
                "run_log": run_log["run_log"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
