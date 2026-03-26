"""Tests for expanded in-memory store chunks and new config fields."""
from __future__ import annotations

import pytest

from app.storage.in_memory_store import IN_MEMORY_CHUNKS


class TestExpandedInMemoryStore:
    def test_has_at_least_15_chunks(self):
        assert len(IN_MEMORY_CHUNKS) >= 15

    def test_covers_multiple_sections(self):
        sections = {chunk.section for chunk in IN_MEMORY_CHUNKS}
        assert 'billing' in sections
        assert 'accounts' in sections
        assert 'shipping' in sections
        assert 'orders' in sections
        assert 'payments' in sections
        assert 'refunds' in sections

    def test_all_chunks_have_required_fields(self):
        for chunk in IN_MEMORY_CHUNKS:
            assert chunk.tenant_id
            assert chunk.section
            assert chunk.chunk_id
            assert chunk.doc_id
            assert chunk.source
            assert chunk.updated_at
            assert len(chunk.text) > 10

    def test_chunk_ids_are_unique(self):
        ids = [chunk.chunk_id for chunk in IN_MEMORY_CHUNKS]
        assert len(ids) == len(set(ids))


class TestNewConfigFields:
    def test_pii_redaction_enabled_default(self):
        from app.core.config import Settings
        s = Settings()
        assert s.pii_redaction_enabled is True

    def test_use_expanded_taxonomy_default(self):
        from app.core.config import Settings
        s = Settings()
        assert s.use_expanded_taxonomy is False

    def test_retrieval_enable_reranking_default(self):
        from app.core.config import Settings
        s = Settings()
        assert s.retrieval_enable_reranking is True

    def test_retrieval_enable_dedup_default(self):
        from app.core.config import Settings
        s = Settings()
        assert s.retrieval_enable_dedup is True

    def test_retrieval_stale_penalty_days_default(self):
        from app.core.config import Settings
        s = Settings()
        assert s.retrieval_stale_penalty_days == 180
