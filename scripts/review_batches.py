"""Bound review input without truncating cited source evidence."""
from __future__ import annotations

import json
from typing import Any, Callable

MAX_REVIEW_CHARS = 300_000
MAX_STATEMENTS = 16


def _shared_context(value: Any, path: tuple[str, ...] = (), seen: dict[str, tuple[str, ...]] | None = None) -> Any:
    """Reference exact duplicate author records; retain their first complete copy."""
    seen = {} if seen is None else seen
    signature = json.dumps(value, sort_keys=True, ensure_ascii=False)
    if len(signature) > 1024:
        if signature in seen:
            return {"review_reference": list(seen[signature])}
        seen[signature] = path
    if isinstance(value, dict):
        return {key: _shared_context(item, (*path, key), seen) for key, item in value.items()}
    if isinstance(value, list):
        return [_shared_context(item, (*path, str(i)), seen) for i, item in enumerate(value)]
    return value


def bounded_batches(items: list[Any], render: Callable[[list[Any]], str], *, overhead: int = 0, max_items: int = 1000) -> list[tuple[list[Any], str]]:
    batches: list[tuple[list[Any], str]] = []
    for item in items:
        single = render([item])
        if len(single) + overhead > MAX_REVIEW_CHARS:
            raise ValueError("review_input_exceeds_budget: indivisible evidence; no provider request sent")
        candidate = [*batches[-1][0], item] if batches else [item]
        content = render(candidate)
        if batches and len(content) + overhead <= MAX_REVIEW_CHARS and len(candidate) <= max_items:
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
    return {"bundle": [{**bundle[i], "source_index": i} for i in indexes],
            "own_results": own,
            "author_context": _shared_context(sources.get("author_context", {})),
            "source_catalog": [{key: row.get(key) for key in ("cited_as", "title", "evidence_type", "directness", "outcome_class", "effect_direction")} for row in bundle]}


async def review_prose(statements: list[dict[str, Any]], sources: Any, *, prompt: str, call: Any, validate: Any, **options: Any) -> dict[str, Any]:
    def render(indexes: list[int]) -> str:
        rows = [statements[i] for i in indexes]
        return json.dumps({"statements": [{**entry, "row": i} for i, entry in enumerate(rows)],
                           "sources": _sources_for(rows, sources)}, ensure_ascii=False, separators=(",", ":"))
    order = sorted(range(len(statements)), key=lambda i: json.dumps([statements[i].get("sources", []), statements[i].get("receipt_ids", [])]))
    batches = bounded_batches(order, render, overhead=len(prompt), max_items=MAX_STATEMENTS)
    assessments: list[dict[str, Any]] = []
    models: list[str] = []
    for indexes, content in batches:
        rows = [statements[i] for i in indexes]
        response = await call(messages=[{"role": "system", "content": prompt}, {"role": "user", "content": content}],
            chain=options["chain"], temperature=0.0,
            validate=lambda parsed: validate(rows, parsed.get("assessments")),
            **{key: value for key, value in options.items() if key in {"client", "ledger", "seed"}})
        validate(rows, response.parsed.get("assessments"))
        assessments.extend({**item, "row": indexes[item["row"]]} for item in response.parsed["assessments"])
        models.append(response.model)
    validate(statements, assessments)
    return {"model": ",".join(dict.fromkeys(models)), "assessments": assessments, "statements": statements,
            "batches": [{"rows": indexes, "input_chars": len(content) + len(prompt)} for indexes, content in batches]}


def revision_inputs(paper: str, asks: list[str], rows: list[dict[str, Any]], payload: dict[str, Any], system: str, template: str) -> list[str]:
    catalog = [{k: v for k, v in row.items() if k not in {"verified_source_sections", "verified_source_tables", "verified_abstract", "source_result_excerpts", "thesis_text"}} for row in rows]
    if rows and any(not b.get("cited_as") or b["cited_as"] not in {r.get("citation_token") for r in rows} for b in payload.get("source_bundle", [])):
        raise ValueError("review_source_citation_mismatch")
    outgoing = {**payload, **({"body_markdown": {"review_reference": "MANUSCRIPT"}} if payload.get("body_markdown") == paper else {})}
    def render(batch: list[dict[str, Any]]) -> str:
        citations = {r.get("citation_token") for r in batch}
        fields = {**outgoing, **({"source_bundle": [b for b in payload["source_bundle"] if b.get("cited_as") in citations]} if rows and "source_bundle" in payload else {})}
        if isinstance(fields.get("sections"), dict):
            fields["sections"] = {heading: {"review_reference": f"MANUSCRIPT section {heading}"} if isinstance(body, str) and body and body in paper else body for heading, body in fields["sections"].items()}
        if "source_bundle" in fields:
            fields["source_bundle"] = [{k: {"review_reference": "this source's excerpt"} if k == "evidence_span" and isinstance(v, str) and v and v == source.get("excerpt") else v for k, v in source.items()} for source in fields["source_bundle"]]
        return template.format(n=len(asks), asks="\n".join(f"{i}. {ask}" for i, ask in enumerate(asks, 1)), paper=paper,
            evidence=json.dumps({"source_catalog": catalog, "batch": batch}, ensure_ascii=False, separators=(",", ":")),
            payload=json.dumps(fields, ensure_ascii=False, separators=(",", ":")))
    return [content for _, content in bounded_batches(rows or [{}], render, overhead=len(system))]
