from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.observability.context import get_request_id

_STANDARD_ATTRS = {
    'name',
    'msg',
    'args',
    'levelname',
    'levelno',
    'pathname',
    'filename',
    'module',
    'exc_info',
    'exc_text',
    'stack_info',
    'lineno',
    'funcName',
    'created',
    'msecs',
    'relativeCreated',
    'thread',
    'threadName',
    'processName',
    'process',
    'message',
    'asctime',
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        request_id = get_request_id()
        if request_id:
            payload['request_id'] = request_id

        trace_id, span_id = _current_trace_context()
        if trace_id:
            payload['trace_id'] = trace_id
        if span_id:
            payload['span_id'] = span_id

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and not key.startswith('_')
        }
        if extras:
            payload.update(extras)

        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(',', ':'))


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = get_request_id()
        prefix = f'[{request_id}] ' if request_id else ''
        base = f'{record.levelname} {record.name} {prefix}{record.getMessage()}'
        if record.exc_info:
            return f'{base}\n{self.formatException(record.exc_info)}'
        return base


def configure_logging(log_level: str, log_format: str = 'json') -> None:
    level = getattr(logging, str(log_level).upper(), logging.INFO)

    handler = logging.StreamHandler()
    formatter: logging.Formatter
    if str(log_format).lower() == 'plain':
        formatter = PlainFormatter()
    else:
        formatter = JsonFormatter()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for logger_name in ('uvicorn', 'uvicorn.access', 'uvicorn.error'):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler]
        logger.setLevel(level)
        logger.propagate = False


def _current_trace_context() -> tuple[str, str]:
    try:
        from opentelemetry import trace
    except Exception:
        return '', ''

    span = trace.get_current_span()
    if span is None:
        return '', ''

    span_context = span.get_span_context()
    if not span_context or not span_context.is_valid:
        return '', ''

    trace_id = format(span_context.trace_id, '032x')
    span_id = format(span_context.span_id, '016x')
    return trace_id, span_id
