from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from app.storage.in_memory_store import ChunkRecord
from app.storage.postgres_store import PostgresRetrievalStore, to_psycopg_dsn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Import retrieval seed chunks JSONL into Postgres doc_chunks.')
    parser.add_argument('--dsn', required=True, help='Postgres DSN, e.g. postgresql://user:pass@host:5432/db')
    parser.add_argument('--jsonl', required=True, help='Path to retrieval_seed_chunks.jsonl')
    parser.add_argument('--vector-dim', type=int, default=64)
    parser.add_argument('--rrf-k', type=int, default=60)
    parser.add_argument('--ensure-tenants', action='store_true')
    return parser.parse_args()


def _safe_str(value: object) -> str:
    if value is None:
        return ''
    return str(value).strip()


def load_chunks(path: Path) -> list[ChunkRecord]:
    rows: list[ChunkRecord] = []
    with path.open('r', encoding='utf-8') as handle:
        for line_num, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                continue

            tenant_id = _safe_str(payload.get('tenant_id'))
            section = _safe_str(payload.get('section')) or 'general'
            chunk_id = _safe_str(payload.get('chunk_id'))
            doc_id = _safe_str(payload.get('doc_id')) or 'external_playbook'
            source = _safe_str(payload.get('source')) or 'external'
            updated_at = _safe_str(payload.get('updated_at'))
            text = _safe_str(payload.get('text'))

            if not (tenant_id and chunk_id and updated_at and text):
                raise ValueError(f'Invalid JSONL row at line {line_num}: missing required fields.')

            rows.append(
                ChunkRecord(
                    tenant_id=tenant_id,
                    section=section,
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    source=source,
                    updated_at=updated_at,
                    text=text,
                )
            )
    return rows


def ensure_tenants(dsn: str, chunks: list[ChunkRecord]) -> int:
    tenant_rows = sorted({(row.tenant_id, row.tenant_id.replace('_', ' ').title()) for row in chunks})
    if not tenant_rows:
        return 0

    with psycopg.connect(to_psycopg_dsn(dsn)) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO tenants (tenant_id, name, status)
                VALUES (%s, %s, 'active')
                ON CONFLICT (tenant_id) DO UPDATE
                SET name = EXCLUDED.name;
                """,
                tenant_rows,
            )
        conn.commit()
    return len(tenant_rows)


def main() -> None:
    args = parse_args()
    path = Path(args.jsonl).expanduser()
    if not path.exists():
        raise FileNotFoundError(f'JSONL file not found: {path}')

    chunks = load_chunks(path)
    if not chunks:
        raise ValueError('No valid chunk rows found in JSONL file.')

    store = PostgresRetrievalStore(
        dsn=args.dsn,
        vector_dim=args.vector_dim,
        rrf_k=args.rrf_k,
    )

    if args.ensure_tenants:
        created = ensure_tenants(args.dsn, chunks)
        print(f'Ensured tenant rows: {created}')

    inserted = store.seed_chunks(chunks)
    print(f'Imported retrieval chunks: {inserted}')


if __name__ == '__main__':
    main()
