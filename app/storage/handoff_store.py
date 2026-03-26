from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.models.schemas import DecisionType, HandoffListResponse, HandoffPayload, HandoffQueueItem, HandoffQueueStatus
from app.storage.postgres_store import to_psycopg_dsn

logger = logging.getLogger(__name__)


class HandoffStore(Protocol):
    def list_handoffs(
        self,
        tenant_id: str,
        queue_status: HandoffQueueStatus | None = None,
        limit: int = 50,
    ) -> HandoffListResponse:
        ...

    def update_queue_status(
        self,
        tenant_id: str,
        handoff_id: str,
        queue_status: HandoffQueueStatus,
        reviewer_id: str | None = None,
        final_decision: DecisionType | None = None,
        final_resolution_path: str | None = None,
        notes: str | None = None,
    ) -> tuple[HandoffQueueItem | None, bool]:
        ...


class NoopHandoffStore:
    def list_handoffs(
        self,
        tenant_id: str,
        queue_status: HandoffQueueStatus | None = None,
        limit: int = 50,
    ) -> HandoffListResponse:
        return HandoffListResponse(items=[])

    def update_queue_status(
        self,
        tenant_id: str,
        handoff_id: str,
        queue_status: HandoffQueueStatus,
        reviewer_id: str | None = None,
        final_decision: DecisionType | None = None,
        final_resolution_path: str | None = None,
        notes: str | None = None,
    ) -> tuple[HandoffQueueItem | None, bool]:
        return None, False


class PostgresHandoffStore:
    def __init__(self, dsn: str):
        self._dsn = to_psycopg_dsn(dsn)

    def list_handoffs(
        self,
        tenant_id: str,
        queue_status: HandoffQueueStatus | None = None,
        limit: int = 50,
    ) -> HandoffListResponse:
        safe_limit = max(1, min(200, int(limit)))
        status_value = queue_status.value if queue_status is not None else None

        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT handoff_id, request_id, tenant_id, reason_codes, handoff_payload, queue_status, created_at
                    FROM handoffs
                    WHERE tenant_id = %s
                      AND (%s IS NULL OR queue_status = %s)
                    ORDER BY created_at DESC
                    LIMIT %s;
                    """,
                    (tenant_id, status_value, status_value, safe_limit),
                )
                rows = cur.fetchall()

        items: list[HandoffQueueItem] = []
        for row in rows:
            item = self._row_to_item(dict(row))
            if item is not None:
                items.append(item)
        return HandoffListResponse(items=items)

    def update_queue_status(
        self,
        tenant_id: str,
        handoff_id: str,
        queue_status: HandoffQueueStatus,
        reviewer_id: str | None = None,
        final_decision: DecisionType | None = None,
        final_resolution_path: str | None = None,
        notes: str | None = None,
    ) -> tuple[HandoffQueueItem | None, bool]:
        if queue_status == HandoffQueueStatus.closed:
            if not (reviewer_id and final_decision is not None and final_resolution_path):
                raise ValueError(
                    'Closing a ticket requires reviewer_id, final_decision, and final_resolution_path '
                    'to ensure ground truth is captured.',
                )

        handoff_uuid = self._to_uuid(handoff_id, scope='handoff')
        ground_truth_recorded = False

        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE handoffs
                    SET queue_status = %s
                    WHERE handoff_id = %s
                      AND tenant_id = %s
                    RETURNING handoff_id, request_id, tenant_id, reason_codes, handoff_payload, queue_status, created_at;
                    """,
                    (queue_status.value, handoff_uuid, tenant_id),
                )
                row = cur.fetchone()

                if row is None:
                    conn.commit()
                    return None, False

                item = self._row_to_item(dict(row))
                if item is None:
                    raise RuntimeError('Failed to parse updated handoff row from storage.')

                should_capture_outcome = queue_status in {HandoffQueueStatus.resolved, HandoffQueueStatus.closed}
                has_outcome_fields = bool(reviewer_id and final_decision is not None and final_resolution_path)

                if should_capture_outcome and has_outcome_fields:
                    request_uuid = self._to_uuid(str(row['request_id']), scope='request')
                    resolution_seconds = self._resolution_seconds(row.get('created_at'))
                    payload = {
                        'handoff_id': str(row['handoff_id']),
                        'request_id': str(row['request_id']),
                        'tenant_id': tenant_id,
                        'queue_status': queue_status.value,
                        'reviewer_id': reviewer_id,
                        'final_decision': final_decision.value,
                        'final_resolution_path': final_resolution_path,
                        'notes': notes,
                        'resolution_seconds': resolution_seconds,
                    }

                    cur.execute(
                        """
                        INSERT INTO reviewer_outcomes (
                          outcome_id,
                          handoff_id,
                          request_id,
                          tenant_id,
                          reviewer_id,
                          final_decision,
                          final_resolution_path,
                          notes,
                          resolution_seconds,
                          payload
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            uuid4(),
                            self._to_uuid(str(row['handoff_id']), scope='handoff'),
                            request_uuid,
                            tenant_id,
                            reviewer_id,
                            final_decision.value,
                            final_resolution_path,
                            notes,
                            resolution_seconds,
                            Jsonb(payload),
                        ),
                    )

                    cur.execute(
                        """
                        INSERT INTO feedback_events (
                          event_id,
                          request_id_text,
                          request_id_uuid,
                          tenant_id,
                          accepted_decision,
                          corrected_resolution_path,
                          notes,
                          payload
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            uuid4(),
                            str(row['request_id']),
                            request_uuid,
                            tenant_id,
                            final_decision.value,
                            final_resolution_path,
                            notes,
                            Jsonb(
                                {
                                    **payload,
                                    'source': 'handoff_reviewer_outcome',
                                }
                            ),
                        ),
                    )
                    ground_truth_recorded = True

            conn.commit()

        return item, ground_truth_recorded

    @staticmethod
    def _row_to_item(row: dict) -> HandoffQueueItem | None:
        try:
            payload = row.get('handoff_payload')
            if not isinstance(payload, dict):
                return None
            handoff_payload = HandoffPayload.model_validate(payload)
            return HandoffQueueItem(
                handoff_id=str(row['handoff_id']),
                request_id=str(row['request_id']),
                tenant_id=str(row['tenant_id']),
                queue_status=HandoffQueueStatus(str(row['queue_status'])),
                reason_codes=list(row.get('reason_codes') or []),
                handoff_payload=handoff_payload,
                created_at=str(row['created_at']),
            )
        except Exception:
            logger.exception(
                'Failed to parse handoff row from storage.',
                extra={'handoff_id': str(row.get('handoff_id', ''))},
            )
            return None

    @staticmethod
    def _resolution_seconds(created_at: object) -> int | None:
        if created_at is None:
            return None

        parsed: datetime | None = None
        if isinstance(created_at, datetime):
            parsed = created_at
        elif isinstance(created_at, str):
            try:
                parsed = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except ValueError:
                parsed = None

        if parsed is None:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        elapsed = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        return max(0, int(elapsed.total_seconds()))

    @staticmethod
    def _to_uuid(raw: str, scope: str) -> UUID:
        try:
            return UUID(raw)
        except ValueError:
            return uuid5(NAMESPACE_URL, f'{scope}:{raw}')
