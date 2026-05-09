"""LLM-assisted qualification rescue for stuck corpus papers.

LLM proposes candidate quantitative effect claims; code validates exact
source text, numeric surface, endpoint, arm, direction, and effect role before
writing anything. This is intentionally a corpus-artifact repair tool, not a
writer shortcut.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from agent.topic_pack import load_topic_pack  # noqa: E402
from vocab import load_domain  # noqa: E402

ALLOWED_CLAIM_TYPES = {
    "p_value", "percentage", "confidence_interval", "hazard_ratio",
    "odds_ratio", "risk_ratio", "mean_sd", "correlation",
}
ALLOWED_DIRECTIONS = {"increase", "decrease", "no_change"}
_NUMBER_RE = re.compile(r"-?(?:\d+(?:\.\d+)?|\.\d+)")
_RAW_TYPE_RE: dict[str, re.Pattern[str]] = {
    "p_value": re.compile(r"^p\s*[<=>]\s*0?\.\d+$", re.IGNORECASE),
    "percentage": re.compile(r"^[~\u2248]?\s*-?\d+(?:\.\d+)?\s*%$"),
    "confidence_interval": re.compile(r"^(?:95\s*%\s*)?CI\b", re.IGNORECASE),
    "hazard_ratio": re.compile(r"^(?:HR|hazard\s+ratio)\s*[=:]?\s*\d", re.IGNORECASE),
    "odds_ratio": re.compile(r"^(?:OR|odds\s+ratio)\s*[=:]?\s*\d", re.IGNORECASE),
    "risk_ratio": re.compile(r"^(?:RR|risk\s+ratio)\s*[=:]?\s*\d", re.IGNORECASE),
    "mean_sd": re.compile(r"^-?\d+(?:\.\d+)?\s*(?:\u00b1|\+/-)\s*\d", re.IGNORECASE),
    "correlation": re.compile(r"^(?:r|rho|correlation)\s*[=:]?\s*-?\d", re.IGNORECASE),
}


@dataclass(frozen=True, slots=True)
class CandidatePaper:
    paper_id: str
    parsed_path: Path
    quant_path: Path
    title: str
    year: str


def _norm(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def _numbers(raw: str) -> tuple[float, ...]:
    values: list[float] = []
    for match in _NUMBER_RE.finditer(raw or ""):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            continue
    return tuple(values)


def _raw_matches_type(raw_text: str, claim_type: str) -> bool:
    pattern = _RAW_TYPE_RE.get(claim_type)
    return bool(pattern and pattern.search(raw_text.strip()))


def _arm_precedes_raw(sentence: str, arm: str, raw_text: str) -> bool:
    low_sentence = sentence.lower()
    low_arm = arm.lower()
    raw_start = low_sentence.find(raw_text.lower())
    if raw_start < 0:
        return False
    return any(m.start() <= raw_start for m in re.finditer(re.escape(low_arm), low_sentence))


def _claim_id(paper_id: str, sentence: str, raw_text: str, endpoint: str) -> str:
    h = hashlib.sha1(
        f"{paper_id}|{sentence}|{raw_text}|{endpoint}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:12]
    return f"{paper_id}-llmrescue-{h}"


def _section_texts(parsed: dict[str, Any], max_chars: int) -> dict[str, str]:
    sections = parsed.get("sections") or {}
    out: dict[str, str] = {}
    budget = max_chars
    for name in ("abstract", "results", "discussion", "conclusion"):
        text = _norm(str(sections.get(name) or ""))
        if not text or budget <= 0:
            continue
        out[name] = text[:budget]
        budget -= len(out[name])
    return out


def _find_sentence(sections: dict[str, str], section: str, sentence: str) -> tuple[str, int] | None:
    wanted = _norm(sentence)
    names = [section] if section in sections else list(sections)
    for name in names:
        text = sections[name]
        idx = text.find(wanted)
        if idx >= 0:
            return name, idx
    return None


def _allowed_arms(topic: str) -> set[str]:
    pack_path = REPO_ROOT / "topic_packs" / f"{topic}.toml"
    pack = load_topic_pack(pack_path)
    arms = {
        "treatment", "active", "pooled", "control", "placebo", "vehicle",
    }
    arms.update(x.strip() for x in pack.aliases if x.strip())
    arms.update(x.strip() for x in pack.active_arm_synonyms if x.strip())
    arms.update(x.strip() for x in pack.placebo_arm_synonyms if x.strip())
    arms.update({"everolimus", "rad001", "rtb101", "mtor inhibitor"})
    return {a.lower() for a in arms}


def _validate_claim(
    *,
    raw: dict[str, Any],
    paper_id: str,
    sections: dict[str, str],
    endpoint_map: dict[str, str],
    endpoint_patterns: dict[str, re.Pattern[str]],
    allowed_arms: set[str],
    model: str,
) -> tuple[dict[str, Any] | None, str]:
    claim_type = str(raw.get("claim_type") or "").strip()
    raw_text = _norm(str(raw.get("raw_text") or ""))
    sentence = _norm(str(raw.get("source_sentence") or raw.get("sentence") or ""))
    section = str(raw.get("source_section") or "").strip().lower()
    endpoint = str(raw.get("endpoint") or "").strip()
    arm = str(raw.get("arm") or "").strip()
    direction = str(raw.get("direction") or "").strip()
    if claim_type not in ALLOWED_CLAIM_TYPES:
        return None, "bad_claim_type"
    if not raw_text or not sentence or raw_text not in sentence:
        return None, "raw_text_not_in_sentence"
    if not _raw_matches_type(raw_text, claim_type):
        return None, "bad_raw_text_shape"
    found = _find_sentence(sections, section, sentence)
    if found is None:
        return None, "sentence_not_in_source"
    section, offset = found
    if endpoint not in endpoint_map:
        return None, "unknown_endpoint"
    pattern = endpoint_patterns.get(endpoint)
    if pattern is not None and not pattern.search(sentence):
        return None, "endpoint_not_in_sentence"
    if arm.lower() not in allowed_arms:
        return None, "unknown_arm"
    if arm.lower() not in sentence.lower():
        return None, "arm_not_in_sentence"
    if not _arm_precedes_raw(sentence, arm, raw_text):
        return None, "arm_does_not_precede_raw_text"
    if direction not in ALLOWED_DIRECTIONS:
        return None, "bad_direction"
    nums = _numbers(raw_text)
    if not nums:
        return None, "no_numeric_value"
    context = sentence[max(0, sentence.find(raw_text) - 60): sentence.find(raw_text) + len(raw_text) + 60]
    return {
        "claim_id": _claim_id(paper_id, sentence, raw_text, endpoint),
        "claim_type": claim_type,
        "raw_text": raw_text,
        "numeric_values": list(nums),
        "units": "%" if "%" in raw_text else "",
        "source_section": section,
        "source_offset": offset + sentence.find(raw_text),
        "sentence": sentence,
        "context_window": context,
        "claim_role": "effect",
        "endpoint": endpoint,
        "arm": arm,
        "direction": direction,
        "binding_confidence": "high",
        "rescue_method": "llm_qualification_rescue_v1",
        "rescue_model": model,
    }, "accepted"


def _candidate_ids(topic_dir: Path) -> set[str]:
    active: set[str] = set()
    report_path = topic_dir / "_extract_report.json"
    if report_path.exists():
        active = {
            str(x) for x in json.loads(report_path.read_text()).get("active_paper_ids") or []
            if str(x).strip()
        }
    classified: set[str] = set()
    class_path = topic_dir / "corpus_classification.json"
    if class_path.exists():
        keep = {"core_on_thesis", "adjacent_clinical", "background_mechanism"}
        classified = {
            str(r.get("paper_id"))
            for r in json.loads(class_path.read_text())
            if isinstance(r, dict)
            and r.get("classification") in keep
            and r.get("paper_id")
        }
    return active | classified


def _load_candidates(topic: str) -> list[CandidatePaper]:
    topic_dir = REPO_ROOT / "docs" / "quality-reference" / topic
    ids = _candidate_ids(topic_dir)
    out: list[CandidatePaper] = []
    for quant_path in sorted((topic_dir / "quant_claims").glob("*.quant_claims.json")):
        data = json.loads(quant_path.read_text())
        pid = str(data.get("paper_id") or quant_path.stem.replace(".quant_claims", ""))
        if pid not in ids:
            continue
        claims = data.get("claims") or []
        if any(c.get("binding_confidence") == "high" for c in claims):
            continue
        parsed_path = topic_dir / "parsed" / f"{pid}.paper_sections.json"
        if not parsed_path.exists():
            continue
        parsed = json.loads(parsed_path.read_text())
        out.append(CandidatePaper(
            paper_id=pid,
            parsed_path=parsed_path,
            quant_path=quant_path,
            title=str(parsed.get("title") or ""),
            year=str(parsed.get("year") or ""),
        ))
    return out


def _chain() -> tuple[Any, ...]:
    from agent.llm_client import CallSpec
    from agent.settings import load_settings

    settings = load_settings()
    return (
        CallSpec(settings.openrouter_base_url, settings.openrouter_api_key, settings.final_layer_reviewer_model, settings.mimo_timeout_sec),
        CallSpec(settings.mimo_base_url, settings.mimo_api_key, settings.mimo_model, settings.mimo_timeout_sec),
        CallSpec(settings.openrouter_base_url, settings.openrouter_api_key, settings.judge_model, settings.mimo_timeout_sec),
        CallSpec(settings.openrouter_base_url, settings.openrouter_api_key, settings.fallback_model, settings.mimo_timeout_sec),
    )


def _prompt(topic: str, paper: CandidatePaper, sections: dict[str, str], endpoints: list[str], arms: set[str]) -> list[dict[str, str]]:
    section_text = "\n\n".join(f"[{k}]\n{v}" for k, v in sections.items())
    return [
        {
            "role": "system",
            "content": (
                "Extract only source-explicit quantitative EFFECT claims. "
                "Return JSON: {\"claims\": [...]}. "
                "Do not infer, summarize, or create claims. Omit doses, durations, ages, "
                "sample sizes, protocol endpoints, prevalence/background facts, and claims "
                "without an exact numeric surface in the provided text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Topic: {topic}\n"
                f"Paper ID: {paper.paper_id}\n"
                f"Title: {paper.title}\nYear: {paper.year}\n\n"
                "Allowed endpoints: " + ", ".join(endpoints) + "\n"
                "Allowed arms: " + ", ".join(sorted(arms)) + "\n"
                "Allowed claim_type values: " + ", ".join(sorted(ALLOWED_CLAIM_TYPES)) + "\n"
                "Allowed direction values: increase, decrease, no_change\n\n"
                "Each claim must include: claim_type, raw_text, source_sentence, "
                "source_section, endpoint, arm, direction. raw_text must be ONLY the "
                "numeric surface, not prose: examples `12%`, `p=0.0015`, "
                "`95% CI 0.73 to 3.18`, `OR = 1.59`. source_sentence must be exact "
                "text below and raw_text must be an exact substring of it.\n\n"
                f"{section_text}"
            ),
        },
    ]


async def _rescue_one(
    paper: CandidatePaper,
    *,
    topic: str,
    endpoints: list[str],
    endpoint_map: dict[str, str],
    endpoint_patterns: dict[str, re.Pattern[str]],
    arms: set[str],
    chain: tuple[Any, ...],
    ledger: Any,
    max_chars: int,
) -> dict[str, Any]:
    from agent.llm_client import chat_json

    parsed = json.loads(paper.parsed_path.read_text())
    sections = _section_texts(parsed, max_chars)
    if not sections:
        return {"paper_id": paper.paper_id, "accepted": 0, "rejected": {"no_text": 1}}
    try:
        resp = await chat_json(
            messages=_prompt(topic, paper, sections, endpoints, arms),
            chain=chain,
            ledger=ledger,
            temperature=0.0,
            max_tokens=1800,
            seed=9,
        )
    except Exception as exc:  # noqa: BLE001 - report per-paper failure.
        return {"paper_id": paper.paper_id, "accepted": 0, "error": str(exc)}
    proposed = resp.parsed.get("claims") or []
    if not isinstance(proposed, list):
        proposed = []
    accepted: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for item in proposed:
        if not isinstance(item, dict):
            rejected["not_object"] += 1
            continue
        claim, reason = _validate_claim(
            raw=item, paper_id=paper.paper_id, sections=sections,
            endpoint_map=endpoint_map, endpoint_patterns=endpoint_patterns,
            allowed_arms=arms, model=resp.model,
        )
        if claim is None:
            rejected[reason] += 1
            continue
        key = f"{claim['raw_text']}|{claim['sentence']}|{claim['endpoint']}"
        if key in seen:
            rejected["duplicate"] += 1
            continue
        seen.add(key)
        accepted.append(claim)
    return {
        "paper_id": paper.paper_id,
        "model": resp.model,
        "proposed": len(proposed),
        "accepted": len(accepted),
        "rejected": dict(rejected),
        "claims": accepted,
    }


def _apply_claims(paper: CandidatePaper, claims: list[dict[str, Any]]) -> None:
    data = json.loads(paper.quant_path.read_text())
    existing = data.get("claims") or []
    known: dict[str, int] = {
        f"{c.get('raw_text')}|{c.get('sentence')}|{c.get('endpoint')}": idx
        for idx, c in enumerate(existing) if isinstance(c, dict)
    }
    additions: list[dict[str, Any]] = []
    changed = False
    for c in claims:
        key = f"{c.get('raw_text')}|{c.get('sentence')}|{c.get('endpoint')}"
        if key in known:
            idx = known[key]
            if idx < len(existing) and existing[idx].get("binding_confidence") != "high":
                existing[idx] = c
                changed = True
            continue
        known[key] = len(existing) + len(additions)
        additions.append(c)
        changed = True
    if not changed:
        return
    data["claims"] = existing + additions
    counts = Counter(c.get("claim_type") for c in data["claims"] if isinstance(c, dict))
    data["claims_count_by_type"] = dict(sorted(counts.items()))
    base_version = str(data.get("extractor_version") or "unknown")
    if "llm_rescue_v1" not in base_version:
        data["extractor_version"] = f"{base_version}+llm_rescue_v1"
    data["rescued_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    paper.quant_path.write_text(json.dumps(data, indent=2) + "\n")


async def _main_async(args: argparse.Namespace) -> int:
    from agent.llm_client import CostLedger

    topic = args.topic
    vocab = load_domain(topic)
    endpoint_map = dict(getattr(vocab, "ENDPOINT_TO_OUTCOME_CLASS", {}))
    endpoint_patterns = {
        str(label): re.compile(str(pattern), re.IGNORECASE)
        for label, pattern in getattr(vocab, "ENDPOINT_VOCAB", ())
    }
    endpoints = sorted(endpoint_map)
    arms = _allowed_arms(topic)
    candidates = _load_candidates(topic)
    if args.paper_id:
        wanted = set(args.paper_id)
        candidates = [p for p in candidates if p.paper_id in wanted]
    if args.offset:
        candidates = candidates[args.offset:]
    if args.limit:
        candidates = candidates[: args.limit]
    ledger = CostLedger()
    chain = _chain()
    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(p: CandidatePaper) -> dict[str, Any]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    _rescue_one(
                        p, topic=topic, endpoints=endpoints,
                        endpoint_map=endpoint_map,
                        endpoint_patterns=endpoint_patterns,
                        arms=arms, chain=chain,
                        ledger=ledger, max_chars=args.max_chars,
                    ),
                    timeout=args.paper_timeout,
                )
            except TimeoutError:
                return {
                    "paper_id": p.paper_id, "accepted": 0,
                    "error": "paper_timeout",
                }

    results: list[dict[str, Any]] = []
    tasks = [asyncio.create_task(guarded(p)) for p in candidates]
    for idx, task in enumerate(asyncio.as_completed(tasks), start=1):
        row = await task
        results.append(row)
        print(
            f"[{idx}/{len(tasks)}] {row.get('paper_id')} "
            f"accepted={row.get('accepted', 0)}",
            file=sys.stderr,
            flush=True,
        )
    by_id = {p.paper_id: p for p in candidates}
    if args.apply:
        for row in results:
            claims = row.get("claims") or []
            if claims:
                _apply_claims(by_id[row["paper_id"]], claims)
    report = {
        "topic": topic,
        "apply": bool(args.apply),
        "candidates": len(candidates),
        "papers_rescued": sum(1 for r in results if int(r.get("accepted") or 0) > 0),
        "claims_accepted": sum(int(r.get("accepted") or 0) for r in results),
        "cost_log": ledger.to_dict(),
        "results": results,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "candidates": report["candidates"],
        "papers_rescued": report["papers_rescued"],
        "claims_accepted": report["claims_accepted"],
        "cost_usd": report["cost_log"]["total_usd"],
        "report": str(args.report),
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--paper-id", action="append", default=[])
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--max-chars", type=int, default=9000)
    parser.add_argument("--paper-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
