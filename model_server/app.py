from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.models.schemas import EvidenceChunk
from app.observability import ObservabilityMiddleware, configure_logging, configure_tracing, metrics_response
from app.services.model_serving import ArtifactRoutingModelEngine, HeuristicRoutingModelEngine

logger = logging.getLogger(__name__)

settings = get_settings()

configure_logging(log_level=settings.log_level, log_format=settings.observability_log_format)

DEFAULT_ROUTE_LABELS = [
    'refund_duplicate_charge',
    'account_access_recovery',
    'shipping_delay_resolution',
    'technical_bug_triage',
    'general_support_triage',
]


class PredictFeatures(BaseModel):
    evidence_count: int = Field(default=0, ge=0)
    top_evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class PredictRequest(BaseModel):
    issue_text: str
    route_labels: list[str] = Field(default_factory=lambda: list(DEFAULT_ROUTE_LABELS))
    features: PredictFeatures = Field(default_factory=PredictFeatures)


class PredictResponse(BaseModel):
    route_probabilities: dict[str, float]
    escalation_prob: float
    backend: str


class ModelPredictor:
    def __init__(self) -> None:
        self.backend = os.getenv('MODEL_SERVER_BACKEND', 'artifact').strip().lower()

        if self.backend == 'heuristic':
            self._engine = HeuristicRoutingModelEngine()
            return

        routing_model_path = os.getenv(
            'ROUTING_MODEL_ARTIFACT_PATH',
            'artifacts/models/routing_linear_v1.json',
        )
        routing_calibration_path = os.getenv(
            'ROUTING_CALIBRATION_ARTIFACT_PATH',
            'artifacts/models/routing_temperature_v1.json',
        )
        escalation_model_path = os.getenv(
            'ESCALATION_MODEL_ARTIFACT_PATH',
            'artifacts/models/escalation_linear_v1.json',
        )
        escalation_calibration_path = os.getenv(
            'ESCALATION_CALIBRATION_ARTIFACT_PATH',
            'artifacts/models/escalation_platt_v1.json',
        )

        try:
            self._engine = ArtifactRoutingModelEngine(
                routing_model_path=routing_model_path,
                routing_calibration_path=routing_calibration_path,
                escalation_model_path=escalation_model_path,
                escalation_calibration_path=escalation_calibration_path,
            )
            self.backend = 'artifact'
        except Exception:
            logger.exception('Failed to initialize artifact model engine, falling back to heuristic model engine.')
            self._engine = HeuristicRoutingModelEngine()
            self.backend = 'heuristic'

    def predict(self, req: PredictRequest) -> PredictResponse:
        evidence_pack: list[EvidenceChunk] = []
        if req.features.evidence_count > 0:
            evidence_pack.append(
                EvidenceChunk(
                    chunk_id='model-serving-synthetic',
                    doc_id='model-serving',
                    score=req.features.top_evidence_score,
                    rank=1,
                    source='model-serving',
                    updated_at='2026-01-01',
                    text='synthetic evidence for model serving features',
                    section='model-serving',
                    tenant_id='system',
                )
            )

        route_probabilities, escalation_prob = self._engine.predict(
            issue_text=req.issue_text,
            evidence_pack=evidence_pack,
            route_labels=req.route_labels,
        )

        normalized = _normalize_route_probabilities(route_probabilities, req.route_labels)
        return PredictResponse(
            route_probabilities={label: round(prob, 6) for label, prob in normalized.items()},
            escalation_prob=round(max(0.0, min(1.0, float(escalation_prob))), 6),
            backend=self.backend,
        )


def _normalize_route_probabilities(route_probabilities: dict[str, float], route_labels: list[str]) -> dict[str, float]:
    labels = route_labels or list(DEFAULT_ROUTE_LABELS)
    cleaned = {label: max(0.0, float(route_probabilities.get(label, 0.0))) for label in labels}
    total = sum(cleaned.values())
    if total <= 0:
        uniform = 1.0 / len(labels)
        return {label: uniform for label in labels}
    return {label: value / total for label, value in cleaned.items()}


predictor = ModelPredictor()

app = FastAPI(
    title='decision-model-serving',
    version='0.1.0',
    description='HTTP model-serving endpoint for routing/escalation inference.',
)
app.add_middleware(ObservabilityMiddleware, service_name='decision-model-serving')

if settings.metrics_enabled:

    @app.get('/metrics', include_in_schema=False)
    def metrics():
        return metrics_response()


configure_tracing(
    app,
    enabled=settings.tracing_enabled,
    service_name='decision-model-serving',
    environment=settings.app_env,
    otlp_endpoint=settings.otlp_endpoint,
    otlp_insecure=settings.otlp_insecure,
    sample_ratio=settings.trace_sample_ratio,
)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok', 'backend': predictor.backend}


@app.post('/v1/models/routing:predict', response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    return predictor.predict(req)
