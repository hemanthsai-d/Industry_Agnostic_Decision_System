from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.models.schemas import EvidenceChunk
from app.storage.in_memory_store import ChunkRecord
from app.utils.embedding import (
    EmbeddingProvider,
    LocalHashEmbeddingProvider,
    create_embedding_provider,
    text_to_embedding,
    vector_to_pg_literal,
)


def to_psycopg_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg://"):
        return dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    return dsn


@dataclass
class PostgresRetrievalStore:
    dsn: str
    vector_dim: int = 64
    rrf_k: int = 60
    embedding_backend: str = 'local'
    _embedding_provider: EmbeddingProvider | None = None

    def __post_init__(self) -> None:
        if self._embedding_provider is None:
            self._embedding_provider = create_embedding_provider(
                self.embedding_backend, dim=self.vector_dim,
            )
            self.vector_dim = self._embedding_provider.dim

    def _embed(self, text: str) -> list[float]:
        """Generate embedding using the configured provider."""
        assert self._embedding_provider is not None
        return self._embedding_provider.embed(text)

    @staticmethod
    def _set_tenant_context(cur, tenant_id: str) -> None:
        """Set RLS tenant context for row-level security policies."""
        cur.execute("SET app.current_tenant = %s", (tenant_id,))

    def ensure_schema(self) -> None:
        ddl = f"""
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS doc_chunks (
          chunk_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          section TEXT NOT NULL,
          doc_id TEXT NOT NULL,
          source TEXT NOT NULL,
          updated_at DATE NOT NULL,
          text_content TEXT NOT NULL,
          embedding VECTOR({self.vector_dim}) NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_doc_chunks_tenant_section
          ON doc_chunks (tenant_id, section);

        CREATE INDEX IF NOT EXISTS idx_doc_chunks_fts
          ON doc_chunks USING GIN (to_tsvector('english', text_content));

        CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding
          ON doc_chunks USING hnsw (embedding vector_cosine_ops);
        """
        with psycopg.connect(to_psycopg_dsn(self.dsn)) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()

    def seed_chunks(self, chunks: list[ChunkRecord]) -> int:
        if not chunks:
            return 0
        sql = f"""
        INSERT INTO doc_chunks (
          chunk_id, tenant_id, section, doc_id, source, updated_at, text_content, embedding
        ) VALUES (
          %(chunk_id)s, %(tenant_id)s, %(section)s, %(doc_id)s, %(source)s, %(updated_at)s, %(text_content)s,
          %(embedding)s::vector
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
          tenant_id = EXCLUDED.tenant_id,
          section = EXCLUDED.section,
          doc_id = EXCLUDED.doc_id,
          source = EXCLUDED.source,
          updated_at = EXCLUDED.updated_at,
          text_content = EXCLUDED.text_content,
          embedding = EXCLUDED.embedding;
        """

        payload = []
        for rec in chunks:
            payload.append(
                {
                    "chunk_id": rec.chunk_id,
                    "tenant_id": rec.tenant_id,
                    "section": rec.section,
                    "doc_id": rec.doc_id,
                    "source": rec.source,
                    "updated_at": date.fromisoformat(rec.updated_at),
                    "text_content": rec.text,
                    "embedding": vector_to_pg_literal(self._embed(rec.text)),
                }
            )

        # Group by tenant_id so RLS WITH CHECK is satisfied per batch
        from itertools import groupby
        payload.sort(key=lambda r: r["tenant_id"])
        with psycopg.connect(to_psycopg_dsn(self.dsn)) as conn:
            for tid, group in groupby(payload, key=lambda r: r["tenant_id"]):
                batch = list(group)
                with conn.cursor() as cur:
                    self._set_tenant_context(cur, tid)
                    cur.executemany(sql, batch)
            conn.commit()
        return len(payload)

    def retrieve(
        self,
        tenant_id: str,
        issue_text: str,
        section: str | None,
        top_k: int = 5,
    ) -> list[EvidenceChunk]:
        vector_literal = vector_to_pg_literal(self._embed(issue_text))
        sparse_rows = self._sparse_search(tenant_id=tenant_id, section=section, issue_text=issue_text, top_k=top_k * 3)
        dense_rows = self._dense_search(
            tenant_id=tenant_id,
            section=section,
            query_vector_literal=vector_literal,
            top_k=top_k * 3,
        )

        if section is not None and not sparse_rows and not dense_rows:
            sparse_rows = self._sparse_search(tenant_id=tenant_id, section=None, issue_text=issue_text, top_k=top_k * 3)
            dense_rows = self._dense_search(
                tenant_id=tenant_id,
                section=None,
                query_vector_literal=vector_literal,
                top_k=top_k * 3,
            )

        fused = self._rrf_fuse(sparse_rows=sparse_rows, dense_rows=dense_rows, top_k=top_k)
        evidence = []
        for idx, row in enumerate(fused, start=1):
            evidence.append(
                EvidenceChunk(
                    chunk_id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    score=round(float(row["fused_score"]), 4),
                    rank=idx,
                    source=row["source"],
                    updated_at=str(row["updated_at"]),
                    text=row["text_content"],
                    section=row["section"],
                    tenant_id=row["tenant_id"],
                )
            )
        return evidence

    def _sparse_search(
        self,
        tenant_id: str,
        section: str | None,
        issue_text: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        sql = """
        SELECT
          chunk_id, doc_id, tenant_id, section, source, updated_at, text_content,
          ts_rank_cd(to_tsvector('english', text_content), plainto_tsquery('english', %(q)s)) AS sparse_score
        FROM doc_chunks
        WHERE tenant_id = %(tenant_id)s
          AND (%(section)s IS NULL OR section = %(section)s)
          AND to_tsvector('english', text_content) @@ plainto_tsquery('english', %(q)s)
        ORDER BY sparse_score DESC
        LIMIT %(k)s;
        """
        with psycopg.connect(to_psycopg_dsn(self.dsn), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                self._set_tenant_context(cur, tenant_id)
                cur.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "section": section,
                        "q": issue_text,
                        "k": top_k,
                    },
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def _dense_search(
        self,
        tenant_id: str,
        section: str | None,
        query_vector_literal: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        sql = """
        SELECT
          chunk_id, doc_id, tenant_id, section, source, updated_at, text_content,
          (1 - (embedding <=> %(query_vec)s::vector)) AS dense_score
        FROM doc_chunks
        WHERE tenant_id = %(tenant_id)s
          AND (%(section)s IS NULL OR section = %(section)s)
        ORDER BY embedding <=> %(query_vec)s::vector
        LIMIT %(k)s;
        """
        with psycopg.connect(to_psycopg_dsn(self.dsn), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                self._set_tenant_context(cur, tenant_id)
                cur.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "section": section,
                        "query_vec": query_vector_literal,
                        "k": top_k,
                    },
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def _rrf_fuse(
        self,
        sparse_rows: list[dict[str, Any]],
        dense_rows: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        rrf_scores = defaultdict(float)

        for rank, row in enumerate(sparse_rows, start=1):
            key = row["chunk_id"]
            merged.setdefault(key, row)
            rrf_scores[key] += 1.0 / (self.rrf_k + rank)

        for rank, row in enumerate(dense_rows, start=1):
            key = row["chunk_id"]
            merged.setdefault(key, row)
            rrf_scores[key] += 1.0 / (self.rrf_k + rank)

        if not merged:
            return []

        max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
        ranked = []
        for chunk_id, row in merged.items():
            fused = rrf_scores[chunk_id] / max_rrf if max_rrf > 0 else 0.0
            row_copy = dict(row)
            row_copy["fused_score"] = fused
            ranked.append(row_copy)

        ranked.sort(key=lambda x: x["fused_score"], reverse=True)
        return ranked[:top_k]
