from __future__ import annotations

import copy
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from backend.audit.models import AuditEvent, AuditPlan, AuditRun, CheckResult, Finding


class AuditRepository(ABC):
    @abstractmethod
    def create_run(self, run: AuditRun) -> AuditRun: ...

    @abstractmethod
    def get_run(self, run_id: str) -> AuditRun | None: ...

    @abstractmethod
    def update_run(self, run: AuditRun) -> AuditRun: ...

    @abstractmethod
    def save_plan(self, plan: AuditPlan) -> AuditPlan: ...

    @abstractmethod
    def get_plan(self, run_id: str, version: int) -> AuditPlan | None: ...

    @abstractmethod
    def get_latest_plan(self, run_id: str) -> AuditPlan | None: ...

    @abstractmethod
    def save_results(self, run_id: str, results: list[CheckResult]) -> None: ...

    @abstractmethod
    def get_results(self, run_id: str) -> list[CheckResult]: ...

    @abstractmethod
    def save_findings(self, run_id: str, findings: list[Finding]) -> None: ...

    @abstractmethod
    def get_findings(self, run_id: str) -> list[Finding]: ...

    @abstractmethod
    def append_event(self, event: AuditEvent) -> AuditEvent: ...

    @abstractmethod
    def list_events(self, run_id: str, after_id: str | None = None) -> list[AuditEvent]: ...


class InMemoryAuditRepository(AuditRepository):
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._plans: dict[str, dict[int, dict[str, Any]]] = {}
        self._results: dict[str, list[dict[str, Any]]] = {}
        self._findings: dict[str, list[dict[str, Any]]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}

    def create_run(self, run: AuditRun) -> AuditRun:
        self._runs[run.run_id] = run.model_dump(mode="json")
        return run

    def get_run(self, run_id: str) -> AuditRun | None:
        data = self._runs.get(run_id)
        return AuditRun.model_validate(data) if data else None

    def update_run(self, run: AuditRun) -> AuditRun:
        run.updated_at = datetime.utcnow()
        self._runs[run.run_id] = run.model_dump(mode="json")
        return run

    def save_plan(self, plan: AuditPlan) -> AuditPlan:
        self._plans.setdefault(plan.run_id, {})[plan.version] = plan.model_dump(mode="json")
        return plan

    def get_plan(self, run_id: str, version: int) -> AuditPlan | None:
        data = self._plans.get(run_id, {}).get(version)
        return AuditPlan.model_validate(data) if data else None

    def get_latest_plan(self, run_id: str) -> AuditPlan | None:
        versions = self._plans.get(run_id, {})
        if not versions:
            return None
        latest = max(versions.keys())
        return AuditPlan.model_validate(versions[latest])

    def save_results(self, run_id: str, results: list[CheckResult]) -> None:
        self._results[run_id] = [r.model_dump(mode="json") for r in results]

    def get_results(self, run_id: str) -> list[CheckResult]:
        return [CheckResult.model_validate(r) for r in self._results.get(run_id, [])]

    def save_findings(self, run_id: str, findings: list[Finding]) -> None:
        self._findings[run_id] = [f.model_dump(mode="json") for f in findings]

    def get_findings(self, run_id: str) -> list[Finding]:
        return [Finding.model_validate(f) for f in self._findings.get(run_id, [])]

    def append_event(self, event: AuditEvent) -> AuditEvent:
        self._events.setdefault(event.run_id, []).append(event.model_dump(mode="json"))
        return event

    def list_events(self, run_id: str, after_id: str | None = None) -> list[AuditEvent]:
        events = [AuditEvent.model_validate(e) for e in self._events.get(run_id, [])]
        if not after_id:
            return events
        idx = next((i for i, e in enumerate(events) if e.event_id == after_id), -1)
        return events[idx + 1 :] if idx >= 0 else events


class FirestoreAuditRepository(AuditRepository):
    def __init__(self, client: Any) -> None:
        self._db = client

    def create_run(self, run: AuditRun) -> AuditRun:
        self._db.collection("audit_runs").document(run.run_id).set(run.model_dump(mode="json"))
        return run

    def get_run(self, run_id: str) -> AuditRun | None:
        doc = self._db.collection("audit_runs").document(run_id).get()
        if not doc.exists:
            return None
        return AuditRun.model_validate(doc.to_dict())

    def update_run(self, run: AuditRun) -> AuditRun:
        run.updated_at = datetime.utcnow()
        self._db.collection("audit_runs").document(run.run_id).set(run.model_dump(mode="json"))
        return run

    def save_plan(self, plan: AuditPlan) -> AuditPlan:
        doc_id = f"{plan.run_id}_v{plan.version}"
        self._db.collection("audit_plans").document(doc_id).set(plan.model_dump(mode="json"))
        return plan

    def get_plan(self, run_id: str, version: int) -> AuditPlan | None:
        doc_id = f"{run_id}_v{version}"
        doc = self._db.collection("audit_plans").document(doc_id).get()
        if not doc.exists:
            return None
        return AuditPlan.model_validate(doc.to_dict())

    def get_latest_plan(self, run_id: str) -> AuditPlan | None:
        run = self.get_run(run_id)
        if not run:
            return None
        return self.get_plan(run_id, run.plan_version)

    def save_results(self, run_id: str, results: list[CheckResult]) -> None:
        self._db.collection("audit_results").document(run_id).set(
            {"run_id": run_id, "results": [r.model_dump(mode="json") for r in results]}
        )

    def get_results(self, run_id: str) -> list[CheckResult]:
        doc = self._db.collection("audit_results").document(run_id).get()
        if not doc.exists:
            return []
        data = doc.to_dict() or {}
        return [CheckResult.model_validate(r) for r in data.get("results", [])]

    def save_findings(self, run_id: str, findings: list[Finding]) -> None:
        self._db.collection("audit_findings").document(run_id).set(
            {"run_id": run_id, "findings": [f.model_dump(mode="json") for f in findings]}
        )

    def get_findings(self, run_id: str) -> list[Finding]:
        doc = self._db.collection("audit_findings").document(run_id).get()
        if not doc.exists:
            return []
        data = doc.to_dict() or {}
        return [Finding.model_validate(f) for f in data.get("findings", [])]

    def append_event(self, event: AuditEvent) -> AuditEvent:
        self._db.collection("audit_events").document(event.event_id).set(event.model_dump(mode="json"))
        return event

    def list_events(self, run_id: str, after_id: str | None = None) -> list[AuditEvent]:
        query = self._db.collection("audit_events").where("run_id", "==", run_id)
        events = [AuditEvent.model_validate(d.to_dict()) for d in query.stream()]
        events.sort(key=lambda e: e.created_at)
        if not after_id:
            return events
        idx = next((i for i, e in enumerate(events) if e.event_id == after_id), -1)
        return events[idx + 1 :] if idx >= 0 else events


_repo_singleton: AuditRepository | None = None


def get_repository() -> AuditRepository:
    global _repo_singleton
    if _repo_singleton is not None:
        return _repo_singleton

    from backend.api.config import settings

    if settings.use_memory_db:
        _repo_singleton = InMemoryAuditRepository()
        return _repo_singleton

    from google.cloud import firestore

    if settings.firestore_emulator_host:
        import os

        os.environ["FIRESTORE_EMULATOR_HOST"] = settings.firestore_emulator_host
    client = firestore.Client(project=settings.google_cloud_project)
    _repo_singleton = FirestoreAuditRepository(client)
    return _repo_singleton


def new_run_id() -> str:
    return str(uuid.uuid4())


def new_event_id() -> str:
    return str(uuid.uuid4())
