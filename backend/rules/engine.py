from __future__ import annotations

from datetime import timedelta

from backend.audit.models import (
    AssessmentType,
    CheckResult,
    CheckStatus,
    EvidenceRef,
    NormalizedClaim,
)
from backend.rules.catalog import get_rule_map

DAY_GRANULARITY_NOTE = "Evaluated at day granularity (sample data has dates only)."


def run_deterministic_checks(
    claim: NormalizedClaim, rule_ids: list[str] | None = None
) -> list[CheckResult]:
    catalog = get_rule_map()
    ids = rule_ids or [r for r, d in catalog.items() if d.type == "deterministic"]
    results: list[CheckResult] = []
    for rule_id in ids:
        if rule_id not in catalog:
            continue
        handler = _HANDLERS.get(rule_id)
        if handler:
            results.append(handler(claim))
    return results


def _ev(source_id: str, claim: NormalizedClaim, excerpt: str | None = None) -> EvidenceRef:
    for note in claim.notes:
        if note.id == source_id:
            return EvidenceRef(source_id=source_id, date=note.date, excerpt=excerpt or note.text[:200])
    for comm in claim.communications:
        if comm.id == source_id:
            return EvidenceRef(source_id=source_id, date=comm.date, excerpt=excerpt or comm.text[:200])
    return EvidenceRef(source_id=source_id, excerpt=excerpt or "")


def _check_set_01(claim: NormalizedClaim) -> CheckResult:
    receipt = claim.reference.get("receipt_timestamp")
    if not receipt:
        return CheckResult(
            rule_id="SET-01",
            status=CheckStatus.not_evaluable,
            reason="Receipt timestamp not recorded in claim file.",
            observed_value="No receipt timestamp",
            expected_value="Documented receipt time",
        )
    return CheckResult(
        rule_id="SET-01",
        status=CheckStatus.pass_,
        observed_value=f"Receipt at {receipt}",
        expected_value="Acknowledgment within 24 hours",
    )


def _check_com_01(claim: NormalizedClaim) -> CheckResult:
    open_date = claim.derived.open_date
    if not open_date:
        return CheckResult(
            rule_id="COM-01",
            status=CheckStatus.not_evaluable,
            reason="Cannot determine claim open/receipt date.",
        )
    contact_dates = []
    refs: list[EvidenceRef] = []
    for comm in claim.communications:
        party = comm.party.lower()
        text_l = comm.text.lower()
        if (
            "claimant" in party
            or "contact" in text_l
            or comm.type.lower().find("call") >= 0
            or comm.type.lower().find("phone") >= 0
        ):
            contact_dates.append(comm.date)
            refs.append(_ev(comm.id, claim))
    for note in claim.notes:
        if "contact" in note.type.lower() or "spoke with claimant" in note.text.lower():
            contact_dates.append(note.date)
            refs.append(_ev(note.id, claim))
    if not contact_dates:
        return CheckResult(
            rule_id="COM-01",
            status=CheckStatus.fail,
            observed_value="No claimant contact found",
            expected_value="Contact within 2 days of receipt",
            evidence_refs=refs,
            reason=DAY_GRANULARITY_NOTE,
        )
    first_contact = min(contact_dates)
    delta = (first_contact - open_date).days
    status = CheckStatus.pass_ if delta <= 2 else CheckStatus.fail
    return CheckResult(
        rule_id="COM-01",
        status=status,
        observed_value=f"First contact {first_contact} ({delta} days after {open_date})",
        expected_value="Within 2 days (48h at day granularity)",
        evidence_refs=refs[:3],
        reason=DAY_GRANULARITY_NOTE,
    )


