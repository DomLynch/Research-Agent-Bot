from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.drafter import RapidEvidenceDrafter
from agent.entity_resolver import resolve_topic, topic_match_ratio
from agent.extractor import StructuredExtractor
from agent.fulltext import FullTextFetcher, entry_identity
from agent.moa_spar_bridge import MoaSparBridgeClient
from agent.planner import QueryPlanner
from agent.provider import MimoClient
from agent.sources.chembl import ChEMBLClient
from agent.sources.clinicaltrials import ClinicalTrialsClient
from agent.sources.doaj import DOAJClient
from agent.sources.europepmc import EuropePMCClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.sources.reporter import NIHReporterClient
from agent.sources.rxiv import RxivClient
from agent.sources.semantic_scholar import SemanticScholarClient
from agent.submit import submit
from agent.validator import validate_citations, validate_draft_quality

_CLINICAL_DOMAINS = {"oncology", "longevity"}
_CLINICAL_KEYWORDS = ("trial", "intervention", "therapy", "clinical")
_RXIV_DOMAINS = {"longevity", "oncology", "metabolic", "general"}
_SEMANTIC_SCHOLAR_DOMAINS = {"longevity", "anti-aging", "anti aging"}
_EUROPEPMC_DOMAINS = {"longevity", "oncology", "metabolic", "cardiology", "neurology", "general"}
_CHEMBL_SUFFIXES = ("mab", "nib", "mycin", "imus", "formin", "glutide", "statin")
_CHEMBL_STOPWORDS = {"and", "or", "anti", "aging", "anti-aging", "longevity", "healthspan", "effects", "outcomes"}
_TOPIC_MATCH_FLOOR = 0.50


def _should_use_clinical_trials(domain: str, topic: str) -> bool:
    if domain in _CLINICAL_DOMAINS:
        return True
    combined = f"{topic} {domain}".lower()
    return any(kw in combined for kw in _CLINICAL_KEYWORDS)


def _should_use_rxiv(domain: str, topic: str) -> bool:
    if domain in _RXIV_DOMAINS:
        return True
    combined = f"{topic} {domain}".lower()
    return any(kw in combined for kw in ("preprint", "mechanism", "geroscience", "aging"))


def _should_use_semantic_scholar(domain: str, topic: str) -> bool:
    if _is_anti_aging_domain(domain) or domain in _SEMANTIC_SCHOLAR_DOMAINS:
        return True
    combined = f"{topic} {domain}".lower()
    return any(kw in combined for kw in ("aging", "geroscience", "longevity"))


def _should_use_europepmc(domain: str, topic: str) -> bool:
    if domain in _EUROPEPMC_DOMAINS:
        return True
    combined = f"{topic} {domain}".lower()
    return any(kw in combined for kw in ("aging", "trial", "therapy", "disease", "older adults", "clinical"))


def _should_use_nih_reporter(domain: str, topic: str) -> bool:
    return _should_use_clinical_trials(domain, topic) or _should_use_semantic_scholar(domain, topic)


def _should_use_chembl(topic: str) -> bool:
    tokens = [tok for tok in _slug(topic).split("-") if tok and tok not in _CHEMBL_STOPWORDS]
    if len(tokens) == 1:
        return True
    return any(tok.endswith(_CHEMBL_SUFFIXES) for tok in tokens)


def _is_anti_aging_domain(domain: str) -> bool:
    normalized = (domain or "").strip().lower()
    return normalized in {"longevity", "anti-aging", "anti aging"} or "aging" in normalized


def _daily_cost(run_dir: str = "runs") -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for f in Path(run_dir).glob("*.json"):
        if f.name.endswith(".raw.json"):
            continue
        if not f.name.startswith(today):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            total += float(data.get("estimated_cost_usd", 0.0) or 0.0)
        except (json.JSONDecodeError, OSError):
            continue
    return round(total, 6)


def _daily_cost_cap() -> float:
    return float(os.getenv("DAILY_COST_CAP_USD", "10.0") or "10.0")


def _is_enabled() -> bool:
    val = os.getenv("BOT_ENABLED", "true").strip().lower()
    return val in {"true", "1", "yes", "on"}


