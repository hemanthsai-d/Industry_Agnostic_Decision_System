from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def configure_tracing(
    app,
    *,
    enabled: bool,
    service_name: str,
    environment: str,
    otlp_endpoint: str,
    otlp_insecure: bool,
    sample_ratio: float,
) -> None:
    if not enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except Exception:
        logger.exception('Tracing enabled but OpenTelemetry packages are missing. Install optional deps.')
        return

    resource = Resource.create(
        {
            'service.name': service_name,
            'deployment.environment': environment,
        }
    )
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(max(0.0, min(1.0, float(sample_ratio)))),
    )
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=bool(otlp_insecure),
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)

    logger.info(
        'tracing_enabled',
        extra={
            'service': service_name,
            'otlp_endpoint': otlp_endpoint,
            'sample_ratio': sample_ratio,
        },
    )
