"""File-backed generated topic-pack persistence.

V1 uses immutable JSON records under topic_packs_db/<slug>/vN.json. This keeps
generated packs out of curated TOML files while preserving version lineage.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from agent.topic_pack_generator import GeneratedTopicPack


@dataclass(frozen=True, slots=True)
class TopicPackRecord:
    topic_pack_id: str
    topic_name: str
    slug: str
    version: int
    tier: str
    status: str
    pack_hash: str
    parent_id: str | None
    generated_by: str
    validated_at: str
    candidate_count: int
    pack_data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def pack_hash(pack_data: dict[str, object]) -> str:
    body = json.dumps(pack_data, sort_keys=True, separators=(",", ":"))
    return sha256(body.encode("utf-8")).hexdigest()


def persist_generated_pack(
    pack: GeneratedTopicPack,
    db_dir: str | Path,
    *,
    candidate_count: int,
    generated_by: str = "deterministic-topic-pack-generator-v1",
    parent_id: str | None = None,
) -> TopicPackRecord:
    if pack.validation_errors:
        raise ValueError(f"cannot persist invalid generated pack: {pack.validation_errors}")
    if pack.status != "proceed":
        raise ValueError(f"cannot persist stopped generated pack: {pack.tier}")
    root = Path(db_dir)
    topic_dir = root / pack.slug
    topic_dir.mkdir(parents=True, exist_ok=True)
    version = _next_version(topic_dir)
    pack_data = pack.to_topic_pack_dict()
    digest = pack_hash(pack_data)
    record = TopicPackRecord(
        topic_pack_id=str(uuid5(NAMESPACE_URL, f"researka:{pack.slug}:{version}:{digest}")),
        topic_name=pack.topic,
        slug=pack.slug,
        version=version,
        tier=pack.tier,
        status=pack.status,
        pack_hash=digest,
        parent_id=parent_id,
        generated_by=generated_by,
        validated_at=datetime.now(UTC).isoformat(),
        candidate_count=candidate_count,
        pack_data=pack_data,
    )
    path = topic_dir / f"v{version}.json"
    if path.exists():
        raise FileExistsError(f"topic-pack version already exists: {path}")
    _write_json(path, record.to_dict())
    _write_json(topic_dir / "latest.json", record.to_dict())
    return record


def load_topic_pack_record(path: str | Path) -> TopicPackRecord:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TopicPackRecord(**data)


def _next_version(topic_dir: Path) -> int:
    versions = []
    for path in topic_dir.glob("v*.json"):
        try:
            versions.append(int(path.stem.removeprefix("v")))
        except ValueError:
            continue
    return max(versions, default=0) + 1


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
