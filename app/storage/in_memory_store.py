from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CHUNKS_PATH = 'artifacts/datasets/knowledge_chunks.json'


@dataclass(frozen=True)
class ChunkRecord:
    tenant_id: str
    section: str
    chunk_id: str
    doc_id: str
    source: str
    updated_at: str
    text: str


def _parse_chunk(raw: dict[str, Any]) -> ChunkRecord | None:
    """Safely parse a single chunk dict into a ChunkRecord."""
    try:
        return ChunkRecord(
            tenant_id=str(raw['tenant_id']),
            section=str(raw['section']),
            chunk_id=str(raw['chunk_id']),
            doc_id=str(raw['doc_id']),
            source=str(raw.get('source', 'unknown')),
            updated_at=str(raw.get('updated_at', '')),
            text=str(raw['text']),
        )
    except (KeyError, TypeError) as exc:
        logger.warning('Skipping malformed chunk record: %s — %s', raw, exc)
        return None


def load_chunks(path: str | None = None) -> list[ChunkRecord]:
    """Load knowledge chunks dynamically from a JSON file.

    The file path is resolved in order:
      1. Explicit ``path`` argument
      2. ``KNOWLEDGE_CHUNKS_PATH`` environment variable
      3. Default ``artifacts/datasets/knowledge_chunks.json``

    The JSON file must contain a top-level array of chunk objects, each with
    at minimum: tenant_id, section, chunk_id, doc_id, text.

    Returns an empty list (with a warning) if the file is missing or invalid,
    so retrieval gracefully degrades.
    """
    resolved = path or os.environ.get('KNOWLEDGE_CHUNKS_PATH', '') or _DEFAULT_CHUNKS_PATH
    file_path = Path(resolved).expanduser()
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path

    if not file_path.exists():
        logger.warning(
            'Knowledge chunks file not found at %s — retrieval will have no in-memory fallback data. '
            'Create the file or set KNOWLEDGE_CHUNKS_PATH to point to your chunks JSON.',
            file_path,
        )
        return []

    try:
        with file_path.open('r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error('Failed to load knowledge chunks from %s: %s', file_path, exc)
        return []

    if not isinstance(data, list):
        logger.error('Knowledge chunks file must contain a JSON array, got %s', type(data).__name__)
        return []

    chunks: list[ChunkRecord] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        record = _parse_chunk(raw)
        if record is not None:
            chunks.append(record)

    logger.info('Loaded %d knowledge chunks from %s', len(chunks), file_path)
    return chunks


def reload_chunks(path: str | None = None) -> None:
    """Hot-reload chunks at runtime without restarting the server.

    Updates the module-level ``IN_MEMORY_CHUNKS`` list in place so all
    components that hold a reference to it see the new data immediately.
    """
    global IN_MEMORY_CHUNKS  # noqa: PLW0603
    new_chunks = load_chunks(path)
    IN_MEMORY_CHUNKS.clear()
    IN_MEMORY_CHUNKS.extend(new_chunks)
    logger.info('Hot-reloaded %d knowledge chunks into IN_MEMORY_CHUNKS', len(IN_MEMORY_CHUNKS))


# ---------- Module-level singleton loaded once at import ----------
IN_MEMORY_CHUNKS: list[ChunkRecord] = load_chunks()

