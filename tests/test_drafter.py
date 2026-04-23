from agent.drafter import RapidEvidenceDrafter, _bundle_entry, _classify_directness
from agent.evidence_cards import build_card
from agent.submit import _quality_gate
from agent.validator import validate_citations


class CaptureProvider:
    prompt_version = "test-prompt/v1"
    model = "mimo-v2-pro"

    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, as evaluated in randomized controlled trials with an intervention duration of at least 6 months, and what is the evidence for safety and efficacy in this population?",
                "search_summary": "Published findings and trial registrations were reviewed separately.",
                "landscape": "The evidence base includes both posted trial findings and registry-only studies.",
                "findings": "Published findings suggest cautious signals [1]. Registered studies are investigating additional outcomes [2].",
                "limitations": "The evidence remains limited and partly indirect.",
                "gaps_identified": "More long-duration trials are needed.",
                "conclusion": "Metformin remains investigational for healthy aging.",
            },
            {},
        )


class BadRegistryProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on frailty and cognition in older adults over at least six months of follow-up, compared with placebo, and what does the published evidence versus trial registration record imply about safety, efficacy, and remaining uncertainty in healthy aging?",
                "search_summary": "Published findings and trial registrations were reviewed separately.",
                "landscape": "A registered trial [2] showed better frailty outcomes.",
                "findings": "Published trial [1] remains relevant. Registered trial [2] showed better frailty outcomes.",
                "limitations": "The evidence remains limited and partly indirect.",
                "gaps_identified": "More long-duration trials are needed.",
                "conclusion": "Metformin remains investigational, although registered study [2] reported benefit.",
            },
            {},
        )


class UnsupportedNumericProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of semaglutide on weight outcomes in adults with obesity over at least six months of follow-up, compared with placebo, and what does the retained evidence indicate about efficacy, safety, and remaining uncertainty?",
                "search_summary": "Recent published findings were reviewed.",
                "landscape": "The evidence base is composed of recent obesity trials.",
                "findings": "One trial reported -15.8% weight loss versus -3.0% placebo [1]. Another found 86.4% achieved at least 5% weight loss [1].",
                "limitations": "The evidence remains limited.",
                "gaps_identified": "Long-term outcomes remain uncertain.",
                "conclusion": "Semaglutide reduced weight by -15.8% versus -3.0% placebo [1].",
            },
            {},
        )


class BadPublishedResultsProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on sarcopenia, frailty, and related healthspan outcomes in older adults, compared with placebo, and how should recent randomized evidence be interpreted for efficacy, safety, and remaining uncertainty in longevity research?",
                "search_summary": "Recent randomized evidence and reviews were examined.",
                "landscape": "A 2025 RCT is investigating physical performance outcomes [1].",
                "findings": "A 2025 RCT is investigating effects on sarcopenia and frailty [1].",
                "limitations": "Many studies, including the ongoing RCT on sarcopenia [1], remain difficult to compare directly.",
                "gaps_identified": "More long-duration trials are needed.",
                "conclusion": "The 2025 RCT is evaluating aging outcomes [1].",
            },
            {},
        )


def test_classify_directness_marks_aging_rct_direct():
    item = {
        "title": "Metformin and aging in older adults: randomized controlled trial",
        "excerpt": "Older adults receiving metformin had aging biomarker outcomes assessed.",
        "evidence_type": "primary",
        "year": 2024,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "aging"])
    assert directness == "direct"


def test_classify_directness_marks_oncology_review_indirect():
    item = {
        "title": "Hyperinsulinemia in obesity, inflammation, and cancer",
        "excerpt": "Review discussing inflammation, aging, and cancer pathways without metformin intervention trials.",
        "evidence_type": "review",
        "year": 2021,
        "source_type": "openalex",
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "longevity"])
    assert directness == "indirect"


def test_classify_directness_marks_chembl_mechanistic():
    item = {
        "title": "Everolimus mechanism of action",
        "excerpt": "mTOR inhibitor mechanism in oncology indications.",
        "evidence_type": "mechanism",
        "source_type": "chembl",
        "year": 2025,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["everolimus", "aging"])
    assert directness == "mechanistic"


