"""End-to-end orchestrator: topic + domain + criteria -> markdown draft.

Pipeline:
  retrieve -> bundle -> write_draft -> qa -> (retry once if rejected) -> render

Per-run telemetry (queries, source counts, role distribution, cost, QA score)
is written to runs/<UTC>-<slug>.json. The markdown artifact, if QA-approved,
goes to runs/<UTC>-<slug>.md.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from agent.bundle import bundle as build_bundle
from agent.judge import JudgeVerdict, judge_draft
from agent.llm import WriterUsage, write_draft
from agent.qa import correction_prompt, qa
from agent.relevance import apply_classifications, classify_relevance
from agent.render import render
from agent.retrieve import retrieve
from agent.settings import Settings, load_settings
from agent.sources._base import USER_AGENT
from agent.sources.clinicaltrials import ClinicalTrialsClient
from agent.sources.europepmc import EuropePMCClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.types import Draft, EvidenceItem


def default_sources() -> list:
    return [PubMedClient(), OpenAlexClient(), EuropePMCClient(), ClinicalTrialsClient()]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _build_draft(
    parsed: dict, items: list[EvidenceItem], topic: str, domain: str, criteria: str
) -> Draft:
    return Draft(
        topic=topic,
        domain=domain,
        criteria=criteria,
        title=str(parsed.get("title", "")).strip(),
        abstract=[str(s) for s in (parsed.get("abstract") or [])],
        sections={
            str(k): [str(s) for s in (v or [])]
            for k, v in (parsed.get("sections") or {}).items()
        },
        bundle=items,
        facts=[],  # V1 does not populate facts; qa.py enforces via gates.
    )


def _merge_usage(a: WriterUsage, b: WriterUsage) -> WriterUsage:
    return WriterUsage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        estimated_cost_usd=a.estimated_cost_usd + b.estimated_cost_usd,
        model=a.model,
        prompt_version=a.prompt_version,
    )


def _today_cost(settings: Settings) -> float:
    runs = Path(settings.runs_dir)
    if not runs.exists():
        return 0.0
    today = time.strftime("%Y-%m-%d", time.gmtime())
    total = 0.0
    for p in runs.glob(f"{today}*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            total += float(data.get("estimated_cost_usd", 0) or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return total


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())


def _write_log(settings: Settings, topic: str, out: dict) -> str:
    runs = Path(settings.runs_dir)
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{_stamp()}-{_slugify(topic)}.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return str(path)


def _write_markdown(settings: Settings, topic: str, markdown: str) -> str:
    runs = Path(settings.runs_dir)
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{_stamp()}-{_slugify(topic)}.md"
    path.write_text(markdown, encoding="utf-8")
    return str(path)


async def run_async(
    *,
    topic: str,
    domain: str,
    criteria: str = "",
    settings: Settings | None = None,
    sources: list | None = None,
    write_log: bool = True,
    use_smart_relevance: bool = True,
) -> dict:
    """Judge always runs when OPENROUTER_API_KEY is configured (mandatory
    safety net — catches semantic hallucinations the regex gates can't).
    Without the key, judge silently no-ops and the QA-only path ships."""
    settings = settings or load_settings()
    if not settings.bot_enabled:
        return {"error": "BOT_ENABLED is false"}
    if not settings.mimo_api_key and not settings.openrouter_api_key:
        return {"error": "MIMO_API_KEY (or OPENROUTER_API_KEY) is not set"}
    if _today_cost(settings) >= settings.daily_cost_cap_usd:
        return {"error": f"daily cost cap ${settings.daily_cost_cap_usd} reached"}

    sources = sources or default_sources()
    started = time.time()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    verdict: JudgeVerdict | None = None

    async with httpx.AsyncClient(timeout=settings.mimo_timeout_sec, headers=headers) as client:
        sources_list, abstracts, raw_signals = await retrieve(
            topic, criteria, sources=sources, client=client, domain=domain,
        )
        if not sources_list:
            return {"error": "no sources retrieved", "topic": topic}

        items = build_bundle(
            sources_list, abstracts,
            topic=topic, domain=domain, raw_signals=raw_signals,
        )

        # Optional LLM relevance pre-filter (Gemma 4) — overrides
        # deterministic direct=True/False with semantic judgment.
        # Catches what regex misses: monkey aging clock papers (background,
        # not core), vitamin-D meta-analyses on mortality (core, not just
        # 'has aging marker'), cancer-therapy papers with the topic drug
        # (excluded for longevity). Single LLM call, ~$0.0005.
        relevance_meta: dict[str, object] | None = None
        if use_smart_relevance and (
            settings.mimo_api_key or settings.openrouter_api_key
        ):
            classifications = await classify_relevance(
                items, topic, domain, settings=settings, client=client,
            )
            if classifications:
                items = apply_classifications(items, classifications)
                relevance_meta = {
                    "applied": True,
                    "core": sum(1 for v in classifications.values() if v == "core"),
                    "background": sum(1 for v in classifications.values() if v == "background"),
                    "excluded": sum(1 for v in classifications.values() if v == "excluded"),
                    "by_ref": {str(k): v for k, v in classifications.items()},
                }

        parsed, usage = await write_draft(
            items, topic, domain, criteria, settings=settings, client=client,
        )
        draft = _build_draft(parsed, items, topic, domain, criteria)
        result = qa(draft)
        attempts = 1

        if not result.approved:
            previous_parsed = parsed
            parsed, usage2 = await write_draft(
                items, topic, domain, criteria,
                settings=settings, client=client,
                correction=correction_prompt(result.failures),
                previous_draft=previous_parsed,
            )
            draft = _build_draft(parsed, items, topic, domain, criteria)
            result = qa(draft)
            usage = _merge_usage(usage, usage2)
            attempts = 2

        # Mandatory second layer of quality control after QA approves.
        # Judge runs whenever OPENROUTER_API_KEY is configured; catches
        # semantic hallucinations (mis-attributed claims, fabricated trial
        # names) that the regex gates can't see. Graceful no-op without
        # the key. If Judge requests revision, the writer revises once
        # AND the judge re-runs on the revised draft — otherwise the
        # rendered Adjudication block would show the stale pre-revision
        # rejection alongside an approved final draft.
        if result.approved:
            verdict = await judge_draft(
                parsed, items, topic, domain, settings=settings, client=client,
            )
            if verdict and not verdict.approved and verdict.revision_notes:
                parsed_rev, usage_rev = await write_draft(
                    items, topic, domain, criteria,
                    settings=settings, client=client,
                    correction=verdict.revision_notes,
                    previous_draft=parsed,
                )
                draft = _build_draft(parsed_rev, items, topic, domain, criteria)
                result = qa(draft)
                usage = _merge_usage(usage, usage_rev)
                attempts += 1
                # Re-judge the revised draft so the artifact's adjudication
                # block reflects the SHIPPED draft, not the rejected one.
                # If the second judgment also rejects, the dual-rejection
                # path takes over and the markdown ships UNVERIFIED.
                if result.approved:
                    parsed = parsed_rev
                    verdict_rev = await judge_draft(
                        parsed_rev, items, topic, domain,
                        settings=settings, client=client,
                    )
                    if verdict_rev is not None:
                        verdict = verdict_rev
                        if not verdict_rev.approved:
                            # Treat as rejection for the dual-rejection path
                            # so the user sees the UNVERIFIED banner.
                            from agent.types import GateFailure, QAResult
                            judge_failures = tuple(
                                GateFailure(
                                    code="judge_rejected_post_revision",
                                    message=f"[{verdict_rev.model}] {issue}",
                                    severity="block",
                                )
                                for issue in verdict_rev.blocking_issues
                            ) or (
                                GateFailure(
                                    code="judge_rejected_post_revision",
                                    message=verdict_rev.summary or "rejected",
                                    severity="block",
                                ),
                            )
                            result = QAResult(
                                approved=False,
                                failures=tuple(result.failures) + judge_failures,
                                score=result.score,
                            )

    meta: dict[str, object] = asdict(usage)
    if verdict is not None:
        meta["judge_model"] = verdict.model
        meta["judge_score"] = verdict.score
        meta["estimated_cost_usd"] = float(meta["estimated_cost_usd"]) + verdict.estimated_cost_usd
    # Surface qa failures + judge verdict to the renderer so the
    # ## QA Failures and ## Adjudication blocks always reflect the
    # true state of validation — even on dual-rejection.
    meta["qa_failures"] = [asdict(f) for f in result.failures]
    meta["qa_approved"] = result.approved
    if verdict is not None:
        meta["judge"] = {
            "model": verdict.model,
            "approved": verdict.approved,
            "score": verdict.score,
            "summary": verdict.summary,
            "blocking_issues": list(verdict.blocking_issues),
        }
    # Always render — the user gets the draft + an UNVERIFIED warning when
    # validation fails, never an empty result. Blank markdown was the
    # 'dual-rejection undefined' bug the reviewer flagged.
    markdown = render(draft, meta=meta)
    if not result.approved and draft.title.strip():
        markdown = _unverified_banner(result.failures) + "\n\n" + markdown

    out: dict[str, object] = {
        "topic": topic,
        "domain": domain,
        "criteria": criteria,
        "approved": result.approved,
        "qa_score": result.score,
        "qa_failures": [asdict(f) for f in result.failures],
        "attempts": attempts,
        "n_sources": len(items),
        "n_direct": sum(1 for it in items if it.direct),
        "role_counts": _counter([it.role for it in items]),
        "tier_counts": _counter([it.tier for it in items]),
        "elapsed_sec": round(time.time() - started, 2),
        "model": usage.model,
        "prompt_version": usage.prompt_version,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "estimated_cost_usd": float(meta.get("estimated_cost_usd", usage.estimated_cost_usd)),
        "judge": (
            {
                "model": verdict.model,
                "approved": verdict.approved,
                "score": verdict.score,
                "summary": verdict.summary,
                "blocking_issues": list(verdict.blocking_issues),
                "input_tokens": verdict.input_tokens,
                "output_tokens": verdict.output_tokens,
                "estimated_cost_usd": verdict.estimated_cost_usd,
            }
            if verdict is not None
            else None
        ),
        "relevance": relevance_meta,
        "markdown": markdown,
    }

    if write_log:
        out["log_path"] = _write_log(settings, topic, out)
        if markdown:
            out["markdown_file"] = _write_markdown(settings, topic, markdown)
    return out


def _counter(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for v in values:
        result[v] = result.get(v, 0) + 1
    return result


def _unverified_banner(failures) -> str:
    """Top-of-document warning when dual-rejection ships markdown."""
    blocks = [f for f in failures if f.severity == "block"]
    n = len(blocks)
    return (
        "> ⚠️ **UNVERIFIED — DRAFT FAILED VALIDATION**\n>\n"
        f"> This draft did not pass the deterministic QA gates after one\n"
        f"> revision attempt ({n} blocking issue{'s' if n != 1 else ''}). The\n"
        "> material issues are listed in `## QA Failures` below. Treat this\n"
        "> as research material for human review, not a publishable artifact."
    )


def run(**kwargs) -> dict:
    """Sync wrapper for CLI / dashboard / tests."""
    return asyncio.run(run_async(**kwargs))
