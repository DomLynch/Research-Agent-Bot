"""Rapamycin/sirolimus vocab pack — Phase 7 demonstration that the
domain refactor scales beyond metformin.

Rapamycin's evidence base differs from metformin:
  - Strong preclinical lifespan extension (mice, marmosets)
  - Limited human RCT data (PEARL, Tame-RCT class)
  - mTOR inhibition as primary mechanism
  - Immunosenescence focus (Mannick 2014, MTOR / RTB101 trials)
  - Adverse-event profile distinct (mucositis, hyperlipidemia)

Curated from the well-known rapamycin/aging literature; same schema
shape as metformin pack — drop-in via TOPIC_DOMAIN=rapamycin.
"""
from __future__ import annotations


ENDPOINT_VOCAB: tuple[tuple[str, str], ...] = (
    # mTOR pathway (load-bearing for rapamycin)
    ("mTOR inhibition", r"\bmTOR(?:C[12])?\s+(?:inhibition|suppression|blockade)\b|"
                       r"rapamycin\s+(?:treatment|exposure)|sirolimus"),
    ("S6K1 phosphorylation", r"\bS6K1\s+phosphorylation|p70S6K|ribosomal\s+protein\s+S6"),
    ("4E-BP1 phosphorylation", r"\b4E-?BP1\s+phosphorylation"),
    ("autophagy", r"\bautophagy\b|autophagic\s+flux|LC3-?II|p62"),
    # Lifespan / mortality (well-studied in rapamycin lit)
    ("lifespan", r"\blifespan\b|life\s+span|maximum\s+lifespan|median\s+lifespan"),
    ("mortality", r"\b(?:all-?cause\s+)?mortality\b|hazard\s+of\s+death|risk\s+of\s+death"),
    ("healthspan", r"\bhealthspan\b|health\s+span|disease-?free\s+years"),
    # Immune / immunosenescence (Mannick et al. line of work)
    ("immunosenescence", r"\bimmunosenescence\b|immune\s+aging|T-?cell\s+(?:exhaust|senescence)"),
    ("influenza vaccine response", r"\binfluenza\s+vaccine\s+(?:response|titer|titre)|"
                                    r"hemagglutination\s+inhibition\s+titer"),
    ("respiratory infection rate", r"\brespiratory\s+(?:tract\s+)?infection|RTI\s+rate|"
                                    r"upper\s+respiratory"),
    # Adverse events (distinct rapamycin AE profile)
    ("mucositis", r"\bmucositis\b|stomatitis\b"),
    ("hyperlipidemia", r"\bhyperlipidemia\b|elevated\s+(?:cholesterol|triglycerides)|"
                       r"lipid\s+abnormalities"),
    # Body composition / aging hallmarks
    ("muscle mass", r"\b(?:lean\s+|skeletal\s+)?muscle\s+mass\b|fat-?free\s+mass"),
    ("body weight", r"\bbody\s+weight\b|\bweight\s+(?:loss|gain|change)\b"),
    # Cellular senescence
    ("cellular senescence", r"\bcellular\s+senescence\b|senescent\s+cells|p16\^?Ink4a|p21"),
    ("inflammation", r"\binflammat(?:ion|ory)\b|\bIL-?6\b|\bTNF-?[αα]?\b|\bCRP\b"),
)


ENDPOINT_TO_OUTCOME_CLASS: dict[str, str] = {
    # mTOR pathway → cardiometabolic (no perfect fit; mechanism class)
    "mTOR inhibition": "cardiometabolic",
    "S6K1 phosphorylation": "cardiometabolic",
    "4E-BP1 phosphorylation": "cardiometabolic",
    "autophagy": "cardiometabolic",
    # Longevity-class
    "lifespan": "longevity",
    "mortality": "longevity",
    "healthspan": "longevity",
    # Immune-class
    "immunosenescence": "immune",
    "influenza vaccine response": "immune",
    "respiratory infection rate": "immune",
    "inflammation": "immune",
    "cellular senescence": "immune",
    # Body composition
    "muscle mass": "muscle_function",
    "body weight": "cardiometabolic",
    # Adverse events — placeholder; tagged cardiometabolic for now
    "mucositis": "cardiometabolic",
    "hyperlipidemia": "cardiometabolic",
}


ENDPOINT_POLARITY: dict[str, int] = {
    # Rapamycin's MOA → mTOR inhibition is the GOAL, not an adverse
    # outcome. Direction polarity inverted vs metformin.
    "mTOR inhibition": +1,         # increase = good (drug working)
    "S6K1 phosphorylation": -1,    # decrease = good (mTOR suppressed)
    "4E-BP1 phosphorylation": -1,
    "autophagy": +1,               # increase = good (clearing damage)
    "lifespan": +1,
    "healthspan": +1,
    "mortality": -1,
    # Immune outcomes
    "immunosenescence": -1,        # decrease = good
    "influenza vaccine response": +1,
    "respiratory infection rate": -1,
    "inflammation": -1,
    "cellular senescence": -1,
    # Body composition
    "muscle mass": +1,
    "body weight": -1,             # in obese populations
    # Adverse events
    "mucositis": -1,               # decrease = good (fewer events)
    "hyperlipidemia": -1,
}


# Per-domain ARM_VOCAB — rapamycin / sirolimus are the active-arm
# bare keywords, not metformin. RTB101 is Mannick et al.'s
# rapamycin analog (immunology trials).
ARM_VOCAB: tuple[tuple[str, str], ...] = (
    ("rapamycin", r"\b(?:rapamycin|sirolimus|RTB101)\s+(?:group|arm|treatment|cohort)|"
                  r"\b(?:rapamycin|sirolimus)-?treated"),
    ("placebo", r"\bplacebo\s+(?:group|arm|cohort|control)|\bplacebo-?treated"),
    ("control", r"\bcontrol\s+(?:group|arm|cohort|subjects?)\b"),
    ("treatment", r"\btreatment\s+(?:group|arm|cohort)\b|\bactive\s+treatment\b"),
    ("pooled", r"\bpooled\b|combined\s+groups?|both\s+(?:groups|arms)|across\s+groups"),
    ("rapamycin", r"\b(?:rapamycin|sirolimus|RTB101)\b"),
    ("placebo", r"\bplacebo\b"),
)
