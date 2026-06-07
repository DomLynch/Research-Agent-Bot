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
            return alias.strip()[:1].upper() + alias.strip()[1:]
    return ""


def _looks_public_alias(alias: str) -> bool:
    clean = alias.strip()
    return bool(clean) and (clean.isupper() or "-" in clean or " " in clean)


def _display_token(token: str, *, title_case: bool) -> str:
    key = token.lower()
    if key in _TOKEN_DISPLAY:
        return _TOKEN_DISPLAY[key]
    return key[:1].upper() + key[1:] if title_case else key