def test_classify_directness_marks_protocol_indirect():
    item = {
        "title": "Metformin and longevity: protocol for a randomized trial in older adults",
        "excerpt": "Rationale and study design for healthy aging outcomes.",
        "evidence_type": "primary",
        "year": 2024,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "longevity"])
    assert directness == "indirect"


def test_classify_directness_marks_registry_only_trial_indirect():
    item = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional clinical trial in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": False,
        "trial_status": "registered",
        "year": 2024,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "frailty"])
    assert directness == "indirect"


def test_drafter_separates_reported_findings_from_registry_only_trials():
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin and physical performance in older people with frailty",
        "excerpt": "Older adults improved frailty scores.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
        "extraction": {
            "found": True,
            "primary_outcome": "frailty index",
            "population": "older adults",
            "intervention": "metformin",
            "comparator": "placebo",
            "methods_summary": "double-blind randomized trial",
            "effects": [{"outcome": "frailty index", "metric": "MEAN", "value": "Metformin=-0.1; Placebo=0.0", "source_span": "Frailty index at 2 years: Metformin=-0.1; Placebo=0.0"}],
            "extractor_version": "ctgov-results-v1",
        },
    }
    registered = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": False,
        "trial_status": "registered",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[published, registered],
        all_evidence=[published, registered],
    )
    assert not artifact.get("error")
    assert "=== REGISTERED / NOT YET REPORTED" in provider.user_prompt
    assert "=== PUBLISHED RESULTS" in provider.user_prompt
    assert "For registered or protocol studies, describe only the study design or aim" in provider.system_prompt


def test_drafter_prioritizes_direct_published_results_in_prompt() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    direct_1 = {
        "title": "Metformin and physical performance in older adults with frailty",
        "excerpt": "Randomized trial in older adults.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/101/",
    }
    direct_2 = {
        "title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People",
        "excerpt": "Interventional trial in insulin resistant older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2023,
        "url": "https://clinicaltrials.gov/study/NCT03733132",
    }
    direct_3 = {
        "title": "Metformin administration improves adverse outcomes in older adult burn patients",
        "excerpt": "Cohort study of metformin in older adults.",
        "evidence_type": "observational",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/102/",
    }
    indirect_review = {
        "title": "Pain and aging: A unique challenge in neuroinflammation and behavior",
        "excerpt": "Review in aging adults without metformin in the title.",
        "evidence_type": "review",
        "source_type": "openalex",
        "year": 2023,
        "url": "https://doi.org/10.1/pain",
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[indirect_review, direct_1, direct_2, direct_3],
        all_evidence=[indirect_review, direct_1, direct_2, direct_3],
    )
    assert not artifact.get("error")
    assert "KEY FINDINGS PRIORITY: focus mainly on direct published-results citations [1], [2]." in provider.user_prompt
    assert provider.user_prompt.find(direct_1["title"]) < provider.user_prompt.find(indirect_review["title"])
    assert provider.user_prompt.find(direct_2["title"]) < provider.user_prompt.find(indirect_review["title"])
    assert provider.user_prompt.find(direct_3["title"]) < provider.user_prompt.find(indirect_review["title"])


def test_drafter_sanitizes_registry_only_outcome_claims_and_adds_numeric_fallback():
    provider = BadRegistryProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin and physical performance in older people with frailty",
        "excerpt": "Older adults improved frailty scores.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
        "extraction": {
            "found": True,
            "primary_outcome": "frailty index",
            "population": "older adults",
            "intervention": "metformin",
            "comparator": "placebo",
            "methods_summary": "double-blind randomized trial",
            "effects": [{"outcome": "frailty index", "metric": "MEAN", "value": "-0.1 vs 0.0", "p_value": "0.04", "n": "Metformin N=58; Placebo N=67", "source_span": "Frailty index at 2 years: -0.1 vs 0.0; p=0.04"}],
            "extractor_version": "ctgov-results-v1",
        },
    }
    registered = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": False,
        "trial_status": "registered",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[published, registered],
        all_evidence=[published, registered],
    )
    findings = artifact["sections"]["Key Findings"]
    assert "Registered trial [2] showed" not in findings
    assert "Registered studies [2] describe study design only" in findings
    assert "MEAN -0.1 vs 0.0" in findings
    assert "p=0.04" in findings


