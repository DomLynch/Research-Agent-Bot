"""Shared endpoint-level direction normalization and comparison."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import cast

from agent.synthesis_schemas import EffectDirection, TensionKind

_DIRECTIONS = frozenset({"positive", "negative", "null", "mixed", "unclear"})


def endpoint_key(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def endpoint_direction_map(
    raw_directions: object, raw_endpoints: object, aggregate_direction: object,
) -> dict[str, EffectDirection]:
    """Normalize endpoint directions; aggregate fallback is single-endpoint only."""
    pairs = raw_directions.items() if isinstance(raw_directions, Mapping) else (
        raw_directions if isinstance(raw_directions, (list, tuple)) else ()
    )
    mapped: dict[str, EffectDirection] = {}
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        endpoint, direction = pair
        key, value = endpoint_key(endpoint), str(direction).strip().lower()
        if key and value in _DIRECTIONS:
            mapped[key] = cast(EffectDirection, value)
    if mapped:
        return mapped
    values: Iterable[object] = (
        raw_endpoints if isinstance(raw_endpoints, (list, tuple, set, frozenset))
        else (raw_endpoints,) if isinstance(raw_endpoints, str) else ()
    )
    endpoints = {endpoint_key(value) for value in values} - {""}
    direction = str(aggregate_direction).strip().lower()
    if len(endpoints) == 1 and direction in _DIRECTIONS:
        mapped[next(iter(endpoints))] = cast(EffectDirection, direction)
    return mapped


def directional_kind(
    direction_a: EffectDirection, direction_b: EffectDirection,
) -> TensionKind:
    if {direction_a, direction_b} == {"positive", "negative"}:
        return "disagreement"
    if direction_a == "null" and direction_b in {"positive", "negative"}:
        return "null_vs_positive" if direction_b == "positive" else "null_vs_negative"
    if direction_b == "null" and direction_a in {"positive", "negative"}:
        return "null_vs_positive" if direction_a == "positive" else "null_vs_negative"
    if direction_a == direction_b and direction_a in {"positive", "negative"}:
        return "agreement"
    return "orthogonal"
