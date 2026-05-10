"""Source-text Cochrane RoB-2 signaling-questionnaire scaffold.

Phase 4 (Wave 17): the ladder defined in `agent.final_gate.RobMethodStatus`
goes from `automated_screening` → `receipt_grounded_screening` →
`source_text_full_cochrane`. The first two run on metadata; the third
requires the LLM to read each paper's Methods/Results sections and
answer the RoB-2 signaling questions per domain.

This module is the scaffold for that third tier. It is INTENTIONALLY
scaffold-only by default — `assess_study_from_source_text` requires a
caller-provided `call_llm` callable. The default factory raises
NotImplementedError so a stray invocation cannot accidentally burn LLM
budget. Real wiring (e.g., agent/llm_client.chat_json) is opt-in via
the adapter's --rob-method-status=source_text_full_cochrane CLI flag.

What's covered here:
  - The RoB-2 5-domain signaling-question registry, transcribed
    verbatim from the Cochrane RoB-2 v9 short-form template.
  - Per-domain prompt builders that render the relevant Methods /
    Results / Discussion section text into a structured prompt.
  - Per-domain response parser (JSON-only, validates rating + rationale
    + signaling answers).
  - Aggregation into a single StudyAssessment with overall_rating that
    follows the Cochrane "weakest-link" rule (worst domain wins).

What's NOT here:
  - LLM client implementation. Bring your own `call_llm`.
  - Cost ledger. Caller is responsible for tracking spend.
  - Caching. Caller is responsible for not double-extracting the same
    paper.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = [
    "DomainName",
    "DomainSignalingQuestion",
    "ROB2_DOMAINS",
    "DomainResponse",
    "StudyAssessmentSourceText",
    "build_domain_prompt",
    "parse_domain_response",
    "assess_study_from_source_text",
    "default_call_llm_raises",
]


DomainName = Literal[
    "randomization",
    "deviations",
    "missing_data",
    "outcome_measurement",
    "selective_reporting",
]

Rating = Literal["low", "some_concerns", "high"]


@dataclass(frozen=True, slots=True)
class DomainSignalingQuestion:
    """One RoB-2 signaling question. Verbatim from RoB-2 v9 short-form."""

    qid: str       # e.g. "1.1"
    text: str      # the question itself
    yes_means: str  # what "yes" implies for risk: e.g. "lower risk", "higher"


# RoB-2 5-domain signaling questionnaire (RCT version). Transcribed
# from the Cochrane RoB-2 v9 short-form template.
ROB2_DOMAINS: Mapping[DomainName, tuple[DomainSignalingQuestion, ...]] = {
    "randomization": (
        DomainSignalingQuestion(
            "1.1",
            "Was the allocation sequence random?",
            "lower risk",
        ),
        DomainSignalingQuestion(
            "1.2",
            "Was the allocation sequence concealed until participants "
            "were enrolled and assigned to interventions?",
            "lower risk",
        ),
        DomainSignalingQuestion(
            "1.3",
            "Did baseline differences between intervention groups "
            "suggest a problem with the randomization process?",
            "higher risk",
        ),
    ),
    "deviations": (
        DomainSignalingQuestion(
            "2.1",
            "Were participants aware of their assigned intervention "
            "during the trial?",
            "higher risk",
        ),
        DomainSignalingQuestion(
            "2.2",
            "Were carers and people delivering the interventions aware "
            "of participants' assigned intervention during the trial?",
            "higher risk",
        ),
        DomainSignalingQuestion(
            "2.3",
            "Were there deviations from the intended intervention that "
            "arose because of the trial context?",
            "higher risk",
        ),
        DomainSignalingQuestion(
            "2.6",
            "Was an appropriate analysis used to estimate the effect of "
            "assignment to intervention (intention-to-treat or similar)?",
            "lower risk",
        ),
    ),
    "missing_data": (
        DomainSignalingQuestion(
            "3.1",
            "Were data for this outcome available for all, or nearly "
            "all, participants randomized?",
            "lower risk",
        ),
        DomainSignalingQuestion(
            "3.2",
            "Is there evidence that the result was not biased by "
            "missing outcome data?",
            "lower risk",
        ),
    ),
    "outcome_measurement": (
        DomainSignalingQuestion(
            "4.1",
            "Was the method of measuring the outcome inappropriate?",
            "higher risk",
        ),
        DomainSignalingQuestion(
            "4.2",
            "Could measurement or ascertainment of the outcome have "
            "differed between intervention groups?",
            "higher risk",
        ),
        DomainSignalingQuestion(
            "4.3",
            "Were outcome assessors aware of the intervention received "
            "by study participants?",
            "higher risk",
        ),
    ),
    "selective_reporting": (
        DomainSignalingQuestion(
            "5.1",
            "Were the data that produced this result analysed in "
            "accordance with a pre-specified analysis plan that was "
            "finalized before unblinded outcome data were available?",
            "lower risk",
        ),
        DomainSignalingQuestion(
            "5.2",
            "Is the numerical result being assessed likely to have been "
            "selected, on the basis of the results, from multiple "
            "outcome measurements within the outcome domain?",
            "higher risk",
        ),
    ),
}


# Per-domain section hints — which paper sections most likely contain
# the evidence for each domain's signaling questions. Used to keep the
# prompt focused (so we don't ship the full paper text every call).
_SECTION_HINTS: Mapping[DomainName, tuple[str, ...]] = {
    "randomization":        ("methods", "introduction"),
    "deviations":           ("methods", "results"),
    "missing_data":         ("methods", "results"),
    "outcome_measurement":  ("methods",),
    "selective_reporting":  ("methods", "results"),
}


@dataclass(frozen=True, slots=True)
class DomainResponse:
    """LLM-returned RoB-2 verdict for one domain on one study."""

    domain: DomainName
    rating: Rating
    rationale: str
    signaling_answers: Mapping[str, str]  # qid -> "yes" | "no" | "unclear" | "no_information"


@dataclass(frozen=True, slots=True)
class StudyAssessmentSourceText:
    """Per-study Cochrane RoB-2 verdict from source-text extraction."""

    study_id: str
    paper_id: str
    overall_rating: Rating
    domains: tuple[DomainResponse, ...]
    method_status: str = "source_text_full_cochrane"
    notes: str = ""


def default_call_llm_raises(prompt: str) -> str:  # noqa: ARG001
    """Default LLM caller — refuses to spend budget. Override at the call
    site (`assess_study_from_source_text(..., call_llm=real_caller)`)
    to enable live extraction."""
    raise NotImplementedError(
        "assess_study_from_source_text requires an explicit call_llm "
        "argument; the default refuses to call any LLM to avoid "
        "accidental spend. Pass a real caller that takes a prompt str "
        "and returns a JSON-string response."
    )


def build_domain_prompt(
    *,
    study_id: str,
    domain: DomainName,
    paper_sections: Mapping[str, str],
) -> str:
    """Render a domain-specific RoB-2 signaling prompt."""
    questions = ROB2_DOMAINS[domain]
    section_text_parts: list[str] = []
    for sec_name in _SECTION_HINTS[domain]:
        text = (paper_sections.get(sec_name) or "").strip()
        if text:
            section_text_parts.append(f"## {sec_name.title()}\n\n{text}")
    paper_excerpt = "\n\n".join(section_text_parts) or "(no relevant sections found)"
    qid_lines = "\n".join(
        f"  {q.qid}: {q.text}  [\"yes\" → {q.yes_means}]"
        for q in questions
    )
    domain_label = domain.replace("_", " ")
    return (
        f"You are a Cochrane systematic-review methodologist completing "
        f"the RoB-2 v9 signaling questionnaire for ONE domain on ONE "
        f"study.\n\n"
        f"Study: {study_id}\n"
        f"Domain: {domain_label}\n\n"
        f"Signaling questions:\n{qid_lines}\n\n"
        f"For each signaling question answer one of: \"yes\", \"no\", "
        f"\"unclear\", or \"no_information\". Then summarise the "
        f"domain-level risk as one of: \"low\", \"some_concerns\", "
        f"\"high\". Cite specific phrases or numbers from the source "
        f"text in your rationale (1-3 sentences).\n\n"
        f"Source text:\n\n{paper_excerpt}\n\n"
        f"Return JSON ONLY in this exact shape:\n"
        f"{{\n"
        f'  "domain": "{domain}",\n'
        f'  "rating": "<low|some_concerns|high>",\n'
        f'  "rationale": "<your 1-3 sentence rationale>",\n'
        f'  "signaling_answers": {{\n'
        f'    "<qid>": "<yes|no|unclear|no_information>", ...\n'
        f"  }}\n"
        f"}}\n"
    )


_VALID_RATINGS = frozenset({"low", "some_concerns", "high"})
_VALID_SIGNALS = frozenset({"yes", "no", "unclear", "no_information"})


def parse_domain_response(domain: DomainName, raw_json: str) -> DomainResponse:
    """Parse + validate the LLM's JSON. Strict construction: bad shapes
    raise ValueError so callers fail-loudly rather than silently ship
    malformed Cochrane assessments."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        # Some LLMs wrap JSON in code fences. Strip and retry once.
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json.strip(), flags=re.M)
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            raise ValueError(f"domain {domain} response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"domain {domain} response is not a JSON object")
    rating = str(data.get("rating") or "").strip().lower()
    if rating not in _VALID_RATINGS:
        raise ValueError(
            f"domain {domain} rating {rating!r} not in {sorted(_VALID_RATINGS)}"
        )
    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        raise ValueError(f"domain {domain} response missing rationale")
    raw_answers = data.get("signaling_answers") or {}
    if not isinstance(raw_answers, dict):
        raise ValueError(f"domain {domain} signaling_answers is not a dict")
    cleaned: dict[str, str] = {}
    for qid, ans in raw_answers.items():
        ans_clean = str(ans or "").strip().lower().replace(" ", "_")
        if ans_clean in _VALID_SIGNALS:
            cleaned[str(qid)] = ans_clean
    return DomainResponse(
        domain=domain,
        rating=rating,  # type: ignore[arg-type]
        rationale=rationale,
        signaling_answers=cleaned,
    )


def _overall_rating(domains: tuple[DomainResponse, ...]) -> Rating:
    """Cochrane RoB-2 overall: worst domain wins. low < some < high."""
    order: dict[Rating, int] = {"low": 0, "some_concerns": 1, "high": 2}
    if not domains:
        return "high"
    return max(domains, key=lambda d: order[d.rating]).rating


def assess_study_from_source_text(
    *,
    study_id: str,
    paper_id: str,
    paper_sections: Mapping[str, str],
    call_llm: Callable[[str], str] = default_call_llm_raises,
) -> StudyAssessmentSourceText:
    """Build a full RoB-2 assessment for one study by issuing one
    LLM call per domain. Raises if `call_llm` returns malformed JSON
    on any domain — fail-closed beats silently shipping junk."""
    domain_responses: list[DomainResponse] = []
    for domain in ROB2_DOMAINS:
        prompt = build_domain_prompt(
            study_id=study_id,
            domain=domain,
            paper_sections=paper_sections,
        )
        raw = call_llm(prompt)
        domain_responses.append(parse_domain_response(domain, raw))
    domains_tuple = tuple(domain_responses)
    return StudyAssessmentSourceText(
        study_id=study_id,
        paper_id=paper_id,
        overall_rating=_overall_rating(domains_tuple),
        domains=domains_tuple,
    )


def load_paper_sections(parsed_path: Path | str) -> dict[str, str]:
    """Read a `<paper_id>.paper_sections.json` and return a flat
    section_name -> text dict.

    The schema produced by scripts/fetch_oa_corpus.py and the PDF
    ingest is `{"sections": {"intro": "...", "methods": "...", ...}}`.
    Falls back to a flat dict when the wrapper is absent."""
    p = Path(parsed_path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    sections = data.get("sections")
    if isinstance(sections, dict):
        return {str(k): str(v) for k, v in sections.items() if v}
    # Fall back: flatten any top-level string fields that look like sections.
    return {
        str(k): str(v)
        for k, v in data.items()
        if k in {"introduction", "methods", "results", "discussion",
                 "conclusion", "abstract", "intro"} and isinstance(v, str)
    }
