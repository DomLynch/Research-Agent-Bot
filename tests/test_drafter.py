from agent.drafter import RapidEvidenceDrafter, _bundle_entry, _classify_directness, _entry_result_sentence, _retarget_singular_trial_citations, _trim_singular_mixed_citations
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


class VagueMetaProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                "search_summary": "Recent direct trials and a broad meta-analysis were reviewed.",
                "landscape": "The evidence includes direct trials and broader comparative syntheses.",
                "findings": "Published RCT results provide mixed evidence [1]. A meta-analysis from 2024 synthesized outcomes for metformin and acarbose in older adults [2].",
                "limitations": "The evidence base remains small and underpowered.",
                "gaps_identified": "Long-duration trials remain sparse.",
                "conclusion": "Metformin remains inconclusive for broad healthspan benefit [1,2].",
            },
            {},
        )


class BrokenNumericProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                "search_summary": "Recent direct trials and a broad meta-analysis were reviewed.",
                "landscape": "The evidence includes direct trials and broader comparative syntheses.",
                "findings": "A recent trial found no significant difference in frailty after 2 years (Metformin mean change -0.0002 vs. [1].",
                "limitations": "The evidence base remains small and underpowered.",
                "gaps_identified": "Long-duration trials remain sparse.",
                "conclusion": "Metformin remains inconclusive for broad healthspan benefit [1].",
            },
            {},
        )


class SplitMashupProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                "search_summary": "Recent direct trials and a broad meta-analysis were reviewed.",
                "landscape": "The evidence includes direct trials and broader comparative syntheses.",
                "findings": "A recent trial found no significant difference in frailty after 2 years (mean change: metformin -0.0002 vs. Published results [1] report Frailty Index Based on Deficit Accumulation; MEAN Metformin=-0.0002; Placebo=0.0002.",
                "limitations": "The evidence base remains small and underpowered.",
                "gaps_identified": "Long-duration trials remain sparse.",
                "conclusion": "Metformin remains inconclusive for broad healthspan benefit [1].",
            },
            {},
        )


class MixedSingularCitationProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                "search_summary": "Recent direct and disease-context studies were reviewed.",
                "landscape": "The evidence includes one direct trial and one observational disease-context study.",
                "findings": "One trial in insulin-resistant elderly found no significant benefit of metformin on brain energy metabolism or cognitive function over 10 months [1, 2].",
                "limitations": "The evidence base remains small and underpowered.",
                "gaps_identified": "Long-duration trials remain sparse.",
                "conclusion": "Metformin remains inconclusive for broad healthspan benefit [1, 2].",
            },
            {},
        )


class DuplicateGroundedProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                "search_summary": "Recent direct trials were reviewed.",
                "landscape": "The evidence includes direct trials.",
                "findings": (
                    "Published results [1] report Frailty Index Based on Deficit Accumulation; "
                    "MEAN Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002). "
                    "Published results [1] report Frailty Index Based on Deficit Accumulation; "
                    "MEAN Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002)."
                ),
                "limitations": "The evidence base remains small and underpowered.",
                "gaps_identified": "Long-duration trials remain sparse.",
                "conclusion": "Metformin remains inconclusive for broad healthspan benefit [1].",
            },
            {},
        )


class OffTopicMultiDrugProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of rapamycin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                "search_summary": "Recent direct trials and broad reviews were reviewed.",
                "landscape": "The evidence includes direct trials and broader comparative syntheses.",
                "findings": (
                    "The direct evidence remains limited. "
                    "Published results [1] reported sirolimus improved vaccine responses in older adults. "
                    "Meta-analysis [2] reported everolimus reduced major adverse cardiovascular events."
                ),
                "limitations": "The evidence base remains small and underpowered.",
                "gaps_identified": "Long-duration trials remain sparse.",
                "conclusion": "Rapamycin remains inconclusive for broad healthspan benefit [1,2].",
            },
            {},
        )


class RefinementProvider(CaptureProvider):
    supports_refinement = True

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        if self.calls == 1:
            return (
                {
                    "question": "What are the effects of rapamycin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                    "search_summary": "Recent direct trials and broad reviews were reviewed.",
                    "landscape": "The evidence includes direct trials and broader comparative syntheses.",
                    "findings": "The overall evidence is limited but hypothesis-generating. Published results [1] reported weekly rapamycin did not change visceral adiposity versus placebo [1].",
                    "limitations": "The evidence base remains small and underpowered.",
                    "gaps_identified": "Long-duration trials remain sparse.",
                    "conclusion": "Rapamycin remains inconclusive for broad healthspan benefit [1].",
                    "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                    "estimated_cost_usd": 0.01,
                    "prompt_version": self.prompt_version,
                    "model": self.model,
                },
                {},
            )
        return (
            {
                "abstract": (
                    "The overall evidence is limited but hypothesis-generating. "
                    "The strongest completed older-adult trial found no change in visceral adiposity versus placebo [1]. "
                    "Supporting human disease-context evidence is secondary and should not be treated as core healthspan proof [2]. "
                    "Protocol and mechanistic sources remain hypothesis-generating rather than outcome evidence [3]."
                ),
                "landscape": (
                    "Tier A1 direct aging evidence comes from completed older-adult trials [1]. "
                    "Tier A2 disease-context human evidence remains less generalizable [2]. "
                    "Tier C protocol/mechanistic support frames future questions without outcome claims [3]."
                ),
                "findings": (
                    "The overall evidence is limited but hypothesis-generating. "
                    "Published results [1] reported weekly rapamycin did not change visceral adiposity versus placebo [1]. "
                    "Supporting human evidence from disease-context studies remains secondary [2]. "
                    "No retained study directly addresses integrated healthspan in a general older-adult population."
                ),
                "conclusion": "Rapamycin shows selective signals but no proven broad healthspan benefit in older adults [1].",
                "usage": {"input_tokens": 60, "output_tokens": 40, "total_tokens": 100},
                "estimated_cost_usd": 0.005,
                "prompt_version": self.prompt_version,
                "model": self.model,
            },
            {},
        )


