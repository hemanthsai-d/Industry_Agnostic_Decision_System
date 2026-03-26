"""Re-embed all doc_chunks with the configured embedding backend.

When migrating from hash-based embeddings (64-dim) to sentence-transformer
(384-dim) or API embeddings (1536-dim), the vector column needs to be
resized and every row re-embedded.

Steps performed:
  1. Alter the ``embedding`` column to the target dimension.
  2. Re-create the HNSW index for the new dimension.
  3. Stream-read every chunk, re-embed the text, and UPDATE in-place.

Usage:
    # Dry-run (shows stats, no writes):
    .venv/bin/python -m scripts.reindex_embeddings --dry-run

    # Full re-embed using sentence-transformer (384-dim):
    EMBEDDING_BACKEND=sentence-transformer \\
    .venv/bin/python -m scripts.reindex_embeddings

    # Full re-embed using API provider:
    EMBEDDING_BACKEND=api EMBEDDING_API_KEY=sk-... \\
    .venv/bin/python -m scripts.reindex_embeddings --batch-size 50
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from app.utils.embedding import create_embedding_provider, vector_to_pg_literal

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _count_chunks(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM doc_chunks;")
        return cur.fetchone()[0]


def _current_vector_dim(conn: psycopg.Connection) -> int | None:
    """Detect the current vector dimension from the column type."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT atttypmod
            FROM pg_attribute
            WHERE attrelid = 'doc_chunks'::regclass
              AND attname = 'embedding';
        """)
        row = cur.fetchone()
        if row and row[0] > 0:
            return row[0]
    return None


def _resize_column(conn: psycopg.Connection, target_dim: int) -> None:
    """ALTER the embedding column to the target dimension."""
    logger.info('Resizing embedding column to %d dimensions...', target_dim)
    with conn.cursor() as cur:
        # Drop and re-create column with new dimension (pgvector requires this)
        cur.execute("DROP INDEX IF EXISTS idx_doc_chunks_embedding;")
        cur.execute("ALTER TABLE doc_chunks DROP COLUMN embedding;")
        cur.execute(f"ALTER TABLE doc_chunks ADD COLUMN embedding VECTOR({target_dim});")
    conn.commit()
    logger.info('Column resized. HNSW index will be recreated after re-embedding.')


def _recreate_hnsw_index(conn: psycopg.Connection) -> None:
    logger.info('Recreating HNSW index...')
    with conn.cursor() as cur:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding
              ON doc_chunks USING hnsw (embedding vector_cosine_ops);
        """)
    conn.commit()
    logger.info('HNSW index created.')


def main() -> None:
    parser = argparse.ArgumentParser(description='Re-embed doc_chunks with configured backend.')
    parser.add_argument('--dry-run', action='store_true', help='Show stats without modifying data.')
    parser.add_argument('--batch-size', type=int, default=100, help='Rows per batch (default: 100).')
    parser.add_argument(
        '--skip-resize',
        action='store_true',
        help='Skip column resize (use when dimension already matches).',
    )
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)
    provider = create_embedding_provider(
        settings.embedding_backend,
        model_name=settings.embedding_model_name,
        api_url=settings.embedding_api_url,
        api_key=settings.embedding_api_key,
        dim=settings.retrieval_vector_dim,
    )
    target_dim = provider.dim

    logger.info(
        'Embedding backend=%s  target_dim=%d',
        settings.embedding_backend,
        target_dim,
    )

    try:
        conn = psycopg.connect(dsn, row_factory=dict_row)
    except psycopg.OperationalError as exc:
        logger.error('Cannot connect to Postgres: %s', exc)
        sys.exit(1)

    total = _count_chunks(conn)
    current_dim = _current_vector_dim(conn)
    logger.info('Total chunks: %d  current_dim: %s  target_dim: %d', total, current_dim, target_dim)

    if args.dry_run:
        needs_resize = current_dim != target_dim
        logger.info(
            'DRY RUN — would %s column (%s → %d) and re-embed %d chunks.',
            'resize' if needs_resize else 'keep',
            current_dim,
            target_dim,
            total,
        )
        conn.close()
        return

    if total == 0:
        logger.info('No chunks to re-embed.')
        conn.close()
        return

    # Step 1: resize column if needed
    if not args.skip_resize and current_dim != target_dim:
        _resize_column(conn, target_dim)

    # Step 2: re-embed in batches
    logger.info('Re-embedding %d chunks in batches of %d...', total, args.batch_size)
    offset = 0
    updated = 0
    t0 = time.monotonic()

    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, text_content FROM doc_chunks ORDER BY chunk_id LIMIT %s OFFSET %s;",
                (args.batch_size, offset),
            )
            rows = cur.fetchall()

        if not rows:
            break

        with conn.cursor() as cur:
            for row in rows:
                vec = provider.embed(row['text_content'])
                literal = vector_to_pg_literal(vec)
                cur.execute(
                    "UPDATE doc_chunks SET embedding = %s::vector WHERE chunk_id = %s;",
                    (literal, row['chunk_id']),
                )
                updated += 1
        conn.commit()

        elapsed = time.monotonic() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        logger.info('  %d / %d chunks re-embedded  (%.1f chunks/s)', updated, total, rate)
        offset += args.batch_size

    # Step 3: recreate index
    _recreate_hnsw_index(conn)

    elapsed = time.monotonic() - t0
    logger.info('Done. Re-embedded %d chunks in %.1fs.', updated, elapsed)
    conn.close()


if __name__ == '__main__':
    main()
