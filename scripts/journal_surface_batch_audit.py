#!/usr/bin/env python3
"""Read-only batch QA for public manuscript journal surface."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = "researka.journal_surface_batch_audit.v1"
BODY_CUTOFF_RE = re.compile(
    r"^##\s+(?:Publication Appendix|Researka Submitter Block|"
    r"Researka Submission Block|"
    r"Data and Code Availability|Search Provenance|AI(?:-Use)? Disclosure|"
    r"Accountability|References)\b",
    re.M,
)
FORBIDDEN_PATTERNS = {
    "audit_meta": (
        "claim_graph.json", "spar_review.json", "patch trail",
        "full grok review", "run manifest", "bundle contains",
        "trust-spine bundle", "certification record", "audit bundle",
    ),
    "template_meta": (
        "this synthesis was produced by", "submission `synthesis-",
        "final-layer reviewer", "patches are auto-applied",
        "spar", "grok", "llm proposes, code disposes", "no llm authorship",
        "rejected-evidence quarantine did not run",
    ),
    "placeholder": (
        "lorem ipsum", "todo", "fixme", "tbd", "insert ",
        "section generation cannot satisfy the validation contract",
        "generated section cannot satisfy the validation contract",
        "deterministic evidence summary", "deterministic synthesis summary",
        "accepted receipts contain source-traced quantitative evidence",
        "this paper evaluates the topic through accepted receipts",
        "the background is limited to corpus-supported context",
        "the conclusion is limited to claims that survive receipt qualification",
        "fallback stub used", "conservative placeholder",
    ),
}
CITATION_ARTIFACT_RE = re.compile(
    r"\[(?:citation needed|source|ref|pmid|doi|TODO)[^\]]*\]"
    r"|(?:^|\s)(?:PMID|DOI):?\s*$"
    r"|<\s*(?:citation|ref)[^>]*>",
    re.I | re.M,
)
HEDGE_FRAGMENT_RE = re.compile(
    r"^(?:may|might|could|appears|suggests|uncertain|preliminary|"
    r"context[- ]dependent|not definitive|requires confirmation)\.?$",
    re.I,
)


@dataclass(frozen=True, slots=True)
class Issue:
    issue_type: str
    severity: str
    location: str
    detail: str


def manuscript_path(run_dir: Path) -> Path:
    for name in ("full_paper.md", "paper.md", "paper_synthesis.md"):
        path = run_dir / name
        if path.exists():
            return path
    raise FileNotFoundError(f"no manuscript found in {run_dir}")


def public_body(text: str) -> str:
    match = BODY_CUTOFF_RE.search(text)
    return text[:match.start()] if match else text


def audit_run(run_dir: Path) -> dict:
    paper = manuscript_path(run_dir)
    body = public_body(paper.read_text(encoding="utf-8"))
    issues = [
        *scan_forbidden(body),
        *scan_duplicate_paragraphs(body),
        *scan_citation_artifacts(body),
        *scan_qei_rows(body),
        *scan_hedge_fragments(body),
    ]
    return {
        "run_dir": str(run_dir),
        "manuscript": str(paper),
        "passed": not issues,
        "issue_count": len(issues),
        "issues": [asdict(issue) for issue in issues],
    }


def scan_forbidden(body: str) -> list[Issue]:
    low = _norm_text(body)
    issues: list[Issue] = []
    for issue_type, patterns in FORBIDDEN_PATTERNS.items():
        for pattern in patterns:
            norm = _norm_text(pattern)
            if _contains_pattern(low, norm):
                issues.append(Issue(issue_type, "P2", "body", pattern))
    return issues


def scan_duplicate_paragraphs(body: str) -> list[Issue]:
    paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", body)
        if len(_tokens(p)) >= 30
    ]
    issues: list[Issue] = []
    for i, left in enumerate(paragraphs):
        left_tokens = set(_tokens(left))
        for j, right in enumerate(paragraphs[i + 1:], start=i + 2):
            right_tokens = set(_tokens(right))
            overlap = len(left_tokens & right_tokens) / max(
                1, min(len(left_tokens), len(right_tokens))
            )
            if overlap >= 0.9:
                issues.append(Issue(
                    "duplicate_paragraph",
                    "P2",
                    f"paragraphs {i + 1},{j}",
                    f"token_overlap={overlap:.2f}",
                ))
    return issues


def scan_citation_artifacts(body: str) -> list[Issue]:
    return [
        Issue("citation_artifact", "P2", f"offset {m.start()}", m.group(0).strip())
        for m in CITATION_ARTIFACT_RE.finditer(body)
    ]


def scan_qei_rows(body: str) -> list[Issue]:
    match = re.search(
        r"^## Quantitative Evidence Index\b.*?\n(.*?)(?=^## |\Z)",
        body,
        flags=re.M | re.S,
    )
    if not match:
        return []
    issues: list[Issue] = []
    for line_no, line in enumerate(match.group(1).splitlines(), start=1):
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:6] == ["Study", "Endpoint", "Arm", "Value", "Type", "Statistic"]:
            continue
        if len(cells) != 6:
            issues.append(Issue(
                "malformed_qei_row", "P2", f"qei row {line_no}",
                f"cell_count={len(cells)}",
            ))
            continue
        if all(c in {"", "-", "—", "–", "none", "n/a", "na"} for c in cells[3:6]):
            issues.append(Issue(
                "malformed_qei_row", "P2", f"qei row {line_no}", "empty numeric cells",
            ))
        if re.search(r"\b(?:19|20)\d{2}[a-z]{2,}\b|_\w{1,5}\b|_+$", cells[0]):
            issues.append(Issue(
                "malformed_qei_row", "P2", f"qei row {line_no}",
                f"malformed study id: {cells[0]}",
            ))
    return issues


def scan_hedge_fragments(body: str) -> list[Issue]:
    issues: list[Issue] = []
    for idx, paragraph in enumerate(re.split(r"\n\s*\n", body), start=1):
        text = re.sub(r"\s+", " ", paragraph.strip())
        if text and len(_tokens(text)) <= 4 and HEDGE_FRAGMENT_RE.match(text):
            issues.append(Issue(
                "standalone_hedge_fragment", "P3", f"paragraph {idx}", text,
            ))
    return issues


def build_report(run_dirs: list[Path]) -> dict:
    runs = []
    for run_dir in run_dirs:
        try:
            runs.append(audit_run(run_dir))
        except OSError as exc:
            runs.append({
                "run_dir": str(run_dir),
                "manuscript": None,
                "passed": False,
                "issue_count": 1,
                "issues": [asdict(Issue(
                    "missing_or_unreadable",
                    "P1",
                    "run_dir",
                    exc.__class__.__name__,
                ))],
            })
    return {
        "schema": SCHEMA,
        "passed": all(run["passed"] for run in runs),
        "run_count": len(runs),
        "issue_count": sum(run["issue_count"] for run in runs),
        "runs": runs,
    }


def write_csv(report: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=("run_dir", "manuscript", "issue_type", "severity",
                        "location", "detail"),
        )
        writer.writeheader()
        for run in report["runs"]:
            for issue in run["issues"]:
                writer.writerow({
                    "run_dir": run["run_dir"],
                    "manuscript": run["manuscript"] or "",
                    **issue,
                })


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Journal Surface Batch Audit",
        "",
        f"- Schema: `{report['schema']}`",
        f"- Passed: `{report['passed']}`",
        f"- Runs: `{report['run_count']}`",
        f"- Issues: `{report['issue_count']}`",
        "",
        "| Run | Passed | Issues |",
        "|---|---:|---:|",
    ]
    for run in report["runs"]:
        lines.append(f"| `{run['run_dir']}` | {run['passed']} | {run['issue_count']} |")
        for issue in run["issues"]:
            lines.append(
                f"| `{issue['issue_type']}` | {issue['severity']} | "
                f"{issue['location']}: {issue['detail']} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _contains_pattern(text: str, pattern: str) -> bool:
    if re.fullmatch(r"[a-z0-9]{2,4}", pattern):
        return bool(re.search(rf"\b{re.escape(pattern)}\b", text))
    return pattern in text


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", help="Run directories to audit")
    parser.add_argument("--json-out", help="Write JSON report to path")
    parser.add_argument("--csv-out", help="Write CSV issues to path")
    parser.add_argument("--md-out", help="Write Markdown summary to path")
    args = parser.parse_args(argv)
    report = build_report([Path(p) for p in args.run_dirs])
    data = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(data, encoding="utf-8")
    else:
        print(data, end="")
    if args.csv_out:
        write_csv(report, Path(args.csv_out))
    if args.md_out:
        write_markdown(report, Path(args.md_out))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
