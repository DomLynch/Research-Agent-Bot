"""Phase 5 SVG forest plot renderer.

Stdlib-only (no matplotlib). Consumes `agent.meta_analysis.EffectRow`
sequence + `PoolResult` and emits a deterministic standalone SVG forest
plot suitable for inclusion in the paper supplement.

Layout (left → right):
  | study label | square + CI bar | numeric effect (CI) |

The pooled diamond is rendered in the bottom row spanning its CI.

Validation:
  - rows must be non-empty and pass `assert_poolable` (n≥3, single metric,
    positive finite SE).
  - pool.metric must match the rows' shared metric.
  - all values must be finite.
"""
from __future__ import annotations

from collections.abc import Sequence
from xml.sax.saxutils import escape as _xml_escape

from agent.meta_analysis import EffectRow, PoolResult, assert_poolable

__all__ = [
    "render_forest_plot_svg",
    "DEFAULT_WIDTH",
    "DEFAULT_ROW_HEIGHT",
]

DEFAULT_WIDTH: int = 720
DEFAULT_ROW_HEIGHT: int = 28
_LABEL_MARGIN: int = 200  # left margin for study labels
_RIGHT_MARGIN: int = 160  # right margin for "effect (CI lo, CI hi)" text
_TOP_MARGIN: int = 36
_BOTTOM_MARGIN: int = 28
_DIAMOND_HEIGHT: int = 14
_HEADER_HEIGHT: int = 24
_NULL_LINE: float = 0.0  # x-axis null reference (MD=0; log_RR=log_OR=0 => RR/OR=1)


def _z(ci_level: float) -> float:
    """Two-tailed z critical value approximated from the pool's ci_level.
    Reuses NormalDist via the meta_analysis module's helper indirectly by
    referencing common values; here we approximate to avoid a second import."""
    # Common z values (ci_level: z):
    #   0.80: 1.282, 0.90: 1.645, 0.95: 1.960, 0.99: 2.576.
    # Simpler/safer: compute via NormalDist.
    from statistics import NormalDist  # local import keeps top tidy
    return NormalDist().inv_cdf(1.0 - (1.0 - ci_level) / 2.0)


def _ci_bounds(point: float, se: float, z: float) -> tuple[float, float]:
    return point - z * se, point + z * se


def _ascii_safe(value: float) -> str:
    """Render a float with 3 decimal places; trim trailing zeros for compact SVG."""
    s = f"{value:.3f}"
    return s


def _format_effect_label(effect: float, ci_lo: float, ci_hi: float) -> str:
    return f"{_ascii_safe(effect)} ({_ascii_safe(ci_lo)}, {_ascii_safe(ci_hi)})"


def _scale_x(value: float, x_min: float, x_max: float, plot_x0: int, plot_x1: int) -> float:
    """Linear map from data x to pixel x within the plot region."""
    if x_max == x_min:
        return (plot_x0 + plot_x1) / 2.0
    return plot_x0 + (value - x_min) * (plot_x1 - plot_x0) / (x_max - x_min)


def _validate_inputs(rows: Sequence[EffectRow], pool: PoolResult) -> None:
    """Run cross-validation on rows + pool."""
    assert_poolable(rows)  # raises on <3, mixed metrics, bad SE
    metrics = {r.metric for r in rows}
    if pool.metric not in metrics:
        raise ValueError(
            f"pool.metric {pool.metric!r} does not match rows' metric "
            f"{sorted(metrics)!r}"
        )


def _build_axis_bounds(
    rows: Sequence[EffectRow], pool: PoolResult, z: float
) -> tuple[float, float]:
    """Compute x-axis bounds from per-study CIs + pooled CI + null line."""
    los: list[float] = [r.effect - z * r.se for r in rows]
    his: list[float] = [r.effect + z * r.se for r in rows]
    los.append(pool.ci_lower)
    his.append(pool.ci_upper)
    los.append(_NULL_LINE)
    his.append(_NULL_LINE)
    x_min = min(los)
    x_max = max(his)
    if x_max == x_min:
        # degenerate — pad symmetrically so SVG still renders
        x_min -= 1.0
        x_max += 1.0
    pad = 0.05 * (x_max - x_min)
    return x_min - pad, x_max + pad


def _svg_text(x: float, y: float, content: str, *, anchor: str = "start", size: int = 11) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="sans-serif" '
        f'font-size="{size}" text-anchor="{anchor}">{_xml_escape(content)}</text>'
    )


def _svg_line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = "black", width: float = 1.0) -> str:
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="{width}"/>'
    )


