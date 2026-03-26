"""PII and entity redaction utilities.

Detects and masks sensitive information before model input or logging,
inspired by entity types from the Bitext customer-support dataset
(30 entity/slot types) and standard PII patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedactionResult:
    """Result of PII redaction."""
    text: str
    redacted_count: int
    entity_types: tuple[str, ...]


_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b')
_PHONE_RE = re.compile(
    r'(?:\+?\d{1,3}[\s\-.]?)?\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,5}\b'
)
_SSN_RE = re.compile(r'\b\d{3}[\s\-]?\d{2}[\s\-]?\d{4}\b')
_CREDIT_CARD_RE = re.compile(r'\b(?:\d[\s\-]?){13,19}\b')
_ORDER_NUMBER_RE = re.compile(r'\b(?:order|ord|ref|confirmation)[\s#:\-]+([A-Z0-9\-]*\d[A-Z0-9\-]{3,19})\b', re.IGNORECASE)
_INVOICE_NUMBER_RE = re.compile(r'\b(?:invoice|inv)[\s#:\-]+([A-Z0-9\-]*\d[A-Z0-9\-]{2,19})\b', re.IGNORECASE)
_ACCOUNT_ID_RE = re.compile(r'\b(?:account|acct|acc)[\s#:\-]+([A-Z0-9\-]*\d[A-Z0-9\-]{2,19})\b', re.IGNORECASE)
_IP_ADDRESS_RE = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
_DATE_RE = re.compile(
    r'\b(?:\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\b'
)
_MONEY_RE = re.compile(r'(?:\$|€|£|¥)\s?\d[\d,]*\.?\d{0,2}\b|\b\d[\d,]*\.?\d{0,2}\s?(?:USD|EUR|GBP|CAD|AUD)\b', re.IGNORECASE)
_URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
_NAME_PREFIX_RE = re.compile(
    r'\b(?:my name is|i am|this is|name:?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'
)
_ADDRESS_RE = re.compile(
    r'\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place)\b',
    re.IGNORECASE,
)


_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (_SSN_RE, '{{SSN}}', 'ssn'),
    (_CREDIT_CARD_RE, '{{Credit Card}}', 'credit_card'),
    (_EMAIL_RE, '{{Email}}', 'email'),
    (_PHONE_RE, '{{Phone Number}}', 'phone'),
    (_IP_ADDRESS_RE, '{{IP Address}}', 'ip_address'),
    (_ORDER_NUMBER_RE, '{{Order Number}}', 'order_number'),
    (_INVOICE_NUMBER_RE, '{{Invoice Number}}', 'invoice_number'),
    (_ACCOUNT_ID_RE, '{{Account ID}}', 'account_id'),
    (_ADDRESS_RE, '{{Address}}', 'address'),
    (_NAME_PREFIX_RE, '{{Client Name}}', 'client_name'),
    (_MONEY_RE, '{{Money Amount}}', 'money_amount'),
    (_DATE_RE, '{{Date}}', 'date'),
    (_URL_RE, '{{URL}}', 'url'),
]


def redact_pii(text: str, *, extra_patterns: list[tuple[re.Pattern[str], str, str]] | None = None) -> RedactionResult:
    """Replace PII/sensitive entities with mask tokens.

    Args:
        text: Raw input text.
        extra_patterns: Optional additional ``(compiled_re, mask, entity_type)`` triples.

    Returns:
        A ``RedactionResult`` with sanitized text, count, and entity types found.
    """
    if not text or not text.strip():
        return RedactionResult(text=text, redacted_count=0, entity_types=())

    all_patterns = list(_PATTERNS)
    if extra_patterns:
        all_patterns.extend(extra_patterns)

    result = text
    count = 0
    types_found: list[str] = []

    for pattern, mask, entity_type in all_patterns:
        matches = pattern.findall(result)
        if matches:
            result = pattern.sub(mask, result)
            count += len(matches)
            if entity_type not in types_found:
                types_found.append(entity_type)

    return RedactionResult(
        text=result,
        redacted_count=count,
        entity_types=tuple(types_found),
    )


def contains_pii(text: str) -> bool:
    """Quick check whether text contains detectable PII."""
    if not text:
        return False
    for pattern, _, _ in _PATTERNS:
        if pattern.search(text):
            return True
    return False


_BITEXT_ENTITY_RE = re.compile(r'\{\{([^}]+)\}\}')


def normalize_bitext_entities(text: str) -> str:
    """Normalize Bitext-style ``{{Entity Name}}`` placeholders to lowercase underscore form.

    Example: ``{{Order Number}}`` → ``{{order_number}}``
    """
    def _normalize_match(m: re.Match[str]) -> str:
        entity = m.group(1).strip().lower().replace(' ', '_')
        return '{{' + entity + '}}'

    return _BITEXT_ENTITY_RE.sub(_normalize_match, text)
