"""
Fetch player-prop odds (anytime goalscorer, assists) for the EPL from The Odds
API -- meant to be run on a network WITHOUT the gambling-domain block seen on
the usual dev machine (see fetch_odds.py's docstring / docs/GOTCHAS.md,
"Gambling-domain network block" entry). Self-contained: stdlib only, same
pattern as fetch_odds.py.

WHY A SEPARATE SCRIPT, NOT AN ADDITION TO fetch_odds.py: player props live on
a DIFFERENT endpoint (the per-event "Event Odds" endpoint, see
docs/odds-sources.md), not the bulk `/sports/{sport}/odds` endpoint
fetch_odds.py already uses for h2h/totals -- different URL shape, different
discovery step (need event IDs first).

WHAT THIS DOESN'T KNOW YET (couldn't verify from this network -- the-odds-api.com
itself is blocked here too, same ISP-level block already documented): whether
EPL player-prop markets are actually POPULATED for any bookmaker on the free
tier. docs/odds-sources.md notes "player props where covered" -- coverage is
the open question. This script tries the documented market keys and REPORTS
what actually comes back rather than assuming -- that report is the real
answer, not a guess.

COST CAUTION (per docs/odds-sources.md: "quota cost = markets x regions, keep
to 1 region + 1 market per call"): defaults to REGIONS="uk" only and a SMALL
MAX_EVENTS for a first diagnostic run. Raise either only after confirming the
markets are actually populated and worth the extra quota on the free 500/month
tier.

Usage:
    ODDS_API_KEY=xxxx python fetch_player_prop_odds.py

After running, copy the whole output folder (default: ./player_prop_odds_output/)
back and share it here -- the JSON responses plus the printed summary are what
answer the "does this data exist and is it useful" question.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "player_prop_odds_output"
SPORT = "soccer_epl"
BASE = f"https://api.the-odds-api.com/v4/sports/{SPORT}"

# Candidate player-prop market keys per docs/odds-sources.md / The Odds API's
# soccer docs. Not all are guaranteed to return data -- that's what this checks.
PLAYER_PROP_MARKETS = [
    "player_goal_scorer_anytime",
    "player_first_goal_scorer",
    "player_last_goal_scorer",
    "player_to_receive_card",
    "player_assists",
]
REGIONS = "uk"   # single region -- see COST CAUTION in the module docstring
MAX_EVENTS = 3   # keep the first diagnostic run cheap


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        return json.loads(resp.read()), remaining, used


def fetch_events(api_key):
    url = f"{BASE}/events?apiKey={api_key}"
    data, remaining, used = get_json(url)
    print(f"[events] {len(data)} upcoming EPL fixtures found "
          f"(quota used={used}, remaining={remaining})")
    return data


def fetch_event_player_props(api_key, event):
    markets = ",".join(PLAYER_PROP_MARKETS)
    url = (f"{BASE}/events/{event['id']}/odds?apiKey={api_key}"
           f"&regions={REGIONS}&markets={markets}&oddsFormat=decimal")
    try:
        return (*get_json(url), None)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        return None, None, None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, None, None, str(e)


def summarise(event_label, data):
    """Which bookmakers actually returned which player-prop markets, and how
    many outcomes (players priced) each one has -- the real coverage answer."""
    if not data or not data.get("bookmakers"):
        print(f"  {event_label}: NO bookmaker data returned")
        return
    for bk in data["bookmakers"]:
        market_keys = [m["key"] for m in bk.get("markets", [])]
        if not market_keys:
            continue
        n_outcomes = sum(len(m.get("outcomes", [])) for m in bk["markets"])
        print(f"  {event_label} | {bk['title']}: markets={market_keys} "
              f"({n_outcomes} priced outcomes)")


if __name__ == "__main__":
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("Set ODDS_API_KEY first:\n"
              "  $env:ODDS_API_KEY='your_key'; python fetch_player_prop_odds.py")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events = fetch_events(api_key)
    (OUT_DIR / "events.json").write_text(json.dumps(events, indent=2))

    print(f"\nChecking player-prop markets for the first {MAX_EVENTS} events "
          f"(of {len(events)} total) -- see COST CAUTION in the docstring "
          f"before raising MAX_EVENTS or REGIONS.\n")

    any_data = False
    for event in events[:MAX_EVENTS]:
        label = f"{event['home_team']} vs {event['away_team']} ({event['commence_time']})"
        data, remaining, used, err = fetch_event_player_props(api_key, event)
        if err:
            print(f"  {label}: FAILED - {err}")
            continue
        dest = OUT_DIR / f"{event['id']}.json"
        dest.write_text(json.dumps(data, indent=2))
        summarise(label, data)
        if data.get("bookmakers"):
            any_data = True
        print(f"    (quota used={used}, remaining={remaining})")

    verdict = "Found real player-prop data -- see above." if any_data else \
        "No player-prop data came back for any checked event/bookmaker in this region."
    print(f"\n{verdict}")
    print(f"\nDone. Copy the '{OUT_DIR.name}' folder back and share it here.")
