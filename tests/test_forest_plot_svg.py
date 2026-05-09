"""Tests for the Phase 5 SVG forest plot renderer."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from agent.forest_plot_svg import (
    DEFAULT_ROW_HEIGHT,
    DEFAULT_WIDTH,
    render_forest_plot_svg,
)
from agent.meta_analysis import (
    EffectRow,
    pool_fixed_effect,
    pool_random_effects,
)


def _three_md_rows() -> list[EffectRow]:
    return [
        EffectRow("Moel 2025", 0.10, 0.10, 80, "MD"),
        EffectRow("Stanfield 2026", 0.50, 0.20, 50, "MD"),
        EffectRow("Kell 2026", 0.30, 0.15, 80, "MD"),
    ]


# ---- Output shape ---------------------------------------------------------


def test_svg_starts_with_svg_root_tag() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")


def test_svg_parses_as_valid_xml() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_svg_uses_default_width_when_not_overridden() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    assert f'width="{DEFAULT_WIDTH}"' in svg


def test_svg_height_scales_with_row_count() -> None:
    rows = _three_md_rows() + [EffectRow(f"S{i}", 0.1, 0.1, 50, "MD") for i in range(5)]
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    root = ET.fromstring(svg)
    height = int(root.attrib["height"])
    # 8 rows * row_height + headers + diamond + margins
    assert height >= 8 * DEFAULT_ROW_HEIGHT


# ---- Content -------------------------------------------------------------


def test_svg_includes_each_study_label() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    assert "Moel 2025" in svg
    assert "Stanfield 2026" in svg
    assert "Kell 2026" in svg


def test_svg_includes_pool_metric_in_header() -> None:
    rows = _three_md_rows()
    pool = pool_fixed_effect(rows)
    svg = render_forest_plot_svg(rows, pool)
    assert "Effect (MD)" in svg


def test_svg_includes_pooled_label_with_method_and_k() -> None:
    rows = _three_md_rows()
    pool_fe = pool_fixed_effect(rows)
    svg_fe = render_forest_plot_svg(rows, pool_fe)
    assert "Pooled" in svg_fe
    assert "fixed-effect" in svg_fe
    assert "k=3" in svg_fe
    pool_re = pool_random_effects(rows)
    svg_re = render_forest_plot_svg(rows, pool_re)
    assert "random-effects" in svg_re


def test_svg_includes_heterogeneity_caption() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    assert "Heterogeneity" in svg
    assert "Q=" in svg
    assert "I^2=" in svg
    assert "tau^2=" in svg


def test_svg_includes_title_when_provided() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool, title="Rapamycin: Cardiometabolic")
    assert "Rapamycin: Cardiometabolic" in svg


def test_svg_omits_title_element_when_none() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    # Title is just a text element, but no specific title content
    root = ET.fromstring(svg)
    title_texts = [
        t.text for t in root.findall(".//{http://www.w3.org/2000/svg}text")
        if t.text and "Rapamycin" in t.text
    ]
    assert title_texts == []


# ---- XML escaping --------------------------------------------------------


def test_svg_escapes_special_chars_in_study_labels() -> None:
    rows = [
        EffectRow("Brown <2024> & Johnson", 0.1, 0.1, 50, "MD"),
        EffectRow("Smith \"quote\" 2025", 0.2, 0.1, 50, "MD"),
        EffectRow("Lee & Park 2026", 0.15, 0.1, 50, "MD"),
    ]
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    # Must still parse as XML
    ET.fromstring(svg)
    # Raw < and & must be escaped
    assert "<2024>" not in svg
    assert "&lt;2024&gt;" in svg or "&amp;" in svg


def test_svg_escapes_special_chars_in_title() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool, title="A & B <test>")
    ET.fromstring(svg)  # must parse


# ---- Validation ----------------------------------------------------------


def test_empty_rows_rejected_via_assert_poolable() -> None:
    pool = pool_random_effects(_three_md_rows())
    with pytest.raises(ValueError, match="at least"):
        render_forest_plot_svg([], pool)


def test_two_rows_rejected_via_assert_poolable() -> None:
    rows = _three_md_rows()[:2]
    pool = pool_random_effects(_three_md_rows())
    with pytest.raises(ValueError, match="at least"):
        render_forest_plot_svg(rows, pool)


def test_mixed_metrics_rejected() -> None:
    rows = [
        EffectRow("a", 0.1, 0.1, 50, "MD"),
        EffectRow("b", 0.2, 0.1, 50, "log_RR"),
        EffectRow("c", 0.15, 0.1, 50, "MD"),
    ]
    pool = pool_random_effects(_three_md_rows())
    with pytest.raises(ValueError, match="mixed metrics"):
        render_forest_plot_svg(rows, pool)


def test_pool_metric_must_match_row_metric() -> None:
    md_rows = _three_md_rows()
    rr_rows = [
        EffectRow("a", 0.1, 0.1, 50, "log_RR"),
        EffectRow("b", 0.2, 0.1, 50, "log_RR"),
        EffectRow("c", 0.15, 0.1, 50, "log_RR"),
    ]
    md_pool = pool_random_effects(md_rows)
    with pytest.raises(ValueError, match="does not match"):
        render_forest_plot_svg(rr_rows, md_pool)


# ---- Determinism ---------------------------------------------------------


def test_same_inputs_produce_same_output() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg1 = render_forest_plot_svg(rows, pool)
    svg2 = render_forest_plot_svg(rows, pool)
    assert svg1 == svg2


def test_no_randomness_in_diamond_position() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    # Diamond is a polygon — exactly one polygon element expected
    root = ET.fromstring(svg)
    polygons = root.findall(".//{http://www.w3.org/2000/svg}polygon")
    assert len(polygons) == 1


def test_null_reference_line_drawn() -> None:
    rows = _three_md_rows()
    pool = pool_random_effects(rows)
    svg = render_forest_plot_svg(rows, pool)
    root = ET.fromstring(svg)
    lines = root.findall(".//{http://www.w3.org/2000/svg}line")
    # One null reference line + one CI line per study (3) = at least 4
    assert len(lines) >= 4
