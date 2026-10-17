from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.api.config import settings
from backend.audit.batch_orchestrator import BatchOrchestrator
from backend.audit.models import AuditRunStatus
from backend.batch.store import get_batch_store
from backend.reports.pdf import markdown_to_pdf_bytes

router = APIRouter(prefix="/api/batch", tags=["batch"])
orchestrator = BatchOrchestrator()


class BatchPlanRequest(BaseModel):
    dataset_id: str
    regulation_set_id: str | None = None
    objective: str | None = None


class BatchApprovalRequest(BaseModel):
    plan_version: int = 1
    approved_by: str = "reviewer"


async def _execute_batch(batch_id: str, skip_approval: bool) -> None:
    try:
        await orchestrator.execute(batch_id, skip_approval=skip_approval)
    except Exception as exc:
        batch = get_batch_store().get_batch(batch_id)
        if batch:
            batch.status = AuditRunStatus.failed
            get_batch_store().save_batch(batch)
        orchestrator._emit(batch_id, "error", str(exc), "failed")


@router.get("")
def list_batch_sessions():
    """Audit session history: each completed/planned run with its data sources."""
    store = get_batch_store()
    sessions = []
    for batch in store.list_batches():
        findings = store.get_findings(batch.batch_id)
        fail_count = sum(1 for f in findings if f.status.value == "fail")
        sessions.append(
            {
                **batch.model_dump(mode="json"),
                "finding_count": len(findings),
                "fail_count": fail_count,
                "has_report": store.get_report(batch.batch_id) is not None,
            }
        )
    return {"sessions": sessions}


@router.post("/plan")
def create_batch_plan(body: BatchPlanRequest):
    try:
        batch = orchestrator.create_plan(body.dataset_id, body.regulation_set_id, body.objective)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"batch": batch.model_dump(mode="json")}


@router.post("/{batch_id}/approve")
def approve_batch(batch_id: str, body: BatchApprovalRequest):
    try:
        batch = orchestrator.approve(batch_id, body.plan_version, body.approved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"batch": batch.model_dump(mode="json")}


@router.post("/{batch_id}/execute")
async def execute_batch(batch_id: str, background_tasks: BackgroundTasks):
    batch = get_batch_store().get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    skip = settings.require_planning_approval is False
    if not skip and (not batch.approval or batch.approval.plan_version != batch.plan_version):
        raise HTTPException(status_code=403, detail="Execute refused: batch plan not approved")
    background_tasks.add_task(_execute_batch, batch_id, skip)
    return {"status": "started", "batch_id": batch_id}


@router.get("/{batch_id}")
def get_batch(batch_id: str):
    batch = get_batch_store().get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    findings = get_batch_store().get_findings(batch_id)
    events = get_batch_store().list_events(batch_id)
    return {
        "batch": batch.model_dump(mode="json"),
        "findings": [f.model_dump(mode="json") for f in findings],
        "events": [e.model_dump(mode="json") for e in events],
    }


@router.get("/{batch_id}/events")
async def batch_events(batch_id: str, request: Request):
    if not get_batch_store().get_batch(batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")

    async def gen():
        last_id: str | None = None
        while True:
            if await request.is_disconnected():
                break
            events = get_batch_store().list_events(batch_id, after_id=last_id)
            for event in events:
                yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
                last_id = event.event_id
            batch = get_batch_store().get_batch(batch_id)
            if batch and batch.status in (AuditRunStatus.completed, AuditRunStatus.failed):
                if events and events[-1].step in ("batch_complete", "error"):
                    break
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{batch_id}/report")
def batch_report(batch_id: str):
    md = get_batch_store().get_report(batch_id)
    if not md:
        raise HTTPException(status_code=404, detail="Report not ready")
    pdf_bytes = markdown_to_pdf_bytes(md)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="batch-audit-{batch_id}.pdf"',
        },
    )
