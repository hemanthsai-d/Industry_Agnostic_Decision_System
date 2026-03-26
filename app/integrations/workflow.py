from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Protocol

from app.models.schemas import HandoffPayload


class HandoffWorkflowEngine(Protocol):
    async def start_handoff(
        self,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
        handoff_payload: HandoffPayload,
    ) -> str | None:
        ...


class NoopHandoffWorkflowEngine:
    async def start_handoff(
        self,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
        handoff_payload: HandoffPayload,
    ) -> str | None:
        return None


class RetryingHandoffWorkflowEngine:
    def __init__(
        self,
        delegate: HandoffWorkflowEngine,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._delegate = delegate
        self._retry_attempts = max(1, retry_attempts)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    async def start_handoff(
        self,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
        handoff_payload: HandoffPayload,
    ) -> str | None:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await self._delegate.start_handoff(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    handoff_payload=handoff_payload,
                )
            except Exception as exc:  # pragma: no cover - behavior verified via tests
                last_error = exc
                if attempt == self._retry_attempts:
                    raise
                await asyncio.sleep(self._retry_backoff_seconds * attempt)

        if last_error is not None:  # pragma: no cover
            raise last_error
        return None


class TemporalHandoffWorkflowEngine:
    def __init__(
        self,
        target_host: str,
        namespace: str,
        task_queue: str,
        workflow_name: str,
        workflow_retry_attempts: int = 5,
        workflow_retry_initial_interval_seconds: float = 1.0,
    ) -> None:
        self._target_host = target_host
        self._namespace = namespace
        self._task_queue = task_queue
        self._workflow_name = workflow_name
        self._workflow_retry_attempts = max(1, workflow_retry_attempts)
        self._workflow_retry_initial_interval_seconds = max(0.1, workflow_retry_initial_interval_seconds)
        self._client = None

    async def _client_instance(self):
        if self._client is not None:
            return self._client
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError('Temporal backend requires temporalio package') from exc

        self._client = await Client.connect(self._target_host, namespace=self._namespace)
        return self._client

    async def start_handoff(
        self,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
        handoff_payload: HandoffPayload,
    ) -> str | None:
        client = await self._client_instance()

        retry_policy = None
        try:
            from temporalio.common import RetryPolicy

            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=self._workflow_retry_initial_interval_seconds),
                maximum_attempts=self._workflow_retry_attempts,
                backoff_coefficient=2.0,
            )
        except Exception:
            retry_policy = None

        workflow_id = f'handoff-{handoff_payload.handoff_id}'
        start_kwargs = {
            'id': workflow_id,
            'task_queue': self._task_queue,
        }
        if retry_policy is not None:
            start_kwargs['retry_policy'] = retry_policy

        await client.start_workflow(
            self._workflow_name,
            {
                'tenant_id': tenant_id,
                'request_id': request_id,
                'trace_id': trace_id,
                'handoff': handoff_payload.model_dump(mode='json'),
            },
            **start_kwargs,
        )
        return workflow_id
