from __future__ import annotations

import html
import re
from typing import Any

import httpx

CLINICALTRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _extract_year(study: dict[str, Any]) -> int | None:
    status = (study.get("protocolSection") or {}).get("statusModule") or {}
    for key in ("primaryCompletionDateStruct", "completionDateStruct", "startDateStruct", "studyFirstPostDateStruct"):
        date_str = (status.get(key) or {}).get("date", "")
        if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
            return int(date_str[:4])
    return None


def _extract_excerpt(study: dict[str, Any]) -> str:
    desc = (study.get("protocolSection") or {}).get("descriptionModule") or {}
    return _clean_text(desc.get("briefSummary"))


def _extract_title(study: dict[str, Any]) -> str:
    ident = (study.get("protocolSection") or {}).get("identificationModule") or {}
    return _clean_text(ident.get("briefTitle") or ident.get("officialTitle"), limit=300)


def _extract_nct_id(study: dict[str, Any]) -> str:
    ident = (study.get("protocolSection") or {}).get("identificationModule") or {}
    return _clean_text(ident.get("nctId"))


def _has_results(study: dict[str, Any]) -> bool:
    return bool(study.get("hasResults"))


def _is_interventional(study: dict[str, Any]) -> str:
    design = (study.get("protocolSection") or {}).get("designModule") or {}
    study_type = _clean_text(design.get("studyType")).lower()
    return "interventional" if study_type == "interventional" else "observational"


def _extract_population(study: dict[str, Any]) -> str:
    eligibility = (study.get("protocolSection") or {}).get("eligibilityModule") or {}
    return _clean_text(eligibility.get("healthyVolunteers") or eligibility.get("eligibilityCriteria"), limit=240)


def _group_counts(outcome: dict[str, Any]) -> dict[str, str]:
    counts: dict[str, str] = {}
    for denom in outcome.get("denoms") or []:
        for item in denom.get("counts") or []:
            group_id = _clean_text(item.get("groupId"))
            value = _clean_text(item.get("value"), limit=40)
            if group_id and value:
                counts[group_id] = value
        if counts:
            break
    return counts


def _group_titles(outcome: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for group in outcome.get("groups") or []:
        group_id = _clean_text(group.get("id"))
        title = _clean_text(group.get("title"), limit=80)
        if group_id and title:
            titles[group_id] = title
    return titles


def _group_measurements(outcome: dict[str, Any]) -> list[dict[str, str]]:
    for klass in outcome.get("classes") or []:
        for category in klass.get("categories") or []:
            measurements = []
            for item in category.get("measurements") or []:
                group_id = _clean_text(item.get("groupId"))
                value = _clean_text(item.get("value"), limit=40)
                spread = _clean_text(item.get("spread"), limit=40)
                if group_id and value:
                    measurements.append({"group_id": group_id, "value": value, "spread": spread})
            if measurements:
                return measurements
    return []


def _extract_results_extraction(study: dict[str, Any]) -> dict[str, Any] | None:
    if not _has_results(study):
        return None
    outcome_module = (study.get("resultsSection") or {}).get("outcomeMeasuresModule") or {}
    outcomes = outcome_module.get("outcomeMeasures") or []
    effects: list[dict[str, str]] = []
    primary_outcome = ""
    intervention = ""
    comparator = ""
    population = _extract_population(study)
    methods_bits = []
    for outcome in outcomes:
        if _clean_text(outcome.get("reportingStatus")).lower() != "posted":
            continue
        title = _clean_text(outcome.get("title"), limit=160)
        if not primary_outcome and _clean_text(outcome.get("type")).upper() == "PRIMARY":
            primary_outcome = title
        group_titles = _group_titles(outcome)
        measurements = _group_measurements(outcome)
        if not measurements:
            continue
        if not intervention and measurements:
            intervention = group_titles.get(measurements[0]["group_id"], "")
        if not comparator and len(measurements) > 1:
            comparator = group_titles.get(measurements[1]["group_id"], "")
        counts = _group_counts(outcome)
        measure_bits = []
        n_bits = []
        for item in measurements[:2]:
            label = group_titles.get(item["group_id"], item["group_id"])
            bit = f"{label}={item['value']}"
            if item["spread"]:
                bit += f" (spread {item['spread']})"
            measure_bits.append(bit)
            if counts.get(item["group_id"]):
                n_bits.append(f"{label} N={counts[item['group_id']]}")
        analysis = (outcome.get("analyses") or [{}])[0]
        p_value = _clean_text(analysis.get("pValue"), limit=40)
        metric = _clean_text(outcome.get("paramType"), limit=40) or "reported"
        span_bits = [title, _clean_text(outcome.get("timeFrame"), limit=80), "; ".join(measure_bits)]
        if n_bits:
            span_bits.append("; ".join(n_bits))
        if p_value:
            span_bits.append(f"p={p_value}")
        effects.append(
            {
                "outcome": title,
                "metric": metric,
                "value": "; ".join(measure_bits),
                "ci_low": "",
                "ci_high": "",
                "p_value": p_value,
                "n": "; ".join(n_bits),
                "source_span": _clean_text(". ".join(bit for bit in span_bits if bit), limit=320),
            }
        )
        if not methods_bits:
            methods_bits = [
                _clean_text(outcome.get("timeFrame"), limit=80),
                _clean_text(outcome.get("unitOfMeasure"), limit=60),
            ]
        if len(effects) >= 2:
            break
    if not effects:
        return None
    return {
        "found": True,
        "primary_outcome": primary_outcome or effects[0]["outcome"],
        "population": population,
        "intervention": intervention,
        "comparator": comparator,
        "methods_summary": _clean_text("; ".join(bit for bit in methods_bits if bit), limit=240),
        "risk_of_bias": "registry-posted outcomes",
        "effects": effects,
        "extractor_version": "ctgov-results-v1",
        "source_doi": _extract_nct_id(study),
    }


class ClinicalTrialsClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1"},
        )

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.get(
            CLINICALTRIALS_URL,
            params={
                "query.term": _clean_text(query, limit=240),
                "pageSize": max(1, min(limit, 20)),
                "format": "json",
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for study in response.json().get("studies", []):
            nct_id = _extract_nct_id(study)
            title = _extract_title(study)
            excerpt = _extract_excerpt(study)
            if not nct_id or not title or not excerpt:
                continue
            year = _extract_year(study)
            design = _is_interventional(study)
            extraction = _extract_results_extraction(study)
            trial_status = "results" if _has_results(study) and extraction else "registered"
            entries.append(
                {
                    "id": nct_id,
                    "title": title,
                    "excerpt": excerpt,
                    "url": f"https://clinicaltrials.gov/study/{nct_id}",
                    "doi": None,
                    "year": year,
                    "query": _clean_text(query, limit=240),
                    "source_type": "clinicaltrials",
                    "evidence_type": design,
                    "trial_status": trial_status,
                    "has_results": trial_status == "results",
                    "extraction": extraction,
                    "journal": None,
                }
            )
            if len(entries) >= limit:
                break
        return entries
