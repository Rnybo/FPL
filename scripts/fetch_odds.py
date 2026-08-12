"""
Fetch odds data -- meant to be run on a network WITHOUT the gambling-domain block
seen on the usual dev machine (see docs/odds-sources.md). Self-contained: uses only
the Python standard library, so it runs anywhere with just `python fetch_odds.py`
-- no pip install, no project dependencies.

After running, copy the whole output folder (default: ./odds_output/) back and
merge it into data/raw/football_data_co_uk/ and data/raw/odds_api/ on the main machine.

Usage:
    python fetch_odds.py                        # historical odds only
    ODDS_API_KEY=xxxx python fetch_odds.py      # historical + live odds

Get a free API key at https://the-odds-api.com (500 requests/month free tier).
Never put the key directly in this file -- pass it via the environment variable
so it doesn't end up committed anywhere.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "odds_output"

# --- Part 1: historical odds (football-data.co.uk, no key needed) ----------------

SEASON_CODES = {
    "2021-22": "2122",
    "2022-23": "2223",
    "2023-24": "2324",
    "2024-25": "2425",
    "2025-26": "2526",
}
FD_BASE = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"


def fetch_historical_odds():
    out = OUT_DIR / "football_data_co_uk"
    out.mkdir(parents=True, exist_ok=True)
    for season, code in SEASON_CODES.items():
        url = FD_BASE.format(code=code)
        dest = out / f"{season}.csv"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                dest.write_bytes(resp.read())
            print(f"[historical] {season}: OK -> {dest} ({dest.stat().st_size} bytes)")
        except Exception as e:
            print(f"[historical] {season}: FAILED - {e}")


# --- Part 2: live/upcoming odds (The Odds API, needs ODDS_API_KEY) ---------------

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"


def fetch_live_odds(api_key: str):
    out = OUT_DIR / "odds_api"
    out.mkdir(parents=True, exist_ok=True)
    url = f"{ODDS_API_BASE}?apiKey={api_key}&regions=uk&markets=h2h&oddsFormat=decimal"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = resp.read()
        parsed = json.loads(data)
        dest = out / "soccer_epl_h2h_snapshot.json"
        dest.write_bytes(data)
        print(f"[live] OK -> {dest} ({len(parsed)} fixtures)")
    except urllib.error.HTTPError as e:
        print(f"[live] FAILED - HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except Exception as e:
        print(f"[live] FAILED - {e}")


if __name__ == "__main__":
    print(f"Output folder: {OUT_DIR}\n")
    fetch_historical_odds()

    api_key = os.environ.get("ODDS_API_KEY")
    if api_key:
        print()
        fetch_live_odds(api_key)
    else:
        print(
            "\n[live] Skipped -- no ODDS_API_KEY environment variable set.\n"
            "Get a free key at https://the-odds-api.com then run:\n"
            "  ODDS_API_KEY=your_key python fetch_odds.py      (macOS/Linux)\n"
            "  $env:ODDS_API_KEY='your_key'; python fetch_odds.py   (Windows PowerShell)"
        )

    print(f"\nDone. Copy the '{OUT_DIR.name}' folder back to the main machine and merge into:\n"
          f"  data/raw/football_data_co_uk/\n  data/raw/odds_api/")
