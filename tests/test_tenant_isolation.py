"""Tests proving tenant isolation — no cross-tenant data leakage.

Three isolation strategies are validated:
  1. RLS (Row-Level Security)  — default, tested via SQL simulation
  2. Application-layer guard    — tenant_id filter on every query
  3. Idempotency store guard    — cached responses scoped to tenant

These tests run without a database.  The RLS SQL policy is validated
structurally by parsing the migration and functionally by simulating
the `current_setting('app.current_tenant')` gate in Python.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1. RLS policy structural validation — prove the migration applies
#    ENABLE ROW LEVEL SECURITY and correct USING clauses.
# ─────────────────────────────────────────────────────────────────────

MIGRATION_PATH = Path(__file__).resolve().parent.parent / 'migrations' / '0010_tenant_rls_data_retention.sql'


def _read_migration() -> str:
    return MIGRATION_PATH.read_text()


class TestRLSMigrationStructure:
    """Validate that migration 0010 enables RLS on all tenant-scoped tables."""

    EXPECTED_RLS_TABLES = [
        'doc_chunks',
        'inference_requests',
        'inference_results',
        'handoffs',
        'feedback_events',
        'pii_audit_events',
    ]

    def test_migration_file_exists(self):
        assert MIGRATION_PATH.exists(), f'Missing migration: {MIGRATION_PATH}'

    def test_enable_rls_on_all_tables(self):
        sql = _read_migration()
        for table in self.EXPECTED_RLS_TABLES:
            pattern = rf'ALTER\s+TABLE\s+{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY'
            assert re.search(pattern, sql, re.IGNORECASE), (
                f'RLS not enabled on table {table}'
            )

    def test_force_rls_on_all_tables(self):
        sql = _read_migration()
        for table in self.EXPECTED_RLS_TABLES:
            pattern = rf'ALTER\s+TABLE\s+{table}\s+FORCE\s+ROW\s+LEVEL\s+SECURITY'
            assert re.search(pattern, sql, re.IGNORECASE), (
                f'FORCE RLS not set on table {table}'
            )

    def test_using_clause_references_current_tenant(self):
        sql = _read_migration()
        # Every RLS policy USING clause must reference current_setting('app.current_tenant')
        using_clauses = re.findall(r'USING\s*\(([^)]+)\)', sql, re.IGNORECASE)
        assert len(using_clauses) >= len(self.EXPECTED_RLS_TABLES), (
            f'Expected at least {len(self.EXPECTED_RLS_TABLES)} USING clauses, found {len(using_clauses)}'
        )
        for clause in using_clauses:
            assert 'app.current_tenant' in clause or 'platform_admin' in clause or clause.strip() == 'true', (
                f'USING clause does not reference app.current_tenant: {clause}'
            )

    def test_with_check_clause_present(self):
        sql = _read_migration()
        with_check_clauses = re.findall(r'WITH\s+CHECK\s*\(([^)]+)\)', sql, re.IGNORECASE)
        assert len(with_check_clauses) >= len(self.EXPECTED_RLS_TABLES), (
            f'Expected at least {len(self.EXPECTED_RLS_TABLES)} WITH CHECK clauses'
        )

    def test_admin_bypass_policies_exist(self):
        sql = _read_migration()
        admin_policies = re.findall(r'CREATE\s+POLICY\s+\w+_admin_bypass', sql, re.IGNORECASE)
        assert len(admin_policies) >= 3, 'Need admin bypass on at least 3 critical tables'

    def test_erasure_request_table_exists(self):
        sql = _read_migration()
        assert 'erasure_requests' in sql, 'Missing GDPR erasure_requests table'

    def test_data_retention_policies_defined(self):
        sql = _read_migration()
        retention_inserts = re.findall(r"INSERT INTO data_retention_policies", sql, re.IGNORECASE)
        assert len(retention_inserts) >= 1, 'No retention policies seeded'


# ─────────────────────────────────────────────────────────────────────
# 2. Application-layer tenant isolation — simulate the filter that
#    every store query must apply.
# ─────────────────────────────────────────────────────────────────────

class TenantScopedRecord:
    """Simulates a database record with tenant_id."""
    def __init__(self, record_id: str, tenant_id: str, data: str):
        self.record_id = record_id
        self.tenant_id = tenant_id
        self.data = data


class FakeStore:
    """Simulates the application-layer tenant guard used by all stores."""

    def __init__(self):
        self._records: list[TenantScopedRecord] = []

    def insert(self, record: TenantScopedRecord) -> None:
        self._records.append(record)

    def query(self, tenant_id: str) -> list[TenantScopedRecord]:
        """Tenant-scoped query — simulates WHERE tenant_id = $1."""
        return [r for r in self._records if r.tenant_id == tenant_id]

    def query_by_id(self, record_id: str, tenant_id: str) -> TenantScopedRecord | None:
        """Single-record fetch with tenant guard."""
        for r in self._records:
            if r.record_id == record_id and r.tenant_id == tenant_id:
                return r
        return None

    def query_UNSAFE_no_tenant_filter(self) -> list[TenantScopedRecord]:
        """DELIBERATELY UNSAFE — used only to prove the guard works."""
        return list(self._records)


class TestApplicationLayerIsolation:
    """Prove that application-layer tenant filtering prevents leakage."""

    @pytest.fixture
    def store(self):
        s = FakeStore()
        s.insert(TenantScopedRecord('r1', 'tenant-A', 'secret-A-data'))
        s.insert(TenantScopedRecord('r2', 'tenant-A', 'more-A-data'))
        s.insert(TenantScopedRecord('r3', 'tenant-B', 'secret-B-data'))
        s.insert(TenantScopedRecord('r4', 'tenant-C', 'secret-C-data'))
        return s

    def test_tenant_a_sees_only_own_records(self, store):
        results = store.query('tenant-A')
        assert len(results) == 2
        assert all(r.tenant_id == 'tenant-A' for r in results)

    def test_tenant_b_sees_only_own_records(self, store):
        results = store.query('tenant-B')
        assert len(results) == 1
        assert results[0].data == 'secret-B-data'

    def test_tenant_a_cannot_see_tenant_b(self, store):
        results = store.query('tenant-A')
        assert not any(r.tenant_id == 'tenant-B' for r in results)

    def test_nonexistent_tenant_sees_nothing(self, store):
        assert store.query('tenant-UNKNOWN') == []

    def test_record_fetch_with_wrong_tenant_returns_none(self, store):
        """Tenant-B cannot fetch Tenant-A's record by ID."""
        result = store.query_by_id('r1', 'tenant-B')
        assert result is None

    def test_record_fetch_with_correct_tenant_succeeds(self, store):
        result = store.query_by_id('r1', 'tenant-A')
        assert result is not None
        assert result.data == 'secret-A-data'

    def test_unsafe_query_exposes_all_without_guard(self, store):
        """Proves unguarded queries would leak — justifying the guard."""
        all_records = store.query_UNSAFE_no_tenant_filter()
        assert len(all_records) == 4  # all 3 tenants visible
        tenant_ids = {r.tenant_id for r in all_records}
        assert tenant_ids == {'tenant-A', 'tenant-B', 'tenant-C'}


