"""Rapamycin/sirolimus endpoint vocab for aging-paper qualification.

This source-backed pack replaces the stale bytecode-only rapamycin vocab path
and extends the shared aging/cardiometabolic base with rapamycin-specific
mechanism, immune, safety, and healthspan endpoints.
"""
from __future__ import annotations

from vocab import metformin as _base


_RAPAMYCIN_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("mTOR inhibition", r"\bmTOR(?:C[12])?\s+(?:inhibition|suppression|blockade)\b|\bmTOR\s+inhibitor\b|\binhibitor\s+of\s+(?:the\s+)?mTOR\s+pathway\b"),
    ("S6K1 phosphorylation", r"\bS6K1\s+phosphorylation|p70S6K|ribosomal\s+protein\s+S6|p-?S6\b"),
    ("4E-BP1 phosphorylation", r"\b4E-?BP1\s+phosphorylation"),
    ("autophagy", r"\bautophagy\b|autophagic\s+flux|LC3-?II|p62"),
    ("cellular senescence", r"\bcellular\s+senescence\b|senescent\s+cells|p16\^?Ink4a|p21"),
    ("immunosenescence", r"\bimmunosenescence\b|immune\s+aging|T-?cell\s+(?:exhaust|senescence)"),
    ("influenza vaccine response", r"\binfluenza\s+vaccine\s+(?:response|titer|titre)|hemagglutination\s+inhibition\s+titer"),
    ("pathogen survival", r"\bpost[-\s]?infection\s+survival\b|\bsurvival\s+(?:of\s+)?mice\s+exposed\s+to\s+pathogens?\b|\bpathogen\s+survival\b"),
    ("respiratory infection rate", r"\brespiratory\s+(?:tract\s+)?infection|RTI\s+rate|upper\s+respiratory"),
    ("mucositis", r"\bmucositis\b|stomatitis\b"),
    ("hyperlipidemia", r"\bhyperlipidemia\b|elevated\s+(?:cholesterol|triglycerides)|lipid\s+abnormalities"),
    ("lean tissue mass", r"\blean\s+tissue\s+mass\b"),
    ("visceral adiposity", r"\bvisceral\s+adiposity\b|visceral\s+fat\b"),
    ("blood biomarkers", r"\bblood\s+biomarkers?\b|hematologic(?:al)?\s+(?:markers?|differences?)|blood\s+chemistr(?:y|ies)"),
    ("self-reported pain", r"\bself-?reported\s+pain\b|\bpain\s+score\b"),
    ("emotional well-being", r"\bemotional\s+well-?being\b|psychological\s+well-?being"),
    ("general health", r"\bgeneral\s+health\b|self-?reported\s+health\b"),
    ("liver inflammation", r"\bfatty\s+liver\b|hepatic\s+inflammation|liver\s+inflammation"),
    ("proteome turnover", r"\bproteome\s+(?:turnover|half-?lives?)\b|\bprotein\s+half-?lives?\b"),
    ("renal function", r"\bkidney\s+(?:enlargement|growth|volume)\b|\bcyst\s+volume\s+density\b|\brenal\s+function\b|\bblood\s+urea\s+nitrogen\b|\bBUN\b"),
    ("microbiome composition", r"\bgut\s+microbiome\b|\bmicrobiome\b|\bBacteroides\b|\bMuribaculum\b|\bRuminococcus\b"),
    ("T-cell function", r"\bT-?cell\b|\bCD4\b|\bCD8\b|\bPD-?1\b|\blymphopenia\b"),
    ("senescence-associated secretory phenotype", r"\bsenescence-?associated\s+secretory\s+phenotype\b|\bSASP\b"),
    ("ovarian reserve", r"\bovarian\s+(?:reserve|lifespan|life\s+span|function)\b|\bfollicle\s+(?:activation|reserve|pool)\b"),
    ("cardiac function", r"\bcardiac\s+function\b|\bheart\s+(?:function|dysfunction)\b|\bcardiomyocyte\b"),
    ("motor neuron count", r"\bmotor\s+neurons?\b|\bBBB\s+scores?\b"),
)


ENDPOINT_VOCAB: tuple[tuple[str, str], ...] = (
    _RAPAMYCIN_ENDPOINTS + _base.ENDPOINT_VOCAB
)

