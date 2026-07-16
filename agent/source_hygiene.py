"""Deterministic source-record hygiene shared by synthesis and submission."""
from __future__ import annotations

import re


_NOTICE_TITLE_RE = re.compile(
    r"^\s*(?:"
    r"retracted(?:\s+article)?\s*:|"
    r"retraction(?:\s+(?:note|notice))?(?:\s+of\b|\s*:)|"
    r"(?:author\s+|publisher\s+)?correction(?:\s+to\b|\s*:)|"
    r"corrigendum(?:\s+to\b|\s*:)|"
    r"erratum(?:\s+(?:in|to)\b|\s*:)|"
    r"expression\s+of\s+concern(?:\s+regarding\b|\s*:)"
    r")",
    re.IGNORECASE,
)


def is_notice_only_source_title(title: object) -> bool:
    """True for publication notices, not original research about correction."""
    return bool(_NOTICE_TITLE_RE.search(str(title or "")))
