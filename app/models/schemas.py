from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class DecisionType(str, Enum):
    recommend = "recommend"
    abstain = "abstain"
    escalate = "escalate"


class HandoffQueueStatus(str, Enum):
    open = "open"
    in_review = "in_review"
    resolved = "resolved"
    closed = "closed"


class DecideRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    section: str | None = None
    issue_text: str
    context: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.medium
    max_evidence_chunks: int = Field(default=5, ge=1, le=12)


class EvidenceChunk(BaseModel):
    chunk_id: str
    doc_id: str
    score: float
    rank: int
    source: str
    updated_at: str
    text: str
    section: str
    tenant_id: str


class ResolutionProb(BaseModel):
    label: str
    prob: float


class ConfidenceBreakdown(BaseModel):
    final: float
    route_conf: float
    evidence_score: float
    ood_score: float
    contradiction_score: float


class PolicyResult(BaseModel):
    allow_auto_response: bool
    final_decision: DecisionType
    reason_codes: list[str] = Field(default_factory=list)


class HandoffPayload(BaseModel):
    handoff_id: str
    reason_codes: list[str]
    summary: str
    evidence_pack: list[EvidenceChunk]
    route_probs: list[ResolutionProb]
    escalation_prob: float
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DecideResponse(BaseModel):
    decision: DecisionType
    resolution_path_probs: list[ResolutionProb]
    escalation_prob: float
    confidence: ConfidenceBreakdown
    evidence_pack: list[EvidenceChunk]
    draft_response: str | None = None
    policy_result: PolicyResult
    handoff_payload: HandoffPayload | None = None
    trace_id: str
    request_id: str
    model_variant: str = 'primary'
    model_backend_fallback: bool = False
    detected_intent: str | None = None
    detected_category: str | None = None
    pii_redacted: bool = False


class FeedbackRequest(BaseModel):
    request_id: str
    tenant_id: str
    accepted_decision: DecisionType | None = None
    corrected_resolution_path: str | None = None
    notes: str | None = None


class FeedbackResponse(BaseModel):
    status: str
    request_id: str


class ReindexRequest(BaseModel):
    tenant_id: str
    section: str | None = None


class ReindexResponse(BaseModel):
    status: str
    tenant_id: str
    section: str | None = None


class HandoffQueueItem(BaseModel):
    handoff_id: str
    request_id: str
    tenant_id: str
    queue_status: HandoffQueueStatus
    reason_codes: list[str]
    handoff_payload: HandoffPayload
    created_at: str


class HandoffListResponse(BaseModel):
    items: list[HandoffQueueItem]


class HandoffStatusUpdateRequest(BaseModel):
    tenant_id: str
    queue_status: HandoffQueueStatus
    reviewer_id: str | None = None
    final_decision: DecisionType | None = None
    final_resolution_path: str | None = None
    notes: str | None = None


class HandoffStatusUpdateResponse(BaseModel):
    handoff_id: str
    tenant_id: str
    queue_status: HandoffQueueStatus
    ground_truth_recorded: bool = False
