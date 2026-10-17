# Claims Audit Workbench (Google Hackathon)

Evidence-backed **batch** claims audit: upload **regulations** separately, upload **claims data**, audit all claims against active regulations, combined report. FastAPI + ADK agent tools + Next.js UI.

## Quick start

### Backend

```powershell
cd E:\hackthon\Tech_Innovators
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
$env:PYTHONPATH="E:\hackthon\Tech_Innovators"
$env:USE_MEMORY_DB="true"
.\scripts\start-api.ps1
# Or: uvicorn on port 8001 (8000 may be occupied by an old server)
# .\.venv\Scripts\uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8001
```

### Frontend

```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 → redirects to **Audit**. Use **Regulations** tab first.

## Docker

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose v2).

Put secrets in a repo-root `.env` (see `.env.example`). Compose reads `GOOGLE_API_KEY` from that file automatically.

### Build and run (Compose — recommended)

From the **repo root**:

```powershell
cd E:\hackthon\Tech_Innovators
docker compose up --build
```

- **Web UI:** http://localhost:3000  
- **API:** http://localhost:8080 (docs: http://localhost:8080/docs)  
- Uploads persist in the `claims_uploads` Docker volume.

Stop with `Ctrl+C`, or run detached:

```powershell
docker compose up --build -d
docker compose logs -f
docker compose down
```

### Build and run images separately

```powershell
cd E:\hackthon\Tech_Innovators

# API
docker build -f docker/Dockerfile.api -t claims-audit-api .
docker run --rm -p 8080:8080 `
  -e USE_MEMORY_DB=true `
  -e CORS_ORIGINS=http://localhost:3000 `
  -e GOOGLE_API_KEY=$env:GOOGLE_API_KEY `
  -v claims_uploads:/app/uploads `
  claims-audit-api

# Web (point browser at the published API)
docker build -f docker/Dockerfile.web `
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8080 `
  -t claims-audit-web .
docker run --rm -p 3000:3000 claims-audit-web
```

## Flow

1. **Regulations** — upload PDF/TXT/MD standards (`POST /api/regulations/upload`).
2. **Audit** — upload adjuster notes JSON, communication logs JSON, reference xlsx (`POST /api/dataset/upload`).
3. Batch audit runs for all claims (`POST /api/batch/...`) → combined PDF report.
4. Each upload starts a **new session**; prior audits remain in **Audit history** (`GET /api/batch`) with claims + regulation data sources.

## Sample data

- [sample_data/adjuster_notes.json](sample_data/adjuster_notes.json)
- [sample_data/communication_logs.json](sample_data/communication_logs.json)
- [sample_data/sample.xlsx](sample_data/sample.xlsx)
- [sample_data/Claims_Handling_Standards.pdf](sample_data/Claims_Handling_Standards.pdf)

Repo `sample_data` is used when `USE_REPO_SAMPLE_DATA=true` (default) for loader tests with `dataset_id=repo`.

## ADK

Optional: `pip install -r backend/requirements-adk.txt` — agent at [backend/agent/agent.py](backend/agent/agent.py), mounted at `/adk` when available. Chat API: `POST /api/chat/send`.

## Tests

```powershell
$env:PYTHONPATH="E:\hackthon\Tech_Innovators"
.\.venv\Scripts\python -m pytest backend\tests -q
```

See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
