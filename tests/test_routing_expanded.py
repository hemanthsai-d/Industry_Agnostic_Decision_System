"""Tests for expanded routing with taxonomy integration."""
from __future__ import annotations

import pytest

from app.services.model_serving import HeuristicRoutingModelEngine
from app.services.routing import RoutingService


class TestExpandedRouting:
    def _make_routing_service(self, **kwargs):
        engine = HeuristicRoutingModelEngine()
        return RoutingService(model_engine=engine, **kwargs)

    def test_predict_returns_detected_intents(self):
        svc = self._make_routing_service()
        from app.models.schemas import EvidenceChunk
        evidence = [
            EvidenceChunk(
                chunk_id='c1', text='Refund policy for duplicate charges', score=0.8,
                doc_id='d1', source='wiki', rank=1, updated_at='2025-01-01',
                section='billing', tenant_id='org_demo',
            ),
        ]
        route_probs, esc_prob, ood_score, contradiction_score, meta = svc.predict_with_metadata(
            issue_text='I want a refund for a duplicate charge',
            evidence_pack=evidence,
        )
        assert isinstance(route_probs, list)
        assert len(route_probs) > 0
        assert isinstance(meta, dict)
        assert 'detected_intents' in meta

    def test_contradiction_detection(self):
        svc = self._make_routing_service()
        from app.models.schemas import EvidenceChunk
        evidence = [
            EvidenceChunk(
                chunk_id='c1', text='Refund approved for this case', score=0.8,
                doc_id='d1', source='wiki', rank=1, updated_at='2025-01-01',
                section='billing', tenant_id='org_demo',
            ),
            EvidenceChunk(
                chunk_id='c2', text='No refund possible for this category', score=0.7,
                doc_id='d2', source='wiki', rank=2, updated_at='2025-01-01',
                section='billing', tenant_id='org_demo',
            ),
        ]
        _, _, _, contradiction_score, _ = svc.predict_with_metadata(
            issue_text='Can I get a refund?',
            evidence_pack=evidence,
        )
        assert isinstance(contradiction_score, float)

    def test_ood_score_for_vague_input(self):
        svc = self._make_routing_service()
        _, _, ood_score, _, _ = svc.predict_with_metadata(
            issue_text='hi',
            evidence_pack=[],
        )
        assert ood_score >= 0.0


class TestHeuristicRoutingExpandedKeywords:
    def test_expanded_keywords_include_taxonomy_terms(self):
        engine = HeuristicRoutingModelEngine()
        assert hasattr(engine, 'EXPANDED_PATH_KEYWORDS')
        assert len(engine.EXPANDED_PATH_KEYWORDS) > 0

    def test_high_escalation_terms_expanded(self):
        engine = HeuristicRoutingModelEngine()
        assert 'stolen' in engine.HIGH_ESCALATION_TERMS
        assert 'identity theft' in engine.HIGH_ESCALATION_TERMS
        assert 'attorney' in engine.HIGH_ESCALATION_TERMS
