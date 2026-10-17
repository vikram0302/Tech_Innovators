from __future__ import annotations

import json
import logging
from datetime import datetime

from pydantic import BaseModel, Field

from backend.api.config import settings
from backend.audit.models import (
    AssessmentType,
    CheckResult,
    CheckStatus,
    EvidenceRef,
    NormalizedClaim,
)
from backend.rules.catalog import get_rule_map

logger = logging.getLogger(__name__)

PROMPT_VERSION = "1.0"


class JudgmentResponse(BaseModel):
    verdict: str
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    rationale: str


def _timeline_context(claim: NormalizedClaim) -> str:
    lines = []
    for event in claim.timeline:
        lines.append(f"{event.source_id} ({event.date}): [{event.type}] {event.text}")
    return "\n".join(lines)


def _heuristic_judgment(claim: NormalizedClaim, check_id: str) -> CheckResult:
    """Fallback when Gemini is unavailable."""
    if check_id == "DOC-03":
        note_police = next(
            (n for n in claim.notes if "police report obtained" in n.text.lower()), None
        )
        comm_received = next(
            (
                c
                for c in claim.communications
                if "police report" in c.text.lower()
                and ("received" in c.text.lower() or "reviewed" in c.text.lower())
            ),
            None,
        )
        if note_police and comm_received and note_police.date < comm_received.date:
            return CheckResult(
                rule_id=check_id,
                status=CheckStatus.fail,
                observed_value="Note claims report obtained before communication log shows receipt",
                expected_value="Consistent dates across notes and communications",
                evidence_refs=[
                    EvidenceRef(source_id=note_police.id, date=note_police.date, excerpt=note_police.text),
                    EvidenceRef(source_id=comm_received.id, date=comm_received.date, excerpt=comm_received.text),
                ],
                reason="Heuristic: date discrepancy on police report.",
                assessment_type=AssessmentType.ai_assessed,
            )
    if check_id == "INV-02":
        for note in claim.notes:
            if "requested" in note.text.lower() and ("photo" in note.text.lower() or "video" in note.text.lower()):
                follow_up = any(
                    "photo" in n.text.lower() or "video" in n.text.lower()
                    for n in claim.notes
                    if n.date > note.date
                )
                if not follow_up:
                    return CheckResult(
                        rule_id=check_id,
                        status=CheckStatus.fail,
                        observed_value="Requested photos/videos with no documented follow-up",
                        expected_value="Follow-up on requested evidence",
                        evidence_refs=[EvidenceRef(source_id=note.id, date=note.date, excerpt=note.text)],
                        assessment_type=AssessmentType.ai_assessed,
                    )
    if check_id == "INV-03":
        liability_notes = [n for n in claim.notes if "fault" in n.text.lower() or "liability" in n.text.lower()]
        if liability_notes:
            return CheckResult(
                rule_id=check_id,
                status=CheckStatus.fail,
                observed_value="Liability conclusion may lack independent corroboration",
                expected_value="Liability supported by file evidence",
                evidence_refs=[
                    EvidenceRef(
                        source_id=liability_notes[0].id,
                        date=liability_notes[0].date,
                        excerpt=liability_notes[0].text,
                    )
                ],
                reason="Heuristic liability review.",
                assessment_type=AssessmentType.ai_assessed,
            )
    return CheckResult(
        rule_id=check_id,
        status=CheckStatus.pass_,
        observed_value="No issues detected (heuristic)",
        assessment_type=AssessmentType.ai_assessed,
    )


