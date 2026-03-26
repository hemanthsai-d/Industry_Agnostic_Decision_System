from __future__ import annotations

import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.models.schemas import EvidenceChunk
from app.models.intent_taxonomy import INTENT_BY_ID, INTENT_CATALOG
from app.utils.text_normalization import tokenize_support_text

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    return tokenize_support_text(text)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _softmax(scores: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    if not scores:
        return {}

    safe_temperature = max(1e-6, temperature)
    max_score = max(scores.values())
    exp_values = {label: math.exp((score - max_score) / safe_temperature) for label, score in scores.items()}
    total = sum(exp_values.values())

    if total <= 0:
        uniform = 1.0 / len(scores)
        return {label: uniform for label in scores}

    return {label: value / total for label, value in exp_values.items()}


def _normalize_probabilities(probs: dict[str, float], labels: list[str]) -> dict[str, float]:
    if not labels:
        return {}

    filtered = {label: max(0.0, float(probs.get(label, 0.0))) for label in labels}
    total = sum(filtered.values())
    if total <= 0:
        uniform = 1.0 / len(labels)
        return {label: uniform for label in labels}
    return {label: value / total for label, value in filtered.items()}


class RoutingModelEngine(Protocol):
    def predict(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
        route_labels: list[str],
    ) -> tuple[dict[str, float], float]:
        ...


class HeuristicRoutingModelEngine:
    PATH_KEYWORDS: dict[str, list[str]] = {
        'refund_duplicate_charge': ['charged twice', 'duplicate', 'refund', 'double charge'],
        'account_access_recovery': ['password', 'locked', 'login', 'reset'],
        'shipping_delay_resolution': ['shipping', 'delay', 'carrier', 'delivery'],
        'technical_bug_triage': ['error', 'bug', 'crash', 'failed'],
        'general_support_triage': ['help', 'support', 'question'],
    }

    EXPANDED_PATH_KEYWORDS: dict[str, list[str]] = {
        defn.intent_id: list(defn.keywords)
        for defn in INTENT_CATALOG
    }

    HIGH_ESCALATION_TERMS = {
        'fraud', 'breach', 'legal', 'lawsuit', 'security incident', 'chargeback',
        'unauthorized', 'stolen', 'hacked', 'identity theft', 'data leak',
        'threatening', 'harassment', 'discrimination', 'regulator', 'attorney',
    }

    def predict(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
        route_labels: list[str],
    ) -> tuple[dict[str, float], float]:
        labels = route_labels or list(self.PATH_KEYWORDS.keys())
        scores = self._path_scores(issue_text, labels)
        probabilities = _softmax(scores)
        top_prob = max(probabilities.values()) if probabilities else 0.0
        escalation_prob = self._escalation_prob(issue_text, top_prob)
        return probabilities, escalation_prob

    def _path_scores(self, issue_text: str, route_labels: list[str]) -> dict[str, float]:
        txt = issue_text.lower()
        scores = {label: 0.2 for label in route_labels}

        for label, terms in self.EXPANDED_PATH_KEYWORDS.items():
            if label not in scores:
                continue
            score = 0.2
            for term in terms:
                if term in txt:
                    score += 1.2
            scores[label] = max(scores.get(label, 0.2), score)

        for label, terms in self.PATH_KEYWORDS.items():
            if label not in scores:
                continue
            score = scores.get(label, 0.2)
            for term in terms:
                if term in txt:
                    score += 1.2
            scores[label] = score

        return scores

    def _escalation_prob(self, issue_text: str, top_route_prob: float) -> float:
        txt = issue_text.lower()
        risk_hits = sum(1 for term in self.HIGH_ESCALATION_TERMS if term in txt)
        base = 0.15 + (0.35 if risk_hits > 0 else 0.0)
        uncertainty_penalty = max(0.0, 0.4 - top_route_prob)
        return _clamp(base + uncertainty_penalty + (0.1 * risk_hits), 0.0, 0.98)


class ArtifactRoutingModelEngine:
    def __init__(
        self,
        routing_model_path: str,
        routing_calibration_path: str,
        escalation_model_path: str,
        escalation_calibration_path: str,
    ) -> None:
        self._routing_model = self._load_json(routing_model_path, artifact_type='routing model')
        self._routing_calibration = self._load_json(routing_calibration_path, artifact_type='routing calibration')
        self._escalation_model = self._load_json(escalation_model_path, artifact_type='escalation model')
        self._escalation_calibration = self._load_json(
            escalation_calibration_path,
            artifact_type='escalation calibration',
        )

        self._routing_labels = [str(label) for label in self._routing_model.get('labels', [])]
        self._routing_bias = {str(label): float(value) for label, value in self._routing_model.get('bias', {}).items()}

        self._routing_token_weights: dict[str, dict[str, float]] = {}
        for token, label_weights in self._routing_model.get('token_weights', {}).items():
            if not isinstance(label_weights, dict):
                continue
            self._routing_token_weights[str(token)] = {
                str(label): float(weight) for label, weight in label_weights.items()
            }

        self._routing_temperature = float(self._routing_calibration.get('temperature', 1.0) or 1.0)
        self._routing_min_probability = float(self._routing_calibration.get('min_probability', 0.0001) or 0.0001)
        self._routing_max_probability = float(self._routing_calibration.get('max_probability', 0.9999) or 0.9999)

        self._escalation_bias = float(self._escalation_model.get('bias', -1.0) or -1.0)
        self._escalation_token_weights = {
            str(token): float(weight) for token, weight in self._escalation_model.get('token_weights', {}).items()
        }
        self._route_uncertainty_weight = float(self._escalation_model.get('route_uncertainty_weight', 1.0) or 1.0)
        self._evidence_gap_weight = float(self._escalation_model.get('evidence_gap_weight', 0.5) or 0.5)
        self._long_word_ratio_weight = float(self._escalation_model.get('long_word_ratio_weight', 0.2) or 0.2)

        self._escalation_calibration_a = float(self._escalation_calibration.get('a', 1.0) or 1.0)
        self._escalation_calibration_b = float(self._escalation_calibration.get('b', 0.0) or 0.0)
        self._escalation_min_probability = float(self._escalation_calibration.get('min_probability', 0.0001) or 0.0001)
        self._escalation_max_probability = float(self._escalation_calibration.get('max_probability', 0.9999) or 0.9999)

    def predict(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
        route_labels: list[str],
    ) -> tuple[dict[str, float], float]:
        labels = route_labels or self._routing_labels
        if not labels:
            raise RuntimeError('No route labels available for routing model inference')

        token_counts = Counter(_tokenize(issue_text))
        route_scores = {label: float(self._routing_bias.get(label, 0.0)) for label in labels}

        for token, count in token_counts.items():
            label_weights = self._routing_token_weights.get(token)
            if not label_weights:
                continue
            for label, weight in label_weights.items():
                if label in route_scores:
                    route_scores[label] += weight * count

        route_probabilities = _softmax(route_scores, temperature=self._routing_temperature)
        route_probabilities = {
            label: _clamp(prob, self._routing_min_probability, self._routing_max_probability)
            for label, prob in route_probabilities.items()
        }
        route_probabilities = _normalize_probabilities(route_probabilities, labels)

        top_route_prob = max(route_probabilities.values()) if route_probabilities else 0.0
        escalation_prob = self._predict_escalation_prob(
            issue_text=issue_text,
            evidence_pack=evidence_pack,
            top_route_prob=top_route_prob,
        )

        return route_probabilities, escalation_prob

    def _predict_escalation_prob(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
        top_route_prob: float,
    ) -> float:
        tokens = _tokenize(issue_text)
        token_counts = Counter(tokens)

        top_evidence_score = _clamp(float(evidence_pack[0].score), 0.0, 1.0) if evidence_pack else 0.0
        evidence_gap = 1.0 - top_evidence_score
        long_word_ratio = len([token for token in tokens if len(token) >= 12]) / max(1, len(tokens))

        raw_score = self._escalation_bias
        raw_score += self._route_uncertainty_weight * (1.0 - _clamp(top_route_prob, 0.0, 1.0))
        raw_score += self._evidence_gap_weight * evidence_gap
        raw_score += self._long_word_ratio_weight * long_word_ratio

        for token, count in token_counts.items():
            raw_score += self._escalation_token_weights.get(token, 0.0) * count

        uncalibrated_prob = _sigmoid(raw_score)
        return self._calibrate_escalation_probability(uncalibrated_prob)

    def _calibrate_escalation_probability(self, probability: float) -> float:
        safe_probability = _clamp(probability, 1e-6, 1.0 - 1e-6)
        logit = math.log(safe_probability / (1.0 - safe_probability))
        calibrated = _sigmoid((self._escalation_calibration_a * logit) + self._escalation_calibration_b)
        return _clamp(calibrated, self._escalation_min_probability, self._escalation_max_probability)

    @staticmethod
    def _load_json(path: str, artifact_type: str) -> dict[str, Any]:
        file_path = Path(path).expanduser()
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path

        if not file_path.exists():
            raise RuntimeError(f'Missing {artifact_type} artifact: {file_path}')

        try:
            with file_path.open('r', encoding='utf-8') as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'Invalid JSON in {artifact_type} artifact: {file_path}') from exc

        if not isinstance(data, dict):
            raise RuntimeError(f'Unexpected payload in {artifact_type} artifact: {file_path}')

        return data


