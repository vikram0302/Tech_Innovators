from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    not_evaluable = "not_evaluable"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AssessmentType(str, Enum):
    deterministic = "deterministic"
    ai_assessed = "ai_assessed"


class NoteEntry(BaseModel):
    id: str
    date: DateType
    adjuster: str
    type: str
    text: str


class CommunicationEntry(BaseModel):
    id: str
    date: DateType
    type: str
    party: str
    text: str


class TimelineEvent(BaseModel):
    event_id: str
    source: str
    source_id: str
    date: DateType
    adjuster: str | None = None
    type: str
    text: str


class DerivedFields(BaseModel):
    open_date: Optional[DateType] = None
    close_date: Optional[DateType] = None
    days_open: Optional[int] = None


class NormalizedClaim(BaseModel):
    claim_number: str
    notes: list[NoteEntry]
    communications: list[CommunicationEntry]
    timeline: list[TimelineEvent]
    reference: dict[str, Any] = Field(default_factory=dict)
    derived: DerivedFields


class EvidenceRef(BaseModel):
    source_id: str
    date: Optional[DateType] = None
    excerpt: str


class RuleDefinition(BaseModel):
    rule_id: str
    standard_section: str
    title: str
    description: str
    type: str
    required_inputs: list[str] = Field(default_factory=list)
    threshold: str | None = None
    severity_if_failed: Severity
    remediation: str


class CheckResult(BaseModel):
    rule_id: str
    status: CheckStatus
    observed_value: Optional[str] = None
    expected_value: Optional[str] = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    reason: Optional[str] = None
    assessment_type: AssessmentType = AssessmentType.deterministic


class Finding(BaseModel):
    finding_id: str
    run_id: str
    claim_number: Optional[str] = None
    rule_id: str
    severity: Severity
    status: CheckStatus
    observed_value: Optional[str] = None
    expected_value: Optional[str] = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    explanation: Optional[str] = None
    recommended_action: Optional[str] = None
    assessment_type: AssessmentType = AssessmentType.deterministic


class PlanRuleItem(BaseModel):
    rule_id: str
    enabled: bool = True
    data_gaps: list[str] = Field(default_factory=list)


class AuditPlan(BaseModel):
    run_id: str
    version: int
    claim_number: str
    objective: Optional[str] = None
    rules: list[PlanRuleItem]
    data_gaps_summary: list[str] = Field(default_factory=list)


class RunApproval(BaseModel):
    plan_version: int
    approved_at: datetime
    approved_by: str = "reviewer"


class AuditRunStatus(str, Enum):
    planned = "planned"
    approved = "approved"
    running = "running"
    completed = "completed"
    failed = "failed"


class AuditRun(BaseModel):
    run_id: str
    claim_number: str
    status: AuditRunStatus
    plan_version: int = 1
    approval: Optional[RunApproval] = None
    rule_catalog_version: str = "1.0"
    prompt_version: str = "1.0"
    objective: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AuditEvent(BaseModel):
    event_id: str
    run_id: str
    step: str
    message: str
    status: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BatchAuditRun(BaseModel):
    batch_id: str
    dataset_id: str
    regulation_set_id: str
    claim_numbers: list[str] = Field(default_factory=list)
    status: AuditRunStatus = AuditRunStatus.planned
    plan_version: int = 1
    approval: Optional[RunApproval] = None
    objective: Optional[str] = None
    child_run_ids: dict[str, str] = Field(default_factory=dict)
    regulation_file_names: list[str] = Field(default_factory=list)
    dataset_file_names: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
