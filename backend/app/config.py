"""
Central config: paths, DB location, and sys.path wiring so the backend can
import directly from ../scripts (the existing, already-validated model
pipeline) instead of duplicating any modeling logic here. The backend is a
thin API layer over what already works -- see docs/model-architecture.md and
README.md in the project root for what each imported module actually does.
"""
import os
import sys
from pathlib import Path

# Local dev: backend/app/config.py -> 3 parents up -> project root (FPL/).
# Docker (see Dockerfile): scripts/ and app/ are copied flattened into /srv/,
# a different depth -- FPL_PROJECT_ROOT env var overrides the computed path
# rather than hardcoding either layout's assumption into the code.
PROJECT_ROOT = Path(os.environ.get("FPL_PROJECT_ROOT", Path(__file__).resolve().parent.parent.parent))
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DB_PATH = PROJECT_ROOT / "data" / "fpl_cache.db"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

CURRENT_SEASON = "2026-27"

# CORS: the Vercel-hosted frontend's origin(s). Reads from ALLOWED_ORIGINS env var
# (comma-separated) if set -- e.g. "https://fpl-xyz.vercel.app" in production --
# falling back to localhost dev ports so nothing changes for local development.
# Vite auto-increments past 5173 if that port's already taken by another
# project on the same machine (a real, recurring case on a dev box running
# several things at once) -- covering a small range here avoids a CORS
# failure just because Vite picked 5174/5175 instead of the default.
_origins_env = os.environ.get("ALLOWED_ORIGINS")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",")] if _origins_env else [
    "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
    "http://localhost:5176", "http://localhost:3000",
]
