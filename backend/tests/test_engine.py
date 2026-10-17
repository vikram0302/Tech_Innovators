from __future__ import annotations

import pytest

from backend.audit.loader import load_claim, list_claim_numbers_for_dataset
from backend.audit.models import CheckStatus
from backend.judgment.checks import run_judgment_check
from backend.rules.engine import run_deterministic_checks


@pytest.fixture
def golden_claim():
    return load_claim("VAPJPAS086739", "repo")


def test_list_repo_claims():
    claims = list_claim_numbers_for_dataset("repo")
    assert "VAPJPAS086739" in claims


def test_com_01_pass_golden(golden_claim):
    results = {r.rule_id: r for r in run_deterministic_checks(golden_claim, ["COM-01"])}
    assert results["COM-01"].status == CheckStatus.pass_


def test_inv_01_pass_golden(golden_claim):
    results = {r.rule_id: r for r in run_deterministic_checks(golden_claim, ["INV-01"])}
    assert results["INV-01"].status == CheckStatus.pass_


def test_set_01_not_evaluable_golden(golden_claim):
    results = {r.rule_id: r for r in run_deterministic_checks(golden_claim, ["SET-01"])}
    assert results["SET-01"].status == CheckStatus.not_evaluable


def test_doc_02_pass_with_final_assessment(golden_claim):
    results = {r.rule_id: r for r in run_deterministic_checks(golden_claim, ["DOC-02"])}
    assert results["DOC-02"].status == CheckStatus.pass_


def test_doc_03_heuristic_judgment(golden_claim):
    result = run_judgment_check(golden_claim, "DOC-03")
    assert result.status == CheckStatus.fail
    assert result.evidence_refs
