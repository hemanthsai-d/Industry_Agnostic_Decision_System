from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, Field


class EventMessage(BaseModel):
    event_type: str
    tenant_id: str
    request_id: str
    trace_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    emitted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EventBus(Protocol):
    async def publish(self, event: EventMessage) -> None:
        ...


class NoopEventBus:
    async def publish(self, event: EventMessage) -> None:
        return


class RetryingEventBus:
    def __init__(
        self,
        delegate: EventBus,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.25,
    ) -> None:
        self._delegate = delegate
        self._retry_attempts = max(1, retry_attempts)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    async def publish(self, event: EventMessage) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                await self._delegate.publish(event)
                return
            except Exception as exc:  # pragma: no cover - behavior verified via tests
                last_error = exc
                if attempt == self._retry_attempts:
                    raise
                await asyncio.sleep(self._retry_backoff_seconds * attempt)

        if last_error is not None:  # pragma: no cover
            raise last_error


class PubSubEventBus:
    def __init__(
        self,
        project_id: str,
        topic: str,
        publish_timeout_seconds: float = 5.0,
    ) -> None:
        self._project_id = project_id
        self._topic = topic
        self._publish_timeout_seconds = max(0.1, publish_timeout_seconds)
        self._publisher = None

    def _publisher_client(self):
        if self._publisher is not None:
            return self._publisher
        try:
            from google.cloud import pubsub_v1
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError('Pub/Sub backend requires google-cloud-pubsub package') from exc

        self._publisher = pubsub_v1.PublisherClient()
        return self._publisher

    async def publish(self, event: EventMessage) -> None:
        publisher = self._publisher_client()
        topic_path = publisher.topic_path(self._project_id, self._topic)
        payload = json.dumps(event.model_dump(mode='json'), separators=(',', ':'), sort_keys=True).encode('utf-8')

        future = publisher.publish(
            topic_path,
            payload,
            event_type=event.event_type,
            tenant_id=event.tenant_id,
            request_id=event.request_id,
            trace_id=event.trace_id,
        )
        await asyncio.to_thread(future.result, timeout=self._publish_timeout_seconds)
