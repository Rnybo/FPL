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
3. `vercel --prod --yes` from `frontend/` -- rebuilds and redeploys, the
   production alias (`frontend-six-orcin-32.vercel.app`) stays the same
   across deploys even though the underlying deployment URL changes each time
4. Curls `/api/health` on the backend to confirm it's actually up afterward

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
