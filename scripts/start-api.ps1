# Run from repo root: .\scripts\start-api.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$env:PYTHONPATH = (Get-Location).Path
$env:USE_MEMORY_DB = "true"

$port = if ($env:API_PORT) { $env:API_PORT } else { "8001" }
Write-Host "Starting Claims Audit API on http://127.0.0.1:$port (title should be Claims Audit API 0.2.0)"
Write-Host "Open http://127.0.0.1:$port/docs to verify /api/regulations routes exist."

.\.venv\Scripts\uvicorn backend.api.main:app --host 127.0.0.1 --port $port --reload
