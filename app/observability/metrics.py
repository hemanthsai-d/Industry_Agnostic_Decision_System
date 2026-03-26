from __future__ import annotations

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Summary, generate_latest

# ── Core HTTP metrics ────────────────────────────────────────────────
HTTP_REQUESTS_TOTAL = Counter(
    'assist_http_requests_total',
    'Total HTTP requests handled by service.',
    labelnames=('service', 'method', 'path', 'status'),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    'assist_http_request_duration_seconds',
    'HTTP request latency distribution in seconds.',
    labelnames=('service', 'method', 'path'),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0),
)
HTTP_REQUEST_ERRORS_TOTAL = Counter(
    'assist_http_request_errors_total',
    'Total HTTP request exceptions.',
    labelnames=('service', 'method', 'path', 'error_type'),
)

# ── Decision pipeline metrics ────────────────────────────────────────
DECISIONS_TOTAL = Counter(
    'assist_decisions_total',
    'Decision outcomes emitted by orchestrator.',
    labelnames=('service', 'decision'),
)
HANDOFFS_TOTAL = Counter(
    'assist_handoffs_total',
    'Handoff workflow outcomes.',
    labelnames=('service', 'workflow_started'),
)
DECISION_CACHE_HITS_TOTAL = Counter(
    'assist_decision_cache_hits_total',
    'Decision requests served from persisted idempotency cache.',
    labelnames=('service',),
)
RATE_LIMIT_EXCEEDED_TOTAL = Counter(
    'assist_rate_limit_exceeded_total',
    'Rate limit rejections.',
    labelnames=('service', 'scope', 'action'),
)
MODEL_GUARDRAIL_FALLBACK_TOTAL = Counter(
    'assist_model_guardrail_fallback_total',
    'Forced handoffs triggered by model guardrails.',
    labelnames=('service', 'reason', 'model_variant'),
)
SHADOW_PREDICTIONS_TOTAL = Counter(
    'assist_shadow_predictions_total',
    'Shadow/canary challenger predictions logged.',
    labelnames=('service', 'model_variant', 'traffic_bucket'),
)
ISSUE_TEXT_TOKEN_COUNT = Histogram(
    'assist_issue_text_token_count',
    'Issue text token-count distribution for input drift monitoring.',
    labelnames=('service',),
    buckets=(1, 3, 5, 8, 12, 16, 24, 32, 48, 64, 96, 128),
)
DECISION_CONFIDENCE = Histogram(
    'assist_decision_confidence',
    'Final decision confidence distribution.',
    labelnames=('service', 'model_variant'),
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
)

# ── Pipeline stage latency (p50/p95/p99 per stage) ──────────────────
PIPELINE_STAGE_DURATION = Histogram(
    'assist_pipeline_stage_duration_seconds',
    'Per-stage latency inside the decide pipeline.',
    labelnames=('service', 'stage'),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
)
PIPELINE_TOTAL_DURATION = Histogram(
    'assist_pipeline_total_duration_seconds',
    'End-to-end decide() wall time (excludes HTTP overhead).',
    labelnames=('service',),
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0),
)

# ── Throughput gauge ─────────────────────────────────────────────────
INFLIGHT_REQUESTS = Gauge(
    'assist_inflight_requests',
    'Currently in-flight /v1/assist/decide requests.',
    labelnames=('service',),
)

# ── Cost tracking ────────────────────────────────────────────────────
REQUEST_COST_DOLLARS = Histogram(
    'assist_request_cost_dollars',
    'Estimated cost per decision request (USD).',
    labelnames=('service', 'generation_backend'),
    buckets=(0.0, 0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05),
)

# ── Model evaluation metrics ────────────────────────────────────────
ROUTING_ACCURACY = Gauge(
    'assist_routing_accuracy',
    'Latest batch routing accuracy (updated by daily eval job).',
    labelnames=('service', 'model_variant'),
)
CALIBRATION_ECE = Gauge(
    'assist_calibration_ece',
    'Expected Calibration Error from latest evaluation.',
    labelnames=('service', 'model_variant'),
)
ABSTAIN_RATE = Gauge(
    'assist_abstain_rate',
    'Fraction of decisions that were abstain.',
    labelnames=('service',),
)

