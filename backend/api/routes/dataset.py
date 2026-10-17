from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.api.config import settings
from backend.audit.loader import list_claim_numbers_for_dataset
from backend.dataset.store import get_dataset_store
from backend.regulations.store import get_regulations_store

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


@router.post("/upload")
async def upload_dataset(
    adjuster_notes: UploadFile = File(...),
    communication_logs: UploadFile = File(...),
    reference: UploadFile = File(...),
):
    if not get_regulations_store().get_active():
        raise HTTPException(
            status_code=400,
            detail="Upload regulations first (Regulations tab) before claims data.",
        )
    notes_bytes = await adjuster_notes.read()
    comms_bytes = await communication_logs.read()
    ref_bytes = await reference.read()
    ref_name = reference.filename or "reference.xlsx"
    try:
        record = get_dataset_store().save_upload(
            notes_bytes, comms_bytes, ref_bytes, reference_filename=ref_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "dataset_id": record.dataset_id,
        "claim_numbers": record.claim_numbers,
        "claim_count": len(record.claim_numbers),
        "source_files": record.source_files,
    }


@router.get("/active")
def get_active_dataset():
    record = get_dataset_store().get_active()
    if not record:
        return {"active": False, "dataset_id": None, "claim_numbers": [], "source_files": []}
    return {
        "active": True,
        "dataset_id": record.dataset_id,
        "claim_numbers": record.claim_numbers,
        "source_files": record.source_files,
    }


@router.get("/{dataset_id}/claims")
def list_dataset_claims(dataset_id: str):
    try:
        claims = list_claim_numbers_for_dataset(dataset_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"dataset_id": dataset_id, "claims": claims}


@router.post("/demo-load")
def demo_load_dataset():
    if not settings.use_repo_sample_data:
        raise HTTPException(status_code=400, detail="Demo dataset disabled")
    record = get_dataset_store().ensure_demo_dataset()
    return {"dataset_id": record.dataset_id, "claim_numbers": record.claim_numbers}
