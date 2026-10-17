from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.config import settings
from backend.api.routes import audits, batch, chat, claims, dataset, regulations

app = FastAPI(title="Claims Audit API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(claims.router)
app.include_router(audits.router)
app.include_router(regulations.router)
app.include_router(dataset.router)
app.include_router(batch.router)
app.include_router(chat.router)

import os

if os.environ.get("ENABLE_ADK_MOUNT", "").lower() in ("1", "true", "yes"):
    try:
        from google.adk.cli.fast_api import get_fast_api_app

        adk_app = get_fast_api_app(
            agent_dir=str(__import__("pathlib").Path(__file__).resolve().parents[1] / "agent")
        )
        app.mount("/adk", adk_app)
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok"}