def _call_gemini(claim: NormalizedClaim, check_id: str, rule_title: str, rule_desc: str) -> JudgmentResponse | None:
    if not settings.google_api_key and not settings.google_genai_use_vertexai:
        return None
    try:
        from google import genai
        from google.genai import types

        client_kwargs: dict = {}
        if settings.google_genai_use_vertexai:
            client_kwargs["vertexai"] = True
            client_kwargs["project"] = settings.google_cloud_project
            client_kwargs["location"] = settings.google_cloud_location
        else:
            client_kwargs["api_key"] = settings.google_api_key

        client = genai.Client(**client_kwargs)
        from backend.audit.batch_orchestrator import get_regulation_context

        reg_ctx = get_regulation_context()
        reg_block = ""
        if reg_ctx:
            reg_block = f"\nUploaded regulations (excerpt):\n{reg_ctx[:8000]}\n"

        prompt = f"""You are an insurance claims audit assistant. Evaluate ONLY the following rule using the timeline entries.
Cite evidence using source_id values (N1, C1, etc.) and quote exact excerpts from those entries.
Do not invent facts. Use uploaded regulations as the standard where applicable.
{reg_block}
Rule {check_id}: {rule_title}
{rule_desc}

Timeline:
{_timeline_context(claim)}

Return JSON matching: verdict (pass|fail|not_evaluable), confidence (0-1), evidence_refs (list of source_id, date YYYY-MM-DD, excerpt), rationale.
"""
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=JudgmentResponse.model_json_schema(),
            ),
        )
        text = response.text or "{}"
        return JudgmentResponse.model_validate(json.loads(text))
    except Exception as exc:
        logger.warning("Gemini judgment failed for %s: %s", check_id, exc)
        return None


def run_judgment_check(claim: NormalizedClaim, check_id: str) -> CheckResult:
    catalog = get_rule_map()
    rule = catalog.get(check_id)
    if not rule or rule.type != "judgment":
        return CheckResult(
            rule_id=check_id,
            status=CheckStatus.not_evaluable,
            reason=f"Unknown judgment rule: {check_id}",
            assessment_type=AssessmentType.ai_assessed,
        )

    parsed = _call_gemini(claim, check_id, rule.title, rule.description)
    if parsed is None:
        result = _heuristic_judgment(claim, check_id)
        result.computed_at = datetime.utcnow()
        return result

    status_map = {
        "pass": CheckStatus.pass_,
        "fail": CheckStatus.fail,
        "not_evaluable": CheckStatus.not_evaluable,
    }
    status = status_map.get(parsed.verdict.lower(), CheckStatus.not_evaluable)
    return CheckResult(
        rule_id=check_id,
        status=status,
        observed_value=parsed.rationale[:500],
        expected_value=rule.description,
        evidence_refs=parsed.evidence_refs,
        reason=f"AI-assessed (prompt v{PROMPT_VERSION}, confidence {parsed.confidence:.2f})",
        assessment_type=AssessmentType.ai_assessed,
    )


def explain_results(results: list[CheckResult]) -> dict[str, str]:
    """Plain-language explanations keyed by rule_id."""
    explanations: dict[str, str] = {}
    for result in results:
        prefix = "AI assessment: " if result.assessment_type == AssessmentType.ai_assessed else "Deterministic check: "
        body = result.observed_value or result.reason or "No additional detail."
        explanations[result.rule_id] = prefix + body
    if settings.google_api_key or settings.google_genai_use_vertexai:
        try:
            from google import genai

            client_kwargs: dict = {}
            if settings.google_genai_use_vertexai:
                client_kwargs["vertexai"] = True
                client_kwargs["project"] = settings.google_cloud_project
                client_kwargs["location"] = settings.google_cloud_location
            else:
                client_kwargs["api_key"] = settings.google_api_key
            client = genai.Client(**client_kwargs)
            payload = [
                {
                    "rule_id": r.rule_id,
                    "status": r.status.value,
                    "observed": r.observed_value,
                    "expected": r.expected_value,
                }
                for r in results
            ]
            prompt = (
                "Write one sentence per rule explaining the audit outcome. "
                "Use ONLY facts from the JSON. Return JSON object rule_id -> explanation.\n"
                + json.dumps(payload)
            )
            response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
            if response.text:
                parsed = json.loads(response.text)
                if isinstance(parsed, dict):
                    explanations.update({str(k): str(v) for k, v in parsed.items()})
        except Exception as exc:
            logger.debug("Explanation pass skipped: %s", exc)
    return explanations
