"""Tests for text normalization with colloquial expansion."""
from __future__ import annotations

import pytest

from app.utils.text_normalization import (
    expand_colloquial,
    normalize_support_text,
    tokenize_support_text,
    unique_terms,
)


class TestNormalizeSupportText:
    def test_removes_urls(self):
        assert 'http' not in normalize_support_text('Visit https://example.com for help')

    def test_removes_handles(self):
        assert 'support' not in normalize_support_text('@support please help')

    def test_extracts_hashtag_text(self):
        result = normalize_support_text('#helpme with account')
        assert 'helpme' in result

    def test_strips_emoji(self):
        result = normalize_support_text('Thanks! 😊👍')
        assert '😊' not in result
        assert '👍' not in result

    def test_removes_mask_placeholders(self):
        result = normalize_support_text('My email is __email__ and phone is __phone__')
        assert '__email__' not in result
        assert '__phone__' not in result

    def test_folds_repeated_chars(self):
        result = normalize_support_text('helllllp meeeee')
        assert 'llll' not in result

    def test_normalizes_smart_quotes(self):
        result = normalize_support_text("it\u2019s fine")
        assert "'" in result

    def test_empty_string(self):
        assert normalize_support_text('') == ''

    def test_none_input(self):
        assert normalize_support_text(None) == ''


class TestExpandColloquial:
    def test_expands_common_abbreviations(self):
        assert expand_colloquial('u r great') == 'you are great'

    def test_expands_please(self):
        assert expand_colloquial('pls help') == 'please help'

    def test_expands_thanks(self):
        assert expand_colloquial('thx for the help') == 'thanks for the help'

    def test_expands_account(self):
        assert expand_colloquial('my acct is locked') == 'my account is locked'

    def test_preserves_unknown_words(self):
        assert expand_colloquial('hello world') == 'hello world'

    def test_empty_string(self):
        assert expand_colloquial('') == ''


class TestTokenizeSupportText:
    def test_returns_tokens(self):
        tokens = tokenize_support_text('Hello, how can I help you?')
        assert 'hello' in tokens
        assert 'help' in tokens

    def test_excludes_urls(self):
        tokens = tokenize_support_text('Visit https://example.com')
        assert 'https' not in tokens


class TestUniqueTerms:
    def test_returns_set(self):
        terms = unique_terms('hello hello world')
        assert isinstance(terms, set)
        assert 'hello' in terms
        assert 'world' in terms

    def test_deduplicates(self):
        terms = unique_terms('help help help me')
        assert len(terms) == 2
