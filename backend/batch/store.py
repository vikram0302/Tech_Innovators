from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from backend.api.config import settings
from backend.audit.models import AuditEvent, BatchAuditRun, Finding

REPO_ROOT = Path(__file__).resolve().parents[2]


class BatchStore:
    def __init__(self) -> None:
        self.base = REPO_ROOT / settings.upload_dir / "batches"
        self.base.mkdir(parents=True, exist_ok=True)
        self._batches: dict[str, BatchAuditRun] = {}
        self._events: dict[str, list[AuditEvent]] = {}
        self._findings: dict[str, list[Finding]] = {}
        self._report: dict[str, str] = {}

    def _path(self, batch_id: str) -> Path:
        return self.base / f"{batch_id}.json"

    def _findings_path(self, batch_id: str) -> Path:
        return self.base / f"{batch_id}_findings.json"

    def _events_path(self, batch_id: str) -> Path:
        return self.base / f"{batch_id}_events.json"

    def save_batch(self, batch: BatchAuditRun) -> BatchAuditRun:
        batch.updated_at = datetime.utcnow()
        self._batches[batch.batch_id] = batch
        self._path(batch.batch_id).write_text(batch.model_dump_json(indent=2), encoding="utf-8")
        return batch

    def get_batch(self, batch_id: str) -> BatchAuditRun | None:
        if batch_id in self._batches:
            return self._batches[batch_id]
        path = self._path(batch_id)
        if path.exists():
            batch = BatchAuditRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
            self._batches[batch_id] = batch
            return batch
        return None

    def list_batches(self) -> list[BatchAuditRun]:
        seen: set[str] = set()
        rows: list[BatchAuditRun] = []
        for path in sorted(self.base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            name = path.name
            if name.endswith("_findings.json") or name.endswith("_events.json"):
                continue
            if not name.endswith(".json"):
                continue
            batch_id = path.stem
            if batch_id in seen:
                continue
            batch = self.get_batch(batch_id)
            if batch:
                seen.add(batch_id)
                rows.append(batch)
        rows.sort(key=lambda b: b.created_at, reverse=True)
        return rows

    def append_event(self, event: AuditEvent) -> AuditEvent:
        self._events.setdefault(event.run_id, []).append(event)
        self._persist_events(event.run_id)
        return event

    def _persist_events(self, batch_id: str) -> None:
        events = self._events.get(batch_id, [])
        payload = [e.model_dump(mode="json") for e in events]
        self._events_path(batch_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_events(self, batch_id: str) -> list[AuditEvent]:
        if batch_id in self._events:
            return self._events[batch_id]
        path = self._events_path(batch_id)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            events = [AuditEvent.model_validate(item) for item in raw]
            self._events[batch_id] = events
            return events
        self._events[batch_id] = []
        return []

    def list_events(self, batch_id: str, after_id: str | None = None) -> list[AuditEvent]:
        events = list(self._load_events(batch_id))
        if not after_id:
            return events
        idx = next((i for i, e in enumerate(events) if e.event_id == after_id), -1)
        return events[idx + 1 :] if idx >= 0 else events

    def save_findings(self, batch_id: str, findings: list[Finding]) -> None:
        self._findings[batch_id] = findings
        payload = [f.model_dump(mode="json") for f in findings]
        self._findings_path(batch_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_findings(self, batch_id: str) -> list[Finding]:
        if batch_id in self._findings:
            return self._findings[batch_id]
        path = self._findings_path(batch_id)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            findings = [Finding.model_validate(item) for item in raw]
            self._findings[batch_id] = findings
            return findings
        return []

    def save_report(self, batch_id: str, markdown: str) -> None:
        self._report[batch_id] = markdown
        (self.base / f"{batch_id}_report.md").write_text(markdown, encoding="utf-8")

    def get_report(self, batch_id: str) -> str | None:
        if batch_id in self._report:
            return self._report[batch_id]
        path = self.base / f"{batch_id}_report.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None


def new_batch_id() -> str:
    return str(uuid.uuid4())


def new_event_id() -> str:
    return str(uuid.uuid4())


_store: BatchStore | None = None


def get_batch_store() -> BatchStore:
    global _store
    if _store is None:
        _store = BatchStore()
    return _store
