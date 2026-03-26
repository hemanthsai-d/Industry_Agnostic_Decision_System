from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.models.schemas import DecisionType, ResolutionProb
from app.storage.postgres_store import to_psycopg_dsn

logger = logging.getLogger(__name__)


@dataclass
class RolloutConfig:
    config_id: str
    challenger_model_name: str
    challenger_model_version: str
    canary_percent: int
    quality_gate_min_route_accuracy: float
    quality_gate_min_escalation_recall: float
    quality_gate_max_ece: float
    quality_gate_max_abstain_rate: float
    quality_gate_min_sample_size: int


class ModelOpsStore(Protocol):
    def persist_shadow_prediction(
        self,
        *,
        request_id: str,
        tenant_id: str,
        model_name: str,
        model_version: str,
        model_variant: str,
        traffic_bucket: str,
        route_probabilities: list[ResolutionProb],
        escalation_prob: float,
        final_confidence: float | None,
        decision: DecisionType | None,
        model_backend_fallback: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...

    def get_rollout_config(self) -> RolloutConfig:
        ...

    def update_canary_percent(self, canary_percent: int) -> RolloutConfig:
        ...


class NoopModelOpsStore:
    def __init__(
        self,
        *,
        challenger_model_name: str,
        challenger_model_version: str,
        canary_percent: int,
        quality_gate_min_route_accuracy: float,
        quality_gate_min_escalation_recall: float,
        quality_gate_max_ece: float,
        quality_gate_max_abstain_rate: float,
        quality_gate_min_sample_size: int,
    ) -> None:
        self._config = RolloutConfig(
            config_id='primary',
            challenger_model_name=challenger_model_name,
            challenger_model_version=challenger_model_version,
            canary_percent=max(0, min(100, int(canary_percent))),
            quality_gate_min_route_accuracy=float(quality_gate_min_route_accuracy),
            quality_gate_min_escalation_recall=float(quality_gate_min_escalation_recall),
            quality_gate_max_ece=float(quality_gate_max_ece),
            quality_gate_max_abstain_rate=float(quality_gate_max_abstain_rate),
            quality_gate_min_sample_size=max(1, int(quality_gate_min_sample_size)),
        )

    def persist_shadow_prediction(
        self,
        *,
        request_id: str,
        tenant_id: str,
        model_name: str,
        model_version: str,
        model_variant: str,
        traffic_bucket: str,
        route_probabilities: list[ResolutionProb],
        escalation_prob: float,
        final_confidence: float | None,
        decision: DecisionType | None,
        model_backend_fallback: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return

    def get_rollout_config(self) -> RolloutConfig:
        return self._config

    def update_canary_percent(self, canary_percent: int) -> RolloutConfig:
        self._config.canary_percent = max(0, min(100, int(canary_percent)))
        return self._config


class PostgresModelOpsStore:
    def __init__(
        self,
        dsn: str,
        *,
        default_rollout_config: RolloutConfig,
    ) -> None:
        self._dsn = to_psycopg_dsn(dsn)
        self._default_rollout_config = default_rollout_config

    def persist_shadow_prediction(
        self,
        *,
        request_id: str,
        tenant_id: str,
        model_name: str,
        model_version: str,
        model_variant: str,
        traffic_bucket: str,
        route_probabilities: list[ResolutionProb],
        escalation_prob: float,
        final_confidence: float | None,
        decision: DecisionType | None,
        model_backend_fallback: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        request_uuid = self._to_uuid(request_id, scope='request')
        top_route = route_probabilities[0].label if route_probabilities else None
        top_prob = float(route_probabilities[0].prob) if route_probabilities else None
        route_prob_payload = {
            route.label: float(route.prob)
            for route in route_probabilities
        }

        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO model_shadow_predictions (
                          shadow_id,
                          request_id,
                          tenant_id,
                          model_name,
                          model_version,
                          model_variant,
                          traffic_bucket,
                          route_probabilities,
                          top_resolution_path,
                          top_resolution_prob,
                          escalation_prob,
                          final_confidence,
                          decision,
                          model_backend_fallback,
                          metadata
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s
                        );
                        """,
                        (
                            uuid4(),
                            request_uuid,
                            tenant_id,
                            model_name,
                            model_version,
                            model_variant,
                            traffic_bucket,
                            Jsonb(route_prob_payload),
                            top_route,
                            top_prob,
                            float(escalation_prob),
                            float(final_confidence) if final_confidence is not None else None,
                            decision.value if decision is not None else None,
                            bool(model_backend_fallback),
                            Jsonb(metadata or {}),
                        ),
                    )
                conn.commit()
        except Exception:
            logger.exception(
                'Failed to persist shadow prediction.',
                extra={'request_id': request_id, 'tenant_id': tenant_id, 'model_variant': model_variant},
            )

    def get_rollout_config(self) -> RolloutConfig:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                          config_id,
                          challenger_model_name,
                          challenger_model_version,
                          canary_percent,
                          quality_gate_min_route_accuracy,
                          quality_gate_min_escalation_recall,
                          quality_gate_max_ece,
                          quality_gate_max_abstain_rate,
                          quality_gate_min_sample_size
                        FROM model_rollout_config
                        WHERE config_id = 'primary'
                        LIMIT 1;
                        """
                    )
                    row = cur.fetchone()

                    if row is None:
                        self._insert_default_rollout_config(cur)
                        cur.execute(
                            """
                            SELECT
                              config_id,
                              challenger_model_name,
                              challenger_model_version,
                              canary_percent,
                              quality_gate_min_route_accuracy,
                              quality_gate_min_escalation_recall,
                              quality_gate_max_ece,
                              quality_gate_max_abstain_rate,
                              quality_gate_min_sample_size
                            FROM model_rollout_config
                            WHERE config_id = 'primary'
                            LIMIT 1;
                            """
                        )
                        row = cur.fetchone()
                conn.commit()

            if row is None:
                return self._default_rollout_config

            return RolloutConfig(
                config_id=str(row['config_id']),
                challenger_model_name=str(row['challenger_model_name']),
                challenger_model_version=str(row['challenger_model_version']),
                canary_percent=max(0, min(100, int(row['canary_percent']))),
                quality_gate_min_route_accuracy=float(row['quality_gate_min_route_accuracy']),
                quality_gate_min_escalation_recall=float(row['quality_gate_min_escalation_recall']),
                quality_gate_max_ece=float(row['quality_gate_max_ece']),
                quality_gate_max_abstain_rate=float(row['quality_gate_max_abstain_rate']),
                quality_gate_min_sample_size=max(1, int(row['quality_gate_min_sample_size'])),
            )
        except Exception:
            logger.exception('Failed to fetch rollout config.')
            return self._default_rollout_config

    def update_canary_percent(self, canary_percent: int) -> RolloutConfig:
        safe_percent = max(0, min(100, int(canary_percent)))
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    self._insert_default_rollout_config(cur)
                    cur.execute(
                        """
                        UPDATE model_rollout_config
                        SET canary_percent = %s, updated_at = now()
                        WHERE config_id = 'primary'
                        RETURNING
                          config_id,
                          challenger_model_name,
                          challenger_model_version,
                          canary_percent,
                          quality_gate_min_route_accuracy,
                          quality_gate_min_escalation_recall,
                          quality_gate_max_ece,
                          quality_gate_max_abstain_rate,
                          quality_gate_min_sample_size;
                        """,
                        (safe_percent,),
                    )
                    row = cur.fetchone()
                conn.commit()

            if row is None:
                fallback = self._default_rollout_config
                fallback.canary_percent = safe_percent
                return fallback

            return RolloutConfig(
                config_id=str(row['config_id']),
                challenger_model_name=str(row['challenger_model_name']),
                challenger_model_version=str(row['challenger_model_version']),
                canary_percent=max(0, min(100, int(row['canary_percent']))),
                quality_gate_min_route_accuracy=float(row['quality_gate_min_route_accuracy']),
                quality_gate_min_escalation_recall=float(row['quality_gate_min_escalation_recall']),
                quality_gate_max_ece=float(row['quality_gate_max_ece']),
                quality_gate_max_abstain_rate=float(row['quality_gate_max_abstain_rate']),
                quality_gate_min_sample_size=max(1, int(row['quality_gate_min_sample_size'])),
            )
        except Exception:
            logger.exception('Failed to update canary percent.', extra={'canary_percent': safe_percent})
            fallback = self._default_rollout_config
            fallback.canary_percent = safe_percent
            return fallback

    def _insert_default_rollout_config(self, cur: psycopg.Cursor) -> None:
        default = self._default_rollout_config
        cur.execute(
            """
            INSERT INTO model_rollout_config (
              config_id,
              challenger_model_name,
              challenger_model_version,
              canary_percent,
              quality_gate_min_route_accuracy,
              quality_gate_min_escalation_recall,
              quality_gate_max_ece,
              quality_gate_max_abstain_rate,
              quality_gate_min_sample_size
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (config_id) DO NOTHING;
            """,
            (
                default.config_id,
                default.challenger_model_name,
                default.challenger_model_version,
                int(default.canary_percent),
                float(default.quality_gate_min_route_accuracy),
                float(default.quality_gate_min_escalation_recall),
                float(default.quality_gate_max_ece),
                float(default.quality_gate_max_abstain_rate),
                int(default.quality_gate_min_sample_size),
            ),
        )

    @staticmethod
    def _to_uuid(raw: str, scope: str) -> UUID:
        try:
            return UUID(raw)
        except ValueError:
            return uuid5(NAMESPACE_URL, f'{scope}:{raw}')
