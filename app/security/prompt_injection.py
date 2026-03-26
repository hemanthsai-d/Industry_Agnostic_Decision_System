"""Prompt injection detection and defense.

RAG pipelines are vulnerable to indirect prompt injection where
malicious instructions are embedded in retrieved documents or
user input.  This module provides multi-layer detection:

  Layer 1 — Regex blocklist (fast, catches obvious attacks)
  Layer 2 — Instruction delimiter analysis (detects role-switching)
  Layer 3 — Heuristic scoring (entropy, instruction-density, suspicious tokens)
"""

from __future__ import annotations

import math
import re
import logging
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InjectionScanResult:
    """Result of prompt injection scan."""
    is_suspicious: bool
    risk_score: float           # 0.0 (clean) — 1.0 (definite injection)
    triggered_rules: tuple[str, ...]
    sanitized_text: str         # text with dangerous patterns neutralized


# ---------------------------------------------------------------------------
# Layer 1: Regex blocklist
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Direct instruction override
    (re.compile(r'ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|rules?|prompts?)', re.I),
     'instruction_override'),
    (re.compile(r'disregard\s+(?:all\s+)?(?:previous|above|prior|your)\s+(?:instructions?|rules?|guidelines?|context)', re.I),
     'instruction_disregard'),
    (re.compile(r'forget\s+(?:everything|all|what)\s+(?:you\s+)?(?:know|were\s+told|above)', re.I),
     'instruction_forget'),

    # Role-switching
    (re.compile(r'you\s+are\s+now\s+(?:a|an|the)\s+\w+', re.I), 'role_switch'),
    (re.compile(r'act\s+as\s+(?:a|an|if)\s+', re.I), 'role_impersonation'),
    (re.compile(r'pretend\s+(?:you\s+are|to\s+be)\s+', re.I), 'role_pretend'),
    (re.compile(r'from\s+now\s+on\s+you\s+(?:are|will|must|should)', re.I), 'role_override'),

    # System prompt extraction
    (re.compile(r'(?:print|show|reveal|display|output|repeat)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules?)', re.I),
     'prompt_extraction'),
    (re.compile(r'what\s+(?:are|is|were)\s+your\s+(?:system\s+)?(?:instructions?|rules?|prompt|guidelines?)', re.I),
     'prompt_query'),

    # Data exfiltration
    (re.compile(r'(?:send|post|fetch|curl|wget|http)\s+(?:to|from)\s+(?:https?://|[a-z]+\.)', re.I),
     'exfiltration_attempt'),

    # Delimiter injection
    (re.compile(r'```\s*(?:system|assistant|user)\s*\n', re.I), 'delimiter_injection'),
    (re.compile(r'<\|(?:im_start|im_end|system|user|assistant)\|>', re.I), 'chatml_injection'),
    (re.compile(r'\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>', re.I), 'llama_delimiter_injection'),

    # Encoding evasion (base64 instructions, unicode tricks)
    (re.compile(r'(?:base64|b64)\s*(?:decode|encoded?)\s*[:=]', re.I), 'encoding_evasion'),

    # Jailbreak patterns
    (re.compile(r'(?:DAN|Do\s+Anything\s+Now)\s+(?:mode|prompt|jailbreak)', re.I), 'jailbreak_dan'),
    (re.compile(r'(?:developer|debug|god|admin|root)\s+mode', re.I), 'jailbreak_mode'),
]


# Tokens that are suspicious in user input / evidence chunks
_SUSPICIOUS_TOKENS = frozenset({
    'ignore', 'disregard', 'override', 'bypass', 'jailbreak',
    'roleplay', 'pretend', 'persona', 'sudo', 'admin',
    'system_prompt', 'reveal', 'instructions',
})


# ---------------------------------------------------------------------------
# Layer 2: Delimiter analysis
# ---------------------------------------------------------------------------

_ROLE_MARKER_RE = re.compile(
    r'(?:^|\n)\s*(?:system|user|assistant|human|ai)\s*[:>]\s',
    re.I | re.MULTILINE,
)


def _count_role_markers(text: str) -> int:
    return len(_ROLE_MARKER_RE.findall(text))


# ---------------------------------------------------------------------------
# Layer 3: Heuristic scoring
# ---------------------------------------------------------------------------

def _instruction_density(text: str) -> float:
    """Ratio of imperative/instruction-like sentences."""
    sentences = [s.strip() for s in re.split(r'[.!?\n]+', text) if s.strip()]
    if not sentences:
        return 0.0

    imperative_starters = re.compile(
        r'^(?:you\s+(?:must|should|will|are|need)|do\s+not|don\'t|please\s+(?:ignore|forget|disregard)|'
        r'now\s+|always\s+|never\s+|stop\s+|start\s+)',
        re.I,
    )
    imperative_count = sum(1 for s in sentences if imperative_starters.match(s))
    return imperative_count / len(sentences)


def _char_entropy(text: str) -> float:
    """Shannon entropy of character distribution.  Very low entropy can signal encoded payloads."""
    if not text:
        return 0.0
    counts = Counter(text.lower())
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_for_injection(text: str) -> InjectionScanResult:
    """Scan text for prompt injection attempts.  Returns sanitized text + risk score."""
    if not text or not text.strip():
        return InjectionScanResult(
            is_suspicious=False, risk_score=0.0, triggered_rules=(), sanitized_text=text,
        )

    triggered: list[str] = []
    sanitized = text

    # Layer 1: regex blocklist
    for pattern, rule_name in _INJECTION_PATTERNS:
        if pattern.search(text):
            triggered.append(rule_name)
            sanitized = pattern.sub('[BLOCKED]', sanitized)

    # Layer 2: delimiter analysis
    role_markers = _count_role_markers(text)
    if role_markers >= 2:
        triggered.append('excessive_role_markers')

    # Layer 3: heuristic scoring
    density = _instruction_density(text)
    if density > 0.5:
        triggered.append('high_instruction_density')

    # suspicious token count
    text_lower = text.lower()
    suspicious_hit_count = sum(1 for t in _SUSPICIOUS_TOKENS if t in text_lower)
    if suspicious_hit_count >= 3:
        triggered.append('suspicious_token_cluster')

    # Compute risk score
    rule_weight = min(1.0, len(triggered) * 0.25)
    density_weight = min(0.3, density * 0.4)
    marker_weight = min(0.2, role_markers * 0.1)
    suspicious_weight = min(0.2, suspicious_hit_count * 0.05)

    risk_score = min(1.0, rule_weight + density_weight + marker_weight + suspicious_weight)

    is_suspicious = risk_score >= 0.25 or len(triggered) >= 1

    if is_suspicious:
        logger.warning(
            'Prompt injection detected.',
            extra={
                'risk_score': round(risk_score, 3),
                'triggered_rules': triggered,
                'text_preview': text[:120],
            },
        )

    return InjectionScanResult(
        is_suspicious=is_suspicious,
        risk_score=round(risk_score, 4),
        triggered_rules=tuple(triggered),
        sanitized_text=sanitized,
    )


def scan_evidence_chunks(chunks: list[dict[str, str]]) -> list[InjectionScanResult]:
    """Scan retrieved evidence chunks for indirect injection.

    Indirect injection is the primary RAG vulnerability — malicious
    content in the knowledge base that manipulates the LLM when
    injected into the context window.
    """
    results = []
    for chunk in chunks:
        text = chunk.get('text', '') or chunk.get('text_content', '')
        results.append(scan_for_injection(text))
    return results