def _is_submit_enabled() -> bool:
    val = os.getenv("BOT_SUBMIT_ENABLED", "true").strip().lower()
    return val in {"true", "1", "yes", "on"}


def _drafter_provider() -> Any:
    builder = MimoClient.from_env()
    # Tests patch MimoClient.from_env with lightweight fake providers. Keep
    # those direct while production uses the Hermes-derived MoA+Spar bridge.
    if not isinstance(builder, MimoClient):
        return builder
    return MoaSparBridgeClient.from_env(builder=builder)


def _slug(value: str) -> str:
    return "-".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in value).split() if part)[:80]


def _run_stem(started_at: str, topic: str) -> str:
    stamp = started_at.replace("+00:00", "Z").replace(":", "-")
    return f"{stamp}-{_slug(topic)}"


def _write_json(run_dir: Path, payload: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{_run_stem(payload['started_at'], payload['topic'])}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_markdown(run_dir: Path, *, started_at: str, topic: str, markdown: str) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{_run_stem(started_at, topic)}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def _write_protocol_json(
    run_dir: Path,
    *,
    started_at: str,
    topic: str,
    raw_topic: str,
    domain: str,
    criteria: str,
    queries: list[str],
    scope_signals: list[str],
    sources: list[str],
    entity_resolution: dict[str, Any],
) -> Path:
    protocol_dir = run_dir / "protocols"
    protocol_dir.mkdir(parents=True, exist_ok=True)
    path = protocol_dir / f"{_run_stem(started_at, topic)}.protocol.json"
    payload = {
        "registered_at": started_at,
        "topic": topic,
        "raw_topic": raw_topic,
        "domain_slug": domain,
        "criteria": criteria,
        "queries": queries,
        "scope_signals": scope_signals,
        "sources": sources,
        "entity_resolution": entity_resolution,
        "analysis_plan": "Rapid evidence synthesis with direct/indirect evidence labeling, GRADE-lite source grading, and PRISMA-style flow reporting.",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _count_by(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _md_cell(value: Any) -> str:
    return str(value or "n/a").replace("|", "/").replace("\n", " ").strip() or "n/a"


def _evidence_table_lines(source_bundle: list[dict[str, Any]]) -> list[str]:
    total = len(source_bundle)
    strict = sum(1 for item in source_bundle if item.get("strict_eligibility_met"))
    lines = [
        "## Evidence Table",
        "",
        f"Strict eligibility met: {strict}/{total} retained sources.",
        "",
        "| Ref | Tier | Design | Strict eligibility? | Confidence | Risk of bias | Role |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, item in enumerate(source_bundle, start=1):
        card = item.get("card") or {}
        design = card.get("study_type") or item.get("evidence_type") or "unknown"
        strict_label = "Yes" if item.get("strict_eligibility_met") else "No"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"[{i}]",
                    _md_cell(item.get("evidence_tier")),
                    _md_cell(design),
                    strict_label,
                    _md_cell(item.get("evidence_confidence") or card.get("evidence_grade")),
                    _md_cell(item.get("risk_of_bias") or card.get("risk_of_bias")),
                    _md_cell(item.get("role")),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _high_severity_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [violation for violation in violations if violation.get("severity") == "high"]


def _draft_revision_feedback(violations: list[dict[str, Any]]) -> str:
    lines = [
        "Rewrite the draft so every section stays faithful to the retained evidence bundle.",
        "Keep inline citations on factual sentences in Key Findings and preserve citation/source alignment.",
        "Published results and meta-analyses must use past-tense reported/evaluated language.",
        "Registered or protocol studies must stay design-only and must not claim outcomes.",
        "Abstract should include at least one numeric effect when structured trial results are retained.",
        "Do not leak raw extractor templates like 'Published results [n] report ...' into the Abstract or Conclusion.",
        "If a support/meta-analysis sentence mentions another intervention or drug class, frame it explicitly as contextual rather than as evidence for the queried topic.",
    ]
    for violation in violations[:5]:
        ref = violation.get("citation")
        role = violation.get("role", "unknown")
        issue = violation.get("issue", "unknown")
        phrase = violation.get("phrase")
        if ref is None:
            detail = f"section={violation.get('section', 'unknown')} issue={issue}"
        else:
            detail = f"[{ref}] role={role} issue={issue}"
        if phrase:
            detail += f" phrase='{phrase}'"
        lines.append(detail)
    return "\n".join(lines)


def _validate_artifact(artifact: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    source_bundle = artifact.get("source_bundle", [])
    citation_violations = validate_citations(artifact, source_bundle)
    draft_quality_violations = validate_draft_quality(artifact, source_bundle)
    return (
        citation_violations,
        draft_quality_violations,
        _high_severity_violations(citation_violations),
        _high_severity_violations(draft_quality_violations),
    )


def _semantic_graph_hits(
    client: SemanticScholarClient,
    evidence: list[dict[str, Any]],
    *,
    canonical_term: str,
    aliases: list[str],
    limit_per_seed: int = 8,
) -> list[dict[str, Any]]:
    needles = [str(canonical_term or "").lower().strip(), *[str(alias).lower().strip() for alias in aliases]]
    seed_dois: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        doi = str(item.get("doi") or "").strip()
        if not doi or doi.lower() in seen:
            continue
        if str(item.get("evidence_type") or "").lower() != "review":
            continue
        text = f"{item.get('title', '')} {item.get('excerpt', '')}".lower()
        if needles and not any(needle and needle in text for needle in needles):
            continue
        seed_dois.append(doi)
        seen.add(doi.lower())
        if len(seed_dois) >= 2:
            break
    expanded: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for doi in seed_dois:
        for item in client.references_of(doi, limit=limit_per_seed):
            key = str(item.get("doi") or item.get("url") or item.get("title") or "").lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            expanded.append(item)
        for item in client.recommendations_for(doi, limit=max(2, min(6, limit_per_seed))):
            key = str(item.get("doi") or item.get("url") or item.get("title") or "").lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            expanded.append(item)
    return expanded


def _exclusion_reasons(scope_signals: list[str], run_log: dict[str, Any]) -> str:
    reasons: list[str] = []
    scope_map = {
        "human_only": "non-human or non-clinical evidence",
        "review_only": "non-review study designs",
        "primary_only": "non-primary study designs",
        "safety_focus": "records without clear safety signal relevance",
        "mechanism_focus": "records without mechanistic/pathway relevance",
    }
    for signal in scope_signals:
        if signal.startswith("year>="):
            reasons.append(f"publication year before {signal.split('>=', 1)[1]}")
        elif signal in scope_map:
            reasons.append(scope_map[signal])
    if run_log.get("bundle_stages", {}).get("excluded_after_filter", 0):
        reasons.append("lower-ranked or less direct evidence removed during final bundle assembly")
    return "; ".join(dict.fromkeys(reasons)) or "none"


def _build_methods_block(run_log: dict[str, Any], artifact: dict[str, Any], source_names: list[str]) -> str:
    stages = run_log.get("bundle_stages", {})
    scope_signals = run_log.get("scope_signals", [])
    full_text = run_log.get("full_text") or {}
    extraction = run_log.get("extraction") or {}
    source_bundle = artifact.get("source_bundle") or []
    bundle_full_text = sum(1 for item in source_bundle if item.get("card", {}).get("full_text_found"))
    bundle_extracted = sum(1 for item in source_bundle if item.get("card", {}).get("extraction_found"))
    trial_results_ct = sum(1 for item in source_bundle if item.get("source_type") == "clinicaltrials" and item.get("has_results"))
    full_text_line = ""
    if full_text.get("attempted", 0):
        full_text_line = (
            f" Full text: {bundle_full_text} bundle-backed items; {full_text.get('found', 0)} of {full_text.get('attempted', 0)} "
            f"eligible literature records fetched via {', '.join((full_text.get('source_counts') or {}).keys()) or 'cache/Europe PMC'}."
        )
    extraction_line = ""
    if extraction.get("attempted", 0) or trial_results_ct:
        registry_str = f"; {trial_results_ct} ClinicalTrials result entries supplied structured outcomes" if trial_results_ct else ""
        extraction_line = (
            f" Structured extraction: {bundle_extracted} bundle-backed items; {extraction.get('found', 0)} of {extraction.get('attempted', 0)} "
            f"full-text-backed records parsed into fact tables (version {extraction.get('version', 'unknown')}){registry_str}."
        )
    return (
        f"Search date: {run_log['started_at']}. Databases/sources searched: {', '.join(source_names)}. "
        f"Queries: {' | '.join(run_log.get('queries', []))}. "
        f"PRISMA-style flow: {stages.get('retrieved', 0)} retrieved, "
        f"{stages.get('screened', 0)} screened, "
        f"{stages.get('excluded_scope', 0)} excluded during scope/domain filtering, "
        f"{stages.get('excluded_after_filter', 0)} excluded during final bundle assembly, "
        f"{stages.get('final_bundle', 0)} included in the final source bundle. "
        f"Exclusion reasons: {_exclusion_reasons(scope_signals, run_log)}. "
        f"Scope signals: {', '.join(scope_signals) or 'none'}.{full_text_line}{extraction_line}"
    )


def _payload_to_markdown(payload: dict, *, topic: str, criteria: str) -> str:
    lines = [
        f"# {payload['title']}",
        "",
        f"- Topic: {topic}",
        f"- Domain: {payload['domain_slug']}",
    ]
    if payload.get("bridge"):
        bridge = payload["bridge"]
        models = ", ".join((bridge.get("moa") or {}).get("reference_models") or [])
        lines.append(f"- Reasoning: MoA+Spar ({models})")
    if criteria.strip():
        lines.append(f"- Criteria: {criteria.strip()}")
    lines.extend(["", "## Abstract", "", payload["abstract"], ""])
    if payload.get("methods"):
        lines.extend(["## Methods", "", payload["methods"], ""])
    for heading, body in payload.get("sections", {}).items():
        if heading == "Methods" and payload.get("methods"):
            continue
        lines.extend([f"## {heading}", "", body, ""])
    if payload.get("source_bundle"):
        lines.extend(_evidence_table_lines(payload["source_bundle"]))
        lines.extend(["## Sources", ""])
        for i, item in enumerate(payload["source_bundle"], start=1):
            title = item.get("title", "Untitled")
            year = item.get("year", "unknown")
            url = item.get("url")
            etype = item.get("evidence_type", "unknown")
            src = item.get("source_type", "")
            url_str = f" — {url}" if url else ""
            src_str = f", {src}" if src else ""
            card = item.get("card") or {}
            citation = card.get("citation", "")
            journal = card.get("journal", "")
            quality = card.get("quality_signal", "")
            grade = card.get("evidence_grade", "")
            directness = item.get("directness", "")
            evidence_tier = item.get("evidence_tier", "")
            strict_eligibility = "yes" if item.get("strict_eligibility_met") else "no"
            confidence = item.get("evidence_confidence", "")
            risk = item.get("risk_of_bias", "")
            card_str = ""
            if citation:
                card_str += f" | {citation}"
            if journal:
                card_str += f" | {journal}"
            if quality:
                card_str += f" | {quality}"
            if card.get("journal_quality"):
                card_str += f" | {card['journal_quality']}"
            if grade:
                card_str += f" | GRADE-lite {grade}"
            if directness:
                card_str += f" | {directness}"
            if evidence_tier:
                card_str += f" | {evidence_tier}"
            card_str += f" | strict eligibility {strict_eligibility}"
            if confidence:
                card_str += f" | confidence {confidence}"
            if risk:
                card_str += f" | risk of bias {risk}"
            lines.append(f"[{i}] {title} ({year}), {etype}{src_str}{card_str}{url_str}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Research Agent Bot")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--criteria", default="")
    parser.add_argument("--per-source-limit", type=int, default=25)
    parser.add_argument("--run-dir", default="runs")
    return parser


def run_agent(
    *,
    topic: str,
    domain: str,
    criteria: str = "",
    per_source_limit: int = 25,
    run_dir: str = "runs",
) -> dict:
    if not _is_enabled():
        return {"error": "BOT_ENABLED is not set to true. Run blocked by kill switch.", "started_at": datetime.now(timezone.utc).isoformat(), "topic": topic}
    started_at = datetime.now(timezone.utc).isoformat()
    spent = _daily_cost(run_dir)
    cap = _daily_cost_cap()
    if spent >= cap:
        return {"error": f"Daily cost cap reached (${spent:.4f} >= ${cap:.2f}). Set DAILY_COST_CAP_USD to override.", "started_at": started_at, "topic": topic}
    chembl_client = ChEMBLClient() if _should_use_chembl(topic) else None
    doaj_client = DOAJClient(cache_dir=Path(run_dir) / "doaj-cache")
    entity = resolve_topic(topic, chembl_client=chembl_client)
    if entity.get("blocked"):
        return {
            "error": f"Could not confidently resolve topic '{topic}'. Verify spelling and try again.",
            "started_at": started_at,
            "topic": topic,
            "canonical_topic": entity.get("canonical_topic"),
            "did_you_mean": entity.get("did_you_mean"),
            "resolver_confidence": entity.get("confidence", 0.0),
        }
    resolved_topic = str(entity.get("canonical_topic") or topic)
    semantic_scholar_client = SemanticScholarClient() if _should_use_semantic_scholar(domain, resolved_topic) else None
    plan = QueryPlanner().build(topic=resolved_topic, domain_slug=domain, criteria=criteria)
    queries = plan.primary_queries()
    source_names: list[str] = ["pubmed", "openalex"]
    run_log = {
        "started_at": started_at,
        "topic": resolved_topic,
        "raw_topic": topic,
        "canonical_topic": resolved_topic,
        "canonical_term": entity.get("canonical_term"),
        "did_you_mean": entity.get("did_you_mean"),
        "resolver_confidence": entity.get("confidence", 1.0),
        "resolver_source": entity.get("resolver_source", "identity"),
        "domain_slug": domain,
        "criteria": criteria,
        "queries": queries,
        "scope_signals": plan.scope_signals(),
        "evidence_retrieved": 0,
        "evidence_selected": 0,
        "source_errors": [],
        "source_counts": {},
        "bundle_stages": {},
    }
    evidence: list[dict] = []
    sources: list[tuple[str, Any]] = [("pubmed", PubMedClient()), ("openalex", OpenAlexClient())]
    if _should_use_europepmc(domain, topic):
        sources.append(("europepmc", EuropePMCClient()))
        source_names.append("europepmc")
    if _should_use_rxiv(domain, topic):
        sources.append(("rxiv", RxivClient()))
        source_names.append("rxiv")
    if _should_use_clinical_trials(domain, topic):
        sources.append(("clinicaltrials", ClinicalTrialsClient()))
        source_names.append("clinicaltrials")
    if chembl_client:
        sources.append(("chembl", chembl_client))
        source_names.append("chembl")
    if _should_use_nih_reporter(domain, topic):
        sources.append(("nih_reporter", NIHReporterClient()))
        source_names.append("nih_reporter")
    if semantic_scholar_client:
        source_names.append("semantic_scholar")
    protocol_path = _write_protocol_json(
        Path(run_dir),
        started_at=started_at,
        topic=resolved_topic,
        raw_topic=topic,
        domain=domain,
        criteria=criteria,
        queries=queries,
        scope_signals=plan.scope_signals(),
        sources=source_names,
        entity_resolution=entity,
    )
    run_log["protocol_file"] = protocol_path.name
    source_counts: dict[str, int] = {name: 0 for name, _ in sources}
    # Specialty sources (ChEMBL = compound metadata, not literature) get a
    # hard per-query cap so they contribute context without swamping the
    # literature signal from pubmed/openalex/rxiv.
    _SPECIALTY_CAP = {"chembl": 5, "clinicaltrials": 8}
    for query in queries:
        for source_name, client in sources:
            try:
                cap = min(per_source_limit, _SPECIALTY_CAP.get(source_name, per_source_limit))
                hits = client.search(query, limit=cap)
                evidence.extend(hits)
                source_counts[source_name] += len(hits)
            except Exception as exc:
                run_log["source_errors"].append(f"{source_name}:{query}:{exc}")
    if semantic_scholar_client:
        source_counts["semantic_scholar"] = source_counts.get("semantic_scholar", 0)
        try:
            graph_hits = _semantic_graph_hits(
                semantic_scholar_client,
                evidence,
                canonical_term=str(entity.get("canonical_term") or resolved_topic),
                aliases=list(entity.get("aliases") or []),
            )
            evidence.extend(graph_hits)
            source_counts["semantic_scholar"] += len(graph_hits)
        except Exception as exc:
            run_log["source_errors"].append(f"semantic_scholar:graph:{exc}")
    run_log["source_counts"] = source_counts
    run_log["evidence_retrieved"] = len(evidence)
    retrieved_n = len(evidence)
    all_evidence = plan.filter_evidence(list(evidence))
    evidence = plan.filter_evidence(evidence)
    full_text_fetcher = FullTextFetcher(cache_dir=Path(run_dir) / "fulltext-cache")
    all_evidence, full_text_stats = full_text_fetcher.enrich_entries(all_evidence, limit=12)
    extractor = StructuredExtractor.from_env(cache_dir=Path(run_dir) / "extract-cache")
    all_evidence, extraction_stats = extractor.enrich_entries(all_evidence, limit=6)
    enriched_lookup = {entry_identity(item): item for item in all_evidence if entry_identity(item)}
    evidence = [dict(enriched_lookup.get(entry_identity(item), item)) for item in evidence]
    run_log["evidence_selected"] = len(evidence)
    run_log["full_text"] = full_text_stats
    run_log["extraction"] = extraction_stats
    topic_ratio = topic_match_ratio(
        evidence[:20],
        canonical_term=str(entity.get("canonical_term") or resolved_topic),
        aliases=list(entity.get("aliases") or []),
    ) if entity.get("entity_type") == "compound" else 1.0
    run_log["topic_match_ratio"] = topic_ratio
    run_log["bundle_stages"] = {
        "retrieved": retrieved_n,
        "screened": retrieved_n,
        "after_domain_filter": len(evidence),
        "excluded_scope": max(0, retrieved_n - len(evidence)),
    }
    should_apply_topic_gate = bool(entity.get("did_you_mean")) or str(entity.get("resolver_source") or "") in {"fuzzy_alias", "chembl"}
    if entity.get("entity_type") == "compound" and evidence and should_apply_topic_gate and topic_ratio < _TOPIC_MATCH_FLOOR:
        run_log["error"] = (
            f"Low topic-match ratio ({topic_ratio:.2f}) for '{resolved_topic}'. "
            f"Verify topic spelling or refine the query."
        )
        run_log["run_log"] = str(_write_json(Path(run_dir), run_log))
        return run_log
    try:
        drafter = RapidEvidenceDrafter(provider=_drafter_provider())
        artifact, raw_output = drafter.draft(
            topic=resolved_topic,
            domain_slug=domain,
            criteria=criteria,
            queries=queries,
            evidence=evidence,
            all_evidence=all_evidence,
            topic_profile=entity,
        )
        if raw_output:
            run_dir_p = Path(run_dir)
            run_dir_p.mkdir(parents=True, exist_ok=True)
            stem = _run_stem(started_at, topic)
            (run_dir_p / f"{stem}.raw.json").write_text(json.dumps(raw_output, indent=2), encoding="utf-8")
        (
            citation_violations,
            draft_quality_violations,
            high_severity_citation,
            high_severity_draft_quality,
        ) = _validate_artifact(artifact)
        high_severity = [*high_severity_citation, *high_severity_draft_quality]
        if high_severity and not artifact.get("error"):
            artifact, retry_raw = drafter.draft(
                topic=resolved_topic,
                domain_slug=domain,
                criteria=criteria,
                queries=queries,
                evidence=evidence,
                all_evidence=all_evidence,
                topic_profile=entity,
                revision_feedback=_draft_revision_feedback(high_severity),
            )
            run_log["citation_retry_count"] = 1
            run_log["quality_retry_count"] = 1
            if retry_raw:
                run_dir_p = Path(run_dir)
                run_dir_p.mkdir(parents=True, exist_ok=True)
                stem = _run_stem(started_at, topic)
                (run_dir_p / f"{stem}.retry.raw.json").write_text(json.dumps(retry_raw, indent=2), encoding="utf-8")
            (
                citation_violations,
                draft_quality_violations,
                high_severity_citation,
                high_severity_draft_quality,
            ) = _validate_artifact(artifact)
            high_severity = [*high_severity_citation, *high_severity_draft_quality]
            if high_severity and not artifact.get("error"):
                if high_severity_draft_quality:
                    artifact["error"] = "High-severity draft-quality violations remained after one revision pass."
                    artifact["gate_reason"] = "draft_quality_violation"
                else:
                    artifact["error"] = "High-severity citation-role violations remained after one revision pass."
                    artifact["gate_reason"] = "citation_role_violation"
        else:
            run_log["citation_retry_count"] = 0
            run_log["quality_retry_count"] = 0
        run_log["bundle_stages"]["final_bundle"] = len(artifact.get("source_bundle", []))
        run_log["bundle_stages"]["excluded_after_filter"] = max(
            0, run_log["bundle_stages"].get("after_domain_filter", 0) - run_log["bundle_stages"]["final_bundle"]
        )
        artifact["methods"] = _build_methods_block(run_log, artifact, source_names)
        if "Methods" not in artifact.get("sections", {}):
            artifact["sections"] = {"Methods": artifact["methods"], **artifact.get("sections", {})}
        if (
            not artifact.get("error")
            and _is_anti_aging_domain(domain)
            and artifact.get("bundle_profile", {}).get("direct_count", 0) == 0
        ):
            artifact["error"] = f"Insufficient evidence: no direct evidence for '{resolved_topic}' in the {domain} domain."
            artifact["gate_reason"] = "insufficient_direct_evidence"
        artifact["citation_violations"] = citation_violations
        artifact["draft_quality_violations"] = draft_quality_violations
        artifact["high_severity_citation_count"] = len(high_severity_citation)
        artifact["high_severity_draft_quality_count"] = len(high_severity_draft_quality)
        artifact["source_bundle"] = doaj_client.annotate_entries(artifact.get("source_bundle", []))
        for entry in artifact["source_bundle"]:
            if entry.get("card") is not None and entry.get("journal_quality"):
                entry["card"]["journal_quality"] = str(entry.get("journal_quality"))
        run_log.update(artifact)
        run_log["source_telemetry"] = {
            "retrieved": source_counts,
            "post_filter": _count_by(evidence, "source_type"),
            "final_bundle": _count_by(artifact.get("source_bundle", []), "source_type"),
            "final_directness": _count_by(artifact.get("source_bundle", []), "directness"),
            "full_text": full_text_stats,
            "extraction": extraction_stats,
        }
        if not artifact.get("error"):
            markdown = _payload_to_markdown(artifact, topic=resolved_topic, criteria=criteria)
            markdown_path = _write_markdown(Path(run_dir), started_at=started_at, topic=resolved_topic, markdown=markdown)
            run_log["markdown"] = markdown
            run_log["markdown_file"] = markdown_path.name
            if os.getenv("RESEARKA_URL") and _is_submit_enabled():
                try:
                    sub = submit(artifact, run_dir=run_dir)
                    run_log["submission"] = sub
                    sub_id = sub.get("submission", {}).get("id")
                    if sub_id:
                        run_log["submission_id"] = sub_id
                    run_log["submission_status"] = sub.get("decision", {}).get("status", "unknown")
                    if sub.get("fingerprint"):
                        run_log["fingerprint"] = sub["fingerprint"]
                except Exception as exc:
                    run_log["submission_error"] = str(exc)
    except Exception as exc:
        run_log["error"] = str(exc)
    run_log["run_log"] = str(_write_json(Path(run_dir), run_log))
    return run_log


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_log = run_agent(
        topic=args.topic,
        domain=args.domain,
        criteria=args.criteria,
        per_source_limit=args.per_source_limit,
        run_dir=args.run_dir,
    )
    if run_log.get("error"):
        print(json.dumps({"error": run_log["error"], "run_log": run_log.get("run_log")}))
        return 1
    print(
        json.dumps(
            {
                "model": run_log.get("model"),
                "estimated_cost_usd": run_log.get("estimated_cost_usd", 0.0),
                "markdown_file": run_log.get("markdown_file"),
                "run_log": run_log["run_log"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
