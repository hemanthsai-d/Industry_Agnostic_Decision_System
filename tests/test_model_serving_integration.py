from __future__ import annotations

from pathlib import Path

from app.services.model_serving import (
    ArtifactRoutingModelEngine,
    FallbackRoutingModelEngine,
    HeuristicRoutingModelEngine,
)
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService


def _artifact_paths() -> tuple[str, str, str, str]:
    root = Path(__file__).resolve().parents[1]
    return (
        str(root / 'artifacts/models/routing_linear_v1.json'),
        str(root / 'artifacts/models/routing_temperature_v1.json'),
        str(root / 'artifacts/models/escalation_linear_v1.json'),
        str(root / 'artifacts/models/escalation_platt_v1.json'),
    )


def _artifact_engine() -> ArtifactRoutingModelEngine:
    routing_model, routing_calibration, escalation_model, escalation_calibration = _artifact_paths()
    return ArtifactRoutingModelEngine(
        routing_model_path=routing_model,
        routing_calibration_path=routing_calibration,
        escalation_model_path=escalation_model,
        escalation_calibration_path=escalation_calibration,
    )


def test_artifact_model_predicts_refund_route_with_low_escalation():
    engine = _artifact_engine()
    evidence_pack = RetrievalService().retrieve(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer was charged twice and asks for a refund.',
        top_k=3,
    )

    route_probs, escalation_prob = engine.predict(
        issue_text='Customer was charged twice and asks for a refund.',
        evidence_pack=evidence_pack,
        route_labels=RoutingService.DEFAULT_ROUTE_LABELS,
    )

    top_label = max(route_probs, key=route_probs.get)
    assert top_label == 'refund_duplicate_charge'
    assert 0.0 <= escalation_prob < 0.6


def test_artifact_model_predicts_high_escalation_for_risk_language():
    engine = _artifact_engine()
    evidence_pack = RetrievalService().retrieve(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer threatens legal lawsuit over fraud and security breach.',
        top_k=3,
    )

    _, escalation_prob = engine.predict(
        issue_text='Customer threatens legal lawsuit over fraud and security breach.',
        evidence_pack=evidence_pack,
        route_labels=RoutingService.DEFAULT_ROUTE_LABELS,
    )

    assert escalation_prob > 0.75


class BrokenRoutingEngine:
    def predict(self, issue_text: str, evidence_pack, route_labels):
        raise RuntimeError('primary model backend unavailable')


def test_fallback_model_engine_uses_heuristic_when_primary_fails():
    fallback_engine = HeuristicRoutingModelEngine()
    engine = FallbackRoutingModelEngine(primary=BrokenRoutingEngine(), fallback=fallback_engine)

    route_probs, escalation_prob = engine.predict(
        issue_text='Customer was charged twice and asks for a refund.',
        evidence_pack=[],
        route_labels=RoutingService.DEFAULT_ROUTE_LABELS,
    )

    top_label = max(route_probs, key=route_probs.get)
    assert top_label == 'refund_duplicate_charge'
    assert 0.0 <= escalation_prob <= 1.0
