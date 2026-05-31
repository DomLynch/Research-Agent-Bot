from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import revision_coverage  # type: ignore[import-not-found]  # noqa: E402


def _chat(parsed: dict[str, Any]) -> Any:
    async def fake(**_kwargs: Any) -> Any:
        return type("Resp", (), {"parsed": parsed})()
    return fake


def _unmet(asks: list[str], parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unmet_asks("MANUSCRIPT BODY", asks, chat=_chat(parsed), settings=object())


def test_unmet_asks_empty_when_all_addressed(monkeypatch) -> None:
    assert _unmet(["a", "b"], {"addressed": [True, True]}, monkeypatch) == []


def test_unmet_asks_flags_unaddressed_in_order(monkeypatch) -> None:
    assert _unmet(["hedge claims", "clarify scope"], {"addressed": [True, False]}, monkeypatch) == ["clarify scope"]


def test_unmet_asks_failopen_on_malformed_verdict(monkeypatch) -> None:
    # Length mismatch / wrong shape must not block submit.
    assert _unmet(["a", "b"], {"addressed": [True]}, monkeypatch) == []
    assert _unmet(["a"], {"addressed": "nope"}, monkeypatch) == []


def test_unmet_asks_empty_for_no_asks(monkeypatch) -> None:
    assert _unmet([], {"addressed": []}, monkeypatch) == []


def test_unmet_asks_failopen_on_judge_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unmet_asks("M", ["a"], chat=boom, settings=object()) == []


_PAPER = "## Abstract\n\nEGCG reverses aging in humans.\n\n## Results\n\nMixed, mostly null.\n"


def _claims(parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unsupported_abstract_claims(_PAPER, chat=_chat(parsed), settings=object())


def test_unsupported_abstract_claims_flags_overclaim(monkeypatch) -> None:
    assert _claims({"unsupported": ["EGCG reverses aging in humans."]}, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_ignores_neutral_profile_summaries(monkeypatch) -> None:
    parsed = {
        "unsupported": [
            "The evidence profile contains no sources classified primarily as mechanistic evidence.",
            "Positive study-level signals concentrate in no dominant outcome class.",
            "positive signals concentrated in contextual cardioprotection, negative signals in cardiometabolic domains",
            "EGCG reverses aging in humans.",
        ],
    }
    assert _claims(parsed, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_empty_when_supported(monkeypatch) -> None:
    assert _claims({"unsupported": []}, monkeypatch) == []


def test_unsupported_abstract_claims_no_abstract_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    assert revision_coverage.unsupported_abstract_claims("## Results\n\nx\n", chat=_chat({"unsupported": ["x"]}), settings=object()) == []


def test_unsupported_abstract_claims_failopen_on_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unsupported_abstract_claims(_PAPER, chat=boom, settings=object()) == []
