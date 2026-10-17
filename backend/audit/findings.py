from __future__ import annotations

import uuid

from backend.audit.models import AssessmentType, CheckResult, Finding, Severity
from backend.rules.catalog import get_rule_map


def build_findings(run_id: str, results: list[CheckResult]) -> list[Finding]:
    catalog = get_rule_map()
    findings: list[Finding] = []
    for result in results:
        rule = catalog.get(result.rule_id)
        if not rule:
            continue
        severity = Severity.low
        if result.status.value == "fail":
            severity = rule.severity_if_failed
        elif result.status.value == "not_evaluable":
            severity = Severity.low
        findings.append(
            Finding(
                finding_id=str(uuid.uuid4()),
                run_id=run_id,
                rule_id=result.rule_id,
                severity=severity,
                status=result.status,
                observed_value=result.observed_value,
                expected_value=result.expected_value or rule.threshold,
                evidence_refs=result.evidence_refs,
                recommended_action=rule.remediation,
                assessment_type=result.assessment_type,
            )
        )
    severity_order = {Severity.high: 0, Severity.medium: 1, Severity.low: 2}
    findings.sort(key=lambda f: (severity_order.get(f.severity, 3), f.rule_id))
    return findings
