from __future__ import annotations

from backend.audit.models import AuditPlan, NormalizedClaim, PlanRuleItem
from backend.rules.catalog import get_rule_catalog
from backend.rules.engine import run_deterministic_checks


def propose_plan(
    run_id: str,
    claim: NormalizedClaim,
    version: int = 1,
    objective: str | None = None,
    enabled_rule_ids: list[str] | None = None,
) -> AuditPlan:
    _, catalog = get_rule_catalog()
    preview = run_deterministic_checks(claim, [r.rule_id for r in catalog if r.type == "deterministic"])
    gap_by_rule = {p.rule_id: p.reason or p.observed_value for p in preview if p.status.value == "not_evaluable"}

    rules: list[PlanRuleItem] = []
    data_gaps_summary: list[str] = []
    for rule in catalog:
        enabled = True if enabled_rule_ids is None else rule.rule_id in enabled_rule_ids
        gaps: list[str] = []
        if rule.rule_id in gap_by_rule and gap_by_rule[rule.rule_id]:
            gaps.append(gap_by_rule[rule.rule_id] or "Potential data gap")
            data_gaps_summary.append(f"{rule.rule_id}: {gaps[0]}")
        rules.append(PlanRuleItem(rule_id=rule.rule_id, enabled=enabled, data_gaps=gaps))

    return AuditPlan(
        run_id=run_id,
        version=version,
        claim_number=claim.claim_number,
        objective=objective,
        rules=rules,
        data_gaps_summary=list(dict.fromkeys(data_gaps_summary)),
    )