def test_drafter_repairs_design_language_on_published_results() -> None:
    provider = BadPublishedResultsProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin and physical performance in older people with probable sarcopenia and frailty",
        "excerpt": "Randomized placebo-controlled trial in older adults with frailty outcomes.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
    }
    meta = {
        "title": "Evaluation of glucose-lowering medications in older people: meta-analysis",
        "excerpt": "Meta-analysis in older adults with aging outcomes.",
        "evidence_type": "review",
        "source_type": "pubmed",
        "year": 2024,
        "url": "https://pubmed.ncbi.nlm.nih.gov/39137064/",
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[published, meta],
        all_evidence=[published, meta],
    )
    assert not artifact.get("error")
    assert "is investigating" not in artifact["sections"]["Key Findings"].lower()
    assert "ongoing rct" not in artifact["sections"]["Limitations"].lower()
    assert "is evaluating" not in artifact["sections"]["Conclusion"].lower()
    assert "evaluated" in artifact["sections"]["Key Findings"].lower()
    assert not any(v["severity"] == "high" for v in validate_citations(artifact, artifact["source_bundle"]))


def test_bundle_entry_appends_effect_source_span_to_excerpt():
    entry = _bundle_entry(
        {
            "title": "Metformin and frailty outcomes",
            "excerpt": "Older adults completed a randomized trial.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "extraction": {
                "effects": [
                    {
                        "outcome": "frailty index",
                        "metric": "MEAN",
                        "value": "-0.1 vs 0.0",
                        "source_span": "Frailty index at 2 years: -0.1 vs 0.0; p=0.04",
                    }
                ]
            },
        },
        ["metformin", "frailty"],
        "longevity",
    )
    assert "Older adults completed a randomized trial." in entry["excerpt"]
    assert "Frailty index at 2 years: -0.1 vs 0.0; p=0.04" in entry["excerpt"]


def test_bundle_entry_keeps_numeric_result_sentence_from_later_in_excerpt():
    entry = _bundle_entry(
        {
            "title": "Semaglutide and cardiovascular outcomes",
            "excerpt": (
                "Semaglutide was studied in adults with obesity and cardiovascular disease. "
                "Background details and eligibility criteria were described extensively for the study cohort. "
                "Treatment reduced major adverse cardiovascular events by 20% (HR 0.80, 95% CI 0.72-0.90) over 39.8 months."
            ),
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2024,
        },
        ["semaglutide", "cardiovascular"],
        "metabolic",
    )
    assert "20% (HR 0.80, 95% CI 0.72-0.90)" in entry["excerpt"]
    assert "39.8 months" in entry["excerpt"]


def test_quality_gate_fires_on_classifier_generated_indirect_only_bundle():
    topic_tokens = ["everolimus", "aging"]
    items = [
        {
            "title": f"Everolimus oncology review {i}",
            "excerpt": "Cancer outcomes and transplant immunosuppression without healthy aging endpoints.",
            "evidence_type": "review" if i % 2 == 0 else "primary",
            "year": 2024,
            "source_type": "openalex",
            "doi": f"10.1/onco{i}",
        }
        for i in range(8)
    ]
    bundle = [_bundle_entry(item, topic_tokens, "longevity") for item in items]
    artifact = {
        "title": "Rapid Evidence Synthesis: everolimus",
        "domain_slug": "longevity",
        "source_bundle": bundle,
    }
    assert _quality_gate(artifact, current_year=2026, topic="everolimus aging") == "indirect_only_bundle"


def test_drafter_strips_unsupported_numeric_claims():
    provider = UnsupportedNumericProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Semaglutide trial in obesity",
        "excerpt": "Adults with obesity were treated with semaglutide. The trial reported improved weight outcomes and gastrointestinal adverse events.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
    }
    companion = {
        **published,
        "title": "Companion semaglutide obesity outcomes paper",
        "url": "https://pubmed.ncbi.nlm.nih.gov/2/",
    }
    artifact, _ = drafter.draft(
        topic="semaglutide weight loss",
        domain_slug="metabolic",
        criteria="2020 onwards RCTs",
        queries=["semaglutide obesity trial"],
        evidence=[published, companion],
        all_evidence=[published, companion],
    )
    findings = artifact["sections"]["Key Findings"]
    conclusion = artifact["sections"]["Conclusion"]
    assert "-15.8%" not in findings
    assert "86.4%" not in findings
    assert "-15.8%" not in conclusion
