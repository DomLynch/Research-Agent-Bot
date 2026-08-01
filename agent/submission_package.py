"""Submission package finalizer — deterministic multi-file packager.

Composes the final submission package from sidecars + manuscript already
present in a run_dir. Reuses existing builders in `manuscript_appendix`
for the disclosure / provenance / data-availability blocks (no
duplication). Universal: any topic, any field — the package shape is
fixed by the target journal contract, not the corpus content.

Slice 4 of the 15-step plan (Wave 47 — flagship route, move #6).

Output layout (under `<run_dir>/submission_package/`):
  final_manuscript.md             — copy of full_paper.md
  structured_evidence_tables.md   — copy of existing supplement
  search_provenance.md            — from manuscript_appendix.build_search_provenance_appendix
  AI_use_disclosure.md            — from manuscript_appendix.build_ai_use_disclosure
  data_code_availability.md       — from manuscript_appendix.build_data_code_availability
  ethics_funding_conflict.md      — template; human-fillable stub
  cover_letter.md                 — template; human-fillable stub
  final_status.json               — copy of run_dir/final_status.json
  manifest.json                   — list of all package files + provenance

Gate: refuses to compose unless `final_status.maturity_level >= 5`. This
prevents shipping a submission package built on top of a paper that
failed runtime / audit / surface / pre-submit.

Stdlib-only.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.target_journal_pack import load_and_validate

PACKAGE_DIRNAME = "submission_package"


@dataclass(frozen=True, slots=True)
class PackageManifest:
    """Provenance record of what the finalizer emitted."""

    run_dir: str
    package_dir: str
    files: tuple[str, ...]
    maturity_level: int
    maturity_label: str
    target_journal: str
    author: str
    notes: str = ""


class SubmissionPackageError(RuntimeError):
    """Raised when the run_dir lacks the prerequisites for finalization."""


def _read_final_status(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "final_status.json"
    if not p.is_file():
        raise SubmissionPackageError(
            "final_status.json missing — run Stage 5d first",
        )
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise SubmissionPackageError(
            f"final_status.json unreadable: {e!r}",
        ) from e


def _read_pack(run_dir: Path) -> dict[str, Any]:
    pack, issues = load_and_validate(run_dir)
    if pack is None or issues:
        detail = "; ".join(f"{issue.field}:{issue.code}" for issue in issues)
        raise SubmissionPackageError(
            f"target_journal_pack.json invalid: {detail}",
        )
    return asdict(pack)


def _read_signoff(run_dir: Path) -> dict[str, Any]:
    from agent.human_signoff import load_and_validate
    signoff, issues = load_and_validate(run_dir)
    if signoff is None or issues:
        detail = "; ".join(f"{issue.field}:{issue.code}" for issue in issues)
        raise SubmissionPackageError(f"human_signoff.json invalid: {detail}")
    return asdict(signoff)


# --- builders for the two stub files (templates, not synthesized) ---------


_ETHICS_TEMPLATE = """# Ethics, Funding, and Competing Interests

## Ethics statement
This synthesis is a literature review of previously published research.
No primary human-subject or animal data were collected by the authors of
this manuscript. Authors must replace this paragraph with the journal-
specific ethics statement if primary data are added.

