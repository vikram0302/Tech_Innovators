from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.api.schemas import (
    ApprovalRequest,
    AuditDetailResponse,
    EvidenceItem,
    EvidenceListResponse,
    PlanRequest,
    PlanResponse,
    PlanUpdateRequest,
    RunSummary,
    SeveritySummary,
)
from backend.audit.models import AuditRunStatus, Severity
from backend.audit.orchestrator import AuditOrchestrator
from backend.db.repositories import get_repository
from backend.reports.builder import build_report_markdown
from backend.reports.pdf import markdown_to_pdf_bytes

router = APIRouter(prefix="/api/audits", tags=["audits"])
orchestrator = AuditOrchestrator()


def _run_summary(run) -> RunSummary:
    return RunSummary(
        run_id=run.run_id,
        claim_number=run.claim_number,
        status=run.status,
        plan_version=run.plan_version,
        approval=run.approval,
        objective=run.objective,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.post("/plan", response_model=PlanResponse)
def create_plan(body: PlanRequest) -> PlanResponse:
    try:
        run, plan = orchestrator.create_plan(body.claim_number, body.objective)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlanResponse(run=_run_summary(run), plan=plan)


@router.put("/{run_id}/plan", response_model=PlanResponse)
def update_plan(run_id: str, body: PlanUpdateRequest) -> PlanResponse:
    try:
        plan = orchestrator.update_plan(run_id, body.enabled_rule_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = get_repository().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return PlanResponse(run=_run_summary(run), plan=plan)


@router.post("/{run_id}/approve")
def approve_run(run_id: str, body: ApprovalRequest):
    try:
        run = orchestrator.approve(run_id, body.plan_version, body.approved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run": _run_summary(run)}


async def _execute_background(run_id: str) -> None:
    try:
        await orchestrator.execute(run_id)
    except Exception as exc:
        run_failed = get_repository().get_run(run_id)
        if run_failed:
            run_failed.status = AuditRunStatus.failed
            get_repository().update_run(run_failed)
        orchestrator._emit(run_id, "error", str(exc), "failed")


@router.post("/{run_id}/execute")
async def execute_run(run_id: str, background_tasks: BackgroundTasks):
    run = get_repository().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.approval or run.approval.plan_version != run.plan_version:
        raise HTTPException(status_code=403, detail="Execute refused: plan not approved for current version.")

    background_tasks.add_task(_execute_background, run_id)
    return {"status": "started", "run_id": run_id}


@router.get("/{run_id}", response_model=AuditDetailResponse)
def get_run_detail(run_id: str) -> AuditDetailResponse:
    repo = get_repository()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    plan = repo.get_plan(run_id, run.plan_version)
    findings = repo.get_findings(run_id)
    return AuditDetailResponse(run=_run_summary(run), plan=plan, findings=findings)


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    repo = get_repository()
    if not repo.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        last_id: str | None = None
        while True:
            if await request.is_disconnected():
                break
            events = repo.list_events(run_id, after_id=last_id)
            for event in events:
                payload = event.model_dump(mode="json")
                yield f"data: {json.dumps(payload)}\n\n"
                last_id = event.event_id
            run = repo.get_run(run_id)
            if run and run.status in (AuditRunStatus.completed, AuditRunStatus.failed):
                if not events:
                    break
                if events and events[-1].step in ("complete", "error"):
                    break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{run_id}/evidence", response_model=EvidenceListResponse)
def get_evidence(run_id: str) -> EvidenceListResponse:
    repo = get_repository()
    if not repo.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    by_source: dict[str, EvidenceItem] = {}
    rule_map: dict[str, list[str]] = defaultdict(list)
    for finding in repo.get_findings(run_id):
        for ref in finding.evidence_refs:
            rule_map[ref.source_id].append(finding.rule_id)
            if ref.source_id not in by_source:
                by_source[ref.source_id] = EvidenceItem(
                    source_id=ref.source_id,
                    date=str(ref.date) if ref.date else None,
                    excerpt=ref.excerpt,
                    rule_ids=[finding.rule_id],
                )
            elif finding.rule_id not in by_source[ref.source_id].rule_ids:
                by_source[ref.source_id].rule_ids.append(finding.rule_id)
    items = list(by_source.values())
    return EvidenceListResponse(run_id=run_id, items=items)


@router.get("/{run_id}/report")
def download_report(run_id: str):
    repo = get_repository()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    findings = repo.get_findings(run_id)
    if not findings:
        raise HTTPException(status_code=404, detail="Report not ready")
    md = build_report_markdown(run, findings)
    pdf_bytes = markdown_to_pdf_bytes(md)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="audit-{run_id}.pdf"'},
    )
