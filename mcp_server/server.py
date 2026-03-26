from __future__ import annotations

import asyncio
import threading

from app.api.deps import get_orchestrator
from app.models.schemas import DecideRequest, RiskLevel

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "MCP package is not installed. Install dependencies with: pip install -r requirements.txt"
    ) from exc


mcp = FastMCP("decision-platform")


@mcp.tool()
def health() -> dict[str, str]:
    return {"status": "ok", "service": "decision-platform-mcp"}


@mcp.tool()
def decide_issue(
    tenant_id: str,
    issue_text: str,
    section: str = "general",
    risk_level: str = "medium",
    max_evidence_chunks: int = 5,
) -> dict:
    req = DecideRequest(
        tenant_id=tenant_id,
        section=section,
        issue_text=issue_text,
        risk_level=RiskLevel(risk_level),
        max_evidence_chunks=max_evidence_chunks,
    )
    return _run_decide(req)


def _run_decide(req: DecideRequest) -> dict:
    orchestrator = get_orchestrator()
    coroutine = orchestrator.decide(req)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(coroutine)
        return result.model_dump()

    result_holder: dict[str, dict] = {}
    error_holder: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            result = asyncio.run(coroutine)
            result_holder["payload"] = result.model_dump()
        except BaseException as exc:  # pragma: no cover - defensive handoff path
            error_holder["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join()

    if "error" in error_holder:
        raise RuntimeError("Failed to execute decision flow from MCP tool.") from error_holder["error"]
    return result_holder["payload"]


if __name__ == "__main__":
    mcp.run(transport="stdio")
