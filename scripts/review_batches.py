"""Bound review input without truncating cited source evidence."""
from __future__ import annotations

import json
from typing import Any, Callable

MAX_REVIEW_CHARS = 300_000
MAX_SINGLE_PROSE_CHARS = 360_000
MAX_STATEMENTS = 16


def _shared_context(value: Any, path: tuple[str, ...] = (), seen: dict[str, tuple[str, ...]] | None = None) -> Any:
    """Reference exact duplicate author records; retain their first complete copy."""
    seen = {} if seen is None else seen
    signature = json.dumps(value, sort_keys=True, ensure_ascii=False)
    if len(signature) > 256 and (previous := seen.setdefault(signature, path)) != path:
        return {"review_reference": list(previous)}
    if isinstance(value, dict):
        if len(value) > 1 and all(isinstance(row, dict) for row in value.values()):
            if field := next((key for key in next(iter(value.values())) if all(row.get(key) == identity for identity, row in value.items())), None):
                value = {"review_key_field": field, "review_records": list(value.values())}
        return {key: _shared_context(item, (*path, key), seen) for key, item in value.items()}
    if isinstance(value, list):
        return [_shared_context(item, (*path, str(i)), seen) for i, item in enumerate(value)]
    return value


def bounded_batches(items: list[Any], render: Callable[[list[Any]], str], *, overhead: int = 0, max_items: int = 1000, single_limit: int = MAX_REVIEW_CHARS) -> list[tuple[list[Any], str]]:
    batches: list[tuple[list[Any], str]] = []
    for item in items:
        single = render([item])
        if len(single) + overhead > single_limit:
            raise ValueError("review_input_exceeds_budget: indivisible evidence; no provider request sent")
        candidate = [*batches[-1][0], item] if batches else [item]
        content = render(candidate)
        if batches and len(content) + overhead <= min(MAX_REVIEW_CHARS, single_limit) and len(candidate) <= max_items:
            batches[-1] = (candidate, content)
        else:
            batches.append(([item], single))
    return batches


def _sources_for(statements: list[dict[str, Any]], sources: Any) -> Any:
    if isinstance(sources, list) and not any("receipt_ids" in row for row in statements):
        return sources
    if not isinstance(sources, dict) or "bundle" not in sources:
        receipts = sources if isinstance(sources, list) else sources.get("receipts", [])
        ids = {rid for row in statements for rid in row.get("receipt_ids", [])}
        selected = [row for row in receipts if row.get("receipt_id") in ids]
        if ids != {row.get("receipt_id") for row in selected} or len(selected) != len(ids):
            raise ValueError("review_source_citation_mismatch")
        return selected if isinstance(sources, list) else {**sources, "receipts": selected,
            "author_context": _shared_context(sources.get("author_context", {}))}
    bundle = sources["bundle"]
    indexes = sorted({index for row in statements for index in row.get("sources", [])})
    if any(type(i) is not int or i < 0 or i >= len(bundle) for i in indexes):
        raise ValueError("review_source_index_invalid")
    own = [r for r in sources.get("own_results", []) if r.get("citation_token") in {bundle[i].get("cited_as") for i in indexes}]
    if len(own) != len(indexes):
        raise ValueError("review_source_citation_mismatch")
    from agent.revision_claim_trace import _sentences
    from journal_finalizer import _findings_map_roster_sentence, _manifest_direction_heterogeneity_note
    accounting = set(map(str.strip, _sentences("Outcome-class roster: " + _findings_map_roster_sentence(sources.get("own_results", [])) + "\n" + _manifest_direction_heterogeneity_note(sources.get("own_results", [])))))
    if statements and all(row.get("text", "").strip() in accounting for row in statements):
        own = [{k: v for k, v in row.items() if k not in {"verified_source_sections", "verified_source_tables", "verified_abstract"}} for row in own]
    return {"bundle": [{**bundle[i], "source_index": i} for i in indexes], "own_results": _shared_context(own),
            "author_context": _shared_context(sources.get("author_context", {})),
            "source_catalog": [{key: row.get(key) for key in ("cited_as", "title", "evidence_type", "directness", "outcome_class", "effect_direction")} for row in bundle]}


def _prose_units(statements: list[dict[str, Any]], prompt: str,
                 render: Callable[[list[dict[str, Any]]], str]) -> list[tuple[int, dict[str, Any]]]:
    order = sorted(range(len(statements)), key=lambda i: json.dumps([statements[i].get("sources", []), statements[i].get("receipt_ids", [])]))
    units: list[tuple[int, dict[str, Any]]] = []
    for index in order:
        row = statements[index]
        if len(render([row])) + len(prompt) <= MAX_SINGLE_PROSE_CHARS:
            units.append((index, row))
            continue
        key = "sources" if row.get("sources") else "receipt_ids" if row.get("receipt_ids") else None
        if key is None or row.get("sources") and row.get("receipt_ids"):
            raise ValueError("review_input_exceeds_budget: indivisible evidence; no provider request sent")
        refs = list(dict.fromkeys(row[key]))
        def fits(group: list[Any]) -> bool:
            marked = {**row, key: group, "source_partition": {"part": len(refs), "total": len(refs)}}
            return len(render([marked])) + len(prompt) <= MAX_SINGLE_PROSE_CHARS
        groups: list[list[Any]] = []
        for ref in refs:
            candidate = [*groups[-1], ref] if groups else [ref]
            if fits(candidate):
                if groups:
                    groups[-1] = candidate
                else:
                    groups.append(candidate)
            elif fits([ref]):
                groups.append([ref])
            else:
                raise ValueError("review_input_exceeds_budget: indivisible evidence; no provider request sent")
        if len(groups) < 2 or [ref for group in groups for ref in group] != refs:
            raise ValueError("review_input_exceeds_budget: incomplete source partition")
        units.extend((index, {**row, key: group, "source_partition": {"part": part, "total": len(groups)}})
                     for part, group in enumerate(groups, 1))
    return units


