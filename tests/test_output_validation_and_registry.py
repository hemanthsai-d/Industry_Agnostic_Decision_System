"""Tests for output validation — schema enforcement, PII re-check,
forbidden content detection, and model registry versioning."""

from __future__ import annotations

import pytest
from app.security.output_validation import validate_output, validate_and_sanitize
from app.services.model_registry import (
    ModelRegistry,
    ModelArtifact,
    ModelStage,
    ArtifactType,
)


# ─────────────────────────────────────────────────────────────────────
# Output Validation
# ─────────────────────────────────────────────────────────────────────

class TestOutputSchemaValidation:
    def test_valid_output(self):
        text = "Your refund has been processed [chunk_abc]. Please allow 3-5 business days."
        result = validate_output(text)
        assert result.is_valid
        assert result.violations == []

    def test_too_short(self):
        result = validate_output("Hi")
        assert not result.is_valid
        assert 'too_short:2<10' in result.violations

    def test_too_long(self):
        text = "a " * 1500  # 3000 chars
        result = validate_output(text, max_length=2000)
        assert not result.is_valid
        assert any('too_long' in v for v in result.violations)
        assert result.sanitized_text.endswith('...')

    def test_missing_citations(self):
        result = validate_output("Your refund has been processed. Please wait.")
        assert not result.is_valid
        assert 'missing_citations' in result.violations

    def test_citations_not_required(self):
        result = validate_output(
            "Your refund has been processed. Please wait.",
            require_citations=False,
        )
        assert result.is_valid


class TestOutputPIIRecheck:
    def test_email_leak(self):
        text = "Please contact support at user@example.com [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        assert 'pii_leak:email' in result.violations
        assert 'user@example.com' not in result.sanitized_text
        assert '[REDACTED_EMAIL]' in result.sanitized_text

    def test_phone_leak(self):
        text = "Call us at 555-123-4567 for help [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        assert 'pii_leak:phone' in result.violations
        assert '555-123-4567' not in result.sanitized_text

    def test_ssn_leak(self):
        text = "Your SSN 123-45-6789 is on file [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        assert 'pii_leak:ssn' in result.violations

    def test_credit_card_leak(self):
        text = "Card ending in 4111 1111 1111 1111 was charged [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        assert 'pii_leak:credit_card' in result.violations

    def test_no_pii(self):
        text = "Your order #12345 has shipped [chunk_1]."
        result = validate_output(text)
        assert result.is_valid
        assert result.pii_types_found == []


class TestOutputForbiddenContent:
    def test_system_prompt_leak(self):
        text = "As my system prompt says, I should help [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        assert 'forbidden:system_prompt_leak' in result.violations

    def test_chatml_markers(self):
        text = "Here is info <|im_start|>system [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        assert 'forbidden:role_marker_leak' in result.violations

    def test_markdown_image_injection(self):
        """Markdown image with external URL is caught (url_injection fires first
        since the patterns are evaluated in order; either violation suffices)."""
        text = "Check this ![image](https://evil.com/track.png) [chunk_1]."
        result = validate_output(text)
        assert not result.is_valid
        # url_injection matches first and strips the scheme, but the output is
        # still flagged as unsafe.
        assert any(
            v.startswith('forbidden:') for v in result.violations
        )

    def test_clean_urls_allowed(self):
        """URLs to support/help/docs domains should not be flagged."""
        text = "Visit https://support.example.com for help [chunk_1]."
        result = validate_output(text)
        # The url_injection pattern excludes support.* domains
        assert 'forbidden:url_injection' not in result.violations


class TestValidateAndSanitize:
    def test_none_input(self):
        text, violations = validate_and_sanitize(None)
        assert text is None
        assert violations == []

    def test_empty_input(self):
        text, violations = validate_and_sanitize("")
        assert text is None
        assert violations == []

    def test_valid_passthrough(self):
        original = "Your order shipped yesterday [chunk_1]."
        text, violations = validate_and_sanitize(original)
        assert text == original
        assert violations == []

    def test_sanitized_return(self):
        original = "Contact user@test.com for details [chunk_1]."
        text, violations = validate_and_sanitize(original)
        assert 'pii_leak:email' in violations
        assert text is not None
        assert 'user@test.com' not in text


# ─────────────────────────────────────────────────────────────────────
# Model Registry — Versioning, Stage Transitions, Reproducibility
# ─────────────────────────────────────────────────────────────────────

