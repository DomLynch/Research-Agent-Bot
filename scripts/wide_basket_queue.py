"""Build a read-only wide-basket queue from topic packs and run artifacts."""
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any


def build_report(topic_pack_dir: Path, runs_dir: Path, *, limit: int = 20) -> dict[str, Any]:
    packs = _topic_packs(topic_pack_dir)
    runs = _runs_by_topic(runs_dir)
    rich_topics = {topic for topic, paths in runs.items() if any("RICH" in p.name for p in paths)}
    queue = sorted([
        _queue_entry(topic, pack, runs.get(topic, []))
        for topic, pack in sorted(packs.items())
        if topic not in rich_topics
    ], key=_queue_sort)[:limit]
    rich = [_rich_comparison(topic, paths) for topic, paths in sorted(runs.items()) if topic in rich_topics]
    return {
        "inventory": {
            "topic_packs": len(packs),
            "run_dirs": sum(len(paths) for paths in runs.values()),
            "rich_topics": sorted(rich_topics),
            "mapped_topics": sorted(set(packs) & set(runs)),
            "unmapped_run_topics": sorted(set(runs) - set(packs)),
        },
        "queue": queue,
        "evidence_ranking": _evidence_ranking(packs, runs),
        "topics_with_no_rich_rerun": [row["topic"] for row in queue],
        "rich_baseline_comparison": rich,
        "cert_regressions": [
            item for item in rich
            if isinstance(item["maturity_delta"], int) and item["maturity_delta"] < 0
        ],
        "corpus_regressions": [
            item for item in rich
            if isinstance(item["receipt_delta"], int) and item["receipt_delta"] < 0
        ],
        "l6_reruns_needed": [
            item for item in rich
            if item["latest_rich_maturity"] >= 5 and not item["latest_rich_l6_candidate"]
        ],
        "journal_surface_blocks": [
            item for item in rich if item["latest_rich_journal_surface"] == "false"
        ],
        "watchlist": _watchlist(rich),
    }


