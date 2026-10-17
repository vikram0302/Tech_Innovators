from __future__ import annotations

from collections import Counter

from backend.audit.models import AuditRun, Finding, Severity
from backend.rules.catalog import get_rule_map


def build_report_markdown(run: AuditRun, findings: list[Finding]) -> str:
    catalog = get_rule_map()
    counts = Counter(f.severity.value for f in findings if f.status.value == "fail")
    lines = [
        f"# Claims Audit Report",
        "",
        f"**Run ID:** {run.run_id}  ",
        f"**Claim:** {run.claim_number}  ",
        f"**Status:** {run.status.value}  ",
        f"**Plan version:** {run.plan_version}  ",
        "",
        "## Summary",
        "",
        f"- High severity failures: {counts.get(Severity.high.value, 0)}",
        f"- Medium severity failures: {counts.get(Severity.medium.value, 0)}",
        f"- Low severity failures: {counts.get(Severity.low.value, 0)}",
        "",
        "## Findings",
        "",
    ]
    for finding in findings:
        rule = catalog.get(finding.rule_id)
        title = rule.title if rule else finding.rule_id
        assess = "AI-assessed" if finding.assessment_type.value == "ai_assessed" else "Deterministic"
        lines.extend(
            [
                f"### {finding.rule_id} — {title} ({assess})",
                f"- **Status:** {finding.status.value}",
                f"- **Severity:** {finding.severity.value}",
                f"- **Observed:** {finding.observed_value or '—'}",
                f"- **Expected:** {finding.expected_value or '—'}",
            ]
        )
        if finding.explanation:
            lines.append(f"- **Explanation:** {finding.explanation}")
        if finding.evidence_refs:
            lines.append("- **Evidence:**")
            for ref in finding.evidence_refs:
                lines.append(f"  - `{ref.source_id}` ({ref.date}): \"{ref.excerpt[:200]}\"")
        lines.append("")

    gaps = [f for f in findings if f.status.value == "not_evaluable"]
    if gaps:
        lines.extend(["## Data gaps", ""])
        for g in gaps:
            lines.append(f"- **{g.rule_id}:** {g.observed_value or g.explanation or 'Not evaluable'}")
        lines.append("")

    lines.append("_Hour-level standards are evaluated at day granularity where timestamps are absent._")
    return "\n".join(lines)


def build_combined_report_markdown(
    batch: "BatchAuditRun",
    findings: list[Finding],
    regulation_context: str = "",
) -> str:
    from backend.audit.models import BatchAuditRun

    catalog = get_rule_map()
    failures = [f for f in findings if f.status.value == "fail"]
    counts = Counter(f.severity.value for f in failures)
    by_claim: dict[str, list[Finding]] = {}
    for f in findings:
        cn = f.claim_number or "unknown"
        by_claim.setdefault(cn, []).append(f)

    lines = [
        "# Combined Claims Audit Report",
        "",
        f"**Batch ID:** {batch.batch_id}",
        f"**Dataset:** {batch.dataset_id}",
        f"**Regulation set:** {batch.regulation_set_id}",
        f"**Regulation files:** {', '.join(batch.regulation_file_names) or '—'}",
        f"**Claims audited:** {len(batch.claim_numbers)}",
        "",
        "## Portfolio summary",
        "",
        f"- High severity failures: {counts.get(Severity.high.value, 0)}",
        f"- Medium severity failures: {counts.get(Severity.medium.value, 0)}",
        f"- Low severity failures: {counts.get(Severity.low.value, 0)}",
        "",
    ]
    if regulation_context:
        excerpt = regulation_context[:2000].replace("\n", " ")
        lines.extend(["## Regulations reference (excerpt)", "", excerpt + ("…" if len(regulation_context) > 2000 else ""), ""])

    for claim_number in batch.claim_numbers:
        claim_findings = by_claim.get(claim_number, [])
        lines.append(f"## Claim {claim_number}")
        lines.append("")
        if not claim_findings:
            lines.append("_No findings recorded._")
            lines.append("")
            continue
        for finding in claim_findings:
            rule = catalog.get(finding.rule_id)
            title = rule.title if rule else finding.rule_id
            assess = "AI-assessed" if finding.assessment_type.value == "ai_assessed" else "Deterministic"
            lines.extend(
                [
                    f"### {finding.rule_id} — {title} ({assess})",
                    f"- **Status:** {finding.status.value}",
                    f"- **Severity:** {finding.severity.value}",
                    f"- **Observed:** {finding.observed_value or '—'}",
                ]
            )
            if finding.evidence_refs:
                lines.append("- **Evidence:**")
                for ref in finding.evidence_refs[:3]:
                    lines.append(f"  - `{ref.source_id}`: \"{ref.excerpt[:160]}\"")
            lines.append("")

    gaps = [f for f in findings if f.status.value == "not_evaluable"]
    if gaps:
        lines.extend(["## Data gaps (all claims)", ""])
        for g in gaps:
            lines.append(f"- **{g.claim_number or '?'} / {g.rule_id}:** {g.observed_value or g.explanation or 'Not evaluable'}")
        lines.append("")

    lines.append("_Audits evaluated against uploaded regulations and deterministic rule catalog._")
    return "\n".join(lines)
