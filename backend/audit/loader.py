from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.api.config import settings
from backend.audit.models import (
    CommunicationEntry,
    DerivedFields,
    NormalizedClaim,
    NoteEntry,
    TimelineEvent,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = REPO_ROOT / "sample_data"


def _parse_date(value: str) -> date:
    if isinstance(value, date):
        return value
    s = str(value)[:10]
    return datetime.strptime(s, "%Y-%m-%d").date()


def _dataset_dir(dataset_id: str) -> Path:
    if dataset_id == "repo":
        return SAMPLE_DATA_DIR
    return REPO_ROOT / settings.upload_dir / "datasets" / dataset_id


def _resolve_dataset_id(dataset_id: str | None) -> str:
    if dataset_id:
        return dataset_id
    from backend.dataset.store import get_dataset_store
    from backend.regulations.store import get_regulations_store

    active = get_regulations_store().get_active_dataset_id()
    if active:
        return active
    if settings.use_repo_sample_data:
        return "repo"
    raise ValueError("No active dataset; upload claims data first.")


def _load_notes_json(path: Path) -> dict[str, list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    raise ValueError("adjuster_notes must be a JSON object keyed by claim number")


def _load_comms_json(path: Path) -> dict[str, list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    raise ValueError("communication_logs must be a JSON object keyed by claim number")


def _reference_path(dataset_dir: Path) -> Path | None:
    for name in ("reference.xlsx", "reference.xls", "sample.xlsx", "reference.csv"):
        p = dataset_dir / name
        if p.exists():
            return p
    return None


def _reference_for_claim(df: pd.DataFrame, claim_number: str) -> dict[str, Any]:
    if df.empty:
        return {}
    for col in df.columns:
        try:
            matches = df[df[col].astype(str).str.contains(claim_number, na=False)]
            if not matches.empty:
                return matches.iloc[0].to_dict()
        except Exception:
            continue
    return {}


def list_claim_numbers_for_dataset(dataset_id: str | None = None) -> list[str]:
    ds_id = _resolve_dataset_id(dataset_id)
    ddir = _dataset_dir(ds_id)
    if ds_id == "repo":
        notes_path = ddir / "adjuster_notes.json"
        if notes_path.exists():
            return sorted(_load_notes_json(notes_path).keys())
        return _legacy_folder_claims()
    notes_path = ddir / "adjuster_notes.json"
    if not notes_path.exists():
        raise FileNotFoundError(f"Dataset {ds_id} missing adjuster_notes.json")
    keys = set(_load_notes_json(notes_path).keys())
    comms_path = ddir / "communication_logs.json"
    if comms_path.exists():
        keys |= set(_load_comms_json(comms_path).keys())
    return sorted(keys)


def list_claim_numbers() -> list[str]:
    try:
        return list_claim_numbers_for_dataset(None)
    except ValueError:
        return _legacy_folder_claims()


def _legacy_folder_claims() -> list[str]:
    claims: list[str] = []
    if not SAMPLE_DATA_DIR.is_dir():
        return claims
    for path in sorted(SAMPLE_DATA_DIR.iterdir()):
        if path.is_dir() and (path / "notes.json").exists():
            ref_path = path / "reference.json"
            if ref_path.exists():
                ref = json.loads(ref_path.read_text(encoding="utf-8"))
                claims.append(ref.get("claim_number", path.name))
            else:
                claims.append(path.name)
    return claims


def _parse_note_row(row: dict[str, Any], idx: int) -> NoteEntry:
    return NoteEntry(
        id=f"N{idx}",
        date=_parse_date(row.get("Date") or row.get("date")),
        adjuster=str(row.get("Adjuster Name") or row.get("adjuster") or ""),
        type=str(row.get("Note Type") or row.get("type") or ""),
        text=str(row.get("Note Text") or row.get("text") or ""),
    )


def _parse_comm_row(row: dict[str, Any], idx: int) -> CommunicationEntry:
    party = row.get("party") or row.get("Adjuster Name") or row.get("Communication Type") or ""
    return CommunicationEntry(
        id=f"C{idx}",
        date=_parse_date(row.get("Date") or row.get("date")),
        type=str(row.get("Communication Type") or row.get("type") or ""),
        party=str(party),
        text=str(row.get("Communication Text") or row.get("text") or ""),
    )


def load_claim(claim_number: str, dataset_id: str | None = None) -> NormalizedClaim:
    ds_id = _resolve_dataset_id(dataset_id)
    ddir = _dataset_dir(ds_id)

    if ds_id == "repo" and (ddir / "adjuster_notes.json").exists():
        return _load_claim_from_master_files(ddir, claim_number)

    if (ddir / "adjuster_notes.json").exists():
        return _load_claim_from_master_files(ddir, claim_number)

    return _load_claim_legacy_folder(claim_number)


def _load_claim_from_master_files(dataset_dir: Path, claim_number: str) -> NormalizedClaim:
    notes_raw = _load_notes_json(dataset_dir / "adjuster_notes.json")
    comms_raw = _load_comms_json(dataset_dir / "communication_logs.json")
    note_rows = notes_raw.get(claim_number, [])
    comm_rows = comms_raw.get(claim_number, [])
    if not note_rows and not comm_rows:
        raise FileNotFoundError(f"Claim not found: {claim_number}")

    notes = [_parse_note_row(r, i) for i, r in enumerate(note_rows, start=1)]
    communications = [_parse_comm_row(r, i) for i, r in enumerate(comm_rows, start=1)]

    ref_path = _reference_path(dataset_dir)
    reference: dict[str, Any] = {}
    if ref_path:
        if ref_path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(ref_path)
        else:
            df = pd.read_csv(ref_path)
        reference = _reference_for_claim(df, claim_number)
        reference["claim_number"] = claim_number

    timeline: list[TimelineEvent] = []
    for note in notes:
        timeline.append(
            TimelineEvent(
                event_id=f"TL-{note.id}",
                source="note",
                source_id=note.id,
                date=note.date,
                adjuster=note.adjuster,
                type=note.type,
                text=note.text,
            )
        )
    for comm in communications:
        timeline.append(
            TimelineEvent(
                event_id=f"TL-{comm.id}",
                source="communication",
                source_id=comm.id,
                date=comm.date,
                adjuster=None,
                type=comm.type,
                text=comm.text,
            )
        )
    timeline.sort(key=lambda e: (e.date, e.source_id))

    open_date = min((e.date for e in timeline), default=None)
    close_date = _infer_close_date(notes, communications)
    days_open = (close_date - open_date).days if open_date and close_date else None

    return NormalizedClaim(
        claim_number=claim_number,
        notes=notes,
        communications=communications,
        timeline=timeline,
        reference=reference,
        derived=DerivedFields(open_date=open_date, close_date=close_date, days_open=days_open),
    )


def _load_claim_legacy_folder(claim_number: str) -> NormalizedClaim:
    claim_dir = _claim_dir(claim_number)
    notes_raw = json.loads((claim_dir / "notes.json").read_text(encoding="utf-8"))
    comms_raw = json.loads((claim_dir / "communications.json").read_text(encoding="utf-8"))
    reference = json.loads((claim_dir / "reference.json").read_text(encoding="utf-8"))

    notes = [
        NoteEntry(
            id=f"N{idx}",
            date=_parse_date(row["date"]),
            adjuster=row.get("adjuster", ""),
            type=row.get("type", ""),
            text=row.get("text", ""),
        )
        for idx, row in enumerate(notes_raw, start=1)
    ]
    communications = [
        CommunicationEntry(
            id=f"C{idx}",
            date=_parse_date(row["date"]),
            type=row.get("type", ""),
            party=row.get("party", ""),
            text=row.get("text", ""),
        )
        for idx, row in enumerate(comms_raw, start=1)
    ]
    timeline: list[TimelineEvent] = []
    for note in notes:
        timeline.append(
            TimelineEvent(
                event_id=f"TL-{note.id}",
                source="note",
                source_id=note.id,
                date=note.date,
                adjuster=note.adjuster,
                type=note.type,
                text=note.text,
            )
        )
    for comm in communications:
        timeline.append(
            TimelineEvent(
                event_id=f"TL-{comm.id}",
                source="communication",
                source_id=comm.id,
                date=comm.date,
                adjuster=None,
                type=comm.type,
                text=comm.text,
            )
        )
    timeline.sort(key=lambda e: (e.date, e.source_id))
    open_date = min((e.date for e in timeline), default=None)
    close_date = _infer_close_date(notes, communications)
    days_open = (close_date - open_date).days if open_date and close_date else None
    return NormalizedClaim(
        claim_number=claim_number,
        notes=notes,
        communications=communications,
        timeline=timeline,
        reference=reference,
        derived=DerivedFields(open_date=open_date, close_date=close_date, days_open=days_open),
    )


def _claim_dir(claim_number: str) -> Path:
    for path in SAMPLE_DATA_DIR.iterdir():
        if not path.is_dir():
            continue
        ref_path = path / "reference.json"
        if ref_path.exists():
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
            if ref.get("claim_number") == claim_number:
                return path
        if path.name == claim_number:
            return path
    raise FileNotFoundError(f"Claim not found: {claim_number}")


def _infer_close_date(
    notes: list[NoteEntry], communications: list[CommunicationEntry]
) -> date | None:
    for note in reversed(notes):
        t = note.type.lower()
        if "final" in t or "closure" in t or "closed" in note.text.lower():
            return note.date
        if "resolved" in note.text.lower():
            return note.date
    for comm in reversed(communications):
        if "closure" in comm.text.lower() or "closed" in comm.text.lower():
            return comm.date
    if notes:
        return notes[-1].date
    return None
