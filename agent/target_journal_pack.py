"""Target-journal submission pack — schema + writer + validator.

Defines the contract a `target_journal_pack.json` sidecar must satisfy
for `final_status.target_journal_pass = True`. Universal: applies to any
journal in any field — the schema describes journal-imposed requirements
(word limits, reference style, AI-disclosure rule), not domain content.

Slice 2 of the 15-step plan (Wave 47 — flagship route, move #2).

Required fields:
  journal                 — non-empty journal name (e.g. "Aging Cell")
  article_type            — submission category ("Original Research",
                            "Review", "Perspective", "Methods")
  abstract_max_words      — positive int (journal-imposed cap)
  main_word_limit         — positive int (journal-imposed cap)
  reference_style         — citation style identifier ("Vancouver",
                            "APA", "Harvard", "AMA", etc.)

Optional fields with defaults:
  requires_prisma         — bool (default False); if True the submission
                            package MUST include a PRISMA flow diagram
  requires_ai_disclosure  — bool (default False); ICMJE-style AI use note
  allows_supplement       — bool (default True); journal accepts a
                            supplementary materials file

Stdlib-only, no LLM. Fail-closed: invalid JSON → empty pack → invalid.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PACK_FILENAME = "target_journal_pack.json"


@dataclass(frozen=True, slots=True)
class PackIssue:
    """One validation failure on a TargetJournalPack instance."""

    field: str
    code: str       # snake_case identifier
    detail: str


@dataclass(frozen=True, slots=True)
class TargetJournalPack:
    """Minimum journal-targeting contract for L5 promotion.

    All fields are universal — no domain assumptions about the paper's
    topic. The pack describes the *journal* and its constraints, not the
    *paper*.
    """

    journal: str
    article_type: str
    abstract_max_words: int
    main_word_limit: int
    reference_style: str
    requires_prisma: bool = False
    requires_ai_disclosure: bool = False
    allows_supplement: bool = True
    notes: str = ""              # optional free-text journal-specific note

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TargetJournalPack":
        """Build from a parsed-JSON dict. Missing fields use defaults; the
        caller should still run `validate()` to confirm completeness."""
        return cls(
            journal=str(raw.get("journal") or ""),
            article_type=str(raw.get("article_type") or ""),
            abstract_max_words=int(raw.get("abstract_max_words") or 0),
            main_word_limit=int(raw.get("main_word_limit") or 0),
            reference_style=str(raw.get("reference_style") or ""),
            requires_prisma=bool(raw.get("requires_prisma", False)),
            requires_ai_disclosure=bool(
                raw.get("requires_ai_disclosure", False),
            ),
            allows_supplement=bool(raw.get("allows_supplement", True)),
            notes=str(raw.get("notes") or ""),
        )


# ---- validator (universal, no domain logic) -------------------------------


def validate(pack: TargetJournalPack) -> tuple[PackIssue, ...]:
    """Structural validation of a TargetJournalPack. Returns issues; an
    empty tuple means the pack is valid for `final_status` promotion.
    Universal — no journal-name allowlist, no field-content assumptions.
    """
    issues: list[PackIssue] = []
    if not pack.journal.strip():
        issues.append(PackIssue(
            field="journal", code="empty_journal",
            detail="'journal' must be a non-empty string",
        ))
    if not pack.article_type.strip():
        issues.append(PackIssue(
            field="article_type", code="empty_article_type",
            detail="'article_type' must be a non-empty string",
        ))
    if not pack.reference_style.strip():
        issues.append(PackIssue(
            field="reference_style", code="empty_reference_style",
            detail="'reference_style' must be a non-empty string",
        ))
    if pack.abstract_max_words <= 0:
        issues.append(PackIssue(
            field="abstract_max_words", code="nonpositive_abstract_cap",
            detail=f"'abstract_max_words' must be > 0, got "
                   f"{pack.abstract_max_words!r}",
        ))
    if pack.main_word_limit <= 0:
        issues.append(PackIssue(
            field="main_word_limit", code="nonpositive_main_cap",
            detail=f"'main_word_limit' must be > 0, got "
                   f"{pack.main_word_limit!r}",
        ))
    # Sanity: abstract cap can't exceed main cap.
    if (
        pack.abstract_max_words > 0
        and pack.main_word_limit > 0
        and pack.abstract_max_words > pack.main_word_limit
    ):
        issues.append(PackIssue(
            field="abstract_max_words", code="abstract_exceeds_main",
            detail=f"abstract_max_words={pack.abstract_max_words} cannot "
                   f"exceed main_word_limit={pack.main_word_limit}",
        ))
    return tuple(issues)


# ---- IO helpers -----------------------------------------------------------


def load(run_dir: Path) -> TargetJournalPack | None:
    """Return the pack stored at `<run_dir>/target_journal_pack.json`,
    or None when the file is absent / unreadable / not a JSON object."""
    p = run_dir / PACK_FILENAME
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return TargetJournalPack.from_dict(raw)
    except (TypeError, ValueError):
        return None


def write(run_dir: Path, pack: TargetJournalPack) -> Path:
    """Write the pack to `<run_dir>/target_journal_pack.json` as JSON."""
    out = run_dir / PACK_FILENAME
    out.write_text(json.dumps(asdict(pack), indent=2) + "\n")
    return out


def load_and_validate(
    run_dir: Path,
) -> tuple[TargetJournalPack | None, tuple[PackIssue, ...]]:
    """Convenience: load + validate in one call. Returns (pack | None,
    issues). pack is None iff the file was absent/unreadable."""
    pack = load(run_dir)
    if pack is None:
        return None, (PackIssue(
            field="file", code="pack_missing",
            detail=f"{PACK_FILENAME} not present in run_dir",
        ),)
    return pack, validate(pack)


# ---- CLI ------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="target_journal_pack")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="emit target_journal_pack.json")
    p_write.add_argument("run_dir", type=Path)
    p_write.add_argument("--journal", required=True)
    p_write.add_argument("--article-type", required=True)
    p_write.add_argument("--abstract-max-words", type=int, required=True)
    p_write.add_argument("--main-word-limit", type=int, required=True)
    p_write.add_argument("--reference-style", required=True)
    p_write.add_argument("--requires-prisma", action="store_true")
    p_write.add_argument("--requires-ai-disclosure", action="store_true")
    p_write.add_argument("--no-supplement", action="store_true")
    p_write.add_argument("--notes", default="")

    p_check = sub.add_parser("check", help="validate an existing pack")
    p_check.add_argument("run_dir", type=Path)

    args = parser.parse_args(argv)

    if args.cmd == "write":
        pack = TargetJournalPack(
            journal=args.journal,
            article_type=args.article_type,
            abstract_max_words=args.abstract_max_words,
            main_word_limit=args.main_word_limit,
            reference_style=args.reference_style,
            requires_prisma=args.requires_prisma,
            requires_ai_disclosure=args.requires_ai_disclosure,
            allows_supplement=not args.no_supplement,
            notes=args.notes,
        )
        issues = validate(pack)
        if issues:
            print(json.dumps({
                "ok": False,
                "issues": [asdict(i) for i in issues],
            }, indent=2))
            return 2
        out = write(args.run_dir, pack)
        print(json.dumps({"ok": True, "wrote": str(out)}, indent=2))
        return 0

    # check
    loaded, issues = load_and_validate(args.run_dir)
    print(json.dumps({
        "ok": loaded is not None and not issues,
        "pack": asdict(loaded) if loaded else None,
        "issues": [asdict(i) for i in issues],
    }, indent=2))
    return 0 if loaded is not None and not issues else 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_main())
