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
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.target_journal_pack import PRISMA_FLOW_FILES, load_and_validate, package_requirement_issues

PACKAGE_DIRNAME = "submission_package"
_PACKAGE_SOURCE_FILES = (
    "full_paper.md", "structured_evidence_tables.md", "manifest.json",
    "citation_registry.json", "artifact_consistency.json", "full_paper.audit.json",
    "full_paper.review_patches.json", "debug/full_paper.review_patch_log.json",
    "benchmark_runtime.json", "full_paper.journal_surface.json", "pre_submit_gate.json",
    "final_status.json", "target_journal_pack.json", "human_signoff.json", *PRISMA_FLOW_FILES,
    "revision_evidence_snapshot/citation_registry.json",
)
_PACKAGE_SOURCE_GLOBS = ("revision_evidence_snapshot/parsed/*.paper_sections.json",)


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
    paper_sha256: str
    notes: str = ""


class SubmissionPackageError(RuntimeError):
    """Raised when the run_dir lacks the prerequisites for finalization."""


def _source_snapshot(run_dir: Path) -> dict[str, bytes]:
    try:
        paths = [run_dir / name for name in _PACKAGE_SOURCE_FILES]
        for pattern in _PACKAGE_SOURCE_GLOBS:
            paths.extend(run_dir.glob(pattern))
        return {path.relative_to(run_dir).as_posix(): path.read_bytes()
                for path in paths if path.is_file()}
    except OSError as exc:
        raise SubmissionPackageError(f"submission source snapshot unreadable: {exc!r}") from exc


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


def _validate_source_snapshot(
    source_snapshot: dict[str, bytes], *, allow_below_l4: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="v3-package-source-") as tmp:
        snapshot_dir = Path(tmp)
        for name, content in source_snapshot.items():
            path = snapshot_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        if not allow_below_l4:
            from agent.artifact_consistency import consistency_receipt_matches
            consistency = json.loads(source_snapshot.get("artifact_consistency.json", b"{}"))
            if not consistency_receipt_matches(snapshot_dir, consistency):
                raise SubmissionPackageError(
                    "artifact_consistency is missing or stale; refresh final status before composing",
                )
        pack = _read_pack(snapshot_dir)
        from agent.target_journal_pack import TargetJournalPack
        if requirements := package_requirement_issues(
            snapshot_dir, TargetJournalPack.from_dict(pack),
        ):
            raise SubmissionPackageError(
                "target journal requirements unmet: " + ",".join(requirements),
            )
        _read_signoff(snapshot_dir)
        if not allow_below_l4:
            from agent.final_status import compute
            live = compute(snapshot_dir)
            if not live.journal_submission_ready or live.maturity_level < 5:
                raise SubmissionPackageError(
                    "stored final status is stale; live readiness is not L5",
                )


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
    pkg = run_dir / PACKAGE_DIRNAME
    if pkg.exists():
        shutil.rmtree(pkg)
    source_snapshot = _source_snapshot(run_dir)
    if "final_status.json" not in source_snapshot:
        raise SubmissionPackageError("final_status.json missing — run Stage 5d first")
    try:
        fs = json.loads(source_snapshot["final_status.json"])
    except ValueError as exc:
        raise SubmissionPackageError(f"final_status.json unreadable: {exc!r}") from exc
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
    manuscript_text = source_snapshot.get("full_paper.md", b"").decode()
    if not manuscript_text.strip():
        raise SubmissionPackageError("full_paper.md missing or empty — manuscript is required")
    _validate_source_snapshot(source_snapshot, allow_below_l4=allow_below_l4)
    pack = json.loads(source_snapshot.get("target_journal_pack.json", b"{}"))
    from agent.target_journal_pack import TargetJournalPack
    pack_contract = TargetJournalPack.from_dict(pack)
    signoff = json.loads(source_snapshot.get("human_signoff.json", b"{}"))

    # Manifest is needed by the existing manuscript_appendix builders.
    manifest_data = json.loads(source_snapshot["manifest.json"])
    audit_data: dict[str, Any] | None = None
    if source_snapshot.get("full_paper.audit.json"):
        audit_data = json.loads(source_snapshot["full_paper.audit.json"])

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
        run_id=run_dir.name,
        git_sha=str(manifest_data.get("git_sha") or manifest_data.get("commit_sha") or ""),
        bundle_path=(str(manifest_data["bundle_path"]) if manifest_data.get("bundle_path") else None),
        topic=topic, verdict=verdict,
    )

    staging = Path(tempfile.mkdtemp(prefix=f".{PACKAGE_DIRNAME}-", dir=run_dir))
    try:
        files: list[str] = []

        def _emit(name: str, content: str) -> None:
            (staging / name).write_text(content)
            files.append(name)

        def _copy(src_name: str, dst_name: str) -> None:
            content = source_snapshot.get(src_name)
            if content is not None:
                (staging / dst_name).write_bytes(content)
                files.append(dst_name)

        _copy("full_paper.md", "final_manuscript.md")
        if pack_contract.allows_supplement:
            _copy("structured_evidence_tables.md", "structured_evidence_tables.md")
        if pack_contract.requires_prisma:
            prisma_name = next(
                name for name in PRISMA_FLOW_FILES
                if source_snapshot.get(name, b"").strip()
            )
            _copy(prisma_name, prisma_name)

        from agent.artifact_consistency import paper_content_hash
        paper_sha256 = paper_content_hash(manuscript_text)
        if paper_content_hash((staging / "final_manuscript.md").read_text()) != paper_sha256:
            raise SubmissionPackageError("final_manuscript.md does not match full_paper.md")

        _emit("search_provenance.md", search_provenance)
        _emit("AI_use_disclosure.md", ai_use_disclosure)
        _emit("data_code_availability.md", data_code_availability)
        _emit("ethics_funding_conflict.md", _build_ethics_stub())
        _emit("cover_letter.md", _build_cover_letter(pack, str(signoff.get("author") or "")))
        _copy("final_status.json", "final_status.json")
        _copy("target_journal_pack.json", "target_journal_pack.json")
        _copy("human_signoff.json", "human_signoff.json")
        _copy("full_paper.review_patches.json", "review_patches.json")
        _copy("debug/full_paper.review_patch_log.json", "review_patch_log.json")

        manifest = PackageManifest(
            run_dir=str(run_dir), package_dir=str(pkg), files=tuple(sorted(set(files))),
            maturity_level=level, maturity_label=str(fs.get("maturity_label") or ""),
            target_journal=str(pack.get("journal") or ""),
            author=str(signoff.get("author") or ""), paper_sha256=paper_sha256,
        )
        (staging / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2) + "\n")
        if _source_snapshot(run_dir) != source_snapshot:
            raise SubmissionPackageError("submission sources changed during package composition")
        staging.replace(pkg)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


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