class HttpRoutingModelEngine:
    def __init__(
        self,
        endpoint_url: str,
        timeout_seconds: float = 2.0,
        api_key: str = '',
    ) -> None:
        self._endpoint_url = endpoint_url
        self._timeout_seconds = max(0.1, timeout_seconds)
        self._api_key = api_key.strip()

    def predict(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
        route_labels: list[str],
    ) -> tuple[dict[str, float], float]:
        payload = {
            'issue_text': issue_text,
            'route_labels': route_labels,
            'features': {
                'evidence_count': len(evidence_pack),
                'top_evidence_score': float(evidence_pack[0].score) if evidence_pack else 0.0,
            },
        }
        headers = {}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'

        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.post(self._endpoint_url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        if not isinstance(body, dict):
            raise RuntimeError('Model serving response must be a JSON object')

        route_probabilities_raw = body.get('route_probabilities')
        if not isinstance(route_probabilities_raw, dict):
            raise RuntimeError("Model serving response missing 'route_probabilities' object")

        labels = route_labels or sorted(str(label) for label in route_probabilities_raw.keys())
        route_probabilities = {
            str(label): float(probability) for label, probability in route_probabilities_raw.items()
        }
        route_probabilities = _normalize_probabilities(route_probabilities, labels)

        escalation_prob = _clamp(float(body.get('escalation_prob', 0.0)), 0.0, 1.0)
        return route_probabilities, escalation_prob


class FallbackRoutingModelEngine:
    def __init__(self, primary: RoutingModelEngine, fallback: RoutingModelEngine) -> None:
        self._primary = primary
        self._fallback = fallback
        self.last_used_fallback: bool = False

    def predict(
        self,
        issue_text: str,
        evidence_pack: list[EvidenceChunk],
        route_labels: list[str],
    ) -> tuple[dict[str, float], float]:
        self.last_used_fallback = False
        try:
            return self._primary.predict(issue_text=issue_text, evidence_pack=evidence_pack, route_labels=route_labels)
        except Exception:
            self.last_used_fallback = True
            logger.exception('Routing model backend failed. Falling back to heuristic routing model.')
            return self._fallback.predict(issue_text=issue_text, evidence_pack=evidence_pack, route_labels=route_labels)
