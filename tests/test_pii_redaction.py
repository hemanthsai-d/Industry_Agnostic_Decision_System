"""Tests for PII redaction utility."""
from __future__ import annotations

import pytest

from app.utils.pii_redaction import contains_pii, normalize_bitext_entities, redact_pii


class TestRedactPii:
    def test_redacts_email(self):
        result = redact_pii('Contact me at john@example.com please')
        assert 'john@example.com' not in result.text
        assert '{{Email}}' in result.text
        assert result.redacted_count >= 1
        assert 'email' in result.entity_types

    def test_redacts_phone(self):
        result = redact_pii('Call me at 555-123-4567')
        assert '555-123-4567' not in result.text
        assert '{{Phone Number}}' in result.text

    def test_redacts_ssn(self):
        result = redact_pii('My SSN is 123-45-6789')
        assert '123-45-6789' not in result.text
        assert '{{SSN}}' in result.text

    def test_redacts_credit_card(self):
        result = redact_pii('Card number 4111111111111111')
        assert '4111111111111111' not in result.text
        assert '{{Credit Card}}' in result.text

    def test_redacts_order_number(self):
        result = redact_pii('Order ORD-12345 is delayed')
        assert 'ORD-12345' not in result.text
        assert '{{Order Number}}' in result.text

    def test_redacts_ip_address(self):
        result = redact_pii('Connecting from 192.168.1.100')
        assert '192.168.1.100' not in result.text
        assert '{{IP Address}}' in result.text

    def test_no_pii_returns_original(self):
        text = 'I need help with my order status'
        result = redact_pii(text)
        assert result.text == text
        assert result.redacted_count == 0

    def test_multiple_entities(self):
        result = redact_pii('Email john@test.com, phone 555-000-1234')
        assert result.redacted_count >= 2

    def test_custom_extra_patterns(self):
        import re
        result = redact_pii('Token ABC999', extra_patterns=[(re.compile(r'ABC\d+'), '{{CUSTOM}}', 'custom')])
        assert 'ABC999' not in result.text
        assert '{{CUSTOM}}' in result.text


class TestContainsPii:
    def test_returns_true_for_email(self):
        assert contains_pii('email: alice@example.com')

    def test_returns_false_for_clean_text(self):
        assert not contains_pii('How do I check my order status')


class TestNormalizeBitextEntities:
    def test_normalizes_curly_entities(self):
        result = normalize_bitext_entities('Hello {{Client Name}}, your {{Order Number}} is ready.')
        assert '{{client_name}}' in result
        assert '{{order_number}}' in result

    def test_no_entities_unchanged(self):
        text = 'Plain text without entities'
        assert normalize_bitext_entities(text) == text
