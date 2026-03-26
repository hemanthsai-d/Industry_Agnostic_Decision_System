from __future__ import annotations

import re

from app.models.intent_taxonomy import (
    ALL_INTENT_LABELS,
    INTENT_BY_ID,
    detect_intents_heuristic,
    get_category,
    get_escalation_hint,
    get_risk_level,
    map_to_legacy_route,
)
from app.models.schemas import EvidenceChunk, ResolutionProb
from app.services.model_serving import HeuristicRoutingModelEngine, RoutingModelEngine


class RoutingService:
    DEFAULT_ROUTE_LABELS = [
        'refund_duplicate_charge',
        'account_access_recovery',
        'shipping_delay_resolution',
        'technical_bug_triage',
        'general_support_triage',
    ]

    EXPANDED_ROUTE_LABELS = ALL_INTENT_LABELS

    _CONTRADICTION_PAIRS: list[tuple[str, str, float]] = [
        ('refund', 'do not refund', 0.4),
        ('refund', 'no refund', 0.35),
        ('refund', 'non-refundable', 0.35),
        ('fraud', 'safe to proceed', 0.4),
        ('fraud', 'no fraud detected', 0.3),
        ('cancel', 'cannot cancel', 0.3),
        ('cancel', 'non-cancellable', 0.3),
        ('free', 'additional fee', 0.25),
        ('discount', 'not eligible', 0.25),
        ('urgent', 'standard processing', 0.2),
        ('broken', 'working as expected', 0.3),
        ('lost', 'delivered', 0.3),
        ('overcharged', 'correct amount', 0.3),
    ]

    def __init__(
        self,
        model_engine: RoutingModelEngine | None = None,
        route_labels: list[str] | None = None,
        *,
        use_expanded_taxonomy: bool = False,
    ) -> None:
        if route_labels is not None:
            self._route_labels = list(route_labels)
        elif use_expanded_taxonomy:
            self._route_labels = list(self.EXPANDED_ROUTE_LABELS)
        else:
            self._route_labels = list(self.DEFAULT_ROUTE_LABELS)

        self._model_engine = model_engine or HeuristicRoutingModelEngine()
        self._use_expanded_taxonomy = use_expanded_taxonomy

    def predict(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
    ) -> tuple[list[ResolutionProb], float, float, float]:
        route_probs, escalation_prob, ood_score, contradiction_score, _ = self.predict_with_metadata(
            issue_text=issue_text,
            evidence_pack=evidence_pack,
        )
        return route_probs, escalation_prob, ood_score, contradiction_score

    def predict_with_metadata(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
    ) -> tuple[list[ResolutionProb], float, float, float, dict[str, object]]:
        route_probabilities, escalation_prob = self._model_engine.predict(
            issue_text=issue_text,
            evidence_pack=evidence_pack,
            route_labels=self._route_labels,
        )

        normalized_probs = self._normalize_route_probabilities(route_probabilities)
        sorted_probs = sorted(
            [ResolutionProb(label=label, prob=round(probability, 4)) for label, probability in normalized_probs.items()],
            key=lambda p: p.prob,
            reverse=True,
        )

        top_route_prob = sorted_probs[0].prob if sorted_probs else 0.0
        top_route_label = sorted_probs[0].label if sorted_probs else ''
        ood_score = self._ood_score(issue_text, evidence_pack, top_route_prob)
        contradiction_score = self._contradiction_score(issue_text, evidence_pack)

        taxonomy_escalation_hint = get_escalation_hint(top_route_label)
        adjusted_escalation = escalation_prob * 0.75 + taxonomy_escalation_hint * 0.25

        bounded_escalation_prob = max(0.0, min(1.0, float(adjusted_escalation)))

        detected_intents = detect_intents_heuristic(issue_text, top_k=3)
        detected_category = get_category(top_route_label)
        detected_risk = get_risk_level(top_route_label)

        metadata: dict[str, object] = {
            'used_fallback': bool(getattr(self._model_engine, 'last_used_fallback', False)),
            'detected_intents': detected_intents,
            'detected_category': detected_category,
            'detected_risk_level': detected_risk,
            'taxonomy_escalation_hint': taxonomy_escalation_hint,
        }
        return (
            sorted_probs,
            round(bounded_escalation_prob, 4),
            round(ood_score, 4),
            round(contradiction_score, 4),
            metadata,
        )

    def _normalize_route_probabilities(self, probabilities: dict[str, float]) -> dict[str, float]:
        cleaned = {label: max(0.0, float(probabilities.get(label, 0.0))) for label in self._route_labels}
        total = sum(cleaned.values())
        if total <= 0:
            uniform = 1.0 / len(self._route_labels)
            return {label: uniform for label in self._route_labels}
        return {label: value / total for label, value in cleaned.items()}

    @staticmethod
    def _ood_score(issue_text: str, evidence_pack: list[EvidenceChunk], top_prob: float) -> float:
        if not evidence_pack:
            return 0.95
        top_evidence = evidence_pack[0].score

        tokens = issue_text.lower().split()
        long_word_count = len([t for t in tokens if len(t) >= 12])
        unknown_ratio = long_word_count / max(1, len(tokens))

        brevity_penalty = 0.0
        if len(tokens) <= 2:
            brevity_penalty = 0.15

        evidence_diversity = 0.0
        if len(evidence_pack) >= 2:
            scores = [e.score for e in evidence_pack[:5]]
            score_range = max(scores) - min(scores)
            if score_range < 0.05:
                evidence_diversity = 0.10

        raw = (
            (1 - top_prob) * 0.45
            + (1 - top_evidence) * 0.30
            + unknown_ratio * 0.10
            + brevity_penalty
            + evidence_diversity * 0.05
        )
        return max(0.0, min(1.0, raw))

    @staticmethod
    def _contradiction_score(issue_text: str, evidence_pack: list[EvidenceChunk]) -> float:
        txt = issue_text.lower()
        if not evidence_pack:
            return 0.3

        score = 0.03
        evidence_corpus = ' '.join(chunk.text.lower() for chunk in evidence_pack)

        for issue_kw, evidence_kw, weight in RoutingService._CONTRADICTION_PAIRS:
            if issue_kw in txt and evidence_kw in evidence_corpus:
                score += weight

        return min(1.0, score)
