from agent.dashboard import _render_page


def test_render_page_urlencodes_download_filename() -> None:
    html = _render_page(
        form={},
        result={
            "model": "MiniMax-M2.7-highspeed",
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
