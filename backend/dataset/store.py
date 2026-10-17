from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.api.config import settings
from backend.regulations.store import get_regulations_store

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = REPO_ROOT / "sample_data"


class DatasetRecord(BaseModel):
    dataset_id: str
    claim_numbers: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    has_adjuster_notes: bool = False
    has_communication_logs: bool = False
    has_reference: bool = False
    source_files: list[str] = Field(default_factory=list)


class DatasetStore:
    def __init__(self) -> None:
        self.base = REPO_ROOT / settings.upload_dir / "datasets"
        self.base.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, dataset_id: str) -> Path:
        return self.base / dataset_id / "meta.json"

    def _dir(self, dataset_id: str) -> Path:
        return self.base / dataset_id

    def save_upload(
        self,
        adjuster_notes: bytes | None,
        communication_logs: bytes | None,
        reference: bytes | None,
        reference_filename: str = "reference.xlsx",
    ) -> DatasetRecord:
        if not adjuster_notes or not communication_logs or not reference:
            raise ValueError("All three files are required: adjuster_notes, communication_logs, reference")

        _validate_json(adjuster_notes, "adjuster_notes")
        _validate_json(communication_logs, "communication_logs")

        dataset_id = str(uuid.uuid4())
        dest = self._dir(dataset_id)
        dest.mkdir(parents=True, exist_ok=True)

        notes_name = "adjuster_notes.json"
        comms_name = "communication_logs.json"
        (dest / notes_name).write_bytes(adjuster_notes)
        (dest / comms_name).write_bytes(communication_logs)
        ref_name = "reference.xlsx" if reference_filename.lower().endswith((".xlsx", ".xls")) else "reference.csv"
        (dest / ref_name).write_bytes(reference)

        from backend.audit.loader import list_claim_numbers_for_dataset

        claims = list_claim_numbers_for_dataset(dataset_id)
        record = DatasetRecord(
            dataset_id=dataset_id,
            claim_numbers=claims,
            has_adjuster_notes=True,
            has_communication_logs=True,
            has_reference=True,
            source_files=[notes_name, comms_name, ref_name],
        )
        self._meta_path(dataset_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
        get_regulations_store().set_active_dataset_id(dataset_id)
        return record

    def get(self, dataset_id: str) -> DatasetRecord | None:
        path = self._meta_path(dataset_id)
        if not path.exists():
            return None
        return DatasetRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def get_active(self) -> DatasetRecord | None:
        active_id = get_regulations_store().get_active_dataset_id()
        if active_id:
            return self.get(active_id)
        return None

    def ensure_demo_dataset(self) -> DatasetRecord:
        """Copy repo sample_data files into a demo dataset."""
        dataset_id = "demo-repo-sample"
        dest = self._dir(dataset_id)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SAMPLE_DATA_DIR / "adjuster_notes.json", dest / "adjuster_notes.json")
        shutil.copy2(SAMPLE_DATA_DIR / "communication_logs.json", dest / "communication_logs.json")
        shutil.copy2(SAMPLE_DATA_DIR / "sample.xlsx", dest / "reference.xlsx")
        from backend.audit.loader import list_claim_numbers_for_dataset

        claims = list_claim_numbers_for_dataset(dataset_id)
        record = DatasetRecord(
            dataset_id=dataset_id,
            claim_numbers=claims,
            has_adjuster_notes=True,
            has_communication_logs=True,
            has_reference=True,
            source_files=["adjuster_notes.json", "communication_logs.json", "reference.xlsx"],
        )
        self._meta_path(dataset_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
        get_regulations_store().set_active_dataset_id(dataset_id)
        return record

    def list_datasets(self) -> list[DatasetRecord]:
        rows: list[DatasetRecord] = []
        for child in sorted(self.base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if child.is_dir() and (child / "meta.json").exists():
                meta = self.get(child.name)
                if meta:
                    rows.append(meta)
        return rows


def _validate_json(data: bytes, label: str) -> None:
    try:
        json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {label}: {exc}") from exc


_store: DatasetStore | None = None


def get_dataset_store() -> DatasetStore:
    global _store
    if _store is None:
        _store = DatasetStore()
    return _store