class CitationStrippingRefinementProvider(CaptureProvider):
    supports_refinement = True

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        if self.calls == 1:
            return (
                {
                    "question": "What are the effects of metformin on frailty and cognition outcomes in older adults, compared to placebo, and what does direct and supporting human evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
                    "search_summary": "Direct and supporting studies were reviewed.",
                    "landscape": "Tier A1 evidence comes from direct older-adult trials [1]. Tier B context comes from broader syntheses [2].",
                    "findings": "Published results [1] reported no significant difference in frailty versus placebo [1]. Supporting review evidence remained contextual only [2].",
                    "limitations": "The evidence base remains limited.",
                    "gaps_identified": "Longer trials remain needed.",
                    "conclusion": "Direct trial evidence remains inconclusive for broad geroprotection [1].",
                },
                {},
            )
        return (
            {
                "abstract": "The evidence remains limited.",
                "landscape": "Tier A1 evidence comes from direct older-adult trials. Tier B context comes from broader syntheses.",
                "findings": "Published results reported no significant difference in frailty versus placebo. Supporting review evidence remained contextual only.",
                "conclusion": "Direct trial evidence remains inconclusive for broad geroprotection.",
            },
            {},
        )


class StableRefMappingProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on aging-relevant outcomes in older adults, compared with placebo, and how should direct trials versus supporting human evidence be interpreted for efficacy and uncertainty in longevity research?",
                "search_summary": "Direct trials and supporting human evidence were reviewed.",
                "landscape": "One trial in insulin-resistant older adults found no significant effect on brain energy metabolism or cognitive function [3]. A broad meta-analysis provided supporting context rather than direct proof [4].",
                "findings": "The strongest direct signal remained limited [1].",
                "limitations": "The evidence base remains small and heterogeneous [1].",
                "gaps_identified": "More long-duration trials are needed.",
                "conclusion": "Metformin remains inconclusive for broad geroprotection [1].",
            },
            {},
        )


class BrokenStableRefProvider(CaptureProvider):
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            {
                "question": "What are the effects of metformin on frailty and cognition outcomes in older adults, compared with placebo, and what does the retained evidence imply about efficacy and remaining uncertainty in healthy aging?",
                "search_summary": "Direct trials were reviewed.",
                "landscape": "The evidence base includes recent direct trials [R9].",
                "findings": "Published results remained limited [R9].",
                "limitations": "The evidence base remains small [R9].",
                "gaps_identified": "More long-duration trials are needed.",
                "conclusion": "Metformin remains investigational [R9].",
            },
            {},
        )


