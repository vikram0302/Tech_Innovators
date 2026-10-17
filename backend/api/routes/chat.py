from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.agent import tools as agent_tools
from backend.api.config import settings
from backend.audit.batch_orchestrator import BatchOrchestrator
from backend.dataset.store import get_dataset_store
from backend.regulations.store import get_regulations_store

router = APIRouter(prefix="/api/chat", tags=["chat"])
batch_orchestrator = BatchOrchestrator()


class ChatRequest(BaseModel):
    message: str
    planning_mode: bool = False
    dataset_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    batch_id: str | None = None
    actions: list[dict[str, Any]] = []


@router.post("/send", response_model=ChatResponse)
async def chat_send(body: ChatRequest):
    """Agent-style chat: interprets intent and invokes batch audit tools."""
    msg = body.message.lower()
    reg = get_regulations_store().get_active()
    if not reg:
        return ChatResponse(
            reply="Please upload regulation files in the Regulations tab before starting an audit.",
        )

    ds_id = body.dataset_id
    if not ds_id:
        active_ds = get_dataset_store().get_active()
        ds_id = active_ds.dataset_id if active_ds else None
    if not ds_id:
        return ChatResponse(
            reply="Upload adjuster notes, communication logs, and reference workbook in the claims upload panel.",
        )

    if any(k in msg for k in ("audit", "start", "run", "all claims", "verify")):
        try:
            batch = batch_orchestrator.create_plan(ds_id, reg.regulation_set_id, body.message)
            if body.planning_mode:
                return ChatResponse(
                    reply=(
                        f"Batch audit plan created for {len(batch.claim_numbers)} claim(s) "
                        f"against regulation set {reg.regulation_set_id}. "
                        "Click Approve & Start audit when you are ready."
                    ),
                    batch_id=batch.batch_id,
                    actions=[{"type": "batch_planned", "batch_id": batch.batch_id}],
                )
            batch = batch_orchestrator.approve(batch.batch_id, batch.plan_version)
            return ChatResponse(
                reply=(
                    f"Batch audit plan approved for {len(batch.claim_numbers)} claim(s). "
                    "Starting audit — watch the Task Panel for progress."
                ),
                batch_id=batch.batch_id,
                actions=[{"type": "batch_ready_to_execute", "batch_id": batch.batch_id}],
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    claims = agent_tools.list_dataset_claims_tool(ds_id)
    return ChatResponse(
        reply=(
            f"Claims Audit Agent ready. Active regulations: {', '.join(f.filename for f in reg.files)}. "
            f"Dataset has {len(claims.get('claims', []))} claim(s). "
            "Ask me to audit all claims against the regulations."
        ),
        actions=[{"type": "info"}],
    )


@router.get("/adk-status")
def adk_status():
    from backend.agent.agent import root_agent

    return {
        "adk_available": root_agent is not None,
        "gemini_configured": bool(settings.google_api_key or settings.google_genai_use_vertexai),
    }
