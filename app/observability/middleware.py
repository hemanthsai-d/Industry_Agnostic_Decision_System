from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.observability.context import reset_request_id, set_request_id
from app.observability.metrics import observe_http_error, observe_http_request

logger = logging.getLogger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str = 'decision-api'):
        super().__init__(app)
        self._service_name = service_name

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('x-request-id') or uuid4().hex
        method = request.method
        path = request.url.path
        start_time = time.perf_counter()

        token = set_request_id(request_id)
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers['x-request-id'] = request_id
            return response
        except Exception as exc:
            observe_http_error(
                service=self._service_name,
                method=method,
                path=path,
                error_type=type(exc).__name__,
            )
            logger.exception(
                'http_request_failed',
                extra={
                    'service': self._service_name,
                    'method': method,
                    'path': path,
                    'status_code': status_code,
                },
            )
            raise
        finally:
            duration = time.perf_counter() - start_time
            observe_http_request(
                service=self._service_name,
                method=method,
                path=path,
                status_code=status_code,
                duration_seconds=duration,
            )
            logger.info(
                'http_request',
                extra={
                    'service': self._service_name,
                    'method': method,
                    'path': path,
                    'status_code': status_code,
                    'duration_ms': round(duration * 1000.0, 2),
                },
            )
            reset_request_id(token)
