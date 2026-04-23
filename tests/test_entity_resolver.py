from agent.entity_resolver import resolve_topic, topic_match_ratio


class ResolverStub:
    def __init__(self, canonical_name: str = "Everolimus", confidence: float = 0.95):
        self.canonical_name = canonical_name
        self.confidence = confidence

    def resolve(self, query: str):
        return {"canonical_name": self.canonical_name, "confidence": self.confidence}


def test_resolve_topic_corrects_common_typo():
    out = resolve_topic("evrolimus", chembl_client=None)
    assert out["canonical_topic"] == "everolimus"
    assert out["did_you_mean"] == "everolimus"
    assert out["blocked"] is False


def test_resolve_topic_uses_chembl_canonical_name():
    out = resolve_topic("everolimus and aging", chembl_client=ResolverStub())
    assert out["canonical_topic"] == "everolimus and aging"
    assert out["canonical_term"] == "everolimus"
    assert out["blocked"] is False


def test_resolve_topic_blocks_unresolved_compound():
    out = resolve_topic("zzzimus", chembl_client=None)
    assert out["entity_type"] == "compound"
    assert out["blocked"] is True
    assert out["resolver_source"] == "unresolved"


def test_topic_match_ratio_uses_canonical_and_aliases():
    entries = [
        {"title": "Everolimus in older adults", "excerpt": ""},
        {"title": "sirolimus aging trial", "excerpt": ""},
        {"title": "melatonin sleep study", "excerpt": ""},
    ]
    ratio = topic_match_ratio(entries, canonical_term="everolimus", aliases=["evrolimus", "sirolimus"])
    assert ratio == 0.667


def test_resolve_topic_keeps_known_compound_identity():
    out = resolve_topic("NAD precursors NMN NR aging", chembl_client=None)
    assert out["blocked"] is False
    assert out["canonical_term"] == "nmn"
    assert out["resolver_source"] == "known_compound"


def test_resolve_topic_combines_glp1_and_omega3_tokens():
    glp = resolve_topic("GLP-1 agonists cardiometabolic outcomes", chembl_client=None)
    omega = resolve_topic("omega-3 EPA DHA cardiovascular outcomes", chembl_client=None)
    assert glp["blocked"] is False
    assert glp["canonical_term"] == "glp1"
    assert omega["blocked"] is False
    assert omega["canonical_term"] == "omega3"


def test_resolve_topic_returns_aliases_and_class_terms_for_longevity_compounds():
    rapa = resolve_topic("rapamycin aging older adults", chembl_client=None)
    met = resolve_topic("metformin aging older adults", chembl_client=None)
    seno = resolve_topic("senolytics aging older adults", chembl_client=None)
    assert "sirolimus" in rapa["aliases"]
    assert "mtor inhibitor" in rapa["class_terms"]
    assert "glucophage" in met["aliases"]
    assert "biguanide" in met["class_terms"]
    assert "dasatinib" in seno["aliases"]
    assert "senolytic" in seno["class_terms"]