# ── RAG quality metrics (observed per-request) ───────────────────────
RAG_FAITHFULNESS = Histogram(
    'assist_rag_faithfulness',
    'Per-request faithfulness score (bigram grounding).',
    labelnames=('service',),
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
RAG_HALLUCINATION_RATIO = Histogram(
    'assist_rag_hallucination_ratio',
    'Per-request hallucination ratio (ungrounded tokens / total).',
    labelnames=('service',),
    buckets=(0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0),
)
RAG_CITATION_COVERAGE = Histogram(
    'assist_rag_citation_coverage',
    'Per-request citation coverage (fraction of sentences with citations).',
    labelnames=('service',),
    buckets=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
)
RETRIEVAL_EVIDENCE_SCORE = Histogram(
    'assist_retrieval_evidence_score',
    'Per-request mean evidence relevance score.',
    labelnames=('service',),
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

# ── Prompt injection metrics ─────────────────────────────────────────
INJECTION_DETECTIONS_TOTAL = Counter(
    'assist_injection_detections_total',
    'Prompt injection scan outcomes.',
    labelnames=('service', 'source', 'action'),
)

# ── Circuit breaker metrics ──────────────────────────────────────────
CIRCUIT_BREAKER_STATE = Gauge(
    'assist_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half_open).',
    labelnames=('service', 'target'),
)
CIRCUIT_BREAKER_TRIPS_TOTAL = Counter(
    'assist_circuit_breaker_trips_total',
    'Total circuit breaker trip events.',
    labelnames=('service', 'target'),
)


def observe_http_request(service: str, method: str, path: str, status_code: int, duration_seconds: float) -> None:
    HTTP_REQUESTS_TOTAL.labels(
        service=service,
        method=method,
        path=path,
        status=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        service=service,
        method=method,
        path=path,
    ).observe(max(0.0, float(duration_seconds)))


def observe_http_error(service: str, method: str, path: str, error_type: str) -> None:
    HTTP_REQUEST_ERRORS_TOTAL.labels(
        service=service,
        method=method,
        path=path,
        error_type=error_type,
    ).inc()


def observe_decision(decision: str, service: str = 'decision-api') -> None:
    DECISIONS_TOTAL.labels(service=service, decision=decision).inc()


def observe_handoff(workflow_started: bool, service: str = 'decision-api') -> None:
    HANDOFFS_TOTAL.labels(
        service=service,
        workflow_started='true' if workflow_started else 'false',
    ).inc()


def observe_decision_cache_hit(service: str = 'decision-api') -> None:
    DECISION_CACHE_HITS_TOTAL.labels(service=service).inc()


def observe_rate_limit_exceeded(scope: str, action: str, service: str = 'decision-api') -> None:
    RATE_LIMIT_EXCEEDED_TOTAL.labels(
        service=service,
        scope=str(scope),
        action=str(action),
    ).inc()


def observe_model_guardrail_fallback(
    reason: str,
    model_variant: str,
    service: str = 'decision-api',
) -> None:
    MODEL_GUARDRAIL_FALLBACK_TOTAL.labels(
        service=service,
        reason=str(reason),
        model_variant=str(model_variant or 'unknown'),
    ).inc()


def observe_shadow_prediction(model_variant: str, traffic_bucket: str, service: str = 'decision-api') -> None:
    SHADOW_PREDICTIONS_TOTAL.labels(
        service=service,
        model_variant=str(model_variant or 'challenger'),
        traffic_bucket=str(traffic_bucket or 'shadow'),
    ).inc()


def observe_issue_text_tokens(issue_text: str, service: str = 'decision-api') -> None:
    token_count = max(1, len([token for token in str(issue_text or '').split() if token]))
    ISSUE_TEXT_TOKEN_COUNT.labels(service=service).observe(float(token_count))


def observe_decision_confidence(confidence: float, model_variant: str, service: str = 'decision-api') -> None:
    bounded = max(0.0, min(1.0, float(confidence)))
    DECISION_CONFIDENCE.labels(service=service, model_variant=str(model_variant or 'primary')).observe(bounded)


# ── Stage-level instrumentation ──────────────────────────────────────

def observe_pipeline_stage(stage: str, duration_seconds: float, service: str = 'decision-api') -> None:
    PIPELINE_STAGE_DURATION.labels(service=service, stage=stage).observe(max(0.0, float(duration_seconds)))


def observe_pipeline_total(duration_seconds: float, service: str = 'decision-api') -> None:
    PIPELINE_TOTAL_DURATION.labels(service=service).observe(max(0.0, float(duration_seconds)))


def track_inflight(delta: int, service: str = 'decision-api') -> None:
    if delta > 0:
        INFLIGHT_REQUESTS.labels(service=service).inc(delta)
    elif delta < 0:
        INFLIGHT_REQUESTS.labels(service=service).dec(abs(delta))


def observe_request_cost(cost_usd: float, generation_backend: str = 'template', service: str = 'decision-api') -> None:
    REQUEST_COST_DOLLARS.labels(service=service, generation_backend=generation_backend).observe(max(0.0, float(cost_usd)))


# ── Evaluation batch metrics ─────────────────────────────────────────

def set_routing_accuracy(accuracy: float, model_variant: str = 'primary', service: str = 'decision-api') -> None:
    ROUTING_ACCURACY.labels(service=service, model_variant=model_variant).set(max(0.0, min(1.0, float(accuracy))))


def set_calibration_ece(ece: float, model_variant: str = 'primary', service: str = 'decision-api') -> None:
    CALIBRATION_ECE.labels(service=service, model_variant=model_variant).set(max(0.0, float(ece)))


def set_abstain_rate(rate: float, service: str = 'decision-api') -> None:
    ABSTAIN_RATE.labels(service=service).set(max(0.0, min(1.0, float(rate))))


# ── RAG quality per-request ──────────────────────────────────────────

def observe_rag_faithfulness(score: float, service: str = 'decision-api') -> None:
    RAG_FAITHFULNESS.labels(service=service).observe(max(0.0, min(1.0, float(score))))


def observe_rag_hallucination(ratio: float, service: str = 'decision-api') -> None:
    RAG_HALLUCINATION_RATIO.labels(service=service).observe(max(0.0, min(1.0, float(ratio))))


def observe_rag_citation_coverage(coverage: float, service: str = 'decision-api') -> None:
    RAG_CITATION_COVERAGE.labels(service=service).observe(max(0.0, min(1.0, float(coverage))))


def observe_retrieval_evidence_score(mean_score: float, service: str = 'decision-api') -> None:
    RETRIEVAL_EVIDENCE_SCORE.labels(service=service).observe(max(0.0, min(1.0, float(mean_score))))


# ── Prompt injection ─────────────────────────────────────────────────

def observe_injection_detection(source: str, action: str, service: str = 'decision-api') -> None:
    """source: 'user_input' | 'evidence_chunk', action: 'blocked' | 'filtered' | 'passed'"""
    INJECTION_DETECTIONS_TOTAL.labels(service=service, source=source, action=action).inc()


# ── Circuit breaker ──────────────────────────────────────────────────

def set_circuit_breaker_state(target: str, state_code: int, service: str = 'decision-api') -> None:
    CIRCUIT_BREAKER_STATE.labels(service=service, target=target).set(state_code)


def observe_circuit_breaker_trip(target: str, service: str = 'decision-api') -> None:
    CIRCUIT_BREAKER_TRIPS_TOTAL.labels(service=service, target=target).inc()


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
