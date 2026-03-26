from __future__ import annotations

from app.services.retrieval import RetrievalService


class BrokenPostgresStore:
    def retrieve(self, tenant_id: str, issue_text: str, section: str | None, top_k: int = 5):
        raise RuntimeError("db unavailable")


def test_retrieval_falls_back_to_in_memory_on_postgres_error():
    retrieval = RetrievalService(postgres_store=BrokenPostgresStore())
    evidence = retrieval.retrieve(
        tenant_id="org_demo",
        section="billing",
        issue_text="customer charged twice and wants refund",
        top_k=3,
    )
    assert len(evidence) >= 1
    assert evidence[0].tenant_id == "org_demo"

