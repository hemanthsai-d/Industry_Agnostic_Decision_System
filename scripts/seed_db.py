from __future__ import annotations

import argparse
import sys

import psycopg

from app.core.config import get_settings
from app.storage.in_memory_store import IN_MEMORY_CHUNKS
from app.storage.postgres_store import PostgresRetrievalStore, to_psycopg_dsn


def seed_tenants(dsn: str) -> int:
    tenant_rows = sorted({(r.tenant_id, r.tenant_id.replace("_", " ").title()) for r in IN_MEMORY_CHUNKS})
    with psycopg.connect(dsn) as conn:
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


def truncate_seeded_tables(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE doc_chunks RESTART IDENTITY CASCADE;")
            cur.execute("TRUNCATE TABLE tenants RESTART IDENTITY CASCADE;")
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Postgres data")
    parser.add_argument("--reset", action="store_true", help="truncate seed tables before seeding")
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)
    store = PostgresRetrievalStore(
        dsn=settings.postgres_dsn,
        vector_dim=settings.retrieval_vector_dim,
        rrf_k=settings.retrieval_rrf_k,
    )

    try:
        if args.reset:
            truncate_seeded_tables(dsn)
            print("Truncated tenants and doc_chunks.")

        tenant_count = seed_tenants(dsn)
        chunk_count = store.seed_chunks(IN_MEMORY_CHUNKS)
        print(f"Seed complete. Tenants: {tenant_count}, Chunks: {chunk_count}")
    except psycopg.OperationalError as exc:
        print(
            "Database connection failed. Ensure Postgres is running and POSTGRES_DSN is correct.\n"
            f"Details: {exc}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