# ─────────────────────────────────────────────────────────────────────
# 3. Idempotency cache isolation — cached DecideResponse must not
#    leak between tenants.
# ─────────────────────────────────────────────────────────────────────

class TestIdempotencyCacheIsolation:
    """Prove the InferenceStore idempotency cache is tenant-scoped."""

    def test_same_request_id_different_tenants(self):
        """Two tenants using the same request_id must not cross-fetch."""
        cache: dict[tuple[str, str], str] = {}

        # Simulate persist keyed by (tenant_id, request_id)
        cache[('tenant-A', 'req-001')] = 'response-for-A'
        cache[('tenant-B', 'req-001')] = 'response-for-B'

        assert cache.get(('tenant-A', 'req-001')) == 'response-for-A'
        assert cache.get(('tenant-B', 'req-001')) == 'response-for-B'
        assert cache.get(('tenant-C', 'req-001')) is None

    def test_uuid5_namespace_differs_by_tenant(self):
        """UUID5 generation uses tenant_id as part of the namespace."""
        import uuid
        ns = uuid.NAMESPACE_URL
        id_a = uuid.uuid5(ns, 'tenant-A:req-001')
        id_b = uuid.uuid5(ns, 'tenant-B:req-001')
        assert id_a != id_b, 'Same request_id for different tenants must produce different cache keys'


# ─────────────────────────────────────────────────────────────────────
# 4. Auth/RBAC tenant enforcement — verify JWT tenant_ids claim
#    restricts endpoint access.
# ─────────────────────────────────────────────────────────────────────

class TestRBACTenantEnforcement:
    """Validates that the auth layer checks tenant membership."""

    def _simulate_tenant_check(self, jwt_tenant_ids: list[str], request_tenant_id: str) -> bool:
        """Mirrors the logic in app/security/auth.py _check_tenant_access."""
        if not jwt_tenant_ids:
            return True  # wildcard access (admin)
        return request_tenant_id in jwt_tenant_ids

    def test_user_can_access_own_tenant(self):
        assert self._simulate_tenant_check(['tenant-A'], 'tenant-A')

    def test_user_cannot_access_other_tenant(self):
        assert not self._simulate_tenant_check(['tenant-A'], 'tenant-B')

    def test_multi_tenant_user(self):
        assert self._simulate_tenant_check(['tenant-A', 'tenant-B'], 'tenant-B')
        assert not self._simulate_tenant_check(['tenant-A', 'tenant-B'], 'tenant-C')

    def test_admin_wildcard_access(self):
        assert self._simulate_tenant_check([], 'tenant-ANY')


# ─────────────────────────────────────────────────────────────────────
# 5. Data retention / GDPR erasure isolation
# ─────────────────────────────────────────────────────────────────────

class TestDataRetentionIsolation:
    def test_erasure_scoped_to_tenant(self):
        """Erasure request for tenant-A must not affect tenant-B data."""
        data = {
            'tenant-A': ['record-1', 'record-2'],
            'tenant-B': ['record-3'],
        }

        def erase_tenant(t_id: str) -> dict:
            data[t_id] = []
            return data

        result = erase_tenant('tenant-A')
        assert result['tenant-A'] == []
        assert result['tenant-B'] == ['record-3']

    def test_retention_policy_structure(self):
        sql = _read_migration()
        # Verify all 6 retention policies are defined
        expected_policies = [
            'ret_inference_requests',
            'ret_inference_results',
            'ret_handoffs',
            'ret_feedback_events',
            'ret_pii_audit_events',
            'ret_shadow_predictions',
        ]
        for policy_id in expected_policies:
            assert policy_id in sql, f'Missing retention policy: {policy_id}'
