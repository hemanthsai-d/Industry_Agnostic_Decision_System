from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import date

from app.models.schemas import EvidenceChunk
from app.storage.in_memory_store import IN_MEMORY_CHUNKS, ChunkRecord
from app.storage.postgres_store import PostgresRetrievalStore
from app.utils.text_normalization import normalize_support_text, tokenize_support_text

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        postgres_store: PostgresRetrievalStore | None = None,
        *,
        enable_reranking: bool = True,
        enable_dedup: bool = True,
        stale_penalty_days: int = 180,
        dedup_similarity_threshold: float = 0.85,
    ) -> None:
        self._records = IN_MEMORY_CHUNKS
        self._postgres_store = postgres_store
        self._enable_reranking = enable_reranking
        self._enable_dedup = enable_dedup
        self._stale_penalty_days = max(30, stale_penalty_days)
        self._dedup_similarity_threshold = max(0.5, min(0.99, dedup_similarity_threshold))

    def retrieve(
        self,
        tenant_id: str,
        issue_text: str,
        section: str | None = None,
        top_k: int = 5,
    ) -> list[EvidenceChunk]:
        if self._postgres_store is not None:
            try:
                pg_results = self._postgres_store.retrieve(
                    tenant_id=tenant_id,
                    section=section,
                    issue_text=issue_text,
                    top_k=top_k * 3 if self._enable_reranking else top_k,
                )
                if pg_results:
                    if self._enable_dedup:
                        pg_results = self._deduplicate_results(pg_results)
                    if self._enable_reranking:
                        pg_results = self._cross_encoder_rerank(issue_text, pg_results, top_k=top_k)
                    pg_results = self._apply_stale_penalty(pg_results)
                    return pg_results[:top_k]
            except Exception:
                logger.exception('Postgres retrieval failed, falling back to in-memory retrieval.')

        candidates = [
            r
            for r in self._records
            if r.tenant_id == tenant_id and (section is None or r.section == section)
        ]
        if not candidates and section is not None:
            candidates = [r for r in self._records if r.tenant_id == tenant_id]

        scored = [(self._lexical_score(issue_text, c), c) for c in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        evidence: list[EvidenceChunk] = []
        for idx, (score, rec) in enumerate(top, start=1):
            evidence.append(
                EvidenceChunk(
                    chunk_id=rec.chunk_id,
                    doc_id=rec.doc_id,
                    score=round(float(score), 4),
                    rank=idx,
                    source=rec.source,
                    updated_at=rec.updated_at,
                    text=rec.text,
                    section=rec.section,
                    tenant_id=rec.tenant_id,
                )
            )

        if self._enable_dedup:
            evidence = self._deduplicate_results(evidence)
        return evidence

    def _cross_encoder_rerank(
        self,
        query: str,
        candidates: list[EvidenceChunk],
        top_k: int = 5,
    ) -> list[EvidenceChunk]:
        """Rerank candidates using a lightweight cross-encoder scoring heuristic.

        This uses a detailed token overlap analysis as a proxy for cross-encoder
        scoring.  When a real cross-encoder model is available, replace the
        scoring logic inside this method.
        """
        if not candidates:
            return candidates

        query_tokens = Counter(tokenize_support_text(query))
        query_bigrams = self._bigram_set(tokenize_support_text(query))
        query_trigrams = self._trigram_set(tokenize_support_text(query))

        reranked: list[tuple[float, EvidenceChunk]] = []
        for chunk in candidates:
            doc_tokens = Counter(tokenize_support_text(chunk.text))
            doc_bigrams = self._bigram_set(tokenize_support_text(chunk.text))
            doc_trigrams = self._trigram_set(tokenize_support_text(chunk.text))

            common = set(query_tokens) & set(doc_tokens)
            if not common:
                token_score = 0.0
            else:
                weighted = sum(
                    min(query_tokens[t], doc_tokens[t]) * (1.0 / (1.0 + math.log1p(doc_tokens[t])))
                    for t in common
                )
                max_possible = sum(v for v in query_tokens.values())
                token_score = weighted / max(1.0, max_possible)

            bigram_score = 0.0
            if query_bigrams and doc_bigrams:
                bigram_score = len(query_bigrams & doc_bigrams) / max(len(query_bigrams), 1)

            trigram_score = 0.0
            if query_trigrams and doc_trigrams:
                trigram_score = len(query_trigrams & doc_trigrams) / max(len(query_trigrams), 1)

            ce_score = (
                0.30 * token_score
                + 0.25 * bigram_score
                + 0.15 * trigram_score
                + 0.30 * chunk.score
            )
            reranked.append((ce_score, chunk))

        reranked.sort(key=lambda x: x[0], reverse=True)

        result: list[EvidenceChunk] = []
        for idx, (score, chunk) in enumerate(reranked[:top_k], start=1):
            result.append(
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    score=round(score, 4),
                    rank=idx,
                    source=chunk.source,
                    updated_at=chunk.updated_at,
                    text=chunk.text,
                    section=chunk.section,
                    tenant_id=chunk.tenant_id,
                )
            )
        return result

    def _deduplicate_results(self, chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
        """Remove near-duplicate evidence chunks based on token-set similarity."""
        if len(chunks) <= 1:
            return chunks

        kept: list[EvidenceChunk] = []
        kept_token_sets: list[set[str]] = []

        for chunk in chunks:
            chunk_tokens = set(tokenize_support_text(chunk.text))
            is_dup = False
            for existing_tokens in kept_token_sets:
                if not chunk_tokens or not existing_tokens:
                    continue
                overlap = len(chunk_tokens & existing_tokens) / max(len(chunk_tokens), len(existing_tokens))
                if overlap >= self._dedup_similarity_threshold:
                    is_dup = True
                    break

            if not is_dup:
                kept.append(chunk)
                kept_token_sets.append(chunk_tokens)

        return kept

    def _apply_stale_penalty(self, chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
        """Penalize scores of stale content beyond the threshold."""
        if not chunks:
            return chunks

        result: list[EvidenceChunk] = []
        for chunk in chunks:
            try:
                days_old = (date.today() - date.fromisoformat(chunk.updated_at)).days
            except Exception:
                days_old = 0

            penalty = 0.0
            if days_old > self._stale_penalty_days:
                excess = days_old - self._stale_penalty_days
                penalty = min(0.15, excess * 0.0005)

            adjusted_score = max(0.01, chunk.score - penalty)
            result.append(
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    score=round(adjusted_score, 4),
                    rank=chunk.rank,
                    source=chunk.source,
                    updated_at=chunk.updated_at,
                    text=chunk.text,
                    section=chunk.section,
                    tenant_id=chunk.tenant_id,
                )
            )
        return result

    @staticmethod
    def _tokenize(text: str) -> Counter[str]:
        return Counter(tokenize_support_text(text))

    def _lexical_score(self, query: str, record: ChunkRecord) -> float:
        normalized_query = normalize_support_text(query)
        normalized_doc = normalize_support_text(record.text)
        q = self._tokenize(normalized_query)
        d = self._tokenize(normalized_doc)
        common = set(q).intersection(d)
        num = sum(min(q[t], d[t]) for t in common)
        den = math.sqrt(sum(v * v for v in q.values()) * sum(v * v for v in d.values()))
        token_cosine = (num / den) if den else 0.0

        phrase_overlap = self._phrase_overlap(normalized_query, normalized_doc)
        fuzzy_overlap = self._fuzzy_token_overlap(q, d)
        section_bonus = 0.03 if record.section in normalized_query else 0.0
        source_bonus = 0.02 if record.source in {'runbook', 'internal_wiki', 'policy'} else 0.0
        recency_bonus = self._recency_bonus(record.updated_at)

        score = (0.68 * token_cosine) + (0.16 * phrase_overlap) + (0.12 * fuzzy_overlap)
        score += section_bonus + source_bonus + recency_bonus

        if score <= 0:
            return 0.01
        return min(1.0, score)

    @staticmethod
    def _phrase_overlap(query: str, doc: str) -> float:
        query_tokens = query.split()
        doc_tokens = doc.split()
        if len(query_tokens) < 2 or len(doc_tokens) < 2:
            return 0.0

        query_bigrams = {f'{query_tokens[i]} {query_tokens[i + 1]}' for i in range(len(query_tokens) - 1)}
        doc_bigrams = {f'{doc_tokens[i]} {doc_tokens[i + 1]}' for i in range(len(doc_tokens) - 1)}
        if not query_bigrams or not doc_bigrams:
            return 0.0

        overlap = len(query_bigrams & doc_bigrams)
        return overlap / float(max(len(query_bigrams), len(doc_bigrams)))

    @staticmethod
    def _bigram_set(tokens: list[str]) -> set[str]:
        if len(tokens) < 2:
            return set()
        return {f'{tokens[i]} {tokens[i + 1]}' for i in range(len(tokens) - 1)}

    @staticmethod
    def _trigram_set(tokens: list[str]) -> set[str]:
        if len(tokens) < 3:
            return set()
        return {f'{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}' for i in range(len(tokens) - 2)}

    @staticmethod
    def _fuzzy_token_overlap(query_tokens: Counter[str], doc_tokens: Counter[str]) -> float:
        query_long = [token for token in query_tokens if len(token) >= 5]
        doc_long = [token for token in doc_tokens if len(token) >= 5]
        if not query_long or not doc_long:
            return 0.0

        doc_grams = RetrievalService._char_ngrams(doc_long)
        query_grams = RetrievalService._char_ngrams(query_long)
        if not doc_grams or not query_grams:
            return 0.0

        return len(query_grams & doc_grams) / float(max(len(query_grams), len(doc_grams)))

    @staticmethod
    def _char_ngrams(tokens: list[str], n: int = 3) -> set[str]:
        grams: set[str] = set()
        for token in tokens:
            if len(token) < n:
                continue
            for idx in range(0, len(token) - n + 1):
                grams.add(token[idx : idx + n])
        return grams

    @staticmethod
    def _recency_bonus(updated_at: str) -> float:
        try:
            days_old = (date.today() - date.fromisoformat(updated_at)).days
        except Exception:
            return 0.0

        if days_old <= 30:
            return 0.02
        if days_old <= 90:
            return 0.01
        return 0.0
