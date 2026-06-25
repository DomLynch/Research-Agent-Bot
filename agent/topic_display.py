from __future__ import annotations

import re
import tomllib
from pathlib import Path

_TOKEN_DISPLAY = {
    "ampk": "AMPK",
    "glp1": "GLP-1",
    "hba1c": "HbA1c",
    "hrv": "HRV",
    "mri": "MRI",
    "mtor": "mTOR",
    "mtorc1": "mTORC1",
    "mtorc2": "mTORC2",
    "nad": "NAD+",
    "nmn": "NMN",
    "nr": "NR",
    "sglt2": "SGLT2",
    "vo2max": "VO2max",
}


def humanize_topic(topic: str, *, title_case: bool = False, root: Path | None = None) -> str:
    raw = str(topic or "").strip()
    if not raw:
        return "Research Synthesis" if title_case else "the topic"
    if root is not None:
        alias = _topic_pack_alias(raw, root)
        if alias:
            return alias
    words = [_display_token(token, title_case=title_case) for token in re.split(r"[_\s-]+", raw) if token]
    return " ".join(words) or ("Research Synthesis" if title_case else "the topic")


def intervention_label(
    topic: str, *, title_case: bool = False, root: Path | None = None,
) -> str:
    """The intervention / compound ENTITY ('resveratrol', 'vitamin d',
    'NAD+') — distinct from the humanized topic PHRASE (`humanize_topic`,
    used for the title).

    The slug doubles as both the title-phrase and, wrongly, the compound
    noun in prose ('the candidate compound Resveratrol Metabolism
    Effects'). This returns the compound NAME: the leading slug token plus
    any trailing compound DESIGNATORS (short suffixes like 'a'/'d', or
    alphanumerics with a digit like 'q10'), dropping full-word ASPECT
    tokens (e.g. 'metabolism'/'effects' in biomed, 'efficiency'/'pricing'
    in other domains). So 'resveratrol_metabolism_effects' → 'resveratrol',
    but 'urolithin_a' → 'urolithin a' and 'coenzyme_q10' → 'coenzyme q10'.
    Token-shape based, universal — no aspect-word list, no per-topic table. `root` is
    accepted for call-site parity with `humanize_topic`."""
    raw = str(topic or "").strip()
    if not raw:
        return "the intervention"
    tokens = _compound_name_tokens(raw)
    rendered = [_display_token(t, title_case=title_case) for t in tokens]
    return " ".join(rendered) or "the intervention"


def _compound_name_tokens(raw: str) -> list[str]:
    """Leading token + trailing compound designators (≤2 chars, or
    contains a digit). The first full-word token after the head is an
    aspect, not part of the compound name, and ends the run."""
    tokens = [t for t in re.split(r"[_\s-]+", raw) if t]
    if not tokens:
        return []
    out = [tokens[0]]
    for tok in tokens[1:]:
        if len(tok) <= 2 or any(c.isdigit() for c in tok):
            out.append(tok)
        else:
            break
    return out


def _topic_pack_alias(topic: str, root: Path) -> str:
    pack_path = root / "topic_packs" / f"{topic}.toml"
    if not pack_path.exists():
        return ""
    try:
        pack = tomllib.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    aliases = pack.get("aliases")
    for alias in aliases if isinstance(aliases, list) else ():
        if isinstance(alias, str) and _looks_public_alias(alias):
            return _humanize_alias(alias)
    return ""


def _looks_public_alias(alias: str) -> bool:
    clean = alias.strip()
    if not clean:
        return False
    if "-" in clean or " " in clean:
        return True
    return bool(re.search(r"[A-Za-z0-9]", clean))


def _display_token(token: str, *, title_case: bool) -> str:
    key = re.sub(r"[^a-z0-9]", "", token.lower())
    if key in _TOKEN_DISPLAY:
        return _TOKEN_DISPLAY[key]
    return token[:1].upper() + token[1:] if title_case else token.lower()


def _humanize_alias(alias: str) -> str:
    words = []
    for token in alias.split():
        key = re.sub(r"[^a-z0-9]", "", token.lower())
        words.append(_TOKEN_DISPLAY.get(key, token))
    text = " ".join(words).strip()
    return text[:1].upper() + text[1:] if text else ""
