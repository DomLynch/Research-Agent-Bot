"""Deep read-only wide-basket execution planner."""
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any

PASSING_FAILURES = {"pass", "unknown", "not-run"}
BLOCKING_FAILURES = {"js", "grok", "corpus-thin"}


def build_report(
    topic_pack_dir: Path,
    runs_dir: Path,
    *,
    queue_manifest: Path | None = None,
) -> dict[str, Any]:
    packs = _load_packs(topic_pack_dir)
    runs = _load_runs(runs_dir)
    queue = _load_queue_manifest(queue_manifest)
    summaries = []
    for topic in sorted(packs):
        topic_runs = sorted(runs.get(topic, []), key=lambda row: row["run_dir"])
        latest = topic_runs[-1] if topic_runs else {}
        latest_rich = _latest([row for row in topic_runs if row["is_rich"]])
        baseline = _oldest_acceptable([row for row in topic_runs if not row["is_rich"]])
        summaries.append(_topic_summary(
            topic, packs[topic], topic_runs, latest, latest_rich, baseline, queue,
        ))
    run_now = _by_priority(summaries, "run_now")
    corpus_tune = _by_priority(summaries, "corpus_tune_first")
    l6_reruns = _by_priority(summaries, "l6_rerun")
    rich_monitor = _by_priority(summaries, "rich_monitor")
    return {
        "inventory": {
            "topic_packs": len(packs),
            "run_dirs": sum(len(items) for items in runs.values()),
            "mapped_topics": sorted(set(packs) & set(runs)),
            "run_topics_without_pack": sorted(set(runs) - set(packs)),
        },
        "queue_manifest": {
            "path": queue["path"],
            "topics": queue["topics"],
            "missing_from_packs": sorted(set(queue["topics"]) - set(packs)),
        },
        "topics": sorted(summaries, key=lambda row: row["topic"]),
        "run_now": run_now,
        "corpus_tune_first": corpus_tune,
        "l6_reruns": l6_reruns,
        "rich_monitor": rich_monitor,
    }


def rows_to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def rows_to_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Wide Basket Deep Execution Plan",
        "",
        "## Inventory",
        "",
        f"- topic packs: {data['inventory']['topic_packs']}",
        f"- run dirs: {data['inventory']['run_dirs']}",
        f"- mapped topics: {len(data['inventory']['mapped_topics'])}",
        f"- run topics without pack: {', '.join(data['inventory']['run_topics_without_pack']) or 'none'}",
        f"- queue manifest topics: {len(data['queue_manifest']['topics'])}",
        f"- queue topics without pack: {', '.join(data['queue_manifest']['missing_from_packs']) or 'none'}",
        "",
        "## First 10 Run-Now Topics",
        "",
        "| order | topic | priority | latest run | receipts | pack risk | next command |",
        "| ---: | --- | ---: | --- | ---: | --- | --- |",
    ]
    for idx, row in enumerate(data["run_now"][:10], 1):
        lines.append(
            f"| {idx} | `{row['topic']}` | {row['priority']} | "
            f"`{row['latest_run'] or 'none'}` | {row['latest_receipts']} | "
            f"{_md(', '.join(row['pack_bottlenecks']) or 'none')} | "
            f"`{row['next_command']}` |"
        )
    lines.extend([
        "",
        "Acceptance gates for run-now dry runs:",
        "",
        "- manifest exists",
        "- receipts >= 10",
        "- js_pass != false",
        "- grok_flags == 0",
        "- dry-run artifacts complete",
        "",
        "## Corpus Tune First",
        "",
        "| topic | latest failure | pack bottlenecks | tune command |",
        "| --- | --- | --- | --- |",
    ])
    for row in data["corpus_tune_first"]:
        lines.append(
            f"| `{row['topic']}` | {row['latest_failure']} | "
            f"{_md(', '.join(row['pack_bottlenecks']) or 'artifact-blocked')} | "
            f"`{row['tune_command']}` |"
        )
    lines.extend([
        "",
        "## L6 Reruns",
        "",
        "| topic | latest rich | next command | acceptance gates |",
        "| --- | --- | --- | --- |",
    ])
    for row in data["l6_reruns"]:
        lines.append(
            f"| `{row['topic']}` | `{row['latest_rich_run']}` | "
            f"`{row['next_command']}` | {_md('; '.join(row['acceptance_gates']))} |"
        )
    lines.extend([
        "",
        "## All Topics",
        "",
        "| topic | bucket | status | aliases | queries | canonical trials | latest failure | failure bucket | latest rich failure | rich delta |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ])
    for row in data["topics"]:
        delta = f"maturity {row['maturity_delta']}, receipts {row['receipt_delta']}"
        lines.append(
            f"| `{row['topic']}` | {row['bucket']} | {row['status']} | "
            f"{row['aliases']} | {row['search_queries']} | {row['canonical_trials']} | "
            f"{row['latest_failure']} | {row['failure_bucket']} | "
            f"{row['latest_rich_failure']} | {delta} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic-pack-dir", type=Path, default=Path("topic_packs"))
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--queue-manifest", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    data = build_report(
        args.topic_pack_dir,
        args.runs_dir,
        queue_manifest=args.queue_manifest,
    )
    json_text = rows_to_json(data)
    markdown_text = rows_to_markdown(data)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown_text, encoding="utf-8")
    print(json_text if args.format == "json" else markdown_text, end="")
    return 0


