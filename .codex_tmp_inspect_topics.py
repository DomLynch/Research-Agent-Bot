from __future__ import annotations

import datetime as dt
from pathlib import Path

import scripts.daily_research_paper_cycle as c


ledger_dir = Path("runs/_daily_research_paper_cycle_ledger")
runs_root = Path("runs")
topics = c.discover_topics()
remote_seen, remote_err = c.submit_bridge._remote_published_fingerprints()

terminal = c._terminal_topics(runs_root)
pending, pending_err = c._pending_remote_revision_topics(
    runs_root, ledger_dir, published_loader=lambda: (remote_seen, None)
)
surface = c._surface_repeat_topics(ledger_dir, runs_root=runs_root)
preflight = c._recent_preflight_blocked_topics(ledger_dir)
writer = {
    topic
    for topic, policy in c._writer_gate_repeat_policy(ledger_dir).items()
    if policy.get("action") == "skip_topic"
}
submitted = c._recent_submitted_topics(topics, ledger_dir)
published = c._published_topics(topics, remote_seen, ledger_dir)
source_low = c._current_low_source_precision_topics(topics)
unrepairable = c._unrepairable_source_precision_topics(ledger_dir)
base_excluded = terminal | pending | surface | preflight | writer | submitted | published | unrepairable

current_choice = c.select_topic(
    topics,
    ledger_dir,
    runs_root=runs_root,
    remote_seen=remote_seen,
    exclude=base_excluded,
)

clean_ready = [
    topic
    for topic in topics
    if topic not in base_excluded
    and topic not in source_low
    and topic not in c._recent_blocked_topics(ledger_dir)
    and c._quant_claim_count(topic) >= c.PREFLIGHT_MIN_QUANT_CLAIMS
]
source_low_choice_excluded = set(base_excluded)
if clean_ready:
    source_low_choice_excluded |= source_low
clean_first_choice = c.select_topic(
    topics,
    ledger_dir,
    runs_root=runs_root,
    remote_seen=remote_seen,
    exclude=source_low_choice_excluded,
)

print("now_utc", dt.datetime.now(dt.UTC).isoformat())
print("remote_err", remote_err)
print("pending_err", pending_err)
print("topic_count", len(topics))
for name, values in [
    ("terminal", terminal),
    ("pending", pending),
    ("surface", surface),
    ("preflight", preflight),
    ("writer_skip", writer),
    ("submitted", submitted),
    ("published", published),
    ("source_low", source_low),
    ("unrepairable", unrepairable),
]:
    print(name, len(values), sorted(values)[:12])
print("current_selector_choice", current_choice)
print("current_choice_source_low", current_choice in source_low if current_choice else None)
print("clean_ready_count", len(clean_ready))
print("clean_ready_sample", clean_ready[:12])
print("clean_first_choice", clean_first_choice)
print("clean_first_choice_source_low", clean_first_choice in source_low if clean_first_choice else None)
for topic in ("hrv_autonomic_aging", "glycomic_age_clocks", "metabolism_thresholds"):
    print(
        "topic_state",
        topic,
        {
            "quant": c._quant_claim_count(topic),
            "recent_blocked": topic in c._recent_blocked_topics(ledger_dir),
            "preflight_blocked": topic in preflight,
            "source_low": topic in source_low,
            "submitted": topic in submitted,
            "published": topic in published,
            "attempted_at": c._attempted_at(topic, ledger_dir),
        },
    )