class JudgmentProvider(CaptureProvider):
    supports_reranking = True
    supports_labeling = True

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        def _id_for(needle: str) -> int:
            for line in user_prompt.splitlines():
                if f"title={needle}" in line:
                    head = line.split(";", 1)[0]
                    return int(head.split("=", 1)[1])
            return 0
        if self.calls == 1:
            pearl = _id_for("Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results")
            oral = _id_for("Evaluation of off-label rapamycin use on oral health.")
            rapa_ex = _id_for("Exercise and Weekly Sirolimus (Rapamycin) in Older Adults: RAPA-EX-01 Randomised, Double-Blind, Placebo-Controlled Trial.")
            return (
                {
                    "assessments": [
                        {"id": pearl, "relevance_score": 0.95, "bucket": "core"},
                        {"id": oral, "relevance_score": 0.15, "bucket": "drop"},
                        {"id": rapa_ex, "relevance_score": 0.91, "bucket": "core"},
                    ],
                    "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
                    "estimated_cost_usd": 0.003,
                    "prompt_version": self.prompt_version,
                    "model": self.model,
                },
                {},
            )
        if self.calls == 2:
            pearl = _id_for("Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results")
            oral = _id_for("Evaluation of off-label rapamycin use on oral health.")
            rapa_ex = _id_for("Exercise and Weekly Sirolimus (Rapamycin) in Older Adults: RAPA-EX-01 Randomised, Double-Blind, Placebo-Controlled Trial.")
            return (
                {
                    "labels": [
                        {"id": pearl, "role": "published_results", "directness": "direct", "evidence_tier": "Tier A1 direct aging evidence"},
                        {"id": oral, "role": "observational", "directness": "indirect", "evidence_tier": "Tier B supporting human evidence"},
                        {"id": rapa_ex, "role": "published_results", "directness": "direct", "evidence_tier": "Tier A1 direct aging evidence"},
                    ],
                    "usage": {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60},
                    "estimated_cost_usd": 0.003,
                    "prompt_version": self.prompt_version,
                    "model": self.model,
                },
                {},
            )
        return (
            {
                "question": "What are the effects of rapamycin on healthspan outcomes in older adults, compared to placebo, as evaluated in randomized controlled trials with an intervention duration of at least 6 months, and what is the evidence for safety and efficacy in this population?",
                "search_summary": "Recent direct trials and supporting disease-context evidence were reviewed separately.",
                "landscape": "The evidence includes direct older-adult rapamycin trials and narrower disease-context studies.",
                "findings": "Published results [1] and [2] provide the main direct signal on rapamycin in older adults.",
                "limitations": "The evidence remains limited and partly indirect.",
                "gaps_identified": "Long-duration trials are still sparse.",
                "conclusion": "Rapamycin remains investigational for broad healthspan benefit.",
                "usage": {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120},
                "estimated_cost_usd": 0.005,
                "prompt_version": self.prompt_version,
                "model": self.model,
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
    assert "KEY FINDINGS PRIORITY: focus mainly on direct published-results citations [R1], [R2]." in provider.user_prompt
    assert direct_1["title"] in provider.user_prompt
    assert direct_2["title"] in provider.user_prompt
    assert direct_3["title"] in provider.user_prompt
    assert indirect_review["title"] not in provider.user_prompt
    assert "pipeline statistics" in provider.system_prompt
    assert "Key Findings must synthesize across sources" in provider.user_prompt
    assert "evidence receipts" not in artifact["abstract"].lower()
    assert "structured-extraction" not in artifact["abstract"].lower()
    assert artifact["abstract"].startswith("This rapid review evaluates")


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
    assert "mean -0.1 vs 0.0" in findings
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


def test_bundle_entry_prioritizes_structured_result_over_trial_flow_counts():
    entry = _bundle_entry(
        {
            "title": "Metformin and physical performance in older people (MET-PREVENT)",
            "excerpt": (
                "BACKGROUND: Background sentence. METHODS: Methods sentence. "
                "FINDINGS: Between Aug 1, 2021, and Sept 5, 2023, 1373 people were screened, "
                "105 were eligible, and 72 participants were randomly assigned to metformin (n=35) "
                "or placebo (n=37). Mean age was 80.4 years. At 4 months, adjusted treatment effect "
                "0.001 m/s [95% CI -0.06 to 0.06]; p=0.96. "
                "INTERPRETATION: Metformin did not improve 4-m walk speed."
            ),
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
        },
        ["metformin", "aging", "older", "adults", "glucophage"],
        "longevity",
    )
    first_sentence = entry["excerpt"].split(". ", 1)[0]
    assert "adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96" in first_sentence
    assert "1373 people were screened" not in first_sentence


def test_bundle_entry_prefers_primary_result_over_safety_counts_in_structured_pubmed_excerpt():
    entry = _bundle_entry(
        {
            "title": "Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT)",
            "excerpt": (
                "BACKGROUND: Metformin has effects on multiple biological systems relevant to ageing. "
                "METHODS: Participants were randomly assigned to metformin or placebo. "
                "FINDINGS: Between Aug 1, 2021, and Sept 30, 2022, 268 individuals were screened for inclusion in the trial, "
                "and 72 participants were randomly assigned to either metformin (n=36) or placebo (n=36). "
                "Mean age was 80.4 years. Mean 4-m walk speed at 4 months was 0.57 m/s in the metformin group "
                "and 0.58 m/s in the placebo group (adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96). "
                "108 adverse events occurred in 35 participants who received metformin and 77 adverse events occurred in 33 participants "
                "who received placebo, and 12 participants had hospital admissions in the metformin group versus three in the placebo group. "
                "INTERPRETATION: Metformin did not improve 4-m walk speed and was poorly tolerated in this population."
            ),
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
        },
        ["metformin", "aging", "older", "adults", "glucophage"],
        "longevity",
    )
    first_sentence = entry["excerpt"].split(". ", 1)[0]
    assert "Mean 4-m walk speed at 4 months was 0.57 m/s" in first_sentence
    assert "108 adverse events occurred" not in first_sentence


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
        for i in range(12)
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


def test_drafter_drops_vague_meta_analysis_sentence_without_numeric_grounding() -> None:
    provider = VagueMetaProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "extraction": {
            "effects": [
                {
                    "outcome": "Frailty Index Based on Deficit Accumulation",
                    "metric": "MEAN",
                    "value": "Metformin=-0.0002; Placebo=0.0002",
                    "n": "Metformin N=58; Placebo N=67",
                    "source_span": "Frailty Index Based on Deficit Accumulation. 2 years. Metformin=-0.0002; Placebo=0.0002. Metformin N=58; Placebo N=67",
                }
            ]
        },
    }
    meta = {
        "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
        "excerpt": "A broad comparative meta-analysis in older adults without a metformin-specific pooled estimate in the retained excerpt.",
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
    findings = artifact["sections"]["Key Findings"]
    assert "A meta-analysis from 2024 synthesized outcomes" not in findings
    assert "mean metformin -0.0002 vs placebo 0.0002" in findings
    assert "No retained study directly addresses integrated healthspan" in findings


def test_drafter_caps_metformin_longevity_source_bundle_to_twelve() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": f"Metformin outcome study {idx} in older adults",
            "excerpt": "Metformin study in older adults with aging outcomes.",
            "evidence_type": "primary" if idx % 3 == 0 else "observational",
            "source_type": "pubmed",
            "year": 2025 - (idx % 2),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{1000 + idx}/",
        }
        for idx in range(14)
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    assert len(artifact["source_bundle"]) == 12


def test_drafter_drops_remap_and_collapses_med_pmc_duplicate_records() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin for Preventing Frailty in High-risk Older Adults",
            "excerpt": "Older adults received metformin or placebo with frailty outcomes over two years.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2024,
            "url": "https://clinicaltrials.gov/study/NCT02570672",
        },
        {
            "title": "Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial.",
            "excerpt": "Older adults were randomized to metformin or placebo for physical performance outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "authors": ["Witham", "Smith"],
            "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
        },
        {
            "title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging.",
            "excerpt": "A narrative synthesis on metformin, sarcopenia, and longevity in aging.",
            "evidence_type": "primary",
            "source_type": "europepmc",
            "year": 2026,
            "authors": ["Shim", "Yoon"],
            "url": "https://europepmc.org/article/MED/41751275",
        },
        {
            "title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging",
            "excerpt": "Full-text mirror of the same metformin longevity and sarcopenia synthesis.",
            "evidence_type": "primary",
            "source_type": "europepmc",
            "year": 2026,
            "authors": ["Shim", "Yoon"],
            "url": "https://europepmc.org/article/PMC/PMC12938515",
        },
        {
            "title": "REMAP Trial for Optimizing Surgical Outcomes at UPMC",
            "excerpt": "Elective-surgery outcomes trial in adult patients with metformin short-course intervention arms and hospital free days at day 90.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2022,
            "url": "https://clinicaltrials.gov/study/NCT03861767",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    titles = [str(item.get("title", "")).lower() for item in artifact["source_bundle"]]
    assert not any("remap" in title for title in titles)
    assert sum("therapeutic paradox in aging" in title for title in titles) == 1


def test_drafter_assigns_a1_a2_b_tiers_for_metformin_generically() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial.",
            "excerpt": "Randomized placebo-controlled metformin trial in older adults with gait and physical performance outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
        },
        {
            "title": "APOE4-dependent association between metformin use and Alzheimer's disease-related cortical thickness in older adults with type 2 diabetes.",
            "excerpt": "Cross-sectional metformin exposure study in older adults with diabetes and Alzheimer's disease-related cortical thickness outcomes.",
            "evidence_type": "observational",
            "source_type": "europepmc",
            "year": 2026,
            "url": "https://europepmc.org/article/MED/41761644",
        },
        {
            "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials.",
            "excerpt": "A broad multi-drug review of glucose-lowering medications in older adults that includes metformin among several interventions.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/39137064/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    tiers = {item["title"]: item["evidence_tier"] for item in artifact["source_bundle"]}
    assert tiers["Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial."] == "Tier A1 direct aging evidence"
    assert tiers["APOE4-dependent association between metformin use and Alzheimer's disease-related cortical thickness in older adults with type 2 diabetes."] == "Tier A2 disease-context human evidence"
    assert tiers["Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials."] == "Tier B supporting human evidence"


def test_drafter_drops_broad_disease_review_without_longevity_signal() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial.",
            "excerpt": "Randomized placebo-controlled metformin trial in older adults with gait and physical performance outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
        },
        {
            "title": "Antidiabetic Agents as Antioxidant and Anti-Inflammatory Therapies in Neurological and Cardiovascular Diseases.",
            "excerpt": "Neurological disorders and cardiovascular disease share inflammatory pathways, and metformin is discussed among antidiabetic agents.",
            "evidence_type": "review",
            "source_type": "europepmc",
            "year": 2025,
            "url": "https://europepmc.org/article/PMC/PMC12729538",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    titles = [str(item.get("title", "")).lower() for item in artifact["source_bundle"]]
    assert not any("neurological and cardiovascular diseases" in title for title in titles)


def test_bundle_entry_demotes_systems_modeling_to_mechanistic() -> None:
    entry = _bundle_entry(
        {
            "title": "Metformin Regulation of the Liver Circadian Clock and Metabolic Aging: A Systems Modeling Study.",
            "excerpt": "A systems modeling study describing metformin pathway effects on the liver circadian clock and metabolic aging.",
            "evidence_type": "primary",
            "source_type": "europepmc",
            "year": 2026,
            "url": "https://europepmc.org/article/PMC/PMC13027763",
        },
        topic_tokens=["metformin", "aging", "older", "adults"],
        domain_slug="longevity",
    )
    assert entry["role"] == "mechanistic"
    assert entry["directness"] == "mechanistic"
    assert entry["evidence_tier"] == "Tier C protocol/mechanistic support"


def test_bundle_entry_demotes_active_comparator_claims_to_tier_b() -> None:
    entry = _bundle_entry(
        {
            "title": "Real-World Harm Reduction of Metformin Plus DPP4 Inhibitors versus Metformin Plus Sulfonylureas in Older Adults: A Target Trial Emulation Using German Claims Data.",
            "excerpt": "A target trial emulation comparing metformin plus DPP4 inhibitors versus metformin plus sulfonylureas in older adults using German claims data.",
            "evidence_type": "observational",
            "source_type": "europepmc",
            "year": 2025,
            "url": "https://europepmc.org/article/PMC/PMC12254066",
        },
        topic_tokens=["metformin", "aging", "older", "adults"],
        domain_slug="longevity",
    )
    assert entry["evidence_tier"] == "Tier B supporting human evidence"


def test_drafter_drops_procedural_trials_that_mention_older_adults_but_not_longevity_intent() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial.",
            "excerpt": "Randomized placebo-controlled metformin trial in older adults with gait and physical performance outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
        },
        {
            "title": "Metformin for Preventing Frailty in High-risk Older Adults",
            "excerpt": "Older adults receiving metformin had frailty outcomes assessed over two years.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2024,
            "url": "https://clinicaltrials.gov/study/NCT02570672",
        },
        {
            "title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People",
            "excerpt": "Metformin trial in insulin-resistant elderly people with brain-energy outcomes.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2023,
            "url": "https://clinicaltrials.gov/study/NCT03733132",
        },
        {
            "title": "REMAP Trial for Optimizing Surgical Outcomes at UPMC in older adults",
            "excerpt": "Adults aged 65 years and older undergoing elective surgery received short-course metformin, with hospital free days at day 90 and ICU admission after surgery as outcomes.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2022,
            "url": "https://clinicaltrials.gov/study/NCT03861767",
        },
        {
            "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials.",
            "excerpt": "A multi-drug review in older people that includes metformin among glucose-lowering interventions.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/39137064/",
        },
        {
            "title": "Diet and Exercise Plus Metformin to Treat Frailty in Obese Seniors",
            "excerpt": "Registered protocol of metformin plus lifestyle intervention for frailty in obese seniors.",
            "evidence_type": "protocol",
            "source_type": "clinicaltrials",
            "has_results": False,
            "year": 2025,
            "url": "https://clinicaltrials.gov/study/NCT999001",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    titles = [str(item.get("title", "")).lower() for item in artifact["source_bundle"]]
    assert not any("optimizing surgical outcomes at upmc" in title for title in titles)


def test_drafter_drops_contrastive_support_sentence_for_other_intervention() -> None:
    provider = VagueMetaProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "extraction": {
            "effects": [
                {
                    "outcome": "Frailty Index Based on Deficit Accumulation",
                    "metric": "MEAN",
                    "value": "Metformin=-0.0002; Placebo=0.0002",
                    "n": "Metformin N=58; Placebo N=67",
                    "source_span": "Frailty Index Based on Deficit Accumulation. 2 years. Metformin=-0.0002; Placebo=0.0002. Metformin N=58; Placebo N=67",
                }
            ]
        },
    }
    meta = {
        "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
        "excerpt": "GLP-1RAs, not metformin, reduced major adverse cardiovascular events in a broad multi-drug meta-analysis of older adults.",
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
    findings = artifact["sections"]["Key Findings"]
    assert "GLP-1RAs, not metformin" not in findings


def test_drafter_replaces_broken_vs_mashup_with_grounded_result_sentence() -> None:
    provider = BrokenNumericProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "extraction": {
            "effects": [
                {
                    "outcome": "Frailty Index Based on Deficit Accumulation",
                    "metric": "MEAN",
                    "value": "Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002)",
                    "n": "Metformin N=58; Placebo N=67",
                    "source_span": "Frailty Index Based on Deficit Accumulation. 2 years. Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002). Metformin N=58; Placebo N=67",
                }
            ]
        },
    }
    meta = {
        "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
        "excerpt": "Broad comparative review in older adults.",
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
    findings = artifact["sections"]["Key Findings"]
    assert "vs. [1]" not in findings
    assert "Published results [1] report" not in findings
    assert "One trial reported results for Frailty Index Based on Deficit Accumulation" in findings
    assert "[1]" in findings


def test_drafter_drops_split_vs_mashup_prefix_before_grounded_sentence() -> None:
    provider = SplitMashupProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "extraction": {
            "effects": [
                {
                    "outcome": "Frailty Index Based on Deficit Accumulation",
                    "metric": "MEAN",
                    "value": "Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002)",
                    "n": "Metformin N=58; Placebo N=67",
                    "source_span": "Frailty Index Based on Deficit Accumulation. 2 years. Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002). Metformin N=58; Placebo N=67",
                }
            ]
        },
    }
    meta = {
        "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
        "excerpt": "Broad comparative review in older adults.",
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
    findings = artifact["sections"]["Key Findings"]
    assert "mean change: metformin -0.0002 vs." not in findings
    assert "Published results [1] report" not in findings
    assert "One trial reported results for Frailty Index Based on Deficit Accumulation" in findings
    assert "[1]" in findings


def test_drafter_trims_mixed_singular_citation_clusters() -> None:
    published = _bundle_entry(
        {
            "title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People",
            "excerpt": "Insulin-resistant elderly people were randomized to metformin or placebo for brain-energy and cognitive outcomes.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2023,
            "url": "https://clinicaltrials.gov/study/NCT03733132",
        },
        topic_tokens=["metformin", "aging", "older", "adults"],
        domain_slug="longevity",
    )
    observational = _bundle_entry(
        {
            "title": "APOE4-dependent association between metformin use and Alzheimer's disease-related cortical thickness in older adults with type 2 diabetes.",
            "excerpt": "Cross-sectional metformin exposure study in older adults with diabetes and cortical thickness outcomes.",
            "evidence_type": "observational",
            "source_type": "europepmc",
            "year": 2026,
            "url": "https://europepmc.org/article/MED/41761644",
        },
        topic_tokens=["metformin", "aging", "older", "adults"],
        domain_slug="longevity",
    )
    text = "One trial in insulin-resistant elderly found no significant benefit of metformin on brain energy metabolism or cognitive function over 10 months [1, 2]."
    trimmed = _trim_singular_mixed_citations(text, [published, observational])
    assert "[1, 2]" not in trimmed
    assert "[1]" in trimmed


def test_drafter_retargets_singular_trial_sentence_from_observational_ref() -> None:
    published = _bundle_entry(
        {
            "title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People",
            "excerpt": "Insulin-resistant elderly people were randomized to metformin or placebo for brain-energy and cognitive outcomes.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2023,
            "url": "https://clinicaltrials.gov/study/NCT03733132",
        },
        topic_tokens=["metformin", "aging", "older", "adults"],
        domain_slug="longevity",
    )
    observational = _bundle_entry(
        {
            "title": "APOE4-dependent association between metformin use and Alzheimer's disease-related cortical thickness in older adults with type 2 diabetes.",
            "excerpt": "Cross-sectional metformin exposure study in older adults with diabetes and cortical thickness outcomes.",
            "evidence_type": "observational",
            "source_type": "europepmc",
            "year": 2026,
            "url": "https://europepmc.org/article/MED/41761644",
        },
        topic_tokens=["metformin", "aging", "older", "adults"],
        domain_slug="longevity",
    )
    text = "One trial on brain function in insulin-resistant elderly showed no significant benefit of metformin over placebo on brain energy metabolism or cognitive function after 10 months [2]."
    retargeted = _retarget_singular_trial_citations(text, [published, observational])
    assert "[2]" not in retargeted
    assert "[1]" in retargeted


def test_drafter_grounds_from_structured_pubmed_results_excerpt() -> None:
    provider = CaptureProvider()
    provider.response = {
        "question": "What are the effects of metformin on healthspan outcomes in older adults, compared to placebo, and what does recent direct trial evidence imply about efficacy, safety, and remaining uncertainty for healthy aging?",
        "search_summary": "Recent direct trials were reviewed.",
        "landscape": "The evidence includes direct trials.",
        "findings": "A 2025 trial in prefrail older adults found no benefit on physical performance [1].",
        "limitations": "The evidence base remains small and underpowered.",
        "gaps_identified": "Long-duration trials remain sparse.",
        "conclusion": "Metformin remains inconclusive for broad healthspan benefit [1].",
    }
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin and physical performance in older people (MET-PREVENT)",
        "excerpt": (
            "BACKGROUND: Background sentence. METHODS: Methods sentence. "
            "FINDINGS: Mean 4-m walk speed at 4 months was 0.57 m/s in metformin versus 0.58 m/s in placebo "
            "(adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96). "
            "INTERPRETATION: Metformin did not improve 4-m walk speed."
        ),
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
    }
    meta = {
        "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
        "excerpt": "Broad comparative review in older adults.",
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
    assert "0.001 m/s [95% CI -0.06 to 0.06]; p=0.96" in artifact["source_bundle"][0]["excerpt"]
    findings = artifact["sections"]["Key Findings"]
    assert "0.001 m/s [95% CI -0.06 to 0.06]; p=0.96" in findings


def test_drafter_dedupes_repeated_grounded_sentence() -> None:
    provider = DuplicateGroundedProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin for Preventing Frailty in High-risk Older Adults",
        "excerpt": "Interventional study in older adults.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "extraction": {
            "effects": [
                {
                    "outcome": "Frailty Index Based on Deficit Accumulation",
                    "metric": "MEAN",
                    "value": "Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002)",
                    "n": "Metformin N=58; Placebo N=67",
                }
            ]
        },
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[published, {**published, "url": "https://clinicaltrials.gov/study/NCT00000002", "title": "Metformin companion direct trial"}],
        all_evidence=[published, {**published, "url": "https://clinicaltrials.gov/study/NCT00000002", "title": "Metformin companion direct trial"}],
    )
    findings = artifact["sections"]["Key Findings"]
    assert findings.count("Frailty Index Based on Deficit Accumulation") == 1


