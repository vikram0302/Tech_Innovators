from __future__ import annotations

from fastapi import APIRouter

from backend.audit.loader import list_claim_numbers

router = APIRouter(prefix="/api/claims", tags=["claims"])


@router.get("")
def list_claims():
    return {"claims": list_claim_numbers()}