class TestModelRegistryVersioning:
    @pytest.fixture
    def registry(self):
        return ModelRegistry()

    def test_semantic_versioning(self, registry):
        """Multiple versions of the same model can coexist."""
        v1 = registry.register(ModelArtifact(name='routing', version='v1.0.0'))
        v2 = registry.register(ModelArtifact(name='routing', version='v2.0.0'))
        v3 = registry.register(ModelArtifact(name='routing', version='v2.1.0'))
        assert v1.artifact_id != v2.artifact_id != v3.artifact_id

    def test_stage_transition_order(self, registry):
        """Must promote through DEV → SHADOW → CANARY → PRODUCTION."""
        art = registry.register(ModelArtifact(name='m', version='v1'))
        assert art.stage == ModelStage.DEVELOPMENT

        art = registry.promote(art.artifact_id, ModelStage.SHADOW)
        assert art.stage == ModelStage.SHADOW

        art = registry.promote(art.artifact_id, ModelStage.CANARY)
        assert art.stage == ModelStage.CANARY

        art = registry.promote(art.artifact_id, ModelStage.PRODUCTION)
        assert art.stage == ModelStage.PRODUCTION

    def test_rollback_creates_event(self, registry):
        art = registry.register(ModelArtifact(name='m', version='v1'))
        registry.promote(art.artifact_id, ModelStage.PRODUCTION)
        registry.promote(art.artifact_id, ModelStage.ROLLBACK, reason='quality degradation')

        lineage = registry.get_lineage(art.artifact_id)
        assert any(e.to_stage == ModelStage.ROLLBACK for e in lineage)

    def test_training_data_reference(self, registry):
        """Model artifact stores training data provenance."""
        art = registry.register(ModelArtifact(
            name='routing',
            version='v2',
            training_dataset='bitext-customer-support',
            training_dataset_version='v13.2',
            training_record_count=26872,
            training_config={'lr': 0.001, 'epochs': 10, 'batch_size': 32},
        ))
        fetched = registry.get_artifact(art.artifact_id)
        assert fetched.training_dataset == 'bitext-customer-support'
        assert fetched.training_record_count == 26872
        assert fetched.training_config['lr'] == 0.001

    def test_evaluation_metrics_stored(self, registry):
        """Model stores evaluation metrics for quality gate verification."""
        art = registry.register(ModelArtifact(
            name='routing',
            version='v2',
            evaluation_metrics={
                'accuracy': 0.82,
                'recall': 0.78,
                'ece': 0.09,
                'f1': 0.80,
            },
        ))
        fetched = registry.get_artifact(art.artifact_id)
        assert fetched.evaluation_metrics['accuracy'] == 0.82
        assert fetched.evaluation_metrics['ece'] == 0.09

    def test_checksum_integrity(self, registry):
        """Artifact can store SHA-256 checksum for reproducibility."""
        art = registry.register(ModelArtifact(
            name='routing',
            version='v2',
            checksum_sha256='abc123def456',
            artifact_path='artifacts/models/routing_v2.json',
        ))
        fetched = registry.get_artifact(art.artifact_id)
        assert fetched.checksum_sha256 == 'abc123def456'
        assert fetched.artifact_path == 'artifacts/models/routing_v2.json'

    def test_full_lineage_chain_with_training_data(self, registry):
        """Walk lineage and verify training data at each version."""
        v1 = registry.register(ModelArtifact(
            name='routing', version='v1',
            training_dataset='bitext-v12',
            training_record_count=20000,
        ))
        v2 = registry.register(ModelArtifact(
            name='routing', version='v2',
            training_dataset='bitext-v13',
            training_record_count=26872,
            parent_artifact_id=v1.artifact_id,
        ))
        v3 = registry.register(ModelArtifact(
            name='routing', version='v3',
            training_dataset='bitext-v14',
            training_record_count=30000,
            parent_artifact_id=v2.artifact_id,
        ))

        chain = registry.get_full_lineage_chain(v3.artifact_id)
        assert len(chain) == 3
        assert chain[0].training_dataset == 'bitext-v14'
        assert chain[1].training_dataset == 'bitext-v13'
        assert chain[2].training_dataset == 'bitext-v12'

    def test_compliance_report_flags_missing_data(self, registry):
        """Compliance report flags artifacts without training data or checksum."""
        registry.register(ModelArtifact(name='m1', version='v1'))  # no training_dataset
        registry.register(ModelArtifact(
            name='m2', version='v1',
            training_dataset='bitext',
            checksum_sha256='abc',
        ))

        report = registry.compliance_report()
        assert report['total_artifacts'] == 2
        assert report['artifacts_without_training_data'] == 1
        assert report['artifacts_without_checksum'] == 1

    def test_multiple_artifact_types(self, registry):
        """Different artifact types have independent active models."""
        r = registry.register(ModelArtifact(
            name='routing', version='v1',
            artifact_type=ArtifactType.ROUTING_MODEL,
        ))
        e = registry.register(ModelArtifact(
            name='escalation', version='v1',
            artifact_type=ArtifactType.ESCALATION_MODEL,
        ))
        registry.promote(r.artifact_id, ModelStage.PRODUCTION)
        registry.promote(e.artifact_id, ModelStage.PRODUCTION)

        assert registry.get_active(ArtifactType.ROUTING_MODEL).name == 'routing'
        assert registry.get_active(ArtifactType.ESCALATION_MODEL).name == 'escalation'

    def test_promotion_records_reason(self, registry):
        art = registry.register(ModelArtifact(name='m', version='v1'))
        promoted = registry.promote(
            art.artifact_id,
            ModelStage.PRODUCTION,
            reason='daily eval accuracy=0.85, ECE=0.08',
        )
        assert promoted.promotion_reason == 'daily eval accuracy=0.85, ECE=0.08'
        lineage = registry.get_lineage(art.artifact_id)
        prod_events = [e for e in lineage if e.to_stage == ModelStage.PRODUCTION]
        assert prod_events[0].reason == 'daily eval accuracy=0.85, ECE=0.08'