def _svg_rect(x: float, y: float, w: float, h: float, *, fill: str = "black") -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"/>'


def _svg_diamond(cx: float, cy: float, hw: float, hh: float, *, fill: str = "black") -> str:
    pts = f"{cx - hw:.1f},{cy:.1f} {cx:.1f},{cy - hh:.1f} {cx + hw:.1f},{cy:.1f} {cx:.1f},{cy + hh:.1f}"
    return f'<polygon points="{pts}" fill="{fill}"/>'


def render_forest_plot_svg(
    rows: Sequence[EffectRow],
    pool: PoolResult,
    *,
    title: str | None = None,
    width: int = DEFAULT_WIDTH,
    row_height: int = DEFAULT_ROW_HEIGHT,
) -> str:
    """Render a deterministic standalone SVG forest plot."""
    _validate_inputs(rows, pool)
    z = _z(pool.ci_level)
    x_min, x_max = _build_axis_bounds(rows, pool, z)

    n = len(rows)
    height = (
        _TOP_MARGIN + _HEADER_HEIGHT + n * row_height
        + row_height + _DIAMOND_HEIGHT + _BOTTOM_MARGIN
    )
    plot_x0 = _LABEL_MARGIN
    plot_x1 = width - _RIGHT_MARGIN

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
    )
    if title:
        parts.append(_svg_text(width / 2, 18, title, anchor="middle", size=14))

    # Header
    header_y = _TOP_MARGIN + 14
    parts.append(_svg_text(8, header_y, "Study", size=11))
    parts.append(_svg_text(plot_x0 + 4, header_y, f"Effect ({pool.metric})", size=11))
    parts.append(_svg_text(width - 8, header_y, "Estimate (CI)", anchor="end", size=11))

    # Null reference line
    null_x = _scale_x(_NULL_LINE, x_min, x_max, plot_x0, plot_x1)
    null_y0 = _TOP_MARGIN + _HEADER_HEIGHT
    null_y1 = null_y0 + n * row_height + row_height + _DIAMOND_HEIGHT
    parts.append(_svg_line(null_x, null_y0, null_x, null_y1, stroke="#888", width=0.6))

    # Per-study rows
    for i, row in enumerate(rows):
        ci_lo, ci_hi = _ci_bounds(row.effect, row.se, z)
        row_y = _TOP_MARGIN + _HEADER_HEIGHT + i * row_height + row_height / 2
        parts.append(_svg_text(8, row_y + 4, row.study_id, size=11))
        x_lo = _scale_x(ci_lo, x_min, x_max, plot_x0, plot_x1)
        x_hi = _scale_x(ci_hi, x_min, x_max, plot_x0, plot_x1)
        x_pt = _scale_x(row.effect, x_min, x_max, plot_x0, plot_x1)
        parts.append(_svg_line(x_lo, row_y, x_hi, row_y))
        sq = 6.0
        parts.append(_svg_rect(x_pt - sq / 2, row_y - sq / 2, sq, sq))
        parts.append(_svg_text(
            width - 8, row_y + 4,
            _format_effect_label(row.effect, ci_lo, ci_hi),
            anchor="end", size=11,
        ))

    # Pooled diamond
    diamond_y = (
        _TOP_MARGIN + _HEADER_HEIGHT + n * row_height + row_height / 2
    )
    px_lo = _scale_x(pool.ci_lower, x_min, x_max, plot_x0, plot_x1)
    px_hi = _scale_x(pool.ci_upper, x_min, x_max, plot_x0, plot_x1)
    cx = (px_lo + px_hi) / 2.0
    hw = max(2.0, (px_hi - px_lo) / 2.0)
    parts.append(_svg_diamond(cx, diamond_y, hw, _DIAMOND_HEIGHT / 2.0))
    pool_label = (
        f"Pooled ({pool.method.replace('_', '-')}, k={pool.n_studies})"
    )
    parts.append(_svg_text(8, diamond_y + 4, pool_label, size=11))
    parts.append(_svg_text(
        width - 8, diamond_y + 4,
        _format_effect_label(pool.pooled_effect, pool.ci_lower, pool.ci_upper),
        anchor="end", size=11,
    ))

    # Heterogeneity caption
    caption_y = diamond_y + _DIAMOND_HEIGHT
    caption = (
        f"Heterogeneity: Q={pool.q:.2f}, df={pool.df}, I^2={pool.i_squared:.1f}%, "
        f"tau^2={pool.tau_squared:.4f}"
    )
    parts.append(_svg_text(8, caption_y + 14, caption, size=10))

    parts.append("</svg>")
    return "\n".join(parts)
