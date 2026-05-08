"""Regression tests for public manuscript fallback text."""
from __future__ import annotations

import inspect

from agent import paper_writer


def test_full_paper_fallbacks_do_not_emit_pipeline_error_placeholders() -> None:
    """Fallback sections are allowed, but public manuscripts must not
    leak `_Discussion failed scoped validation._` style internals."""
    src = inspect.getsource(paper_writer)
    assert "failed scoped validation" not in src
    assert "failed validation" not in src
    assert "cannot satisfy the validation contract" not in src
