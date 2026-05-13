"""Final status convergence — single source of truth for submission readiness.

Reads every sidecar produced earlier in the pipeline and emits one
`final_status.json` with:

  - A strict 6-boolean dimension table (runtime / audit / journal_surface /
    pre_submit / target_journal / human_signoff).
  - A frozen L1–L5 maturity label. No "AAA" string is emitted here; the
    label is the only public level identifier the contract recognises.
  - Snake_case reason codes per blocking dimension, so every failing run
    has a concrete diff vs the next iteration.

Universal: every topic/topic_pack writes the same sidecars; this module
makes them agree without re-running any LLM or gate. Stdlib-only.

Frozen label mapping (Wave 47 / 2026-05-13):
    L1 — DRAFT GENERATED             paper rendered but pipeline failed at runtime
    L2 — EVIDENCE BUNDLE VALID       runtime OK but audit failed
    L3 — TRUST-SPINE PASS            audit + surface pass; pre-submit may still fail
    L4 — ANALYTICALLY CERTIFIED      L3 + pre-submit pass; missing target journal / human signoff
    L5 — SUBMISSION PACKAGE READY    all six dimensions pass
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

LabelLevel = Literal[1, 2, 3, 4, 5]
LABELS: dict[int, str] = {
    1: "L1 — DRAFT GENERATED",
    2: "L2 — EVIDENCE BUNDLE VALID",
    3: "L3 — TRUST-SPINE PASS",
    4: "L4 — ANALYTICALLY CERTIFIED",
    5: "L5 — SUBMISSION PACKAGE READY",
}


@dataclass(frozen=True, slots=True)
class BlockingReason:
    stage: str        # runtime / audit / journal_surface / pre_submit / target_journal / human_signoff
    code: str         # snake_case identifier (universal across topics)
    detail: str       # short, evidence-grounded explanation


@dataclass(frozen=True, slots=True)
class FinalStatus:
    runtime_pass: bool
    audit_pass: bool
    journal_surface_pass: bool
    pre_submit_pass: bool
    target_journal_pass: bool
    human_signoff_pass: bool
    submission_ready: bool
    maturity_level: int
    maturity_label: str
    blocking_reasons: tuple[BlockingReason, ...] = ()
    sidecars_read: tuple[str, ...] = ()


# --- per-dimension readers --------------------------------------------------


def _load(p: Path) -> dict[str, Any] | None:
    """Load a sidecar JSON file. Returns dict on success, None on any
    read/parse error or non-dict shape (we only consume dict sidecars).
    """
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_runtime(run_dir: Path) -> tuple[bool, str]:
    d = _load(run_dir / "benchmark_runtime.json")
    if d is None:
        return (False, "benchmark_runtime.json missing")
    rc = d.get("return_code") if isinstance(d, dict) else None
    if rc == 0:
        return (True, "")
    return (False, f"return_code={rc!r}")


def _read_audit(run_dir: Path) -> tuple[bool, str]:
    d = _load(run_dir / "full_paper.audit.json")
    if not isinstance(d, dict):
        return (False, "full_paper.audit.json missing or unreadable")
    n_pass = int(d.get("n_pass") or 0)
    n_total = int(d.get("n_total") or 0)
    p1 = bool(d.get("p1_pass"))
    if p1 and n_total > 0 and n_pass == n_total:
        return (True, "")
    return (False, f"p1_pass={p1} pass={n_pass}/{n_total}")


def _read_journal_surface(run_dir: Path) -> tuple[bool, str]:
    d = _load(run_dir / "full_paper.journal_surface.json")
    if not isinstance(d, dict):
        return (False, "journal_surface missing")
    if d.get("passed"):
        return (True, "")
    issues = d.get("issues") or []
    n = len(issues) if isinstance(issues, list) else 0
    return (False, f"{n} surface issues")


def _read_pre_submit(run_dir: Path) -> tuple[bool, str]:
    d = _load(run_dir / "pre_submit_gate.json")
    if not isinstance(d, dict):
        return (False, "pre_submit_gate missing")
    raw = d.get("result")
    result: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if result.get("passed"):
        return (True, "")
    fails = result.get("failures") or []
    head = ",".join(str(f) for f in fails[:3]) if isinstance(fails, list) else ""
    return (False, head or "pre_submit not passed")


def _read_target_journal(run_dir: Path) -> tuple[bool, str]:
    d = _load(run_dir / "target_journal_pack.json")
    if not isinstance(d, dict):
        return (False, "no target_journal_pack.json")
    if d.get("journal"):
        return (True, "")
    return (False, "target_journal_pack missing 'journal' field")


def _read_human_signoff(run_dir: Path) -> tuple[bool, str]:
    d = _load(run_dir / "human_signoff.json")
    if not isinstance(d, dict):
        return (False, "no human_signoff.json")
    if bool(d.get("ready_to_submit")):
        return (True, "")
    return (False, "ready_to_submit=false")


# --- reason-code mapper (universal, no per-topic logic) ---------------------


_REASON_CODES: tuple[tuple[str, str, str], ...] = (
    # (stage, substring-in-reason-lower, snake_case code)
    ("runtime", "missing", "runtime_missing"),
    ("runtime", "return_code", "runtime_nonzero_exit"),
    ("audit", "missing", "audit_missing"),
    ("audit", "p1_pass=false", "audit_p1_failed"),
    ("audit", "pass=", "audit_check_failed"),
    ("journal_surface", "missing", "journal_surface_missing"),
    ("journal_surface", "issues", "journal_surface_issues"),
    ("pre_submit", "missing", "pre_submit_missing"),
    ("pre_submit", "audit_gates_failed", "audit_gates_failed"),
    ("pre_submit", "not passed", "pre_submit_failed"),
    ("target_journal", "no target_journal", "no_target_journal_pack"),
    ("target_journal", "missing", "invalid_target_journal_pack"),
    ("human_signoff", "no human_signoff", "no_human_signoff"),
    ("human_signoff", "ready_to_submit=false", "human_not_ready"),
)


def _reason_to_code(stage: str, reason: str) -> str:
    rlow = (reason or "").lower()
    for s, needle, code in _REASON_CODES:
        if s == stage and needle in rlow:
            return code
    return f"{stage}_blocked"


# --- maturity ladder --------------------------------------------------------


def _compute_level(dims: dict[str, bool]) -> int:
    """Strict ladder — fail at any rung stops promotion.

    L1: render produced (we got far enough to write sidecars).
    L2: runtime pass.
    L3: runtime + audit + journal_surface pass.
    L4: L3 + pre_submit pass.
    L5: L4 + target_journal + human_signoff.
    """
    if not dims["runtime_pass"]:
        return 1
    if not dims["audit_pass"]:
        return 2
    if not dims["journal_surface_pass"]:
        return 3
    if not dims["pre_submit_pass"]:
        return 3
    if not (dims["target_journal_pass"] and dims["human_signoff_pass"]):
        return 4
    return 5


# --- orchestrator -----------------------------------------------------------


def compute(run_dir: Path) -> FinalStatus:
    """Read every sidecar in `run_dir` and return one source-of-truth status."""
    readers: tuple[tuple[str, str, Callable[[Path], tuple[bool, str]]], ...] = (
        ("runtime", "benchmark_runtime.json", _read_runtime),
        ("audit", "full_paper.audit.json", _read_audit),
        ("journal_surface", "full_paper.journal_surface.json", _read_journal_surface),
        ("pre_submit", "pre_submit_gate.json", _read_pre_submit),
        ("target_journal", "target_journal_pack.json", _read_target_journal),
        ("human_signoff", "human_signoff.json", _read_human_signoff),
    )
    sidecars: list[str] = []
    results: list[tuple[str, bool, str]] = []
    for stage, fname, fn in readers:
        ok, reason = fn(run_dir)
        if (run_dir / fname).is_file():
            sidecars.append(fname)
        results.append((stage, ok, reason))
    dims: dict[str, bool] = {f"{s}_pass": ok for s, ok, _ in results}
    blockers = tuple(
        BlockingReason(
            stage=s, code=_reason_to_code(s, r), detail=r or f"{s} not pass",
        )
        for s, ok, r in results if not ok
    )
    level = _compute_level(dims)
    return FinalStatus(
        runtime_pass=dims["runtime_pass"],
        audit_pass=dims["audit_pass"],
        journal_surface_pass=dims["journal_surface_pass"],
        pre_submit_pass=dims["pre_submit_pass"],
        target_journal_pass=dims["target_journal_pass"],
        human_signoff_pass=dims["human_signoff_pass"],
        submission_ready=all(dims.values()),
        maturity_level=level,
        maturity_label=LABELS[level],
        blocking_reasons=blockers,
        sidecars_read=tuple(sidecars),
    )


def write_sidecar(run_dir: Path, status: FinalStatus) -> Path:
    out = run_dir / "final_status.json"
    payload = {
        "submission_ready": status.submission_ready,
        "maturity_level": status.maturity_level,
        "maturity_label": status.maturity_label,
        "dimensions": {
            "runtime_pass": status.runtime_pass,
            "audit_pass": status.audit_pass,
            "journal_surface_pass": status.journal_surface_pass,
            "pre_submit_pass": status.pre_submit_pass,
            "target_journal_pass": status.target_journal_pass,
            "human_signoff_pass": status.human_signoff_pass,
        },
        "blocking_reasons": [asdict(b) for b in status.blocking_reasons],
        "sidecars_read": list(status.sidecars_read),
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


def compute_and_write(run_dir: Path) -> FinalStatus:
    s = compute(run_dir)
    write_sidecar(run_dir, s)
    return s


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="final_status")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    s = compute_and_write(args.run_dir) if args.write else compute(args.run_dir)
    print(json.dumps({
        "maturity_level": s.maturity_level,
        "maturity_label": s.maturity_label,
        "submission_ready": s.submission_ready,
        "dimensions": {
            "runtime_pass": s.runtime_pass,
            "audit_pass": s.audit_pass,
            "journal_surface_pass": s.journal_surface_pass,
            "pre_submit_pass": s.pre_submit_pass,
            "target_journal_pass": s.target_journal_pass,
            "human_signoff_pass": s.human_signoff_pass,
        },
        "blocking_reasons": [asdict(b) for b in s.blocking_reasons],
    }, indent=2))
    return 0 if s.submission_ready else 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_main())
