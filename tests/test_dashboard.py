from agent.dashboard import _render_page


def test_render_page_urlencodes_download_filename() -> None:
    html = _render_page(
        form={},
        result={
            "model": "mimo-v2.5-pro",
            "evidence_selected": 1,
            "evidence_retrieved": 1,
            "source_errors": [],
            "estimated_cost_usd": 0.0,
            "markdown": "# Test\n",
            "markdown_file": "2026-04-20T07-22-41.074975+00-00-test.md",
            "scope_signals": ["year>=2020"],
        },
    )

    assert "/download?file=2026-04-20T07-22-41.074975%2B00-00-test.md" in html


def test_render_page_uses_manual_status_refresh_instead_of_meta_refresh() -> None:
    html = _render_page(
        form={"topic": "metformin", "domain": "longevity", "criteria": "2023 onwards"},
        result={
            "model": "mimo-v2.5-pro",
            "evidence_selected": 12,
            "evidence_retrieved": 15,
            "source_errors": [],
            "estimated_cost_usd": 0.1,
            "markdown": "# Test\n",
            "submission": {
                "submission": {"id": "abc12345xyz"},
                "decision": {"status": "pending", "decision": "pending", "gate_failures": []},
            },
        },
    )

    assert 'http-equiv="refresh"' not in html
    assert '/status/abc12345xyz' in html
    assert "Refresh status" in html
