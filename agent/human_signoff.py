"""Human signoff record — schema + writer + validator.

Defines the contract a `human_signoff.json` sidecar must satisfy for
`final_status.human_signoff_pass = True`. Universal: applies to any
research artifact in any field — the schema records human-author
accountability, not domain content.

Slice 3 of the 15-step plan (Wave 47 — flagship route, move #7).

Required fields:
  author                      — non-empty string (human author name)
  reviewed                    — bool, True after the author reads the
                                final manuscript
  evidence_claims_reviewed    — bool, True after the author verifies the
                                strongest evidence-bearing claims
                                (renamed from the reviewer's
                                "clinical_claims_reviewed" so the field
                                works across biomedical / climate /
                                materials / economics — see the
                                universal-no-hardcoding rule)
  conflicts_declared          — bool, True after the author declares any
                                competing interests (or explicitly states
                                'none')
  ready_to_submit             — bool, True if and only if all of the
                                above are True and the author affirms
                                submission readiness

Optional:
  timestamp                   — ISO-8601 string; auto-stamped on write
                                when not supplied
  notes                       — optional free-text accountability note

Stdlib-only, no LLM.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

SIGNOFF_FILENAME = "human_signoff.json"
MANUSCRIPT_FILENAME = "full_paper.md"
_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SignoffIssue:
    """One validation failure on a HumanSignoff instance."""

    field: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class HumanSignoff:
    author: str
    reviewed: bool
    evidence_claims_reviewed: bool
    conflicts_declared: bool
    ready_to_submit: bool
    timestamp: str = ""
    notes: str = ""
    signature: str = ""
    manuscript_sha256: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HumanSignoff":
        """Build from a parsed-JSON dict. Accepts the legacy field name
        `clinical_claims_reviewed` as an alias for
        `evidence_claims_reviewed` (the universal name) so existing
        biomedical-domain signoffs migrate cleanly."""
        evidence_reviewed = raw.get(
            "evidence_claims_reviewed", raw.get("clinical_claims_reviewed", False),
        ) is True
        return cls(
            author=str(raw.get("author") or ""),
            reviewed=raw.get("reviewed") is True,
            evidence_claims_reviewed=evidence_reviewed,
            conflicts_declared=raw.get("conflicts_declared") is True,
            ready_to_submit=raw.get("ready_to_submit") is True,
            timestamp=str(raw.get("timestamp") or ""),
            notes=str(raw.get("notes") or ""),
            signature=str(raw.get("signature") or ""),
            manuscript_sha256=str(raw.get("manuscript_sha256") or ""),
        )


def _manuscript_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def validate(
    s: HumanSignoff, manuscript_path: Path | None = None,
) -> tuple[SignoffIssue, ...]:
    """Structural validation. Empty tuple → ready for L5 promotion."""
    issues: list[SignoffIssue] = []
    if not s.author.strip():
        issues.append(SignoffIssue(
            field="author", code="empty_author",
            detail="'author' must be a non-empty string",
        ))
    if not s.signature.strip():
        issues.append(SignoffIssue("signature", "unsigned", "human signoff requires an explicit signature"))
    if not s.timestamp.strip():
        issues.append(SignoffIssue("timestamp", "missing_timestamp", "signed signoff requires a timestamp"))
    if not _SHA256_RE.fullmatch(s.manuscript_sha256):
        issues.append(SignoffIssue("manuscript_sha256", "invalid_manuscript_hash", "manuscript_sha256 must be 64 hexadecimal characters"))
    if manuscript_path is not None:
        digest = _manuscript_sha256(manuscript_path)
        if digest is None:
            issues.append(SignoffIssue("manuscript_sha256", "manuscript_missing", f"{manuscript_path.name} missing or unreadable"))
        elif digest != s.manuscript_sha256.lower():
            issues.append(SignoffIssue("manuscript_sha256", "manuscript_hash_mismatch", "signoff is not bound to the current manuscript"))
    # The four review bits must all be True before ready_to_submit
    # can legitimately be True — author cannot "ready" while denying
    # they reviewed.
    if s.ready_to_submit and not (
        s.reviewed
        and s.evidence_claims_reviewed
        and s.conflicts_declared
    ):
        issues.append(SignoffIssue(
            field="ready_to_submit", code="ready_without_review",
            detail="ready_to_submit=True requires reviewed AND "
                   "evidence_claims_reviewed AND conflicts_declared",
        ))
    if not s.ready_to_submit:
        issues.append(SignoffIssue(
            field="ready_to_submit", code="not_ready",
            detail="'ready_to_submit' must be True for L5 promotion",
        ))
    return tuple(issues)


def load(run_dir: Path) -> HumanSignoff | None:
    """Return the signoff at `<run_dir>/human_signoff.json`, or None
    when absent / unreadable / not a JSON object."""
    p = run_dir / SIGNOFF_FILENAME
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return HumanSignoff.from_dict(raw)


def write(run_dir: Path, signoff: HumanSignoff) -> Path:
    """Write the signoff to `<run_dir>/human_signoff.json`. If the
    record has no timestamp, stamp UTC ISO-8601 at write time."""
    manuscript = run_dir / MANUSCRIPT_FILENAME
    digest = _manuscript_sha256(manuscript)
    if digest is None:
        raise ValueError(f"{MANUSCRIPT_FILENAME} missing or unreadable")
    if signoff.manuscript_sha256 and signoff.manuscript_sha256.lower() != digest:
        raise ValueError("provided manuscript_sha256 does not match current manuscript")
    signoff = replace(
        signoff,
        timestamp=signoff.timestamp or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        manuscript_sha256=digest,
    )
    issues = validate(signoff, manuscript)
    if issues:
        raise ValueError("invalid human signoff: " + ", ".join(issue.code for issue in issues))
    out = run_dir / SIGNOFF_FILENAME
    out.write_text(json.dumps(asdict(signoff), indent=2) + "\n")
    return out


def load_and_validate(
    run_dir: Path,
) -> tuple[HumanSignoff | None, tuple[SignoffIssue, ...]]:
    """Load + validate. Returns (signoff, issues). signoff is None iff
    the file was absent/unreadable."""
    s = load(run_dir)
    if s is None:
        return None, (SignoffIssue(
            field="file", code="signoff_missing",
            detail=f"{SIGNOFF_FILENAME} not present in run_dir",
        ),)
    return s, validate(s, run_dir / MANUSCRIPT_FILENAME)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="human_signoff")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pw = sub.add_parser("write", help="emit human_signoff.json")
    pw.add_argument("run_dir", type=Path)
    pw.add_argument("--author", required=True)
    pw.add_argument("--reviewed", action="store_true")
    pw.add_argument(
        "--evidence-claims-reviewed", action="store_true",
        help="author has verified evidence-bearing claims (universal; "
             "replaces biomedical-only 'clinical_claims_reviewed')",
    )
    pw.add_argument("--conflicts-declared", action="store_true")
    pw.add_argument("--ready-to-submit", action="store_true")
    pw.add_argument("--signature", required=True)
    pw.add_argument("--notes", default="")

    pc = sub.add_parser("check", help="validate an existing signoff")
    pc.add_argument("run_dir", type=Path)

    args = parser.parse_args(argv)

    if args.cmd == "write":
        signoff = HumanSignoff(
            author=args.author,
            reviewed=args.reviewed,
            evidence_claims_reviewed=args.evidence_claims_reviewed,
            conflicts_declared=args.conflicts_declared,
            ready_to_submit=args.ready_to_submit,
            notes=args.notes,
            signature=args.signature,
        )
        try:
            out = write(args.run_dir, signoff)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 2
        print(json.dumps({"ok": True, "wrote": str(out)}, indent=2))
        return 0

    loaded, issues = load_and_validate(args.run_dir)
    print(json.dumps({
        "ok": loaded is not None and not issues,
        "signoff": asdict(loaded) if loaded else None,
        "issues": [asdict(i) for i in issues],
    }, indent=2))
    return 0 if loaded is not None and not issues else 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_main())
