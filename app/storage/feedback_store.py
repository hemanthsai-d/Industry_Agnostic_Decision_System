from __future__ import annotations

import logging
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from psycopg.types.json import Jsonb

from app.models.schemas import FeedbackRequest
from app.storage.postgres_store import to_psycopg_dsn

logger = logging.getLogger(__name__)


class FeedbackStore(Protocol):
    def persist(self, req: FeedbackRequest) -> None:
        ...


class NoopFeedbackStore:
    def persist(self, req: FeedbackRequest) -> None:
        return


class PostgresFeedbackStore:
    def __init__(self, dsn: str):
        self._dsn = to_psycopg_dsn(dsn)

    def persist(self, req: FeedbackRequest) -> None:
        request_uuid = self._to_uuid(req.request_id)
        event_id = uuid4()
        accepted_decision = req.accepted_decision.value if req.accepted_decision is not None else None

        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tenants (tenant_id, name, status)
                        VALUES (%s, %s, 'active')
                        ON CONFLICT (tenant_id) DO NOTHING;
                        """,
                        (req.tenant_id, req.tenant_id.replace("_", " ").title()),
                    )

                    cur.execute(
                        """
                        INSERT INTO feedback_events (
                          event_id, request_id_text, request_id_uuid, tenant_id, accepted_decision,
                          corrected_resolution_path, notes, payload
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            event_id,
                            req.request_id,
                            request_uuid,
                            req.tenant_id,
                            accepted_decision,
                            req.corrected_resolution_path,
                            req.notes,
                            Jsonb(req.model_dump(mode="json")),
                        ),
                    )
                conn.commit()
        except Exception:
            logger.exception('Failed to persist feedback event.', extra={'request_id': req.request_id})
            return

    @staticmethod
    def _to_uuid(raw: str) -> UUID:
        try:
            return UUID(raw)
        except ValueError:
            return uuid5(NAMESPACE_URL, f"feedback-request:{raw}")
