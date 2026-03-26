from __future__ import annotations

import logging
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from app.models.schemas import DecideRequest, DecideResponse
from app.storage.postgres_store import to_psycopg_dsn

logger = logging.getLogger(__name__)


class InferenceStore(Protocol):
    def fetch(self, req: DecideRequest) -> DecideResponse | None:
        ...

    def persist(self, req: DecideRequest, res: DecideResponse) -> None:
        ...


class NoopInferenceStore:
    def fetch(self, req: DecideRequest) -> DecideResponse | None:
        return None

    def persist(self, req: DecideRequest, res: DecideResponse) -> None:
        return


class PostgresInferenceStore:
    def __init__(self, dsn: str):
        self._dsn = to_psycopg_dsn(dsn)

    def fetch(self, req: DecideRequest) -> DecideResponse | None:
        request_uuid = self._to_uuid(req.request_id, scope="request")

        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT inf_res.response_payload
                        FROM inference_requests inf_req
                        JOIN inference_results inf_res
                          ON inf_res.request_id = inf_req.request_id
                        WHERE inf_req.request_id = %s
                          AND inf_req.tenant_id = %s
                          AND ((inf_req.section IS NULL AND %s IS NULL) OR inf_req.section = %s)
                          AND inf_req.issue_text = %s
                          AND inf_req.risk_level = %s
                          AND inf_req.context = %s::jsonb
                        LIMIT 1;
                        """,
                        (
                            request_uuid,
                            req.tenant_id,
                            req.section,
                            req.section,
                            req.issue_text,
                            req.risk_level.value,
                            Jsonb(req.context),
                        ),
                    )
                    row = cur.fetchone()

            if row is None:
                return None

            payload = row[0]
            if not isinstance(payload, dict):
                return None
            return DecideResponse.model_validate(payload)
        except Exception:
            logger.exception(
                'Failed to fetch cached inference result.',
                extra={'request_id': req.request_id},
            )
            return None

    def persist(self, req: DecideRequest, res: DecideResponse) -> None:
        request_uuid = self._to_uuid(req.request_id, scope="request")
        top_path = res.resolution_path_probs[0].label if res.resolution_path_probs else None
        top_prob = float(res.resolution_path_probs[0].prob) if res.resolution_path_probs else None

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
                        INSERT INTO inference_requests (
                          request_id, tenant_id, section, issue_text, risk_level, context
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (request_id) DO UPDATE SET
                          tenant_id = EXCLUDED.tenant_id,
                          section = EXCLUDED.section,
                          issue_text = EXCLUDED.issue_text,
                          risk_level = EXCLUDED.risk_level,
                          context = EXCLUDED.context;
                        """,
                        (
                            request_uuid,
                            req.tenant_id,
                            req.section,
                            req.issue_text,
                            req.risk_level.value,
                            Jsonb(req.context),
                        ),
                    )

                    cur.execute(
                        """
                        INSERT INTO inference_results (
                          request_id, decision, top_resolution_path, top_resolution_prob, escalation_prob,
                          final_confidence, trace_id, policy_result, response_payload,
                          model_variant, model_backend_fallback,
                          detected_intent, detected_category, pii_redacted
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (request_id) DO UPDATE SET
                          decision = EXCLUDED.decision,
                          top_resolution_path = EXCLUDED.top_resolution_path,
                          top_resolution_prob = EXCLUDED.top_resolution_prob,
                          escalation_prob = EXCLUDED.escalation_prob,
                          final_confidence = EXCLUDED.final_confidence,
                          trace_id = EXCLUDED.trace_id,
                          policy_result = EXCLUDED.policy_result,
                          response_payload = EXCLUDED.response_payload,
                          model_variant = EXCLUDED.model_variant,
                          model_backend_fallback = EXCLUDED.model_backend_fallback,
                          detected_intent = EXCLUDED.detected_intent,
                          detected_category = EXCLUDED.detected_category,
                          pii_redacted = EXCLUDED.pii_redacted;
                        """,
                        (
                            request_uuid,
                            res.decision.value,
                            top_path,
                            top_prob,
                            float(res.escalation_prob),
                            float(res.confidence.final),
                            res.trace_id,
                            Jsonb(res.policy_result.model_dump(mode="json")),
                            Jsonb(res.model_dump(mode="json")),
                            res.model_variant,
                            bool(res.model_backend_fallback),
                            res.detected_intent,
                            res.detected_category,
                            bool(res.pii_redacted),
                        ),
                    )

                    if res.handoff_payload is not None:
                        handoff_uuid = self._to_uuid(res.handoff_payload.handoff_id, scope="handoff")
                        cur.execute(
                            """
                            INSERT INTO handoffs (
                              handoff_id, request_id, tenant_id, reason_codes, handoff_payload, queue_status
                            )
                            VALUES (%s, %s, %s, %s, %s, 'open')
                            ON CONFLICT (handoff_id) DO UPDATE SET
                              request_id = EXCLUDED.request_id,
                              tenant_id = EXCLUDED.tenant_id,
                              reason_codes = EXCLUDED.reason_codes,
                              handoff_payload = EXCLUDED.handoff_payload;
                            """,
                            (
                                handoff_uuid,
                                request_uuid,
                                req.tenant_id,
                                res.handoff_payload.reason_codes,
                                Jsonb(res.handoff_payload.model_dump(mode="json")),
                            ),
                        )
                conn.commit()
        except Exception:
            logger.exception('Failed to persist inference result.', extra={'request_id': req.request_id})
            return

    @staticmethod
    def _to_uuid(raw: str, scope: str) -> UUID:
        try:
            return UUID(raw)
        except ValueError:
            return uuid5(NAMESPACE_URL, f"{scope}:{raw}")
