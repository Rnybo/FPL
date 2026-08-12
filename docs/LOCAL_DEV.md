# Running locally

Cloud deployment (GCP VM + Vercel) is on hold -- see docs/DEPLOYMENT.md for
that if it's revisited later. For now, everything runs on this machine only.

## One command

```powershell
.\deploy\run_local.ps1
```

Opens two windows: backend on http://localhost:8000, frontend on whatever
port Vite picks (usually http://localhost:5173, next free port if that's
taken). `frontend/.env` already points `VITE_API_BASE_URL` at localhost, so
no config needed.

## Manually, if preferred

```powershell
# Terminal 1
cd backend
python -m uvicorn app.main:app --port 8000

# Terminal 2
cd frontend
npm run dev
```

## Notes

- The database (`data/fpl_cache.db`) is the same one everything else in this
  repo has always used -- nothing changed there.
- If port 8000 is already in use (e.g. a previous run still open), find and
  stop it first: `Get-Process python | Stop-Process` (careful if you have
  other unrelated Python processes running).