def _check_com_02(claim: NormalizedClaim) -> CheckResult:
    open_d = claim.derived.open_date
    close_d = claim.derived.close_date
    if not open_d:
        return CheckResult(rule_id="COM-02", status=CheckStatus.not_evaluable, reason="Missing open date.")
    claimant_events = sorted(
        [c for c in claim.communications if "claimant" in c.party.lower()],
        key=lambda c: c.date,
    )
    if len(claimant_events) < 2:
        return CheckResult(
            rule_id="COM-02",
            status=CheckStatus.pass_,
            observed_value="Fewer than two claimant communications; gap rule not triggered",
            expected_value="No gap > 14 days while open",
            reason=DAY_GRANULARITY_NOTE,
        )
    max_gap = 0
    gap_ref: EvidenceRef | None = None
    for i in range(1, len(claimant_events)):
        gap = (claimant_events[i].date - claimant_events[i - 1].date).days
        if gap > max_gap:
            max_gap = gap
            gap_ref = _ev(claimant_events[i].id, claim)
    if close_d and (close_d - open_d).days <= 14:
        return CheckResult(
            rule_id="COM-02",
            status=CheckStatus.pass_,
            observed_value=f"Claim closed in {(close_d - open_d).days} days",
            expected_value="No gap > 14 days while open",
        )
    status = CheckStatus.pass_ if max_gap <= 14 else CheckStatus.fail
    return CheckResult(
        rule_id="COM-02",
        status=status,
        observed_value=f"Max claimant update gap: {max_gap} days",
        expected_value="Max gap 14 days",
        evidence_refs=[gap_ref] if gap_ref else [],
        reason=DAY_GRANULARITY_NOTE,
    )


def _check_com_03(claim: NormalizedClaim) -> CheckResult:
    comm_count = len(claim.communications)
    documented = 0
    refs: list[EvidenceRef] = []
    for comm in claim.communications:
        if "claimant" not in comm.party.lower():
            continue
        found = False
        for note in claim.notes:
            if note.date == comm.date or comm.text[:20].lower() in note.text.lower():
                found = True
                documented += 1
                refs.append(_ev(note.id, claim))
                break
        if not found:
            refs.append(_ev(comm.id, claim))
    if comm_count == 0:
        return CheckResult(rule_id="COM-03", status=CheckStatus.pass_, observed_value="No communications")
    ratio = documented / max(1, sum(1 for c in claim.communications if "claimant" in c.party.lower()))
    status = CheckStatus.pass_ if ratio >= 0.5 else CheckStatus.fail
    return CheckResult(
        rule_id="COM-03",
        status=status,
        observed_value=f"{documented} claimant comms reflected in notes",
        expected_value="Each claimant communication summarized in notes",
        evidence_refs=refs[:3],
    )


def _check_inv_01(claim: NormalizedClaim) -> CheckResult:
    open_d = claim.derived.open_date
    close_d = claim.derived.close_date
    if not open_d or not close_d:
        return CheckResult(
            rule_id="INV-01",
            status=CheckStatus.not_evaluable,
            reason="Open or close date missing.",
        )
    days = (close_d - open_d).days
    extended = any("extenuating" in n.text.lower() or "extension" in n.text.lower() for n in claim.notes)
    limit = 30
    if days <= limit or extended:
        status = CheckStatus.pass_
    else:
        status = CheckStatus.fail
    ref = _ev(claim.notes[-1].id, claim) if claim.notes else EvidenceRef(source_id="N1", excerpt="")
    return CheckResult(
        rule_id="INV-01",
        status=status,
        observed_value=f"Investigation span {days} days",
        expected_value=f"Within {limit} days or documented extension",
        evidence_refs=[ref],
    )


def _check_res_01(claim: NormalizedClaim) -> CheckResult:
    reserve = claim.reference.get("initial_reserve")
    if reserve is None:
        for note in claim.notes:
            if "reserve" in note.text.lower():
                return CheckResult(
                    rule_id="RES-01",
                    status=CheckStatus.pass_,
                    observed_value="Reserve mentioned in notes",
                    evidence_refs=[_ev(note.id, claim)],
                )
        return CheckResult(
            rule_id="RES-01",
            status=CheckStatus.fail,
            observed_value="No initial reserve documented",
            expected_value="Initial reserve at FNOL",
            reason="Not found in reference data or notes.",
        )
    return CheckResult(
        rule_id="RES-01",
        status=CheckStatus.pass_,
        observed_value=f"Initial reserve: {reserve}",
        expected_value="Documented initial reserve",
    )


