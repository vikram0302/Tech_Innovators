from __future__ import annotations

from backend.audit.batch_orchestrator import BatchOrchestrator
from backend.audit.findings import build_findings
from backend.audit.loader import list_claim_numbers_for_dataset, load_claim
from backend.audit.plan import propose_plan
from backend.batch.store import get_batch_store
from backend.dataset.store import get_dataset_store
from backend.db.repositories import get_repository
from backend.judgment.checks import run_judgment_check
from backend.regulations.store import get_regulations_store
from backend.reports.builder import build_report_markdown
from backend.rules.catalog import get_rule_catalog
from backend.rules.engine import run_deterministic_checks

_batch = BatchOrchestrator()


def get_active_regulations_tool() -> dict:
    """Return the active uploaded regulation set."""
    active = get_regulations_store().get_active()
    if not active:
        return {"active": False}
    return {
        "active": True,
        "regulation_set_id": active.regulation_set_id,
        "files": [f.filename for f in active.files],
    }


def list_dataset_claims_tool(dataset_id: str | None = None) -> dict:
    """List claim numbers in the uploaded dataset."""
    if not dataset_id:
        rec = get_dataset_store().get_active()
        dataset_id = rec.dataset_id if rec else None
    if not dataset_id:
        return {"claims": [], "error": "No active dataset"}
    return {"dataset_id": dataset_id, "claims": list_claim_numbers_for_dataset(dataset_id)}


def create_batch_audit_plan_tool(
    dataset_id: str | None = None,
    regulation_set_id: str | None = None,
    objective: str | None = None,
) -> dict:
    """Create a batch audit plan for all claims in the dataset."""
    if not dataset_id:
        rec = get_dataset_store().get_active()
        if not rec:
            raise ValueError("No dataset uploaded")
        dataset_id = rec.dataset_id
    batch = _batch.create_plan(dataset_id, regulation_set_id, objective)
    return batch.model_dump(mode="json")


def run_batch_audit_tool(batch_id: str) -> dict:
    """Execute an approved batch audit."""
    import asyncio

    asyncio.get_event_loop().run_until_complete(_batch.execute(batch_id, skip_approval=False))
    batch = get_batch_store().get_batch(batch_id)
    return {"batch_id": batch_id, "status": batch.status.value if batch else "unknown"}


def get_batch_status_tool(batch_id: str) -> dict:
    batch = get_batch_store().get_batch(batch_id)
    if not batch:
        raise ValueError("Batch not found")
    return batch.model_dump(mode="json")


def get_combined_report_tool(batch_id: str) -> str:
    """Return combined Markdown audit report for a batch run."""
    md = get_batch_store().get_report(batch_id)
    if not md:
        raise ValueError("Report not ready")
    return md


def load_claim_tool(claim_number: str, dataset_id: str | None = None) -> dict:
    claim = load_claim(claim_number, dataset_id)
    return claim.model_dump(mode="json")


def get_rule_catalog_tool() -> dict:
    version, rules = get_rule_catalog()
    return {"version": version, "rules": [r.model_dump(mode="json") for r in rules]}


def propose_plan_tool(claim_number: str, run_id: str, objective: str | None = None) -> dict:
    claim = load_claim(claim_number)
    plan = propose_plan(run_id, claim, objective=objective)
    return plan.model_dump(mode="json")


def run_deterministic_checks_tool(claim_number: str, rule_ids: list[str]) -> list[dict]:
    claim = load_claim(claim_number)
    results = run_deterministic_checks(claim, rule_ids)
    return [r.model_dump(mode="json") for r in results]


def run_judgment_check_tool(claim_number: str, check_id: str) -> dict:
    claim = load_claim(claim_number)
    result = run_judgment_check(claim, check_id)
    return result.model_dump(mode="json")


def build_findings_tool(run_id: str, results: list[dict]) -> list[dict]:
    from backend.audit.models import CheckResult

    parsed = [CheckResult.model_validate(r) for r in results]
    findings = build_findings(run_id, parsed)
    return [f.model_dump(mode="json") for f in findings]


def build_report_tool(run_id: str) -> str:
    repo = get_repository()
    run = repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    findings = repo.get_findings(run_id)
    return build_report_markdown(run, findings)
