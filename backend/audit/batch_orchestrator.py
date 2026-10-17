from __future__ import annotations

import asyncio
from datetime import datetime

from backend.audit.findings import build_findings
from backend.audit.loader import list_claim_numbers_for_dataset, load_claim
from backend.audit.models import (
    AuditEvent,
    AuditRunStatus,
    BatchAuditRun,
    Finding,
    RunApproval,
)
from backend.audit.plan import propose_plan
from backend.batch.store import get_batch_store, new_batch_id, new_event_id
from backend.dataset.store import get_dataset_store
from backend.evidence.verify import filter_valid_results
from backend.judgment.checks import explain_results, run_judgment_check
from backend.regulations.store import get_regulations_store
from backend.reports.builder import build_combined_report_markdown
from backend.rules.catalog import get_rule_catalog, get_rule_map
from backend.rules.engine import run_deterministic_checks

# Thread-local-ish regulation context for judgment during batch
_regulation_context: str = ""


def set_regulation_context(text: str) -> None:
    global _regulation_context
    _regulation_context = text


def get_regulation_context() -> str:
    return _regulation_context


class BatchOrchestrator:
    def __init__(self) -> None:
        self.store = get_batch_store()

    def create_plan(
        self,
        dataset_id: str,
        regulation_set_id: str | None = None,
        objective: str | None = None,
    ) -> BatchAuditRun:
        reg_store = get_regulations_store()
        active = reg_store.get_active()
        rid = regulation_set_id or (active.regulation_set_id if active else None)
        if not rid:
            raise ValueError("No active regulation set. Upload regulations first.")

        ds = get_dataset_store().get(dataset_id)
        if not ds:
            raise ValueError(f"Dataset not found: {dataset_id}")

        claims = list_claim_numbers_for_dataset(dataset_id)
        sets = [s for s in reg_store.list_sets() if s.regulation_set_id == rid]
        file_names = [f.filename for f in sets[0].files] if sets else []
        dataset_files = list(ds.source_files) if ds.source_files else [
            "adjuster_notes.json",
            "communication_logs.json",
            "reference.xlsx",
        ]

        batch = BatchAuditRun(
            batch_id=new_batch_id(),
            dataset_id=dataset_id,
            regulation_set_id=rid,
            claim_numbers=claims,
            status=AuditRunStatus.planned,
            objective=objective,
            regulation_file_names=file_names,
            dataset_file_names=dataset_files,
        )
        self.store.save_batch(batch)
        self._emit(
            batch.batch_id,
            "plan",
            f"Plan: audit {len(claims)} claim(s) against {len(file_names)} regulation file(s)",
            "completed",
        )
        for cn in claims:
            self._emit(
                batch.batch_id,
                f"claim_{cn}",
                f"Queued: audit claim {cn}",
                "planned",
            )
        self._emit(
            batch.batch_id,
            "synthesize_report",
            "Queued: build combined report",
            "planned",
        )
        return batch

    def approve(self, batch_id: str, plan_version: int, approved_by: str = "reviewer") -> BatchAuditRun:
        batch = self._require(batch_id)
        if plan_version != batch.plan_version:
            raise ValueError("Plan version mismatch")
        batch.approval = RunApproval(
            plan_version=plan_version,
            approved_at=datetime.utcnow(),
            approved_by=approved_by,
        )
        batch.status = AuditRunStatus.approved
        self.store.save_batch(batch)
        self._emit(batch_id, "approve", "Batch plan approved", "completed")
        return batch

    async def execute(self, batch_id: str, skip_approval: bool = False) -> None:
        batch = self._require(batch_id)
        if not skip_approval:
            if not batch.approval or batch.approval.plan_version != batch.plan_version:
                raise PermissionError("Execute refused: batch plan not approved")

        ctx = get_regulations_store().get_context(batch.regulation_set_id)
        set_regulation_context(ctx)

        batch.status = AuditRunStatus.running
        self.store.save_batch(batch)
        self._emit(batch_id, "batch_start", "Starting batch audit", "running")

        catalog = get_rule_map()
        self._emit(batch_id, "batch_start", "Batch audit started", "completed")
        all_findings: list[Finding] = []
        enabled_det = [r for r, d in catalog.items() if d.type == "deterministic"]
        enabled_judgment = [r for r, d in catalog.items() if d.type == "judgment"]

        for claim_number in batch.claim_numbers:
            step = f"claim_{claim_number}"
            self._emit(batch_id, step, f"Auditing claim {claim_number}", "running")
            try:
                claim = load_claim(claim_number, batch.dataset_id)
                det_results = run_deterministic_checks(claim, enabled_det)
                det_results = filter_valid_results(claim, det_results)

                judgment_results = []
                for jid in enabled_judgment:
                    judgment_results.append(run_judgment_check(claim, jid))
                judgment_results = filter_valid_results(claim, judgment_results)
                results = det_results + judgment_results
                explanations = explain_results(results)
                findings = build_findings(batch_id, results)
                for f in findings:
                    f.claim_number = claim_number
                    if f.rule_id in explanations:
                        f.explanation = explanations[f.rule_id]
                all_findings.extend(findings)
                self._emit(batch_id, step, f"Completed {claim_number}", "completed")
            except Exception as exc:
                self._emit(batch_id, step, f"Error on {claim_number}: {exc}", "failed")

        self._emit(batch_id, "synthesize_report", "Building combined report", "running")
        md = build_combined_report_markdown(batch, all_findings, ctx)
        self.store.save_findings(batch_id, all_findings)
        self.store.save_report(batch_id, md)
        self._emit(batch_id, "synthesize_report", "Combined report ready", "completed")
        batch.status = AuditRunStatus.completed
        self.store.save_batch(batch)
        self._emit(batch_id, "batch_complete", "Batch audit completed", "completed")

    def _require(self, batch_id: str) -> BatchAuditRun:
        batch = self.store.get_batch(batch_id)
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")
        return batch

    def _emit(self, batch_id: str, step: str, message: str, status: str) -> AuditEvent:
        event = AuditEvent(
            event_id=new_event_id(),
            run_id=batch_id,
            step=step,
            message=message,
            status=status,
        )
        return self.store.append_event(event)
