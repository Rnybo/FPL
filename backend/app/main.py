"""
FastAPI entrypoint. Thin API layer over the existing scripts/ pipeline --
see app/config.py for the sys.path wiring that makes `import optimise` etc.
work without duplicating any modeling logic in the backend.

Run locally: uvicorn app.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS
from app.routers import players, model_runs, squad, league, team, fixtures, captain, saved_squads
from app import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    # Pre-computes the expensive gw-window-independent analysis (opponent
    # history, monthly trends, last-season stats) once in the background,
    # so the FIRST real request after a cold start doesn't have to sit
    # through all of it -- see players.py's warm_players_cache docstring.
    # Backgrounded (not awaited) so app startup itself isn't delayed by it.
    threading.Thread(target=players.warm_players_cache, daemon=True).start()
    yield
    scheduler.stop()


app = FastAPI(title="FPL Expected Points API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # POST/PUT/DELETE added for saved_squads (Squad Builder's "save as draft")
    # -- everything else on this API is read-only (GET), that one feature is
    # the sole reason this isn't just ["GET"].
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(players.router)
app.include_router(model_runs.router)
app.include_router(squad.router)
app.include_router(league.router)
app.include_router(team.router)
app.include_router(fixtures.router)
app.include_router(captain.router)
app.include_router(saved_squads.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
