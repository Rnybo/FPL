"""
FastAPI entrypoint. Thin API layer over the existing scripts/ pipeline --
see app/config.py for the sys.path wiring that makes `import optimise` etc.
work without duplicating any modeling logic in the backend.

Run locally: uvicorn app.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS
from app.routers import players, model_runs, squad, league, team, fixtures, captain
from app import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="FPL Expected Points API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(players.router)
app.include_router(model_runs.router)
app.include_router(squad.router)
app.include_router(league.router)
app.include_router(team.router)
app.include_router(fixtures.router)
app.include_router(captain.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
