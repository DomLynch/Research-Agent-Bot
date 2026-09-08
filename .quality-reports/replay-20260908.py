"""Offline renderer/payload regression replay; never submits or asserts acceptance."""
import hashlib
import importlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(repo), str(repo / "scripts")]
methods = importlib.import_module("agent.methods_pack")
finalizer = importlib.import_module("scripts.journal_finalizer")
submission = importlib.import_module("publishing.submission")

source = Path("/private/tmp/v3-boundary-replay-20260907/resveratrol-reviewed-v12")
run = Path(tempfile.mkdtemp(prefix="v3-repair-20260908-")) / "resveratrol"
shutil.copytree(source, run)
original_hash = hashlib.sha256((source / "full_paper.md").read_bytes()).hexdigest()
manifest = json.loads((run / "manifest.json").read_text())
old_pack = json.loads((run / "methods_pack.json").read_text())
funnel = manifest["receipt_funnel"]
pack = methods.build_methods_pack(
    review_type=manifest["review_type"], topic=manifest["topic"],
    corpus_search_queries=old_pack["search_strings"],
    source_inventory=old_pack["source_inventory"], search_dates_iso=old_pack["search_dates"],
    n_retrieved=funnel.get("retrieved", funnel.get("n_retrieved")),
    n_screened=funnel.get("screened", funnel.get("n_screened")),
    n_included=len(manifest["receipts"]),
    n_rejected=funnel.get("rejected", funnel.get("n_rejected")),
    outcome_classes=sorted({row["outcome_class"] for row in manifest["receipts"]}),
    receipt_funnel=funnel,
)
methods.write_methods_pack(run, pack)
text = (run / "full_paper.md").read_text()
pattern = r"^### Findings Map\b.*?(?=^### |^## |\Z)"
def map_rows(body):
    section = re.search(pattern, body, re.M | re.S).group()
    return [line for line in section.splitlines() if line.startswith("|")][2:]
before_rows = len(map_rows(text))
text, _ = finalizer._phase_a_methods_replace(text, run)
# Invoke the same compiler used by the finalizer, not handwritten table facts.
text = re.sub(pattern, lambda _: finalizer._findings_map_section(manifest["receipts"]) + "\n\n", text, count=1, flags=re.M | re.S)
(run / "full_paper.md").write_text(text)
submission.prepare_submission_manuscript(run, enrich_sources=False)
payload = submission.build_payload(run, enrich_sources=False)
body = payload["body_markdown"]
rows = map_rows(body)
assert len(rows) == len(manifest["receipts"]) == 37
assert all(any(name in row for row in rows) for name in ("Rao 2025", "Nikniaz 2023", "Samaei 2020"))
assert "representative" not in "\n".join(rows)
assert "37 records retrieved" not in body and "37 were screened" not in body
assert payload == submission.build_payload(run, enrich_sources=False)
assert hashlib.sha256((source / "full_paper.md").read_bytes()).hexdigest() == original_hash
(run / "candidate_payload.json").write_text(json.dumps(payload, indent=2))
receipt = dict(run=str(run), source_manuscript_sha256=original_hash, source_unchanged=True,
               findings_rows_before=before_rows, findings_rows_after=len(rows),
               missing_sources_restored=True, arbitrary_representative_statistics_removed=True,
               methods_unknown_stages_omitted=True, payload_idempotent=True,
               submitted=False, full_revision_eligibility="not established",
               remaining="Re-extract endpoint results, reclassify and reconcile all sections, then normal review")
(repo / ".quality-reports/replay-20260908.json").write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