## Funding
_(Author to fill in: funding sources, grant numbers, or 'No funding was
received for this work.')_

## Competing interests declaration
_(Author to fill in: declare competing financial / non-financial
interests, or 'The authors declare no competing interests.')_

## Author contributions
_(Author to fill in: contributor roles, e.g. CRediT taxonomy.)_
"""


_COVER_LETTER_TEMPLATE = """# Cover Letter

To the Editors of {journal}:

We submit our manuscript, titled _<TITLE>_, for consideration as a
{article_type} in {journal}.

## Significance
_(Author: 2-3 sentences on why the synthesis matters and why it fits
{journal}'s scope.)_

## Suitability for {journal}
_(Author: explain alignment with the journal's article-type criteria,
{abstract_max_words}-word abstract limit, and {reference_style}
reference style.)_

## Suggested reviewers
_(Optional — author may suggest reviewers per journal policy.)_

## Conflicts and disclosures
The manuscript includes a structured AI-use disclosure
(`AI_use_disclosure.md`) and a competing-interests statement
(`ethics_funding_conflict.md`).

Sincerely,
{author}
"""


def _build_ethics_stub() -> str:
    return _ETHICS_TEMPLATE


def _build_cover_letter(pack: dict[str, Any], author: str) -> str:
    return _COVER_LETTER_TEMPLATE.format(
        journal=pack.get("journal") or "[journal]",
        article_type=pack.get("article_type") or "[article type]",
        abstract_max_words=pack.get("abstract_max_words") or "[abstract cap]",
        reference_style=pack.get("reference_style") or "[reference style]",
        author=author or "[Author]",
    )


# --- orchestrator ---------------------------------------------------------


def compose(
    run_dir: Path, *, allow_below_l4: bool = False,
) -> PackageManifest:
    """Build the submission package under `<run_dir>/submission_package/`.

    Refuses to compose unless `final_status.maturity_level >= 5`, since
    only L5 is journal-submission ready. The legacy-named
    `allow_below_l4=True` override bypasses this gate for ops/testing.
    """
    fs = _read_final_status(run_dir)
    level = int(fs.get("maturity_level") or 0)
    if not allow_below_l4 and (
        level < 5 or fs.get("journal_submission_ready") is not True
    ):
        raise SubmissionPackageError(
            f"maturity_level={level}; journal_submission_ready must be true. "
            f"Not eligible for submission "
            f"package. Resolve blocking_reasons first or pass "
            f"allow_below_l4=True for testing.",
        )

    manuscript = run_dir / "full_paper.md"
    if not manuscript.is_file() or not manuscript.read_text().strip():
        raise SubmissionPackageError(
            "full_paper.md missing or empty — manuscript is required",
        )

    pack = _read_pack(run_dir)
    signoff = _read_signoff(run_dir)

    # Manifest is needed by the existing manuscript_appendix builders.
    manifest_data = json.loads((run_dir / "manifest.json").read_text())
    audit_data: dict[str, Any] | None = None
    if (run_dir / "full_paper.audit.json").is_file():
        audit_data = json.loads((run_dir / "full_paper.audit.json").read_text())

    topic = str(manifest_data.get("topic") or "unknown")
    verdict = str(fs.get("maturity_label") or "")
    from agent.manuscript_appendix import (
        build_ai_use_disclosure,
        build_data_code_availability,
        build_search_provenance_appendix,
    )
    search_provenance = build_search_provenance_appendix(
        manifest_data, topic=topic,
    )
    ai_use_disclosure = build_ai_use_disclosure(
        manifest_data, audit_data, None, verdict=verdict,
    )
    data_code_availability = build_data_code_availability(
        run_id=run_dir.name, git_sha="unknown",
        bundle_path=None, topic=topic, verdict=verdict,
    )

    pkg = run_dir / PACKAGE_DIRNAME
    pkg.mkdir(exist_ok=True)
    files: list[str] = []

    def _emit(name: str, content: str) -> None:
        (pkg / name).write_text(content)
        files.append(name)

    def _copy(src_name: str, dst_name: str) -> None:
        src = run_dir / src_name
        if src.is_file():
            shutil.copy(src, pkg / dst_name)
            files.append(dst_name)

    # Manuscript is mandatory; supplement is optional.
    _copy("full_paper.md", "final_manuscript.md")
    _copy("structured_evidence_tables.md", "structured_evidence_tables.md")

    # Disclosure blocks: reuse existing builders (no duplication)
    _emit("search_provenance.md", search_provenance)
    _emit("AI_use_disclosure.md", ai_use_disclosure)
    _emit("data_code_availability.md", data_code_availability)

    # Human-fillable stubs (universal — no domain assumptions)
    _emit("ethics_funding_conflict.md", _build_ethics_stub())
    _emit(
        "cover_letter.md",
        _build_cover_letter(pack, str(signoff.get("author") or "")),
    )

    # Copy final_status + signoff + pack as provenance
    _copy("final_status.json", "final_status.json")
    _copy("target_journal_pack.json", "target_journal_pack.json")
    _copy("human_signoff.json", "human_signoff.json")

    manifest = PackageManifest(
        run_dir=str(run_dir),
        package_dir=str(pkg),
        files=tuple(sorted(set(files))),
        maturity_level=level,
        maturity_label=str(fs.get("maturity_label") or ""),
        target_journal=str(pack.get("journal") or ""),
        author=str(signoff.get("author") or ""),
    )
    (pkg / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2) + "\n")
    return manifest


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="submission_package")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--allow-below-l4", action="store_true",
        help="bypass the L5 gate; legacy option name (ops/testing only)",
    )
    args = parser.parse_args(argv)
    try:
        m = compose(args.run_dir, allow_below_l4=args.allow_below_l4)
    except SubmissionPackageError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "manifest": asdict(m)}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_main())
