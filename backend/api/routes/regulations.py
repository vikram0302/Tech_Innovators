from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from backend.regulations.store import get_regulations_store

router = APIRouter(prefix="/api/regulations", tags=["regulations"])


@router.post("/upload")
async def upload_regulations(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="At least one regulation file is required")
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        name = f.filename or "regulation.pdf"
        if not name.lower().endswith((".pdf", ".txt", ".md")):
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {name}")
        data = await f.read()
        payloads.append((name, data))
    reg_set = get_regulations_store().upload_to_active(payloads)
    return {
        "regulation_set_id": reg_set.regulation_set_id,
        "files": [x.model_dump() for x in reg_set.files],
        "is_active": True,
    }


@router.get("/active/files/{filename:path}")
def get_active_regulation_file(filename: str):
    store = get_regulations_store()
    active = store.get_active()
    if not active:
        raise HTTPException(status_code=404, detail="No active regulation set")
    path = store.resolve_file_path(active.regulation_set_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return FileResponse(path, media_type="application/pdf", filename=path.name)
    text = path.read_text(encoding="utf-8", errors="replace")
    return PlainTextResponse(content=text, media_type="text/plain; charset=utf-8")


@router.delete("/active/files/{filename:path}")
def delete_active_regulation_file(filename: str):
    store = get_regulations_store()
    active = store.get_active()
    if not active:
        raise HTTPException(status_code=404, detail="No active regulation set")
    try:
        updated = store.remove_file(active.regulation_set_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not updated:
        return {"active": False, "regulation_set_id": None, "files": []}
    return {
        "active": True,
        "regulation_set_id": updated.regulation_set_id,
        "files": [f.filename for f in updated.files],
    }


@router.get("/active")
def get_active_regulations():
    active = get_regulations_store().get_active()
    if not active:
        return {"active": False, "regulation_set_id": None, "files": []}
    return {
        "active": True,
        "regulation_set_id": active.regulation_set_id,
        "files": [f.filename for f in active.files],
        "uploaded_at": active.created_at.isoformat(),
    }


@router.get("")
def list_regulation_sets():
    sets = get_regulations_store().list_sets()
    return {
        "sets": [
            {
                "regulation_set_id": s.regulation_set_id,
                "files": [f.filename for f in s.files],
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat(),
            }
            for s in sets
        ]
    }


@router.put("/{regulation_set_id}/activate")
def activate_regulation_set(regulation_set_id: str):
    try:
        reg = get_regulations_store().activate(regulation_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"regulation_set_id": reg.regulation_set_id, "is_active": True}
