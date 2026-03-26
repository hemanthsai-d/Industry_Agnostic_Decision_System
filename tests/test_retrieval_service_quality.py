from __future__ import annotations

from app.services.retrieval import RetrievalService
from app.storage.in_memory_store import ChunkRecord


def _record() -> ChunkRecord:
    return ChunkRecord(
        tenant_id='org_demo',
        section='billing',
        chunk_id='billing_test',
        doc_id='billing_doc',
        source='internal_wiki',
        updated_at='2026-02-01',
        text='For duplicate charges, verify transaction IDs and issue refund within 3 business days.',
    )


def test_lexical_score_handles_social_noise() -> None:
    service = RetrievalService()
    rec = _record()

    clean_query = 'customer charged twice needs refund for duplicate payment'
    noisy_query = '@brand charged twice!!! need refund pls https://example.com #billing'

    clean_score = service._lexical_score(clean_query, rec)
    noisy_score = service._lexical_score(noisy_query, rec)

    assert clean_score > 0.2
    assert noisy_score > 0.15


def test_lexical_score_uses_fuzzy_overlap_for_typos() -> None:
    service = RetrievalService()
    rec = _record()

    typo_query = 'custmer got duplcate chargs wants refnd'
    typo_score = service._lexical_score(typo_query, rec)

    assert typo_score > 0.05
