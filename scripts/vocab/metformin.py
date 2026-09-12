"""Metformin/aging vocab pack — domain-specific endpoints + polarity.

Curated for the Phase 1.5 → Phase 6.3 metformin corpus (Walton/Konopka/
Witham/Mohammed/Keys/Kulkarni + 9 OA contributors). Schema:

  ENDPOINT_VOCAB: tuple[(canonical_name, regex_pattern), ...]
    Order matters — longer/more-specific patterns FIRST.
  ENDPOINT_TO_OUTCOME_CLASS: dict[canonical_name, outcome_class]
    Maps each endpoint to the SynthesisSchemas OutcomeClass literal.
  ENDPOINT_POLARITY: dict[canonical_name, +1|-1]
    +1 = "increase = better" (lifespan, walk speed); -1 = "decrease
    = better" (mortality, HbA1c). Used by the v0.6 effect_direction
    aggregator.
"""
from __future__ import annotations


ENDPOINT_VOCAB: tuple[tuple[str, str], ...] = (
    # Cardio / aerobic
    ("VO2max", r"\bVO\s*2\s*max\b|\bVO₂\s*max\b|peak\s+oxygen\s+(?:consumption|uptake)|aerobic\s+capacity"),
    ("walk speed", r"\b(?:4-?\s*m|six-?minute)\s+walk(?:\s+(?:speed|distance|test))?\b|gait\s+speed\b"),
    ("cognitive function", r"\bcognitive (?:function|performance)|\binhibitory control\b|\bperceptual processing\b|\bworking memory\b"),
    ("muscle power", r"\b(?:peak )?muscle power\b"),
    ("fat mass", r"\b(?:body )?fat mass\b"),
    # Body composition
    ("thigh muscle mass", r"\bthigh\s+muscle\s+(?:mass|size|area|volume|cross-?sectional\s+area)|thigh\s+CSA"),
    ("lean body mass", r"\blean\s+(?:body\s+)?mass\b|fat-?free\s+mass\b|\bFFM\b"),
    ("muscle hypertrophy", r"\bhypertroph(?:y|ic\s+response)|muscle\s+gain"),
    ("muscle strength", r"\b(?:muscle\s+|grip\s+|leg\s+|knee\s+|handgrip\s+)?strength\b|\b1[\s-]*RM\b|one[\s-]?rep(?:etition)?\s*max(?:imum)?"),
    ("body weight", r"\bbody\s+weight\b|\bweight\s+(?:loss|gain|change)\b"),
    ("body mass index", r"\bbody\s+mass\s+index\b|\bBMI\b"),
    # Glucose / insulin
    ("HbA1c", r"\bHbA1c\b|glycated\s+h(?:a|ae)moglobin|hemoglobin\s+A1c|\bA1c\b"),
    ("insulin sensitivity", r"\binsulin\s+sensitivit(?:y|ies)\b|\bHOMA-?IR\b|insulin\s+action|insulin\s+resistance"),
    ("fasting glucose", r"\bfasting\s+(?:plasma\s+)?glucose\b|FPG\b"),
    ("blood glucose", r"\bblood\s+glucose\b|plasma\s+glucose\b|24-?h(?:r|our)?\s+glucose"),
    # Mitochondrial / cellular
    ("mitochondrial respiration", r"mitochondrial\s+respiration|mitochondrial\s+function|oxygen\s+consumption\s+rate|\bOCR\b"),
    ("AMPK signaling", r"\bAMPK\b|AMP-?activated\s+protein\s+kinase"),
    ("mTOR signaling", r"\bmTORC?[12]?\b|mammalian\s+target\s+of\s+rapamycin|S6K1\b|p70S6K"),
    ("protein synthesis", r"\bprotein\s+synthesis\b|fractional\s+synthesis\s+rate"),
    # Aging-specific
    ("frailty", r"\bfrailt(?:y|ies)\b|frail\s+(?:index|status)|frailty\s+phenotype"),
    ("sarcopenia", r"\bsarcopeni(?:a|c)\b|muscle\s+wasting"),
    ("mortality", r"\b(?:all-?cause\s+)?mortality\b|risk\s+(?:reduction|of\s+death)"
                  r"|death\s+rate|risk\s+of\s+(?:diabetes-?related\s+events|major\s+events|"
                  r"cardiovascular\s+events|cancer-?related\s+events)"
                  r"|reduced\s+the\s+risk\s+of"),
    ("lifespan", r"\blifespan\b|life\s+span|\bmedian\s+survival\b|\bmaximum\s+life\s+span\b"),
    ("healthspan", r"\bhealthspan\b|health\s+span|disease-?free\s+years"),
    # Inflammation / biomarkers
    ("inflammation", r"\binflammat(?:ion|ory)\b|\bIL-?6\b|\bTNF-?[αα]?\b|\bCRP\b|\bhsCRP\b"),
    ("oxidative stress", r"\boxidative\s+stress\b|reactive\s+oxygen\s+species|\bROS\b"),
    ("vaccine response", r"\bvaccine\s+response\b|response\s+to\s+(?:the\s+)?(?:influenza\s+)?vaccine|"
                         r"\bvaccination\s+response\b|\bimmunosenescence\b|immune\s+response"),
    # Common clinical
    ("blood pressure", r"\bblood\s+pressure\b|systolic\s+BP|diastolic\s+BP|\bSBP\b|\bDBP\b"),
    ("cardiorespiratory fitness", r"cardiorespiratory\s+fitness|\bCRF\b"),
)


