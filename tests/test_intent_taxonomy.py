"""Tests for intent taxonomy module."""
from __future__ import annotations

import pytest

from app.models.intent_taxonomy import (
    ALL_CATEGORIES,
    ALL_INTENT_LABELS,
    EXPANDED_TO_LEGACY,
    INTENT_BY_ID,
    INTENT_CATALOG,
    INTENTS_BY_CATEGORY,
    LEGACY_TO_EXPANDED,
    detect_intents_heuristic,
    get_category,
    get_escalation_hint,
    get_risk_level,
    map_to_legacy_route,
)


class TestIntentCatalog:
    def test_catalog_has_expected_count(self):
        assert len(INTENT_CATALOG) >= 25

    def test_all_intents_have_required_fields(self):
        for intent in INTENT_CATALOG:
            assert intent.intent_id
            assert intent.category
            assert intent.description
            assert intent.risk_level in ('low', 'medium', 'high')
            assert isinstance(intent.keywords, tuple)
            assert len(intent.keywords) > 0
            assert 0.0 <= intent.escalation_hint <= 1.0

    def test_intent_by_id_lookup(self):
        assert 'check_refund_policy' in INTENT_BY_ID
        refund = INTENT_BY_ID['check_refund_policy']
        assert refund.category == 'REFUND'

    def test_intents_by_category(self):
        assert 'ORDER' in INTENTS_BY_CATEGORY
        assert len(INTENTS_BY_CATEGORY['ORDER']) >= 2

    def test_all_intent_labels_count(self):
        assert len(ALL_INTENT_LABELS) == len(INTENT_CATALOG)

    def test_all_categories_populated(self):
        assert len(ALL_CATEGORIES) >= 8


class TestDetectIntentsHeuristic:
    def test_detects_refund_intent(self):
        intents = detect_intents_heuristic('I want a refund for my order')
        labels = [intent_id for intent_id, _score in intents]
        assert any('refund' in label for label in labels)

    def test_detects_cancel_intent(self):
        intents = detect_intents_heuristic('Please cancel my subscription')
        labels = [intent_id for intent_id, _score in intents]
        assert any('cancel' in label for label in labels)

    def test_returns_empty_for_gibberish(self):
        intents = detect_intents_heuristic('asdf qwerty xyz')
        assert len(intents) == 0

    def test_max_results_default(self):
        intents = detect_intents_heuristic('I need help with my order delivery refund cancel subscription')
        assert len(intents) <= 3


class TestLegacyMapping:
    def test_legacy_to_expanded(self):
        assert len(LEGACY_TO_EXPANDED) > 0

    def test_expanded_to_legacy(self):
        assert len(EXPANDED_TO_LEGACY) > 0

    def test_map_to_legacy_returns_self_for_legacy(self):
        legacy = map_to_legacy_route('billing_triage')
        assert isinstance(legacy, str)


class TestGetCategory:
    def test_known_intent(self):
        cat = get_category('check_refund_policy')
        assert cat == 'REFUND'

    def test_unknown_intent(self):
        cat = get_category('nonexistent_intent_xyz')
        assert cat == 'GENERAL'


class TestGetRiskLevel:
    def test_known_intent(self):
        level = get_risk_level('report_fraud')
        assert level in ('low', 'medium', 'high')

    def test_unknown_intent(self):
        assert get_risk_level('nonexistent') == 'medium'


class TestGetEscalationHint:
    def test_known_intent(self):
        hint = get_escalation_hint('report_fraud')
        assert isinstance(hint, float)
        assert 0.0 <= hint <= 1.0

    def test_unknown_intent(self):
        assert get_escalation_hint('nonexistent') == 0.10
