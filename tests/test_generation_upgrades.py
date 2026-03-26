"""Tests for generation service channel-aware upgrades."""
from __future__ import annotations

import pytest

from app.services.generation import GenerationService, _CHANNEL_STYLE, _DEFAULT_CHANNEL_STYLE


class TestChannelStyleConfig:
    def test_twitter_style_exists(self):
        assert 'twitter' in _CHANNEL_STYLE
        assert 'max_length' in _CHANNEL_STYLE['twitter']
        assert '280' in _CHANNEL_STYLE['twitter']['max_length']

    def test_chat_style_exists(self):
        assert 'chat' in _CHANNEL_STYLE

    def test_email_style_exists(self):
        assert 'email' in _CHANNEL_STYLE

    def test_phone_style_exists(self):
        assert 'phone' in _CHANNEL_STYLE

    def test_default_channel_is_chat(self):
        assert _DEFAULT_CHANNEL_STYLE == _CHANNEL_STYLE['chat']


class TestGenerationServiceStyleDirective:
    def test_style_directive_includes_channel_format(self):
        svc = GenerationService()
        directive = svc._build_style_directive(
            context={'channel': 'twitter'},
            issue_text='My order is late',
        )
        assert 'twitter' in directive

    def test_style_directive_empathetic_on_fraud(self):
        svc = GenerationService()
        directive = svc._build_style_directive(
            context={},
            issue_text='Someone stole my account this is fraud',
        )
        assert 'empathetic' in directive

    def test_style_directive_professional_for_enterprise(self):
        svc = GenerationService()
        directive = svc._build_style_directive(
            context={'account_tier': 'enterprise'},
            issue_text='Need help with billing',
        )
        assert 'professional' in directive


class TestGenerationServiceFallback:
    def test_fallback_response_on_empty_evidence(self):
        svc = GenerationService()
        result = svc.build_grounded_response(
            issue_text='Help me',
            route_probs=[],
            evidence_pack=[],
        )
        assert result.ok is False
        assert result.reason_code == 'generation_no_evidence'

    def test_fallback_template_with_evidence(self):
        svc = GenerationService(backend='template')
        from app.models.schemas import EvidenceChunk, ResolutionProb
        evidence = [
            EvidenceChunk(
                chunk_id='c1', text='Refund within 3 days', score=0.9,
                doc_id='d1', source='wiki', rank=1, updated_at='2025-01-01',
                section='billing', tenant_id='org_demo',
            ),
        ]
        route_probs = [ResolutionProb(label='billing_triage', prob=0.8)]
        result = svc.build_grounded_response(
            issue_text='Duplicate charge',
            route_probs=route_probs,
            evidence_pack=evidence,
        )
        assert result.ok is True
        assert result.used_fallback is True
        assert result.text is not None
        assert '[c1]' in result.text