ENDPOINT_TO_OUTCOME_CLASS: dict[str, str] = {
    **_base.ENDPOINT_TO_OUTCOME_CLASS,
    "mTOR inhibition": "cardiometabolic",
    "S6K1 phosphorylation": "cardiometabolic",
    "4E-BP1 phosphorylation": "cardiometabolic",
    "autophagy": "longevity",
    "cellular senescence": "immune",
    "immunosenescence": "immune",
    "influenza vaccine response": "immune",
    "pathogen survival": "immune",
    "respiratory infection rate": "immune",
    "mucositis": "safety",
    "hyperlipidemia": "safety",
    "lean tissue mass": "muscle_function",
    "visceral adiposity": "cardiometabolic",
    "blood biomarkers": "cardiometabolic",
    "self-reported pain": "frailty",
    "emotional well-being": "cognitive",
    "general health": "frailty",
    "liver inflammation": "immune",
    "proteome turnover": "mechanism",
    "renal function": "safety",
    "microbiome composition": "immune",
    "T-cell function": "immune",
    "senescence-associated secretory phenotype": "immune",
    "ovarian reserve": "frailty",
    "cardiac function": "cardiometabolic",
    "motor neuron count": "muscle_function",
}

ENDPOINT_POLARITY: dict[str, int] = {
    **_base.ENDPOINT_POLARITY,
    "mTOR inhibition": -1,
    "S6K1 phosphorylation": -1,
    "4E-BP1 phosphorylation": -1,
    "autophagy": +1,
    "cellular senescence": -1,
    "immunosenescence": -1,
    "influenza vaccine response": +1,
    "pathogen survival": +1,
    "respiratory infection rate": -1,
    "mucositis": -1,
    "hyperlipidemia": -1,
    "lean tissue mass": +1,
    "visceral adiposity": -1,
    "blood biomarkers": 0,
    "self-reported pain": -1,
    "emotional well-being": +1,
    "general health": +1,
    "liver inflammation": -1,
    "proteome turnover": +1,
    "renal function": -1,
    "microbiome composition": 0,
    "T-cell function": +1,
    "senescence-associated secretory phenotype": -1,
    "ovarian reserve": +1,
    "cardiac function": +1,
    "motor neuron count": +1,
}

ARM_VOCAB: tuple[tuple[str, str], ...] = (
    ("rapamycin", r"\be?RAPA\s+(?:group|arm|treatment|cohort)|\be?RAPA-?treated"),
    ("rapamycin", r"\bRapa\s+(?:group|arm|treatment|cohort)|\bRapa-?treated"),
    ("rapamycin", r"\bRPM\s+(?:group|arm|treatment|cohort)|\bRPM-?treated"),
    ("rapamycin", r"\bmTOR\s+inhibitor\s+(?:group|arm|treatment|cohort)|\bmTOR\s+inhibitor-?treated"),
    ("rapamycin", r"\brapamycin\s+(?:group|arm|treatment|cohort)|\brapamycin-?treated"),
    ("sirolimus", r"\bsirolimus\s+(?:group|arm|treatment|cohort)|\bsirolimus-?treated"),
    ("Rapamune", r"\bRapamune\s+(?:group|arm|treatment|cohort)|\bRapamune-?treated"),
    ("RAP", r"\bRAP\s+(?:group|arm|treatment|cohort)|\bRAP-?treated"),
    ("rapamycin", r"\b(?:RAD001|RTB101)\s+(?:group|arm|treatment|cohort)|\b(?:RAD001|RTB101)-?treated"),
    ("placebo", r"\bplacebo\s+(?:group|arm|cohort|control)|\bplacebo-?treated"),
    ("control", r"\bcontrol\s+(?:group|arm|cohort|subjects?)\b"),
    ("treatment", r"\btreatment\s+(?:group|arm|cohort)\b|\bactive\s+treatment\b"),
    ("pooled", r"\bpooled\b|combined\s+groups?|both\s+(?:groups|arms)|across\s+groups"),
    ("rapamycin", r"\bmTOR\s+inhibitor\b"),
    ("rapamycin", r"\be?RAPA\b"),
    ("rapamycin", r"\bRapa\b"),
    ("rapamycin", r"\bRPM\b"),
    ("rapamycin", r"\brapamycin\b"),
    ("sirolimus", r"\bsirolimus\b"),
    ("Rapamune", r"\bRapamune\b"),
    ("RAP", r"\bRAP\b"),
    ("rapamycin", r"\b(?:RAD001|RTB101)\b"),
    ("placebo", r"\bplacebo\b"),
)
