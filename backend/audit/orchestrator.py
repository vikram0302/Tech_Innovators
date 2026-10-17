from __future__ import annotations

import asyncio
from datetime import datetime

from backend.audit.findings import build_findings
from backend.audit.loader import load_claim
from backend.audit.models import AuditEvent, AuditRunStatus, RunApproval
from backend.audit.plan import propose_plan
from backend.db.repositories import get_repository, new_event_id, new_run_id
from backend.evidence.verify import filter_valid_results
from backend.judgment.checks import explain_results, run_judgment_check
from backend.reports.builder import build_report_markdown
from backend.rules.catalog import get_rule_catalog, get_rule_map
from backend.rules.engine import run_deterministic_checks

from backend.audit.models import AuditPlan, AuditRun


class AuditOrchestrator:
    def __init__(self) -> None:
        self.repo = get_repository()

    def create_plan(
        self, claim_number: str, objective: str | None = None
    ) -> tuple[AuditRun, AuditPlan]:
        claim = load_claim(claim_number)
        run_id = new_run_id()
        catalog_version, _ = get_rule_catalog()
        run = AuditRun(
            run_id=run_id,
            claim_number=claim_number,
            status=AuditRunStatus.planned,
            plan_version=1,
            rule_catalog_version=catalog_version,
            objective=objective,
        )
        plan = propose_plan(run_id, claim, version=1, objective=objective)
        self.repo.create_run(run)
        self.repo.save_plan(plan)
        self._emit(run_id, "plan", "Audit plan created", "completed")
        return run, plan

    def update_plan(self, run_id: str, enabled_rule_ids: list[str]) -> AuditPlan:
        run = self._require_run(run_id)
        claim = load_claim(run.claim_number)
        new_version = run.plan_version + 1
        plan = propose_plan(
            run_id,
            claim,
            version=new_version,
            objective=run.objective,
            enabled_rule_ids=enabled_rule_ids,
        )
        run.plan_version = new_version
        run.status = AuditRunStatus.planned
        run.approval = None
        self.repo.update_run(run)
        self.repo.save_plan(plan)
        self._emit(run_id, "plan", f"Plan updated to version {new_version}", "completed")
        return plan

    def approve(self, run_id: str, plan_version: int, approved_by: str = "reviewer") -> AuditRun:
        run = self._require_run(run_id)
        if plan_version != run.plan_version:
            raise ValueError("Plan version mismatch; approval must match current plan version.")
        plan = self.repo.get_plan(run_id, plan_version)
        if not plan:
            raise ValueError("Plan not found.")
        run.approval = RunApproval(
            plan_version=plan_version,
            approved_at=datetime.utcnow(),
            approved_by=approved_by,
        )
        run.status = AuditRunStatus.approved
        self.repo.update_run(run)
        self._emit(run_id, "approve", "Plan approved by reviewer", "completed")
        return run

    async def execute(self, run_id: str) -> None:
        run = self._require_run(run_id)
        if not run.approval or run.approval.plan_version != run.plan_version:
            raise PermissionError("Execute refused: plan not approved for current version.")
        plan = self.repo.get_plan(run_id, run.plan_version)
        if not plan:
            raise ValueError("Plan not found.")

        run.status = AuditRunStatus.running
        self.repo.update_run(run)

        claim = load_claim(run.claim_number)
        enabled = [r.rule_id for r in plan.rules if r.enabled]
        catalog = get_rule_map()

        self._emit(run_id, "load", "Claim loaded", "completed")

        det_ids = [rid for rid in enabled if catalog.get(rid) and catalog[rid].type == "deterministic"]
        self._emit(run_id, "deterministic", "Running deterministic checks", "running")
        det_results = run_deterministic_checks(claim, det_ids)
        det_results = filter_valid_results(claim, det_results)
        self.repo.save_results(run_id, det_results)
        self._emit(run_id, "deterministic", f"Completed {len(det_results)} deterministic checks", "completed")

        judgment_ids = [rid for rid in enabled if catalog.get(rid) and catalog[rid].type == "judgment"]
        self._emit(run_id, "judgment", "Running AI judgment checks", "running")
        judgment_results: list = []
        sem = asyncio.Semaphore(3)

        async def run_one(check_id: str):
            async with sem:
                return await asyncio.to_thread(run_judgment_check, claim, check_id)

        if judgment_ids:
            judgment_results = list(await asyncio.gather(*[run_one(j) for j in judgment_ids]))
        judgment_results = filter_valid_results(claim, judgment_results)
        all_results = det_results + judgment_results
        self.repo.save_results(run_id, all_results)
        self._emit(run_id, "judgment", f"Completed {len(judgment_results)} judgment checks", "completed")

        self._emit(run_id, "synthesize", "Building findings", "running")
        findings = build_findings(run_id, all_results)
        explanations = explain_results(all_results)
        for f in findings:
            if f.rule_id in explanations:
                f.explanation = explanations[f.rule_id]
        self.repo.save_findings(run_id, findings)
        self._emit(run_id, "synthesize", f"Created {len(findings)} findings", "completed")

        self._emit(run_id, "report", "Generating report", "running")
        _ = build_report_markdown(run, findings)
        self._emit(run_id, "report", "Report ready", "completed")

        run.status = AuditRunStatus.completed
        self.repo.update_run(run)
        self._emit(run_id, "complete", "Audit run completed", "completed")

    def _require_run(self, run_id: str) -> AuditRun:
        run = self.repo.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        return run

    def _emit(self, run_id: str, step: str, message: str, status: str) -> AuditEvent:
        event = AuditEvent(
            event_id=new_event_id(),
            run_id=run_id,
            step=step,
            message=message,
            status=status,
        )
        return self.repo.append_event(event)
