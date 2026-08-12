"""
Turns docs/live-refresh-runbook.md's manual cadence into an automatic
in-process schedule, via APScheduler. Runs the EXISTING scripts as
subprocesses (not reimplemented here) -- same reasoning as db.py: one place
that changes model/data state, not duplicated into the API layer.

Cadence follows the runbook: news/roster/fixtures are cheap and safe to run
often; fetch_live_gameweek_stats + predict_upcoming are heavier and tied to
gameweek boundaries, so they run less frequently.
"""
import subprocess
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import SCRIPTS_DIR

scheduler = BackgroundScheduler()


def _run_script(name: str):
    script_path = SCRIPTS_DIR / name
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True, text=True, timeout=600,
    )
    status = "OK" if result.returncode == 0 else f"FAILED (code {result.returncode})"
    print(f"[scheduler] {name}: {status}")
    if result.returncode != 0:
        print(result.stderr[-2000:])


def start():
    # Cheap, safe to run often -- news changes fast, especially near deadlines
    scheduler.add_job(lambda: _run_script("fetch_live_team_news.py"),
                       "interval", hours=6, id="live_team_news")

    # Roster/fixtures change rarely mid-week; daily is plenty
    scheduler.add_job(lambda: _run_script("fetch_current_roster.py"),
                       "interval", hours=24, id="current_roster")
    scheduler.add_job(lambda: _run_script("fetch_upcoming_fixtures.py"),
                       "interval", hours=24, id="upcoming_fixtures")

    # Heavier: pick up newly-finished gameweeks, then regenerate predictions.
    # Runs a few times a day -- fetch_live_gameweek_stats.py is idempotent
    # (only processes genuinely new finished gameweeks), so extra runs are safe.
    scheduler.add_job(lambda: _run_script("fetch_live_gameweek_stats.py"),
                       "interval", hours=6, id="live_gameweek_stats")
    scheduler.add_job(lambda: _run_script("predict_upcoming.py"),
                       "interval", hours=6, id="predict_upcoming")

    scheduler.start()
    print("[scheduler] started -- see docs/live-refresh-runbook.md for the cadence rationale")


def stop():
    scheduler.shutdown(wait=False)
