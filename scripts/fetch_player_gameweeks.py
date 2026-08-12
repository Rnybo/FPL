"""
Fetch player-level gameweek stats for the 5 target seasons (merged_gw.csv per
season -- see docs/historical-data-source.md for why this is a one-time bootstrap
import, not a runtime dependency).
"""
import urllib.request
from pathlib import Path

SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/gws/merged_gw.csv"
ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "fpl_api"

if __name__ == "__main__":
    for season in SEASONS:
        out_path = ROOT / season / "merged_gw.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL.format(season=season), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            out_path.write_bytes(resp.read())
        print(f"{season}: {out_path.stat().st_size} bytes -> {out_path}")
