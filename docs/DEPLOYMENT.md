# Deployment

The full production stack: **backend** (FastAPI, on a GCP e2-micro VM, behind
Caddy for HTTPS) + **frontend** (Vite/React, on Vercel).

| | URL |
|---|---|
| Backend  | https://35-252-212-174.sslip.io |
| Frontend | https://frontend-six-orcin-32.vercel.app |
| GitHub   | https://github.com/Rnybo/FPL |

## Everyday deploy: one command

From the repo root:

```powershell
.\deploy\push_and_deploy.ps1
```

Optionally with a commit message: `.\deploy\push_and_deploy.ps1 -Message "Add captain picks"`

This does, in order:
1. `git add -A`, commit (skipped if nothing changed), `git push`
2. SSH into the GCP VM, `git pull`, `docker compose up -d --build` (only
   rebuilds layers that actually changed -- fast if it's just Python code)
3. Runs `ensure_schema.py` inside the container -- applies any schema
   changes (new tables/columns) that only ever landed locally. See "Database
   schema drift" below for why this exists and what it does NOT cover.
4. `vercel --prod --yes` from `frontend/` -- rebuilds and redeploys, the
   production alias (`frontend-six-orcin-32.vercel.app`) stays the same
   across deploys even though the underlying deployment URL changes each time
5. Curls `/api/health` on the backend to confirm it's actually up afterward

Takes 1-2 minutes if the Docker image cache is warm (i.e. you didn't change
`requirements.txt` or system deps), longer if a dependency changed.

## One-time prerequisites (already done, here for reference)

- **Git remote**: `origin` -> `https://github.com/Rnybo/FPL.git`, already set locally
- **gcloud CLI**: authenticated as `rnybo89@gmail.com`, project `hypnotic-pier-267907`.
  Check with `gcloud auth list`. Re-auth if needed: `gcloud auth login`
- **Vercel CLI**: authenticated, project linked as `fpl12/frontend` -- the link
  lives in `frontend/.vercel/` (gitignored, machine-local by design, like any
  Vercel project). On a fresh machine, run `vercel link` in `frontend/` first.
  Check auth with `vercel whoami`. Re-auth if needed: `vercel login`
- **VM**: `fpl-backend` in zone `us-west1-b`, GCP Always Free `e2-micro`.
  SSH keys are managed automatically by `gcloud compute ssh` -- no manual key
  file needed.

## Manual steps, if the script fails partway

**GitHub push failed** -- just fix whatever git complained about and re-run
the script; it's safe to re-run (each step is idempotent-ish).

**Backend deploy failed** -- SSH in directly to see what broke:
```powershell
gcloud compute ssh fpl-backend --zone=us-west1-b
cd repo
git pull
docker compose up -d --build
docker compose logs -f backend   # watch it start
```

**Frontend deploy failed** -- from `frontend/`:
```powershell
vercel --prod --yes
```
If it's a build error, run `npx tsc -b` and `npx vitest run` locally first --
Vercel's build is `tsc -b && vite build`, so any TypeScript error fails the
whole deploy (this happened once already -- see git history around
"Fix pre-existing TS build errors").

## Things that are NOT automated by this script

- **Database refresh**: `data/fpl_cache.db` on the VM is a point-in-time copy,
  not synced automatically. New gameweek data only reaches it if the
  in-container scheduler (`scheduler.py`) is actually running and successfully
  fetching -- check with `docker compose logs backend | grep -i schedul`.
  If you ever need to push a fresh local DB snapshot manually:
  ```powershell
  gcloud compute scp data\fpl_cache.db fpl-backend:repo/data/fpl_cache.db --zone=us-west1-b
  gcloud compute ssh fpl-backend --zone=us-west1-b --command="cd repo && docker compose restart backend"
  ```
- **Database schema drift**: `ensure_schema.py` (step 3 above) closes most of
  this gap automatically now -- it reads `schema.sql` (which IS in git) and
  applies any `CREATE TABLE`/`ALTER TABLE ADD COLUMN` the VM's live `.db`
  (which is NOT in git) is missing, every deploy, safely (idempotent). This
  is exactly what caused a real production 500 once: `captain_simulation.py`
  querying a `starts` column that existed locally but not on the VM, because
  the schema change had no automatic path there.
  **What it does NOT cover**: backfilling actual historical DATA that a new
  column needs (e.g. adding a column is automatic, but populating it from
  `data/raw/fpl_api/*/merged_gw.csv` -- also not in git -- still needs a
  manual one-time transfer + script run, same as the original historical
  load). If a future change needs new historical source data, not just a
  new column, do this once:
  ```powershell
  foreach ($s in @("2021-22","2022-23","2023-24","2024-25","2025-26")) {
    gcloud compute scp "data\raw\fpl_api\$s\merged_gw.csv" "fpl-backend:repo/data/raw/fpl_api/$s/merged_gw.csv" --zone=us-west1-b --quiet
  }
  gcloud compute ssh fpl-backend --zone=us-west1-b --command="docker cp repo/data/raw repo-backend-1:/srv/data/raw && docker exec repo-backend-1 python3 /srv/scripts/load_player_gameweeks_to_cache.py" --quiet
  ```
- **CORS allowlist**: the backend's `ALLOWED_ORIGINS` env var (set in a `.env`
  file directly on the VM, not in git) is pinned to the current Vercel
  production URL. If that URL ever changes (e.g. the Vercel project is
  recreated), update it:
  ```powershell
  gcloud compute ssh fpl-backend --zone=us-west1-b --command="cd repo && echo 'ALLOWED_ORIGINS=<new-url>' > .env && docker compose up -d"
  ```
- **HTTPS hostname**: tied to the VM's IP via sslip.io (`35-252-212-174.sslip.io`).
  If the VM is ever recreated with a new IP, update `deploy/Caddyfile`'s
  hostname to match and re-run `sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
  && sudo systemctl reload caddy` on the VM.
