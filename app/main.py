from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings
from app.observability import ObservabilityMiddleware, configure_logging, configure_tracing, metrics_response

settings = get_settings()

configure_logging(log_level=settings.log_level, log_format=settings.observability_log_format)

app = FastAPI(
    title=settings.app_name,
    version='0.1.0',
    description='Industry-agnostic agent-assist decision platform.',
)
app.add_middleware(ObservabilityMiddleware, service_name=settings.observability_service_name)

if settings.metrics_enabled:

    @app.get('/metrics', include_in_schema=False)
    async def metrics():
        return metrics_response()


configure_tracing(
    app,
    enabled=settings.tracing_enabled,
    service_name=settings.observability_service_name,
    environment=settings.app_env,
    otlp_endpoint=settings.otlp_endpoint,
    otlp_insecure=settings.otlp_insecure,
    sample_ratio=settings.trace_sample_ratio,
)

app.include_router(router)