def test_drafter_topic_claim_fit_guard_is_generic() -> None:
    provider = OffTopicMultiDrugProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Sirolimus and vaccine responses in older adults",
        "excerpt": "Published results: sirolimus improved vaccine responses in older adults.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/501/",
    }
    review = {
        "title": "Evaluation of mTOR inhibitors in older people: systematic review",
        "excerpt": "A multi-intervention review including everolimus and other mTOR inhibitors.",
        "evidence_type": "review",
        "source_type": "pubmed",
        "year": 2024,
        "url": "https://pubmed.ncbi.nlm.nih.gov/502/",
    }
    artifact, _ = drafter.draft(
        topic="rapamycin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["rapamycin aging older adults"],
        evidence=[published, review],
        all_evidence=[published, review],
    )
    findings = artifact["sections"]["Key Findings"].lower()
    assert "everolimus reduced major adverse cardiovascular events" not in findings
    assert "sirolimus improved vaccine responses" in findings


def test_drafter_strengthens_abstract_with_strongest_direct_numeric_result_and_ascii_decimals() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin and physical performance in older people (MET-PREVENT)",
        "excerpt": (
            "BACKGROUND: Background sentence. METHODS: Methods sentence. "
            "FINDINGS: Mean 4-m walk speed at 4 months was 0·57 m/s in metformin versus 0·58 m/s in placebo "
            "(adjusted treatment effect 0·001 m/s [95% CI -0·06 to 0·06]; p=0·96). "
            "INTERPRETATION: Metformin did not improve 4-m walk speed."
        ),
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/",
    }
    companion = {
        "title": "Metformin companion trial in older adults",
        "excerpt": "A smaller metformin trial in older adults reported mixed functional outcomes.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2024,
        "url": "https://pubmed.ncbi.nlm.nih.gov/40147476/",
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[published, companion],
        all_evidence=[published, companion],
    )
    assert "0.001 m/s [95% CI -0.06 to 0.06]; p=0.96" in artifact["abstract"]
    assert "·" not in artifact["abstract"]