ENDPOINT_TO_OUTCOME_CLASS: dict[str, str] = {
    "cognitive function": "cognitive", "muscle power": "muscle_function", "fat mass": "cardiometabolic",
    "VO2max": "muscle_function",
    "thigh muscle mass": "muscle_function",
    "lean body mass": "muscle_function",
    "muscle hypertrophy": "muscle_function",
    "muscle strength": "muscle_function",
    "protein synthesis": "muscle_function",
    "cardiorespiratory fitness": "muscle_function",
    "walk speed": "frailty",
    "frailty": "frailty",
    "sarcopenia": "frailty",
    "mortality": "longevity",
    "lifespan": "longevity",
    "healthspan": "longevity",
    "HbA1c": "cardiometabolic",
    "insulin sensitivity": "cardiometabolic",
    "fasting glucose": "cardiometabolic",
    "blood glucose": "cardiometabolic",
    "body weight": "cardiometabolic",
    "body mass index": "cardiometabolic",
    "AMPK signaling": "cardiometabolic",
    "mTOR signaling": "cardiometabolic",
    "mitochondrial respiration": "cardiometabolic",
    "blood pressure": "cardiometabolic",
    "inflammation": "immune",
    "oxidative stress": "immune",
    "vaccine response": "immune",
}


ENDPOINT_POLARITY: dict[str, int] = {
    "cognitive function": +1, "muscle power": +1, "fat mass": -1,
    # higher = better
    "VO2max": +1, "thigh muscle mass": +1, "lean body mass": +1,
    "muscle hypertrophy": +1, "muscle strength": +1, "lifespan": +1,
    "healthspan": +1, "insulin sensitivity": +1, "AMPK signaling": +1,
    "mitochondrial respiration": +1, "protein synthesis": +1,
    "cardiorespiratory fitness": +1, "walk speed": +1,
    "vaccine response": +1,
    # lower = better
    "mortality": -1, "frailty": -1, "sarcopenia": -1, "HbA1c": -1,
    "fasting glucose": -1, "blood glucose": -1, "body weight": -1,
    "body mass index": -1, "inflammation": -1, "oxidative stress": -1,
    "blood pressure": -1, "mTOR signaling": -1,
}


# Reviewer-fix MEDIUM 2: ARM_VOCAB is per-domain because the
# active-arm bare keywords differ ("metformin"/"placebo" here vs
# "rapamycin"/"sirolimus" in the rapamycin pack). Pre-fix the bare
# fallbacks lived only in quant_endpoints.py and rapamycin runs
# couldn't bind arm → no high-confidence claims for rapamycin
# papers.
ARM_VOCAB: tuple[tuple[str, str], ...] = (
    # Modified-noun forms (most specific).
    ("metformin", r"\bmetformin\s+(?:group|arm|treatment|cohort)|\bmetformin-?treated"),
    ("placebo", r"\bplacebo\s+(?:group|arm|cohort|control)|\bplacebo-?treated"),
    ("control", r"\bcontrol\s+(?:group|arm|cohort|subjects?)\b"),
    ("treatment", r"\btreatment\s+(?:group|arm|cohort)\b|\bactive\s+treatment\b"),
    ("pooled", r"\bpooled\b|combined\s+groups?|both\s+(?:groups|arms)|across\s+groups"),
    # Bare keyword fallbacks (lower confidence) — kept LAST.
    ("metformin", r"\bmetformin\b"),
    ("placebo", r"\bplacebo\b"),
)
