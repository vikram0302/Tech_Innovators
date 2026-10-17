from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.api.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]


class RegulationFileMeta(BaseModel):
    filename: str
    size_bytes: int


class RegulationSet(BaseModel):
    regulation_set_id: str
    files: list[RegulationFileMeta] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = False
    context_text: str = ""


class RegulationsStore:
    def __init__(self) -> None:
        self.base = REPO_ROOT / settings.upload_dir / "regulations"
        self.base.mkdir(parents=True, exist_ok=True)
        self._state_path = REPO_ROOT / settings.upload_dir / "state.json"
        self._load_state()

    def _load_state(self) -> None:
        if self._state_path.exists():
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._active_id: str | None = data.get("active_regulation_set_id")
        else:
            self._active_id = None

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"active_regulation_set_id": self._active_id}
        dataset_id = getattr(self, "_active_dataset_id", None)
        if dataset_id:
            data["active_dataset_id"] = dataset_id
        if self._state_path.exists():
            existing = json.loads(self._state_path.read_text(encoding="utf-8"))
            existing.update(data)
            data = existing
        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_active_dataset_id(self) -> str | None:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8")).get("active_dataset_id")
        return None

    def set_active_dataset_id(self, dataset_id: str) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if self._state_path.exists():
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        data["active_dataset_id"] = dataset_id
        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _set_meta(self, reg_set: RegulationSet) -> None:
        path = self.base / reg_set.regulation_set_id / "meta.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(reg_set.model_dump_json(indent=2), encoding="utf-8")

    def _get_meta(self, regulation_set_id: str) -> RegulationSet | None:
        path = self.base / regulation_set_id / "meta.json"
        if not path.exists():
            return None
        return RegulationSet.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def create_set_from_uploads(self, filenames_and_data: list[tuple[str, bytes]]) -> RegulationSet:
        reg_id = str(uuid.uuid4())
        dest = self.base / reg_id
        dest.mkdir(parents=True, exist_ok=True)
        files_meta: list[RegulationFileMeta] = []
        for name, data in filenames_and_data:
            safe = Path(name).name
            (dest / safe).write_bytes(data)
            files_meta.append(RegulationFileMeta(filename=safe, size_bytes=len(data)))

        context = _extract_regulation_text(dest)
        reg_set = RegulationSet(
            regulation_set_id=reg_id,
            files=files_meta,
            context_text=context[:120_000],
        )
        self._set_meta(reg_set)
        self.activate(reg_id)
        return reg_set

    def upload_to_active(self, filenames_and_data: list[tuple[str, bytes]]) -> RegulationSet:
        active = self.get_active()
        if active:
            return self.add_files(active.regulation_set_id, filenames_and_data)
        return self.create_set_from_uploads(filenames_and_data)

    def add_files(self, regulation_set_id: str, filenames_and_data: list[tuple[str, bytes]]) -> RegulationSet:
        reg_set = self._get_meta(regulation_set_id)
        if not reg_set:
            raise ValueError("Regulation set not found")
        dest = self.base / regulation_set_id
        dest.mkdir(parents=True, exist_ok=True)
        by_name = {f.filename: f for f in reg_set.files}
        for name, data in filenames_and_data:
            safe = Path(name).name
            (dest / safe).write_bytes(data)
            by_name[safe] = RegulationFileMeta(filename=safe, size_bytes=len(data))
        reg_set.files = list(by_name.values())
        reg_set.context_text = _extract_regulation_text(dest)[:120_000]
        self._set_meta(reg_set)
        return reg_set

    def resolve_file_path(self, regulation_set_id: str, filename: str) -> Path | None:
        safe = Path(filename).name
        path = self.base / regulation_set_id / safe
        if path.is_file():
            return path
        return None

    def remove_file(self, regulation_set_id: str, filename: str) -> RegulationSet | None:
        reg_set = self._get_meta(regulation_set_id)
        if not reg_set:
            raise ValueError("Regulation set not found")
        safe = Path(filename).name
        path = self.base / regulation_set_id / safe
        if path.is_file():
            path.unlink()
        reg_set.files = [f for f in reg_set.files if f.filename != safe]
        if not reg_set.files:
            shutil.rmtree(self.base / regulation_set_id, ignore_errors=True)
            if self._active_id == regulation_set_id:
                self._active_id = None
                self._save_state()
            return None
        reg_set.context_text = _extract_regulation_text(self.base / regulation_set_id)[:120_000]
        self._set_meta(reg_set)
        return reg_set

    def activate(self, regulation_set_id: str) -> RegulationSet:
        reg_set = self._get_meta(regulation_set_id)
        if not reg_set:
            raise ValueError("Regulation set not found")
        for child in self.base.iterdir():
            if not child.is_dir():
                continue
            meta = self._get_meta(child.name)
            if meta:
                meta.is_active = child.name == regulation_set_id
                self._set_meta(meta)
        self._active_id = regulation_set_id
        self._save_state()
        reg_set.is_active = True
        return reg_set

    def get_active(self) -> RegulationSet | None:
        if not self._active_id:
            return None
        reg = self._get_meta(self._active_id)
        if reg:
            reg.is_active = True
        return reg

    def list_sets(self) -> list[RegulationSet]:
        sets: list[RegulationSet] = []
        for child in sorted(self.base.iterdir()):
            if child.is_dir():
                meta = self._get_meta(child.name)
                if meta:
                    meta.is_active = meta.regulation_set_id == self._active_id
                    sets.append(meta)
        return sets

    def get_context(self, regulation_set_id: str | None = None) -> str:
        rid = regulation_set_id or self._active_id
        if not rid:
            return ""
        meta = self._get_meta(rid)
        return meta.context_text if meta else ""


def _extract_regulation_text(dest: Path) -> str:
    parts: list[str] = []
    for path in sorted(dest.glob("*")):
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        parts.append(text)
            except Exception:
                parts.append(f"[Could not extract text from {path.name}]")
        elif path.suffix.lower() in (".txt", ".md"):
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n\n".join(parts)


_store: RegulationsStore | None = None


def get_regulations_store() -> RegulationsStore:
    global _store
    if _store is None:
        _store = RegulationsStore()
    return _store