def _load_packs(root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(root.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        topic = str(data.get("topic") or path.stem)
        retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
        out[topic] = {
            "aliases": _list_len(data.get("aliases")),
            "search_queries": _list_len(data.get("corpus_search_queries")),
            "canonical_trials": _list_len(data.get("canonical_trials")),
            "expected_slots": _list_len(data.get("expected_evidence_slots")),
            "scope_terms": _list_len(retrieval.get("scope_terms")),
            "exclude_terms": _list_len(retrieval.get("exclude_terms")),
            "class": str(data.get("class_", "")),
        }
    return out


def _load_runs(root: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(root.glob("synthesis-*")):
        if not path.is_dir():
            continue
        topic = _topic_from_run(path.name)
        row = _run_row(path)
        out.setdefault(topic, []).append(row)
    for rows in out.values():
        _attach_l6(rows)
    return out


def _load_queue_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "topics": [], "order": {}}
    if not path.exists() and path.suffix == ".json":
        markdown = path.with_suffix(".md")
        if markdown.exists():
            path = markdown
    if path.suffix == ".md":
        topics = _topics_from_queue_markdown(path)
        return {
            "path": str(path),
            "topics": topics,
            "order": {topic: idx + 1 for idx, topic in enumerate(topics)},
        }
    data = _read_json(path)
    topics = []
    for key in ("queue", "topics", "run_now"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            topic = item.get("topic") if isinstance(item, dict) else item
            if isinstance(topic, str) and topic not in topics:
                topics.append(topic)
    return {
        "path": str(path),
        "topics": topics,
        "order": {topic: idx + 1 for idx, topic in enumerate(topics)},
    }


def _topics_from_queue_markdown(path: Path) -> list[str]:
    topics = []
    in_queue = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_queue = "Next Queue" in line or "Next 18 Topic Queue" in line
            continue
        if not in_queue:
            continue
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if not cells or cells[0] in {"topic", "order", "rank"}:
            continue
        topic = cells[1] if cells[0].isdigit() and len(cells) > 1 else cells[0]
        if re.fullmatch(r"[a-z0-9_]+", topic) and topic not in topics:
            topics.append(topic)
    return topics


def _topic_summary(
    topic: str,
    pack: dict[str, Any],
    runs: list[dict[str, Any]],
    latest: dict[str, Any],
    latest_rich: dict[str, Any],
    baseline: dict[str, Any],
    queue: dict[str, Any],
) -> dict[str, Any]:
    bottlenecks = _pack_bottlenecks(pack)
    latest_failure = str(latest.get("failure_class", "not-run"))
    latest_rich_failure = str(latest_rich.get("failure_class", "not-run"))
    has_rich = bool(latest_rich)
    maturity_delta = _delta(latest_rich, baseline, "maturity_level")
    receipt_delta = _delta(latest_rich, baseline, "receipts")
    bucket = _bucket(has_rich, latest_rich, latest_failure, latest_rich_failure, bottlenecks)
    priority = _priority(pack, latest, bucket)
    return {
        "topic": topic,
        "class": pack["class"],
        "bucket": bucket,
        "status": _status(bucket),
        "priority": priority,
        "queue_manifest_order": queue["order"].get(topic, ""),
        "aliases": pack["aliases"],
        "search_queries": pack["search_queries"],
        "canonical_trials": pack["canonical_trials"],
        "expected_slots": pack["expected_slots"],
        "scope_terms": pack["scope_terms"],
        "exclude_terms": pack["exclude_terms"],
        "pack_bottlenecks": bottlenecks,
        "run_count": len(runs),
        "rich_run_count": sum(1 for row in runs if row["is_rich"]),
        "latest_run": latest.get("run_dir", ""),
        "latest_rich_run": latest_rich.get("run_dir", ""),
        "baseline_run": baseline.get("run_dir", ""),
        "latest_failure": latest_failure,
        "latest_rich_failure": latest_rich_failure,
        "failure_bucket": _failure_bucket(latest_failure),
        "latest_verdict": latest.get("verdict", "unknown"),
        "latest_maturity": latest.get("maturity_level", 0),
        "latest_receipts": latest.get("receipts", 0),
        "latest_claims": latest.get("claims", 0),
        "latest_tensions": latest.get("tensions", 0),
        "latest_js_pass": latest.get("js_pass", "unknown"),
        "latest_grok_flags": latest.get("grok_flags", 0),
        "latest_strips": latest.get("strips", 0),
        "latest_quarantine": latest.get("quarantine_counts", 0),
        "latest_l6_candidate": latest.get("l6_candidate", False),
        "maturity_delta": maturity_delta,
        "receipt_delta": receipt_delta,
        "next_command": _next_command(topic, bucket),
        "tune_command": f"python scripts/seed_topic_corpus.py --topic {topic} --max-per-source 35",
        "acceptance_gates": _acceptance_gates(bucket),
    }


def _run_row(path: Path) -> dict[str, Any]:
    manifest = _read_json(path / "manifest.json")
    final = _read_json(path / "full_paper.final_verdict.json")
    audit = _read_json(path / "full_paper.audit.json")
    patch = _read_json(path / "full_paper.review_patch_log.json")
    receipts = _num(manifest.get("n_receipts", manifest.get("n_clusters", 0)))
    maturity = _maturity(final, manifest, audit)
    js = _js_pass(final, audit)
    grok = _num(final.get("grok_unresolved_p1", patch.get("n_flagged", 0)))
    strips = _num(final.get("auto_stripped_count", patch.get("n_auto_stripped", 0)))
    return {
        "run_dir": path.name,
        "is_rich": "RICH" in path.name,
        "verdict": _verdict(final, audit),
        "maturity_level": maturity,
        "receipts": receipts,
        "claims": _num(manifest.get("n_high_confidence_claims_total")),
        "tensions": _num(manifest.get("n_non_orthogonal_tensions")),
        "js_pass": js,
        "grok_flags": grok,
        "strips": strips,
        "quarantine_counts": _quarantine_count(manifest, audit),
        "failure_class": _failure(final, audit, receipts, js, grok, strips),
        "l6_candidate": False,
    }


def _attach_l6(rows: list[dict[str, Any]]) -> None:
    streak = 0
    for row in sorted(rows, key=lambda item: item["run_dir"]):
        streak = streak + 1 if row["maturity_level"] >= 5 else 0
        row["l6_candidate"] = streak >= 2


def _bucket(
    has_rich: bool,
    latest_rich: dict[str, Any],
    latest_failure: str,
    latest_rich_failure: str,
    bottlenecks: list[str],
) -> str:
    if has_rich:
        if latest_rich_failure in BLOCKING_FAILURES:
            return "corpus_tune_first"
        if latest_rich.get("maturity_level", 0) >= 5 and not latest_rich.get("l6_candidate"):
            return "l6_rerun"
        return "rich_monitor"
    if latest_failure in BLOCKING_FAILURES or "low_search_queries" in bottlenecks:
        return "corpus_tune_first"
    return "run_now"


def _status(bucket: str) -> str:
    return {
        "run_now": "ready",
        "corpus_tune_first": "needs corpus tuning",
        "l6_rerun": "needs L6 confirmation",
        "rich_monitor": "rich baseline present",
    }[bucket]


def _by_priority(rows: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    return sorted(
        [row for row in rows if row["bucket"] == bucket],
        key=lambda row: (int(row["priority"]), str(row["topic"])),
        reverse=True,
    )


def _priority(pack: dict[str, Any], latest: dict[str, Any], bucket: str) -> int:
    base = {
        "run_now": 100,
        "l6_rerun": 80,
        "corpus_tune_first": 50,
        "rich_monitor": 20,
    }[bucket]
    return (
        base
        + min(_num(latest.get("receipts")), 50)
        + pack["canonical_trials"] * 3
        + pack["search_queries"]
        + pack["expected_slots"]
    )


def _pack_bottlenecks(pack: dict[str, Any]) -> list[str]:
    out = []
    if pack["search_queries"] < 5:
        out.append("low_search_queries")
    if pack["expected_slots"] < 8:
        out.append("few_expected_slots")
    if pack["scope_terms"] < 3:
        out.append("few_scope_terms")
    if pack["exclude_terms"] == 0:
        out.append("no_exclude_terms")
    if pack["canonical_trials"] == 0:
        out.append("no_canonical_trials")
    return out


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
    verdict = str(final.get("verdict", "")).upper()
    if final or audit:
        return "pass" if verdict in {"AAA", "PASS", "TRUST-SPINE PASS"} else "verdict"
    return "unknown"


def _failure_bucket(failure: str) -> str:
    return {
        "js": "surface_gate",
        "grok": "grok",
        "corpus-thin": "thin_corpus",
        "verdict": "writer_or_verdict",
        "backfill": "backfill",
        "pass": "none",
        "unknown": "unknown",
        "not-run": "not_run",
    }.get(failure, "unknown")


def _next_command(topic: str, bucket: str) -> str:
    if bucket == "corpus_tune_first":
        return f"python scripts/seed_topic_corpus.py --topic {topic} --max-per-source 35"
    return f"python scripts/run_v06_synthesis.py --topic {topic} --dry-run"


def _acceptance_gates(bucket: str) -> list[str]:
    gates = ["manifest exists", "receipts >= 10", "js_pass != false", "grok_flags == 0"]
    if bucket == "l6_rerun":
        gates.append("maturity_level >= 5")
    else:
        gates.append("dry-run artifacts complete")
    return gates


def _oldest_acceptable(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in sorted(rows, key=lambda item: item["run_dir"]):
        if row["maturity_level"] >= 4 and row["receipts"] >= 10:
            return row
    return _latest(rows)


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(rows, key=lambda item: item["run_dir"])[-1] if rows else {}


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


def _verdict(final: dict[str, Any], audit: dict[str, Any]) -> str:
    if final.get("verdict"):
        return str(final["verdict"])
    if audit:
        return "pass" if audit.get("p1_pass") is True else "fail"
    return "unknown"


def _js_pass(final: dict[str, Any], audit: dict[str, Any]) -> str:
    for key in ("journal_surface_pass", "js_pass"):
        if isinstance(final.get(key), bool):
            return str(final[key]).lower()
    for check in audit.get("checks", []):
        text = f"{check.get('name', '')} {check.get('detail', '')}".lower()
        if "js" in text or "javascript" in text:
            return str(check.get("passed") is True).lower()
    return "unknown"


def _quarantine_count(manifest: dict[str, Any], audit: dict[str, Any]) -> int:
    rejected = manifest.get("rejected_evidence")
    if isinstance(rejected, list):
        return len(rejected)
    for check in audit.get("checks", []):
        match = re.search(r"(\d+)\s+rejected receipts?", str(check.get("detail", "")))
        if match:
            return int(match.group(1))
    return 0


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


def _md(value: str) -> str:
    return value.replace("|", "\\|")


if __name__ == "__main__":
    raise SystemExit(main())