async def review_prose(statements: list[dict[str, Any]], sources: Any, *, prompt: str, call: Any, validate: Any, **options: Any) -> dict[str, Any]:
    def render(rows: list[dict[str, Any]]) -> str:
        return json.dumps({"statements": [{**entry, "row": i} for i, entry in enumerate(rows)],
                           "sources": _sources_for(rows, sources)}, ensure_ascii=False, separators=(",", ":"))
    units = _prose_units(statements, prompt, render)
    batches = bounded_batches(list(range(len(units))), lambda ids: render([units[i][1] for i in ids]), overhead=len(prompt), max_items=MAX_STATEMENTS,
                              single_limit=MAX_SINGLE_PROSE_CHARS)
    part_reviews: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(statements))}
    models: list[str] = []
    for unit_indexes, content in batches:
        rows = [units[i][1] for i in unit_indexes]
        response = await call(messages=[{"role": "system", "content": prompt}, {"role": "user", "content": content}],
            chain=options["chain"], temperature=0.0,
            validate=lambda parsed: validate(rows, parsed.get("assessments")),
            **{key: value for key, value in options.items() if key in {"client", "ledger", "seed"}})
        validate(rows, response.parsed.get("assessments"))
        for item in response.parsed["assessments"]:
            original, unit = units[unit_indexes[item["row"]]]
            part_reviews[original].append({**item, "row": original,
                                           "source_partition": unit.get("source_partition")})
        models.append(response.model)
    assessments = [{"row": index, "supported": bool(parts) and all(part["supported"] for part in parts),
                    "reason": "; ".join(part["reason"] for part in parts)}
                   for index, parts in part_reviews.items()]
    validate(statements, assessments)
    return {"model": ",".join(dict.fromkeys(models)), "assessments": assessments, "statements": statements,
            "batches": [{"rows": [units[i][0] for i in indexes], "input_chars": len(content) + len(prompt)} for indexes, content in batches],
            "source_partition_reviews": [part for parts in part_reviews.values() for part in parts if part["source_partition"]]}


def revision_inputs(paper: str, asks: list[str], rows: list[dict[str, Any]], payload: dict[str, Any], system: str, template: str) -> list[tuple[list[int], str]]:
    catalog = [{k: v for k, v in row.items() if k not in {"verified_source_sections", "verified_source_tables", "verified_abstract", "source_result_excerpts", "thesis_text"}} for row in rows]
    if rows and any(not b.get("cited_as") or b["cited_as"] not in {r.get("citation_token") for r in rows} for b in payload.get("source_bundle", [])):
        raise ValueError("review_source_citation_mismatch")
    outgoing = {**payload, **({"body_markdown": {"review_reference": "MANUSCRIPT"}} if payload.get("body_markdown") == paper else {})}
    def render(batch: list[dict[str, Any]], indexes: list[int]) -> str:
        citations = {r.get("citation_token") for r in batch}
        fields = {**outgoing, **({"source_bundle": [b for b in payload["source_bundle"] if b.get("cited_as") in citations]} if rows and "source_bundle" in payload else {})}
        for key in ("abstract", "summary"):
            if isinstance(fields.get(key), str) and fields[key] and fields[key] in paper:
                fields[key] = {"review_reference": f"MANUSCRIPT {key}"}
        if isinstance(fields.get("sections"), dict):
            fields["sections"] = {heading: {"review_reference": f"MANUSCRIPT section {heading}"} if isinstance(body, str) and body and body in paper else body for heading, body in fields["sections"].items()}
        if "source_bundle" in fields:
            fields["source_bundle"] = [{k: {"review_reference": "this source's excerpt"} if k == "evidence_span" and isinstance(v, str) and v and v == source.get("excerpt") else v for k, v in source.items()} for source in fields["source_bundle"]]
        return template.format(n=len(indexes), asks="\n".join(f"{i}. {asks[index]}" for i, index in enumerate(indexes, 1)), paper=paper,
            evidence=json.dumps(_shared_context({"source_catalog": catalog, "batch": batch}), ensure_ascii=False, separators=(",", ":")),
            payload=json.dumps(_shared_context(fields), ensure_ascii=False, separators=(",", ":")))
    # Every ask is checked against every source; group compatible ask subsets so
    # a large correction does not get repeated alongside the entire corpus.
    groups: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for row in rows or [{}]:
        for indexes, _ in bounded_batches(list(range(len(asks))), lambda ids: render([row], ids), overhead=len(system)):
            groups.setdefault(tuple(indexes), []).append(row)
    return [(list(indexes), content) for indexes, source_rows in groups.items()
            for _, content in bounded_batches(source_rows, lambda batch: render(batch, list(indexes)), overhead=len(system))]
