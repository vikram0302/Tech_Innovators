from __future__ import annotations

import os

os.environ["USE_MEMORY_DB"] = "true"

from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_execute_requires_approval():
    plan_resp = client.post(
        "/api/audits/plan",
        json={"claim_number": "VAPJPAS086739"},
    )
    assert plan_resp.status_code == 200
    run_id = plan_resp.json()["run"]["run_id"]
    exec_resp = client.post(f"/api/audits/{run_id}/execute")
    assert exec_resp.status_code == 403
