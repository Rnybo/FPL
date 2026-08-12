# Run FPL locally: starts backend (FastAPI/uvicorn) and frontend (Vite dev
# server) each in their own window. Ctrl+C in either window stops that piece.
$RepoRoot = Split-Path -Parent $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RepoRoot\backend'; python -m uvicorn app.main:app --port 8000"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RepoRoot\frontend'; npm run dev"

Write-Host "Backend starting on http://localhost:8000"
Write-Host "Frontend starting -- check its window for the actual port (5173 or next free one)"