def rows_to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def rows_to_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Wide Basket Queue",
        "",
        "## Inventory",
        "",
        f"- topic packs: {data['inventory']['topic_packs']}",
        f"- run dirs: {data['inventory']['run_dirs']}",
        f"- rich topics: {', '.join(data['inventory']['rich_topics'])}",
        f"- unmapped run topics: {', '.join(data['inventory']['unmapped_run_topics']) or 'none'}",
        "",
        "## Evidence Richness",
        "",
        "| topic | best_receipts | best_maturity | runs | rich_runs |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in data["evidence_ranking"][:20]:
        lines.append(
            "| "
            + " | ".join(_md(row[key]) for key in (
                "topic", "best_receipts", "best_maturity", "runs", "rich_runs",
            ))
            + " |"
        )
    lines.extend([
        "",
        "## Next Queue",
        "",
        "| topic | status | corpus_expectation | latest_run | latest_failure | notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in data["queue"]:
        lines.append(
            "| "
            + " | ".join(_md(row[key]) for key in (
                "topic", "status", "corpus_expectation", "latest_run",
                "latest_failure", "notes",
            ))
            + " |"
        )
    lines.extend([
        "",
        "## Rich vs Baseline",
        "",
        "| topic | latest_rich | baseline | maturity_delta | receipt_delta | journal_surface |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in data["rich_baseline_comparison"]:
        lines.append(
            "| "
            + " | ".join(_md(row[key]) for key in (
                "topic", "latest_rich", "baseline", "maturity_delta",
                "receipt_delta", "latest_rich_journal_surface",
            ))
            + " |"
        )
    lines.extend([
        "",
        "## Rerun Flags",
        "",
        f"- L6 reruns needed: {len(data['l6_reruns_needed'])}",
        f"- journal-surface blocks: {len(data['journal_surface_blocks'])}",
        f"- cert regressions: {len(data['cert_regressions'])}",
        f"- corpus regressions: {len(data['corpus_regressions'])}",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic-pack-dir", type=Path, default=Path("topic_packs"))
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    data = build_report(args.topic_pack_dir, args.runs_dir, limit=args.limit)
    json_text = rows_to_json(data)
    markdown_text = rows_to_markdown(data)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown_text, encoding="utf-8")
    print(json_text if args.format == "json" else markdown_text, end="")
    return 0


def _topic_packs(root: Path) -> dict[str, dict[str, Any]]:
    packs = {}
    for path in sorted(root.glob("*.toml")):
        if path.stem.startswith("_"):
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if str(data.get("class_", "")) == "template":
            continue
        packs[str(data.get("topic") or path.stem)] = data
    return packs


def _runs_by_topic(root: Path) -> dict[str, list[Path]]:
    runs: dict[str, list[Path]] = {}
    for path in sorted(root.glob("synthesis-*")):
        if not path.is_dir():
            continue
        topic = _topic_from_run(path.name)
        runs.setdefault(topic, []).append(path)
    return runs


def _queue_entry(topic: str, pack: dict[str, Any], paths: list[Path]) -> dict[str, Any]:
    latest = _latest(paths)
    row = _run_row(latest) if latest else {}
    queries = _list_len(pack.get("corpus_search_queries"))
    slots = _list_len(pack.get("expected_evidence_slots"))
    trials = _list_len(pack.get("canonical_trials"))
    status = _status(row, queries)
    return {
        "topic": topic,
        "status": status,
        "corpus_expectation": _expectation(queries, slots, trials),
        "search_queries": queries,
        "expected_slots": slots,
        "canonical_trials": trials,
        "latest_run": latest.name if latest else "",
        "latest_failure": row.get("failure_class", "not-run"),
        "notes": _notes(status, row, queries),
    }


def _rich_comparison(topic: str, paths: list[Path]) -> dict[str, Any]:
    rich = _latest([p for p in paths if "RICH" in p.name])
    baseline = _oldest_acceptable([p for p in paths if "RICH" not in p.name])
    rich_row = _run_row(rich) if rich else {}
    base_row = _run_row(baseline) if baseline else {}
    return {
        "topic": topic,
        "latest_rich": rich.name if rich else "",
        "baseline": baseline.name if baseline else "",
        "latest_rich_maturity": int(rich_row.get("maturity_level", 0)),
        "baseline_maturity": int(base_row.get("maturity_level", 0)),
        "maturity_delta": _delta(rich_row, base_row, "maturity_level"),
        "latest_rich_receipts": int(rich_row.get("receipts", 0)),
        "baseline_receipts": int(base_row.get("receipts", 0)),
        "receipt_delta": _delta(rich_row, base_row, "receipts"),
        "latest_rich_journal_surface": rich_row.get("journal_surface", "unknown"),
        "latest_rich_l6_candidate": _l6_candidate(paths, rich),
        "latest_rich_failure": rich_row.get("failure_class", "unknown"),
    }


def _evidence_ranking(
    packs: dict[str, dict[str, Any]], runs: dict[str, list[Path]],
) -> list[dict[str, Any]]:
    rows = []
    for topic in sorted(packs):
        run_rows = [_run_row(path) for path in runs.get(topic, [])]
        rows.append({
            "topic": topic,
            "best_receipts": max((row["receipts"] for row in run_rows), default=0),
            "best_maturity": max((row["maturity_level"] for row in run_rows), default=0),
            "runs": len(runs.get(topic, [])),
            "rich_runs": sum(1 for path in runs.get(topic, []) if "RICH" in path.name),
        })
    return sorted(rows, key=lambda row: (
        int(row["best_receipts"]), int(row["best_maturity"]), int(row["rich_runs"]),
    ), reverse=True)


def _watchlist(rich: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rich:
        reasons = []
        if row["latest_rich_journal_surface"] == "false":
            reasons.append("journal-surface")
        if isinstance(row["maturity_delta"], int) and row["maturity_delta"] < 0:
            reasons.append("cert-regression")
        if isinstance(row["receipt_delta"], int) and row["receipt_delta"] < 0:
            reasons.append("corpus-regression")
        if row["latest_rich_failure"] in {"grok", "corpus-thin", "backfill"}:
            reasons.append(row["latest_rich_failure"])
        if reasons:
            out.append({"topic": row["topic"], "run": row["latest_rich"], "reasons": reasons})
    return out


def _run_row(path: Path) -> dict[str, Any]:
    manifest = _read_json(path / "manifest.json")
    final = _read_json(path / "full_paper.final_verdict.json")
    patch = _read_json(path / "full_paper.review_patch_log.json")
    audit = _read_json(path / "full_paper.audit.json")
    receipts = _num(manifest.get("n_receipts", manifest.get("n_clusters", 0)))
    maturity = _maturity(final, manifest, audit)
    js = _journal_surface(final, audit)
    grok = _num(final.get("grok_unresolved_p1", patch.get("n_flagged", 0)))
    strips = _num(final.get("auto_stripped_count", patch.get("n_auto_stripped", 0)))
    return {
        "receipts": receipts,
        "maturity_level": maturity,
        "journal_surface": js,
        "grok_flags": grok,
        "strips": strips,
        "failure_class": _failure(final, audit, receipts, js, grok, strips),
    }


def _failure(
    final: dict[str, Any], audit: dict[str, Any], receipts: int, js: str, grok: int, strips: int,
) -> str:
    if js == "false":
        return "js"
    if grok > 0:
        return "grok"
    if final.get("corpus_gaps") or receipts < 10:
        return "corpus-thin"
    if strips > 0:
        return "backfill"
    if str(final.get("verdict", "")).upper() not in {"AAA", "PASS", "TRUST-SPINE PASS"}:
        return "verdict" if final or audit else "unknown"
    return "pass"


def _status(row: dict[str, Any], queries: int) -> str:
    if queries < 5:
        return "needs corpus tuning"
    if row.get("failure_class") in {"js", "grok", "corpus-thin"}:
        return "needs corpus tuning"
    return "ready"


def _queue_sort(row: dict[str, Any]) -> tuple[int, int, int, str]:
    status_score = 0 if row["status"] == "ready" else 1
    expectation_score = {"high": 0, "medium": 1, "sparse": 2}[row["corpus_expectation"]]
    latest_failure_score = 1 if row["latest_failure"] in {"js", "grok", "corpus-thin"} else 0
    return (status_score, expectation_score, latest_failure_score, str(row["topic"]))


def _expectation(queries: int, slots: int, trials: int) -> str:
    if trials >= 3 or queries >= 7:
        return "high"
    if queries >= 5 and slots >= 8:
        return "medium"
    return "sparse"


def _notes(status: str, row: dict[str, Any], queries: int) -> str:
    if status == "ready" and not row:
        return "topic pack has enough corpus queries; no local run yet"
    if status == "needs corpus tuning":
        return f"latest failure={row.get('failure_class', 'none')}; queries={queries}"
    return "latest local signal does not block queueing"


def _latest(paths: list[Path]) -> Path | None:
    return sorted(paths, key=lambda path: path.name)[-1] if paths else None


def _oldest_acceptable(paths: list[Path]) -> Path | None:
    acceptable = [
        path for path in sorted(paths, key=lambda item: item.name)
        if _run_row(path)["maturity_level"] >= 4 and _run_row(path)["receipts"] >= 10
    ]
    return acceptable[0] if acceptable else _latest(paths)


def _l6_candidate(paths: list[Path], latest: Path | None) -> bool:
    if latest is None:
        return False
    streak = 0
    for path in sorted(paths, key=lambda item: item.name):
        row = _run_row(path)
        streak = streak + 1 if row["maturity_level"] >= 5 else 0
        if path == latest:
            return streak >= 2
    return False


def _topic_from_run(name: str) -> str:
    match = re.match(r"synthesis-(.+?)-(?:v\d+|\d{3})-", name)
    return match.group(1) if match else name.removeprefix("synthesis-")


def _maturity(final: dict[str, Any], manifest: dict[str, Any], audit: dict[str, Any]) -> int:
    for data in (final, manifest, audit):
        for key in ("maturity_level", "level"):
            if isinstance(data.get(key), int | float):
                return int(data[key])
    if str(final.get("verdict", "")).upper() == "AAA":
        return 5
    return 4 if audit.get("p1_pass") is True else 0


def _journal_surface(final: dict[str, Any], audit: dict[str, Any]) -> str:
    for key in ("journal_surface_pass", "js_pass"):
        if isinstance(final.get(key), bool):
            return str(final[key]).lower()
    for check in audit.get("checks", []):
        text = f"{check.get('name', '')} {check.get('detail', '')}".lower()
        if "js" in text or "javascript" in text:
            return str(check.get("passed") is True).lower()
    return "unknown"


def _delta(a: dict[str, Any], b: dict[str, Any], key: str) -> int | str:
    return int(a[key]) - int(b[key]) if key in a and key in b else ""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _num(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
