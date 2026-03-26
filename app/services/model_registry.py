"""Model registry and lineage tracking.

Tracks which model version is deployed, what data it was trained on,
when it was promoted, and the full lineage from training → shadow →
canary → production.

Supports compliance requirements (SOC2, ISO 27001) for model governance.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ModelStage(str, Enum):
    DEVELOPMENT = 'development'
    SHADOW = 'shadow'
    CANARY = 'canary'
    PRODUCTION = 'production'
    ARCHIVED = 'archived'
    ROLLBACK = 'rollback'


class ArtifactType(str, Enum):
    ROUTING_MODEL = 'routing_model'
    ESCALATION_MODEL = 'escalation_model'
    CALIBRATION = 'calibration'
    EMBEDDING_MODEL = 'embedding_model'
    GENERATION_MODEL = 'generation_model'


@dataclass(frozen=True)
class ModelArtifact:
    """A versioned model artifact with full provenance."""
    artifact_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ''
    version: str = 'v1'
    artifact_type: ArtifactType = ArtifactType.ROUTING_MODEL
    stage: ModelStage = ModelStage.DEVELOPMENT
    artifact_path: str = ''                    # local/S3/GCS path
    checksum_sha256: str = ''                  # integrity verification
    training_dataset: str = ''                 # provenance: what data?
    training_dataset_version: str = ''
    training_record_count: int = 0
    training_started_at: str = ''
    training_completed_at: str = ''
    training_config: dict[str, Any] = field(default_factory=dict)  # hyperparams
    evaluation_metrics: dict[str, float] = field(default_factory=dict)  # accuracy, recall, ECE
    created_by: str = 'system'
    created_at: float = field(default_factory=time.time)
    promoted_at: float | None = None
    promoted_by: str | None = None
    promotion_reason: str | None = None
    parent_artifact_id: str | None = None       # lineage: derived from what?
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class LineageEvent:
    """Records a state transition in the model lifecycle."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    artifact_id: str = ''
    from_stage: ModelStage | None = None
    to_stage: ModelStage = ModelStage.DEVELOPMENT
    reason: str = ''
    triggered_by: str = 'system'
    quality_gate_passed: bool = True
    gate_details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class ModelRegistry:
    """In-memory model registry with lineage tracking.

    Production deployment would back this with a database table
    (`model_registry`, `model_lineage_events`) or an external
    system like MLflow / Weights & Biases / Vertex AI Model Registry.
    """

    def __init__(self) -> None:
        self._artifacts: dict[str, ModelArtifact] = {}
        self._lineage: list[LineageEvent] = []
        self._active: dict[ArtifactType, str] = {}  # type → artifact_id of production model

    def register(self, artifact: ModelArtifact) -> ModelArtifact:
        """Register a new model artifact."""
        self._artifacts[artifact.artifact_id] = artifact
        logger.info(
            'Model artifact registered.',
            extra={
                'artifact_id': artifact.artifact_id,
                'model_name': artifact.name,
                'version': artifact.version,
                'stage': artifact.stage.value,
            },
        )
        self._lineage.append(LineageEvent(
            artifact_id=artifact.artifact_id,
            to_stage=artifact.stage,
            reason='initial_registration',
            triggered_by=artifact.created_by,
        ))
        return artifact

    def promote(
        self,
        artifact_id: str,
        to_stage: ModelStage,
        *,
        reason: str = '',
        promoted_by: str = 'system',
        gate_details: dict[str, Any] | None = None,
    ) -> ModelArtifact:
        """Promote a model artifact to a new stage.

        Records lineage event.  If promoting to PRODUCTION, sets
        this as the active model for its artifact type.
        """
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            raise ValueError(f'Artifact {artifact_id!r} not found in registry.')

        old_stage = artifact.stage
        # Create updated artifact (frozen dataclass — need to rebuild)
        updated = ModelArtifact(
            artifact_id=artifact.artifact_id,
            name=artifact.name,
            version=artifact.version,
            artifact_type=artifact.artifact_type,
            stage=to_stage,
            artifact_path=artifact.artifact_path,
            checksum_sha256=artifact.checksum_sha256,
            training_dataset=artifact.training_dataset,
            training_dataset_version=artifact.training_dataset_version,
            training_record_count=artifact.training_record_count,
            training_started_at=artifact.training_started_at,
            training_completed_at=artifact.training_completed_at,
            training_config=artifact.training_config,
            evaluation_metrics=artifact.evaluation_metrics,
            created_by=artifact.created_by,
            created_at=artifact.created_at,
            promoted_at=time.time(),
            promoted_by=promoted_by,
            promotion_reason=reason,
            parent_artifact_id=artifact.parent_artifact_id,
            tags=artifact.tags,
        )
        self._artifacts[artifact_id] = updated

        gate_passed = True
        if gate_details:
            gate_passed = all(v.get('passed', True) if isinstance(v, dict) else bool(v)
                              for v in gate_details.values())

        event = LineageEvent(
            artifact_id=artifact_id,
            from_stage=old_stage,
            to_stage=to_stage,
            reason=reason,
            triggered_by=promoted_by,
            quality_gate_passed=gate_passed,
            gate_details=gate_details or {},
        )
        self._lineage.append(event)

        if to_stage == ModelStage.PRODUCTION:
            # Archive previous production model
            prev_id = self._active.get(artifact.artifact_type)
            if prev_id and prev_id != artifact_id:
                self.promote(prev_id, ModelStage.ARCHIVED, reason='superseded', promoted_by=promoted_by)
            self._active[artifact.artifact_type] = artifact_id

        logger.info(
            'Model artifact promoted.',
            extra={
                'artifact_id': artifact_id,
                'from': old_stage.value,
                'to': to_stage.value,
                'reason': reason,
            },
        )
        return updated

    def get_active(self, artifact_type: ArtifactType) -> ModelArtifact | None:
        """Return the current production model for a given type."""
        aid = self._active.get(artifact_type)
        return self._artifacts.get(aid) if aid else None

    def get_artifact(self, artifact_id: str) -> ModelArtifact | None:
        return self._artifacts.get(artifact_id)

    def get_lineage(self, artifact_id: str) -> list[LineageEvent]:
        """Return the full lifecycle history of an artifact."""
        return [e for e in self._lineage if e.artifact_id == artifact_id]

    def get_full_lineage_chain(self, artifact_id: str) -> list[ModelArtifact]:
        """Walk the parent_artifact_id chain to build full training lineage."""
        chain: list[ModelArtifact] = []
        current_id: str | None = artifact_id
        visited: set[str] = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            artifact = self._artifacts.get(current_id)
            if artifact is None:
                break
            chain.append(artifact)
            current_id = artifact.parent_artifact_id

        return chain

    def list_artifacts(
        self,
        *,
        artifact_type: ArtifactType | None = None,
        stage: ModelStage | None = None,
    ) -> list[ModelArtifact]:
        """List artifacts, optionally filtered by type and/or stage."""
        result = list(self._artifacts.values())
        if artifact_type is not None:
            result = [a for a in result if a.artifact_type == artifact_type]
        if stage is not None:
            result = [a for a in result if a.stage == stage]
        return sorted(result, key=lambda a: a.created_at, reverse=True)

    def compliance_report(self) -> dict[str, Any]:
        """Generate a compliance-friendly summary of model governance."""
        active_models = {
            t.value: self._artifacts[aid].name + ':' + self._artifacts[aid].version
            for t, aid in self._active.items()
            if aid in self._artifacts
        }
        all_artifacts = list(self._artifacts.values())
        return {
            'total_artifacts': len(all_artifacts),
            'total_lineage_events': len(self._lineage),
            'active_production_models': active_models,
            'stages': {
                stage.value: len([a for a in all_artifacts if a.stage == stage])
                for stage in ModelStage
            },
            'models_without_training_data': [
                a.artifact_id for a in all_artifacts
                if not a.training_dataset and a.stage in (ModelStage.PRODUCTION, ModelStage.CANARY)
            ],
            'artifacts_without_training_data': sum(
                1 for a in all_artifacts if not a.training_dataset
            ),
            'artifacts_without_checksum': sum(
                1 for a in all_artifacts if not a.checksum_sha256
            ),
            'failed_quality_gates': [
                {'event_id': e.event_id, 'artifact_id': e.artifact_id, 'to_stage': e.to_stage.value}
                for e in self._lineage if not e.quality_gate_passed
            ],
        }
