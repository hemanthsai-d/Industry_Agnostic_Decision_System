"""Tests for retrieval service upgrades (reranking, dedup, stale penalties)."""
from __future__ import annotations

import pytest

from app.services.retrieval import RetrievalService


class TestRetrievalServiceReranking:
    def test_init_with_reranking_enabled(self):
        svc = RetrievalService(enable_reranking=True)
        assert svc._enable_reranking is True

    def test_init_with_reranking_disabled(self):
        svc = RetrievalService(enable_reranking=False)
        assert svc._enable_reranking is False

    def test_init_with_dedup_enabled(self):
        svc = RetrievalService(enable_dedup=True)
        assert svc._enable_dedup is True

    def test_stale_penalty_days_default(self):
        svc = RetrievalService()
        assert svc._stale_penalty_days == 180

    def test_retrieve_returns_chunks(self):
        svc = RetrievalService()
        results = svc.retrieve('org_demo', 'I need a refund', 'billing', 5)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_retrieve_with_reranking(self):
        svc = RetrievalService(enable_reranking=True, enable_dedup=True)
        results = svc.retrieve('org_demo', 'duplicate charge refund policy', 'billing', 5)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_retrieve_no_results_for_unknown_tenant(self):
        svc = RetrievalService()
        results = svc.retrieve('nonexistent_tenant', 'anything', None, 5)
        assert isinstance(results, list)
        assert len(results) == 0


class TestRetrievalBigramTrigram:
    def test_bigram_set(self):
        bigrams = RetrievalService._bigram_set(['hello', 'world', 'test'])
        assert 'hello world' in bigrams
        assert 'world test' in bigrams

    def test_trigram_set(self):
        trigrams = RetrievalService._trigram_set(['a', 'b', 'c', 'd'])
        assert 'a b c' in trigrams
        assert 'b c d' in trigrams

    def test_bigram_set_short_input(self):
        bigrams = RetrievalService._bigram_set(['hello'])
        assert len(bigrams) == 0
