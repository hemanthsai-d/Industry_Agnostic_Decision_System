"""Output validation — schema enforcement + PII re-check on generated responses.

Applied AFTER generation but BEFORE returning to the caller.
Catches cases where the LLM leaks redacted PII back into the response,
injects forbidden content, or produces structurally invalid output.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── PII patterns (mirrors app/utils/pii_redaction.py categories) ────
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('email', re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', re.IGNORECASE)),
    ('phone', re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')),
    ('ssn', re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
    ('credit_card', re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b')),
    ('ip_address', re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
    # Date of birth in MM/DD/YYYY or YYYY-MM-DD
    ('date_of_birth', re.compile(
        r'\b(?:0[1-9]|1[0-2])[/\-](0[1-9]|[12]\d|3[01])[/\-](19|20)\d{2}\b'
        r'|\b(19|20)\d{2}[/\-](0[1-9]|1[0-2])[/\-](0[1-9]|[12]\d|3[01])\b'
    )),
]

# ── Forbidden output patterns ───────────────────────────────────────
_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('system_prompt_leak', re.compile(
        r'(system\s+prompt|internal\s+instructions?|you\s+are\s+a\s+helpful)',
        re.IGNORECASE,
    )),
    ('role_marker_leak', re.compile(
        r'<\|im_start\|>|<\|im_end\|>|\[INST\]|<<SYS>>',
        re.IGNORECASE,
    )),
    ('url_injection', re.compile(
        r'https?://(?!(?:support|help|docs|faq|status)\.\w+)',
        re.IGNORECASE,
    )),
    ('markdown_injection', re.compile(
        r'!\[.*?\]\(https?://.*?\)',
        re.IGNORECASE,
    )),
]

# ── Schema constraints ───────────────────────────────────────────────
MAX_RESPONSE_LENGTH = 2000  # chars
MIN_RESPONSE_LENGTH = 10
REQUIRED_CITATION_PATTERN = re.compile(r'\[chunk_\w+\]')


@dataclass
class OutputValidationResult:
    """Result of output validation checks."""
    is_valid: bool
    violations: list[str] = field(default_factory=list)
    pii_types_found: list[str] = field(default_factory=list)
    sanitized_text: str = ''
    original_text: str = ''


def validate_output(
    text: str,
    *,
    require_citations: bool = True,
    max_length: int = MAX_RESPONSE_LENGTH,
    pii_recheck: bool = True,
    check_forbidden: bool = True,
) -> OutputValidationResult:
    """Run all output validation checks on a generated response.

    Returns an OutputValidationResult with is_valid=False if any check fails.
    The sanitized_text field contains the cleaned version (PII masked,
    forbidden content stripped).
    """
    violations: list[str] = []
    pii_types: list[str] = []
    sanitized = text

    # ── 1. Schema: length bounds ─────────────────────────────────
    if len(text) < MIN_RESPONSE_LENGTH:
        violations.append(f'too_short:{len(text)}<{MIN_RESPONSE_LENGTH}')
    if len(text) > max_length:
        violations.append(f'too_long:{len(text)}>{max_length}')
        sanitized = sanitized[:max_length] + '...'

    # ── 2. Schema: citation presence ─────────────────────────────
    if require_citations and not REQUIRED_CITATION_PATTERN.search(text):
        violations.append('missing_citations')

    # ── 3. PII re-check ──────────────────────────────────────────
    if pii_recheck:
        for pii_type, pattern in _PII_PATTERNS:
            matches = pattern.findall(sanitized)
            if matches:
                pii_types.append(pii_type)
                violations.append(f'pii_leak:{pii_type}')
                sanitized = pattern.sub(f'[REDACTED_{pii_type.upper()}]', sanitized)

    # ── 4. Forbidden content ─────────────────────────────────────
    if check_forbidden:
        for rule_name, pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(sanitized):
                violations.append(f'forbidden:{rule_name}')
                sanitized = pattern.sub('[BLOCKED]', sanitized)

    # ── 5. Empty after sanitization ──────────────────────────────
    stripped = sanitized.strip()
    if not stripped:
        violations.append('empty_after_sanitization')

    is_valid = len(violations) == 0

    if violations:
        logger.warning(
            'Output validation violations detected.',
            extra={
                'violation_count': len(violations),
                'violations': violations,
                'pii_types': pii_types,
            },
        )

    return OutputValidationResult(
        is_valid=is_valid,
        violations=violations,
        pii_types_found=pii_types,
        sanitized_text=sanitized,
        original_text=text,
    )


def validate_and_sanitize(
    text: str | None,
    *,
    require_citations: bool = True,
) -> tuple[str | None, list[str]]:
    """Convenience wrapper: returns (sanitized_text_or_None, violation_list).

    If the text is None or empty, returns (None, []).
    If violations are found, returns the sanitized text (not None).
    The caller decides whether to block or pass through.
    """
    if not text:
        return None, []

    result = validate_output(text, require_citations=require_citations)
    if result.is_valid:
        return text, []
    return result.sanitized_text, result.violations
