"""
Fetch historical fixtures + teams data for the 5 target seasons.

Source: vaastav/Fantasy-Premier-League GitHub repo (raw.githubusercontent.com),
used per docs/historical-data-source.md as a one-time bootstrap import, not a
runtime dependency. Saves raw CSVs to data/raw/fpl_api/{season}/.
"""
import urllib.request
from pathlib import Path

SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/{file}"
FILES = ["fixtures.csv", "teams.csv"]

ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "fpl_api"


def fetch(season: str, filename: str) -> Path:
    url = BASE.format(season=season, file=filename)
    out_dir = ROOT / season
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    with urllib.request.urlopen(url, timeout=20) as resp:
        out_path.write_bytes(resp.read())
    return out_path


if __name__ == "__main__":
    for season in SEASONS:
        for filename in FILES:
            path = fetch(season, filename)
            size = path.stat().st_size
            print(f"{season}/{filename}: {size} bytes -> {path}")
