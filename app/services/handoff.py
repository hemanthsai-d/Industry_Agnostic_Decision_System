from __future__ import annotations

from uuid import uuid4

from app.models.schemas import EvidenceChunk, HandoffPayload, ResolutionProb


class HandoffService:
    def build_payload(
        self,
        issue_text: str,
        reason_codes: list[str],
        evidence_pack: list[EvidenceChunk],
        route_probs: list[ResolutionProb],
        escalation_prob: float,
    ) -> HandoffPayload:
        summary = (
            f"Handoff required for issue: {issue_text[:160]}. "
            f"Reasons: {', '.join(reason_codes) if reason_codes else 'unspecified'}."
        )
        return HandoffPayload(
            handoff_id=str(uuid4()),
            reason_codes=reason_codes,
            summary=summary,
            evidence_pack=evidence_pack,
            route_probs=route_probs,
            escalation_prob=escalation_prob,
        )