def test_drafter_drops_truncated_sentence_from_human_abstract() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    published = {
        "title": "Metformin frailty trial in older adults",
        "excerpt": "Randomized trial in older adults with frailty outcomes.",
        "evidence_type": "interventional",
        "source_type": "clinicaltrials",
        "has_results": True,
        "trial_status": "results",
        "year": 2024,
        "url": "https://clinicaltrials.gov/study/NCT00000001",
        "extraction": {
            "effects": [
                {
                    "outcome": "Frailty Index Based on Deficit Accumulation",
                    "metric": "MEAN",
                    "value": "Metformin=-0.0002 (spread 0.0002); Placebo=0.0002 (spread 0.0002)",
                    "n": "Metformin N=58 vs.",
                }
            ]
        },
    }
    companion = {
        "title": "Metformin companion trial in older adults",
        "excerpt": "A smaller metformin trial in older adults reported mixed functional outcomes.",
        "evidence_type": "primary",
        "source_type": "pubmed",
        "year": 2024,
        "url": "https://pubmed.ncbi.nlm.nih.gov/40147476/",
    }
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=[published, companion],
        all_evidence=[published, companion],
    )
    assert "N=58 vs." not in artifact["abstract"]


def test_drafter_uses_editor_refinement_and_bundle_tiers_generically() -> None:
    provider = RefinementProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results",
            "excerpt": "Weekly rapamycin in older adults did not change visceral adiposity compared with placebo.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40188830/",
        },
        {
            "title": "Efficacy and safety of sirolimus in the treatment of gastrointestinal angiodysplasias.",
            "excerpt": "Sirolimus improved bleeding outcomes in a disease-specific adult cohort.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40656607/",
        },
        {
            "title": "A single-center randomized placebo-controlled study to evaluate once-weekly sirolimus in older adults",
            "excerpt": "Trial protocol in older adults with strength and endurance outcomes.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/39354527/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="rapamycin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["rapamycin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    assert provider.calls == 2
    assert artifact["editor_refinement_applied"] is True
    assert "Tier A1 direct aging evidence" in artifact["sections"]["Evidence Landscape"]
    assert "Tier A2 disease-context human evidence" in artifact["sections"]["Evidence Landscape"]
    assert "Tier C protocol/mechanistic support" in artifact["sections"]["Evidence Landscape"]
    assert "The overall evidence is limited but hypothesis-generating." not in artifact["abstract"]
    tiers = {item["title"]: item["evidence_tier"] for item in artifact["source_bundle"]}
    assert tiers["Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results"] == "Tier A1 direct aging evidence"
    assert tiers["Efficacy and safety of sirolimus in the treatment of gastrointestinal angiodysplasias."] == "Tier A2 disease-context human evidence"
    assert tiers["A single-center randomized placebo-controlled study to evaluate once-weekly sirolimus in older adults"] == "Tier C protocol/mechanistic support"


def test_drafter_preserves_cited_sections_when_editor_strips_citations() -> None:
    provider = CitationStrippingRefinementProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin for Preventing Frailty in High-risk Older Adults",
            "excerpt": "Frailty outcomes in older adults assigned to metformin or placebo over two years.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2024,
            "url": "https://clinicaltrials.gov/study/NCT02570672",
            "extraction": {
                "effects": [
                    {
                        "outcome": "Frailty Index Based on Deficit Accumulation",
                        "metric": "MEAN",
                        "value": "Metformin=-0.0002; Placebo=0.0002",
                        "source_span": "Frailty Index Based on Deficit Accumulation. 2 years. Metformin=-0.0002; Placebo=0.0002.",
                    }
                ]
            },
        },
        {
            "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
            "excerpt": "A broad comparative meta-analysis in older adults that includes metformin among several interventions.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/39137064/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    assert "[" in artifact["sections"]["Evidence Landscape"]
    assert "[" in artifact["sections"]["Key Findings"]
    assert "[" in artifact["sections"]["Conclusion"]


def test_drafter_maps_prompt_local_citations_to_final_bundle_indices() -> None:
    provider = StableRefMappingProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin and physical performance in older adults with frailty",
            "excerpt": "Randomized trial in older adults with frailty outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/101/",
        },
        {
            "title": "Metformin in pre-frail older adults: direct randomized trial",
            "excerpt": "Randomized placebo-controlled trial in pre-frail older adults with aging outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/102/",
        },
        {
            "title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People",
            "excerpt": "Interventional trial in insulin resistant older adults with brain metabolism and cognition outcomes.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2023,
            "url": "https://clinicaltrials.gov/study/NCT03733132",
        },
        {
            "title": "Metformin and APOE4-related cortical thickness in type 2 diabetes",
            "excerpt": "Cross-sectional study of cortical thickness in adults with type 2 diabetes and APOE4.",
            "evidence_type": "observational",
            "source_type": "europepmc",
            "year": 2024,
            "url": "https://europepmc.org/article/MED/400004",
        },
        {
            "title": "Metformin administration improves adverse outcomes in older adult burn patients",
            "excerpt": "Cohort study of metformin in older adults after burn injury with mortality and recovery outcomes.",
            "evidence_type": "observational",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/103/",
        },
        {
            "title": "Metformin and brain aging in older adults with diabetes",
            "excerpt": "Observational disease-context study of diabetes, metformin, and brain aging in older adults.",
            "evidence_type": "observational",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/104/",
        },
        {
            "title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials",
            "excerpt": "A broad comparative meta-analysis in older adults that includes metformin among several interventions.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/39137064/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    landscape = artifact["sections"]["Evidence Landscape"]
    assert "[3]" in landscape
    assert "[6]" in landscape
    assert "[4]" not in landscape
    assert "[R" not in landscape


def test_drafter_fails_closed_on_unresolved_internal_refs() -> None:
    provider = BrokenStableRefProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Metformin and physical performance in older adults with frailty",
            "excerpt": "Randomized trial in older adults with frailty outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/101/",
        },
        {
            "title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People",
            "excerpt": "Interventional trial in insulin resistant older adults with brain metabolism and cognition outcomes.",
            "evidence_type": "interventional",
            "source_type": "clinicaltrials",
            "has_results": True,
            "trial_status": "results",
            "year": 2023,
            "url": "https://clinicaltrials.gov/study/NCT03733132",
        },
    ]
    artifact, _ = drafter.draft(
        topic="metformin aging older adults",
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=["metformin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    assert artifact["error"] == "Internal citation rendering failed for refs: R9."


def test_entry_result_sentence_rejects_fragmentary_claim_sentence() -> None:
    entry = {
        "excerpt": "Along with presenting evidence that rapamycin can be used safely in adults of normal health status, we discovered that about 26% of rapamycin",
        "card": {"intervention": "rapamycin", "outcomes": "oral health"},
        "role": "observational",
    }
    assert _entry_result_sentence(entry) == ""


def test_drafter_prunes_rapamycin_bundle_generically() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results",
            "excerpt": "Weekly rapamycin in older adults did not change visceral adiposity compared with placebo.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40188830/",
        },
        {
            "title": "Rapamycin exerts geroprotective effects in the ageing human immune system",
            "excerpt": "Rapamycin improved resilience against DNA damage in older adults.",
            "evidence_type": "primary",
            "source_type": "rxiv",
            "year": 2025,
            "url": "https://doi.org/10.1101/2025.08.15.670559",
        },
        {
            "title": "Evaluation of off-label rapamycin use on oral health",
            "excerpt": "Off-label rapamycin use in adults with oral health outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/38839644/",
        },
        {
            "title": "A single-center randomized placebo-controlled study to evaluate once-weekly sirolimus in older adults",
            "excerpt": "Sirolimus trial protocol in older adults with strength and endurance outcomes.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/39354527/",
        },
        {
            "title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging",
            "excerpt": "Metformin review unrelated to rapamycin-specific outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2026,
            "url": "https://pubmed.ncbi.nlm.nih.gov/41751275/",
        },
        {
            "title": "Pain and aging: A unique challenge in neuroinflammation and behavior",
            "excerpt": "Aging review without rapamycin-specific evidence.",
            "evidence_type": "review",
            "source_type": "openalex",
            "year": 2023,
            "url": "https://doi.org/10.1177/17448069231203090",
        },
        {
            "title": "Galleria mellonella pathogen infection models",
            "excerpt": "Insect infection model review unrelated to rapamycin in older adults.",
            "evidence_type": "review",
            "source_type": "openalex",
            "year": 2023,
            "url": "https://doi.org/10.1093/femsre/fuad011",
        },
        {
            "title": "Multiplex Apolipoprotein Panel Improves Cardiovascular Event Prediction",
            "excerpt": "PCSK9 inhibitor study with no rapamycin signal.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40995631/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="rapamycin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["rapamycin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    titles = [str(item.get("title", "")).lower() for item in artifact["source_bundle"]]
    assert not any("metformin" in title for title in titles)
    assert not any("pain and aging" in title for title in titles)
    assert not any("galleria" in title for title in titles)
    assert not any("apolipoprotein panel" in title for title in titles)
    direct_titles = [title for title, item in zip(titles, artifact["source_bundle"]) if item.get("directness") == "direct"]
    assert direct_titles
    assert all("rapamycin" in title or "sirolimus" in title for title in direct_titles)


def test_drafter_uses_mimo_reranking_and_labeling_before_prompt_selection() -> None:
    provider = JudgmentProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results",
            "excerpt": "Weekly rapamycin in older adults did not change visceral adiposity compared with placebo.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/40188830/",
        },
        {
            "title": "Evaluation of off-label rapamycin use on oral health.",
            "excerpt": "Off-label rapamycin use in adults with oral health outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/38839644/",
        },
        {
            "title": "Exercise and Weekly Sirolimus (Rapamycin) in Older Adults: RAPA-EX-01 Randomised, Double-Blind, Placebo-Controlled Trial.",
            "excerpt": "Older adults completed a randomized placebo-controlled sirolimus trial with strength and endurance outcomes.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2026,
            "url": "https://pubmed.ncbi.nlm.nih.gov/41985884/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="rapamycin aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["rapamycin aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    assert provider.calls == 3
    assert artifact["rerank_applied"] is True
    assert artifact["labeling_applied"] is True
    assert "Evaluation of off-label rapamycin use on oral health." not in provider.user_prompt
    assert "RAPA-EX-01" in provider.user_prompt
    assert all("oral health" not in item["title"].lower() for item in artifact["source_bundle"])
    rapa_ex = next(item for item in artifact["source_bundle"] if "RAPA-EX-01" in item["title"])
    assert rapa_ex["role"] == "published_results"
    assert rapa_ex["directness"] == "direct"
    assert rapa_ex["evidence_tier"] == "Tier A1 direct aging evidence"


def test_drafter_prunes_senolytic_bundle_generically_as_blind_topic() -> None:
    provider = CaptureProvider()
    drafter = RapidEvidenceDrafter(provider=provider)
    evidence = [
        {
            "title": "Dasatinib plus quercetin improves physical function in older adults",
            "excerpt": "Senolytic intervention in older adults with physical performance outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/501001/",
        },
        {
            "title": "Fisetin senolytic therapy for frailty in aging adults",
            "excerpt": "Fisetin senolytic trial in older adults with frailty outcomes.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/501002/",
        },
        {
            "title": "Senolytics and healthspan: a systematic review",
            "excerpt": "Review of senolytic interventions and healthspan endpoints in human aging.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/501003/",
        },
        {
            "title": "Metformin and longevity review",
            "excerpt": "Metformin evidence in aging without senolytic intervention.",
            "evidence_type": "review",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/501004/",
        },
        {
            "title": "PCSK9 inhibitor therapy and cardiovascular risk",
            "excerpt": "Cardiology study without senolytic relevance.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2025,
            "url": "https://pubmed.ncbi.nlm.nih.gov/501005/",
        },
        {
            "title": "Mouse senescence model in liver fibrosis",
            "excerpt": "Mouse model only, not human clinical evidence.",
            "evidence_type": "primary",
            "source_type": "pubmed",
            "year": 2024,
            "url": "https://pubmed.ncbi.nlm.nih.gov/501006/",
        },
    ]
    artifact, _ = drafter.draft(
        topic="senolytics aging older adults",
        domain_slug="longevity",
        criteria="2023 onwards human studies relevance",
        queries=["senolytics aging older adults"],
        evidence=evidence,
        all_evidence=evidence,
    )
    titles = [str(item.get("title", "")).lower() for item in artifact["source_bundle"]]
    assert any("dasatinib" in title or "fisetin" in title or "senolytics" in title for title in titles)
    assert not any("metformin" in title for title in titles)
    assert not any("pcsk9" in title for title in titles)
    assert not any("mouse" in title for title in titles)