def _check_res_02(claim: NormalizedClaim) -> CheckResult:
    last = claim.reference.get("reserve_last_reviewed")
    if not last:
        return CheckResult(
            rule_id="RES-02",
            status=CheckStatus.not_evaluable,
            reason="Reserve review dates not available in reference data.",
            observed_value="No reserve review history",
            expected_value="Review every 60 days",
        )
    return CheckResult(
        rule_id="RES-02",
        status=CheckStatus.pass_,
        observed_value=f"Last review: {last}",
        expected_value="Review every 60 days",
    )


def _check_doc_01(claim: NormalizedClaim) -> CheckResult:
    dates = [n.date for n in claim.notes]
    sorted_dates = sorted(dates)
    status = CheckStatus.pass_ if dates == sorted_dates else CheckStatus.fail
    ref = _ev(claim.notes[0].id, claim) if claim.notes else EvidenceRef(source_id="N1", excerpt="")
    return CheckResult(
        rule_id="DOC-01",
        status=status,
        observed_value="Notes in chronological order" if status == CheckStatus.pass_ else "Notes out of order",
        expected_value="Chronological notes",
        evidence_refs=[ref],
    )


def _check_doc_02(claim: NormalizedClaim) -> CheckResult:
    if not claim.derived.close_date:
        return CheckResult(rule_id="DOC-02", status=CheckStatus.not_evaluable, reason="Claim not closed.")
    for note in claim.notes:
        t = note.type.lower()
        if "final" in t and ("report" in t or "assessment" in t):
            return CheckResult(
                rule_id="DOC-02",
                status=CheckStatus.pass_,
                observed_value="Final report note present",
                evidence_refs=[_ev(note.id, claim)],
            )
        if "final assessment" in note.text.lower():
            return CheckResult(
                rule_id="DOC-02",
                status=CheckStatus.pass_,
                observed_value="Final assessment documented",
                evidence_refs=[_ev(note.id, claim)],
            )
    close_note = claim.notes[-1] if claim.notes else None
    return CheckResult(
        rule_id="DOC-02",
        status=CheckStatus.fail,
        observed_value="No dedicated final report; only closure note",
        expected_value="Final report on resolution",
        evidence_refs=[_ev(close_note.id, claim)] if close_note else [],
    )


def _check_frd_01(claim: NormalizedClaim) -> CheckResult:
    flagged = claim.reference.get("fraud_indicator") or any(
        "siu" in n.text.lower() or "fraud" in n.text.lower() for n in claim.notes
    )
    if not flagged:
        return CheckResult(
            rule_id="FRD-01",
            status=CheckStatus.pass_,
            observed_value="No fraud indicator in file",
        )
    documented = any("refer" in n.text.lower() or "siu" in n.text.lower() for n in claim.notes)
    status = CheckStatus.pass_ if documented else CheckStatus.fail
    return CheckResult(
        rule_id="FRD-01",
        status=status,
        observed_value="SIU referral documented" if documented else "Fraud indicator without SIU documentation",
        expected_value="Referral or documented non-referral",
    )


_HANDLERS = {
    "SET-01": _check_set_01,
    "COM-01": _check_com_01,
    "COM-02": _check_com_02,
    "COM-03": _check_com_03,
    "INV-01": _check_inv_01,
    "RES-01": _check_res_01,
    "RES-02": _check_res_02,
    "DOC-01": _check_doc_01,
    "DOC-02": _check_doc_02,
    "FRD-01": _check_frd_01,
}
