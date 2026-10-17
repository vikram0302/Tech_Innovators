from __future__ import annotations

from backend.audit.models import CheckResult, EvidenceRef, NormalizedClaim


def _source_text(claim: NormalizedClaim, source_id: str) -> str | None:
    for note in claim.notes:
        if note.id == source_id:
            return note.text
    for comm in claim.communications:
        if comm.id == source_id:
            return comm.text
    return None


def verify_evidence_ref(claim: NormalizedClaim, ref: EvidenceRef) -> bool:
    text = _source_text(claim, ref.source_id)
    if text is None:
        return False
    if not ref.excerpt:
        return True
    return ref.excerpt.strip() in text or text.strip() in ref.excerpt.strip()


def verify_check_result(claim: NormalizedClaim, result: CheckResult) -> CheckResult:
    valid_refs: list[EvidenceRef] = []
    for ref in result.evidence_refs:
        if verify_evidence_ref(claim, ref):
            valid_refs.append(ref)
    result.evidence_refs = valid_refs
    return result


def filter_valid_results(claim: NormalizedClaim, results: list[CheckResult]) -> list[CheckResult]:
    cleaned: list[CheckResult] = []
    for result in results:
        verified = verify_check_result(claim, result)
        if verified.status.value == "fail" and not verified.evidence_refs:
            verified.reason = (verified.reason or "") + " Evidence citations could not be verified."
        cleaned.append(verified)
    return cleaned
