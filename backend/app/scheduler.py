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
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import SCRIPTS_DIR

scheduler = BackgroundScheduler()

# Which scripts actually change data that /api/players' in-process cache is
# built from (see players.py's _cache/invalidate_players_cache) -- roster
# (prices, team assignments), fixtures (opponents, upcoming schedule), live
# gameweek stats, and predictions all feed it; only the team-news job
# doesn't touch anything players.py queries at all.
_INVALIDATES_PLAYERS_CACHE = {
    "fetch_current_roster.py", "fetch_upcoming_fixtures.py",
    "fetch_live_gameweek_stats.py", "predict_upcoming.py",
}


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
    elif name in _INVALIDATES_PLAYERS_CACHE:
        # Runs in the SAME process as the FastAPI app (this is a background
        # thread, not a separate process, unlike the script subprocess above)
        # -- importing here (not at module top) avoids a circular import
        # between scheduler.py and the routers package at startup.
        #
        # Re-warms IMMEDIATELY after invalidating, in this same background
        # thread -- not just clearing and leaving it cold for whichever real
        # visitor's request happens to hit next. That was a real gap: a
        # cleared-but-not-yet-rewarmed cache looked identical to a genuinely
        # slow one from the outside ("player loading still takes a long
        # time"), and since these jobs fire fairly often, a cold cache could
        # persist for a real user far more often than the rare deploy-restart
        # case warm_players_cache() alone was written for.
        from app.routers.players import invalidate_players_cache, warm_players_cache
        invalidate_players_cache()
        print(f"[scheduler] {name}: players cache invalidated, re-warming...")
        warm_players_cache()
        print(f"[scheduler] {name}: players cache re-warmed")


def start():
    # next_run_time=now+interval on every job below -- APScheduler's default
    # otherwise fires an interval job's FIRST execution IMMEDIATELY on
    # scheduler.start(), not after waiting the stated interval (a known
    # APScheduler gotcha). Left at the default, EVERY container restart/deploy
    # kicked off all 5 scripts at once, including the cache-invalidating ones
    # -- racing against warm_players_cache()'s own startup warm-up and often
    # winning, leaving a freshly-restarted server's cache cold again within
    # minutes even with no genuine new data to fetch. Explicit next_run_time
    # defers the first real run to a sensible time after startup instead.
    now = datetime.now()

    # Cheap, safe to run often -- news changes fast, especially near deadlines
    scheduler.add_job(lambda: _run_script("fetch_live_team_news.py"),
                       "interval", hours=6, next_run_time=now + timedelta(hours=6), id="live_team_news")

    # Roster/fixtures change rarely mid-week; daily is plenty
    scheduler.add_job(lambda: _run_script("fetch_current_roster.py"),
                       "interval", hours=24, next_run_time=now + timedelta(hours=24), id="current_roster")
    scheduler.add_job(lambda: _run_script("fetch_upcoming_fixtures.py"),
                       "interval", hours=24, next_run_time=now + timedelta(hours=24), id="upcoming_fixtures")

    # Heavier: pick up newly-finished gameweeks, then regenerate predictions.
    # Runs a few times a day -- fetch_live_gameweek_stats.py is idempotent
    # (only processes genuinely new finished gameweeks), so extra runs are safe.
    scheduler.add_job(lambda: _run_script("fetch_live_gameweek_stats.py"),
                       "interval", hours=6, next_run_time=now + timedelta(hours=6), id="live_gameweek_stats")
    scheduler.add_job(lambda: _run_script("predict_upcoming.py"),
                       "interval", hours=6, next_run_time=now + timedelta(hours=6), id="predict_upcoming")

    scheduler.start()
    print("[scheduler] started -- see docs/live-refresh-runbook.md for the cadence rationale")


def stop():
    scheduler.shutdown(wait=False)
