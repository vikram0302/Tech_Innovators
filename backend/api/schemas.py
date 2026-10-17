from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.audit.models import (
    AuditPlan,
    AuditRunStatus,
    CheckStatus,
    Finding,
    RunApproval,
    Severity,
)


class PlanRequest(BaseModel):
    claim_number: str
    objective: str | None = None


class PlanUpdateRequest(BaseModel):
    enabled_rule_ids: list[str]


class ApprovalRequest(BaseModel):
    plan_version: int
    approved_by: str = "reviewer"


class RunSummary(BaseModel):
    run_id: str
    claim_number: str
    status: AuditRunStatus
    plan_version: int
    approval: RunApproval | None = None
    objective: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanResponse(BaseModel):
    run: RunSummary
    plan: AuditPlan


class AuditDetailResponse(BaseModel):
    run: RunSummary
    plan: AuditPlan | None = None
    findings: list[Finding] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    source_id: str
    date: str | None = None
    excerpt: str
    rule_ids: list[str] = Field(default_factory=list)


class EvidenceListResponse(BaseModel):
    run_id: str
    items: list[EvidenceItem]


class SeveritySummary(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    failures: int = 0


class ReportMeta(BaseModel):
    run_id: str
    claim_number: str
    summary: SeveritySummary
