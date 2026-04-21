"""Schema validator for gold topic JSON files.

Pure dict-based validation — no library dependencies.
"""
from __future__ import annotations

from typing import Any


ALLOWED_CONCLUSION_DIRECTIONS = {
    "positive",
    "positive_with_caveats",
    "mixed",
    "negative_with_caveats",
    "negative",
    "insufficient_evidence",
}

ALLOWED_FAILURE_MODES = {
    "typo_drift",
    "niche_low_evidence",
    "similar_sounding_different_thing",
    "injection_string",
    "ambiguous_scope",
}

ALLOWED_TIERS = {"adversarial", "breadth"}


def validate_gold_topic(data: dict[str, Any]) -> list[str]:
    """Return list of error messages. Empty list means valid."""
    errors: list[str] = []

    for field in ("topic", "domain", "criteria"):
        if field not in data or not data[field]:
            errors.append(f"Missing or empty required field: {field}")

    if "source_review" not in data or not isinstance(data["source_review"], dict):
        errors.append("Missing or non-dict source_review")
    else:
        sr = data["source_review"]
        for f in ("doi", "title", "year", "journal"):
            if f not in sr or not sr[f]:
                errors.append(f"source_review missing required field: {f}")

    if "included_dois" not in data or not isinstance(data["included_dois"], list):
        errors.append("Missing or non-list included_dois")
    elif len(data["included_dois"]) < 1:
        errors.append("included_dois must have at least 1 entry")

    conclusion_dir = data.get("conclusion_direction", "")
    if conclusion_dir not in ALLOWED_CONCLUSION_DIRECTIONS:
        errors.append(
            f"Invalid conclusion_direction: {conclusion_dir!r}. "
            f"Must be one of {ALLOWED_CONCLUSION_DIRECTIONS}"
        )

    if "limitations" not in data or not isinstance(data["limitations"], list):
        errors.append("Missing or non-list limitations")
    elif len(data["limitations"]) < 1:
        errors.append("limitations must have at least 1 entry")

    if "quantitative_claims" not in data or not isinstance(data["quantitative_claims"], list):
        errors.append("Missing or non-list quantitative_claims")
    elif len(data["quantitative_claims"]) < 1:
        errors.append("quantitative_claims must have at least 1 entry")

    for i, qc in enumerate(data.get("quantitative_claims", [])):
        if not isinstance(qc, dict):
            errors.append(f"quantitative_claims[{i}] is not a dict")
        elif "claim" not in qc or "source_doi" not in qc:
            errors.append(f"quantitative_claims[{i}] missing 'claim' or 'source_doi'")

    if "last_validated" not in data:
        errors.append("Missing last_validated")

    if "curator" not in data or not data["curator"]:
        errors.append("Missing curator")

    return errors


def validate_adversarial(data: dict[str, Any]) -> list[str]:
    """Return list of error messages for adversarial topic."""
    errors: list[str] = []

    if "topic" not in data or not data["topic"]:
        errors.append("Missing or empty topic")
    if "domain" not in data or not data["domain"]:
        errors.append("Missing or empty domain")
    if data.get("tier") not in ALLOWED_TIERS:
        errors.append(f"Invalid tier: {data.get('tier')!r}")
    if data.get("failure_mode") not in ALLOWED_FAILURE_MODES:
        errors.append(f"Invalid failure_mode: {data.get('failure_mode')!r}")
    if "last_validated" not in data:
        errors.append("Missing last_validated")

    return errors


def validate_breadth(data: dict[str, Any]) -> list[str]:
    """Return list of error messages for breadth topic."""
    errors: list[str] = []

    if "topic" not in data or not data["topic"]:
        errors.append("Missing or empty topic")
    if "domain" not in data or not data["domain"]:
        errors.append("Missing or empty domain")
    if data.get("tier") != "breadth":
        errors.append(f"Invalid tier: {data.get('tier')!r} (expected 'breadth')")
    if "last_validated" not in data:
        errors.append("Missing last_validated")

    return errors