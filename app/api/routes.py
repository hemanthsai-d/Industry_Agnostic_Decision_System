from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.api.deps import (
    get_feedback_store,
    get_handoff_store,
    get_orchestrator,
    get_rate_limiter,
    get_readiness_service,
)
from app.models.schemas import (
    DecideRequest,
    DecideResponse,
    FeedbackRequest,
    FeedbackResponse,
    HandoffListResponse,
    HandoffQueueStatus,
    HandoffStatusUpdateRequest,
    HandoffStatusUpdateResponse,
    ReindexRequest,
    ReindexResponse,
)
from app.security.auth import AuthService
from app.security.deps import get_auth_service, require_permission
from app.security.models import AuthContext
from app.security.rate_limit import RateLimiter
from app.services.orchestrator import DecisionOrchestrator
from app.services.readiness import ReadinessService
from app.storage.feedback_store import FeedbackStore
from app.storage.handoff_store import HandoffStore
from app.storage.in_memory_store import reload_chunks

router = APIRouter()


@router.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


@router.get('/ready')
async def ready(readiness_service: ReadinessService = Depends(get_readiness_service)) -> JSONResponse:
    payload = await readiness_service.check()
    status_code = 200 if payload.get('status') == 'ready' else 503
    return JSONResponse(status_code=status_code, content=payload)


@router.post('/v1/assist/decide', response_model=DecideResponse)
async def decide(
    req: DecideRequest,
    orchestrator: DecisionOrchestrator = Depends(get_orchestrator),
    auth_ctx: AuthContext = Depends(require_permission('assist:decide')),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> DecideResponse:
    auth_service.enforce_tenant_access(auth_ctx, req.tenant_id)
    await rate_limiter.enforce(tenant_id=req.tenant_id, user_id=auth_ctx.subject, action='assist:decide')
    return await orchestrator.decide(req)


@router.post('/v1/assist/feedback', response_model=FeedbackResponse)
async def feedback(
    req: FeedbackRequest,
    feedback_store: FeedbackStore = Depends(get_feedback_store),
    auth_ctx: AuthContext = Depends(require_permission('assist:feedback')),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> FeedbackResponse:
    auth_service.enforce_tenant_access(auth_ctx, req.tenant_id)
    await rate_limiter.enforce(tenant_id=req.tenant_id, user_id=auth_ctx.subject, action='assist:feedback')
    await asyncio.to_thread(feedback_store.persist, req)
    return FeedbackResponse(status='accepted', request_id=req.request_id)


@router.post('/v1/assist/reindex', response_model=ReindexResponse)
async def reindex(
    req: ReindexRequest,
    auth_ctx: AuthContext = Depends(require_permission('assist:reindex')),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> ReindexResponse:
    auth_service.enforce_tenant_access(auth_ctx, req.tenant_id)
    await rate_limiter.enforce(tenant_id=req.tenant_id, user_id=auth_ctx.subject, action='assist:reindex')
    import uuid
    import logging as _log

    job_id = str(uuid.uuid4()).replace('-', '')[:16]
    _log.getLogger(__name__).info(
        'Reindex job queued.',
        extra={
            'tenant_id': req.tenant_id,
            'section': req.section,
            'job_id': job_id,
            'requested_by': auth_ctx.subject,
        },
    )
    return ReindexResponse(status='queued', tenant_id=req.tenant_id, section=req.section)


@router.get('/v1/assist/handoffs', response_model=HandoffListResponse)
async def list_handoffs(
    tenant_id: str = Query(..., min_length=1),
    queue_status: HandoffQueueStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    handoff_store: HandoffStore = Depends(get_handoff_store),
    auth_ctx: AuthContext = Depends(require_permission('assist:handoff:read')),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> HandoffListResponse:
    auth_service.enforce_tenant_access(auth_ctx, tenant_id)
    await rate_limiter.enforce(tenant_id=tenant_id, user_id=auth_ctx.subject, action='assist:handoff:read')
    return await asyncio.to_thread(
        handoff_store.list_handoffs,
        tenant_id,
        queue_status,
        limit,
    )


@router.patch('/v1/assist/handoffs/{handoff_id}/status', response_model=HandoffStatusUpdateResponse)
async def update_handoff_queue_status(
    handoff_id: str,
    req: HandoffStatusUpdateRequest,
    handoff_store: HandoffStore = Depends(get_handoff_store),
    auth_ctx: AuthContext = Depends(require_permission('assist:handoff:update')),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> HandoffStatusUpdateResponse:
    auth_service.enforce_tenant_access(auth_ctx, req.tenant_id)
    await rate_limiter.enforce(tenant_id=req.tenant_id, user_id=auth_ctx.subject, action='assist:handoff:update')
    try:
        updated = await asyncio.to_thread(
            handoff_store.update_queue_status,
            req.tenant_id,
            handoff_id,
            req.queue_status,
            req.reviewer_id,
            req.final_decision,
            req.final_resolution_path,
            req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated_item, ground_truth_recorded = updated
    if updated_item is None:
        raise HTTPException(status_code=404, detail='Handoff not found.')
    return HandoffStatusUpdateResponse(
        handoff_id=updated_item.handoff_id,
        tenant_id=updated_item.tenant_id,
        queue_status=updated_item.queue_status,
        ground_truth_recorded=ground_truth_recorded,
    )


@router.post('/v1/admin/reload-chunks')
async def admin_reload_chunks(
    auth_ctx: AuthContext = Depends(require_permission('admin:reload')),
) -> dict[str, str]:
    """Hot-reload knowledge chunks from disk without restarting the server."""
    import asyncio as _asyncio

    await _asyncio.to_thread(reload_chunks)
    from app.storage.in_memory_store import IN_MEMORY_CHUNKS

    return {'status': 'reloaded', 'chunks_loaded': str(len(IN_MEMORY_CHUNKS))}
