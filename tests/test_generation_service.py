from __future__ import annotations

from app.models.schemas import EvidenceChunk, ResolutionProb
from app.services.generation import GenerationService


class StaticBackend:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self._responses:
            return ''
        return self._responses.pop(0)


class FailingBackend:
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError('backend down')


def _evidence() -> list[EvidenceChunk]:
    return [
        EvidenceChunk(
            chunk_id='billing_001',
            doc_id='billing_doc',
            score=0.83,
            rank=1,
            source='runbook',
            updated_at='2026-02-01',
            text='Verify duplicate transaction and issue refund in 3 business days.',
            section='billing',
            tenant_id='org_demo',
        )
    ]


def _routes() -> list[ResolutionProb]:
    return [ResolutionProb(label='refund_duplicate_charge', prob=0.91)]


def test_generation_adds_citation_when_missing() -> None:
    service = GenerationService(backend_client=StaticBackend(['I can help with this refund today.']))
    result = service.build_grounded_response(
        issue_text='I was charged twice and need refund',
        route_probs=_routes(),
        evidence_pack=_evidence(),
        context={'customer_name': 'Sam'},
    )

    assert result.ok is True
    assert result.text is not None
    assert '[billing_001]' in result.text


def test_generation_retries_when_too_similar_to_prior() -> None:
    backend = StaticBackend(
        [
            'We can process your refund after verifying transaction details.',
            'Thanks for waiting. I checked your billing case and we can issue the refund now [billing_001].',
        ]
    )
    service = GenerationService(backend_client=backend)

    result = service.build_grounded_response(
        issue_text='Need refund for double charge',
        route_probs=_routes(),
        evidence_pack=_evidence(),
        context={'previous_answer': 'We can process your refund after verifying transaction details.'},
    )

    assert result.ok is True
    assert result.text is not None
    assert 'Thanks for waiting.' in result.text


def test_generation_fail_closed_returns_error() -> None:
    service = GenerationService(backend_client=FailingBackend(), fail_open=False)
    result = service.build_grounded_response(
        issue_text='Need help',
        route_probs=_routes(),
        evidence_pack=_evidence(),
        context={},
    )

    assert result.ok is False
    assert result.reason_code == 'generation_backend_unavailable'
    assert result.text is None
