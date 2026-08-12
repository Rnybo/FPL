# Fantasy Premier League (FPL) — Rules Reference

> Always compare FPL-related logic/output in this project against this file. Rules are stable structurally, but chip names, defensive-contribution thresholds, and prices can shift per season — verify against the live `bootstrap-static` API when precision matters.

## Squad Rules
- 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD
- Max 3 players per real-world club
- Budget: £100.0m total squad value
- Starting XI: 1 GK, min 3 DEF, min 2 MID, min 1 FWD (11 total)
- 4 bench subs, ordered by priority

## Transfers
- 1 free transfer/gameweek (unused bank up to max 5)
- Extra transfers: -4 pts each
- Wildcard: unlimited transfers for one GW (x2/season, one per half)

## Scoring (standard)
- 60+ mins played: 2 pts (1–59 mins: 1 pt)
- Goal: GK/DEF 6, MID 5, FWD 4
- Assist: 3 pts
- Clean sheet: GK/DEF 4, MID 1, FWD 0 (**requires the player to have played 60+ minutes** — a
  sub coming on for the final 5 minutes of a clean sheet does NOT get these points)
- Every 3 saves (GK): 1 pt
- Penalty save: 5 pts / Penalty miss: -2 pts
- Yellow card: -1 pt / Red card: -3 pts
- Own goal: -2 pts
- Every 2 goals conceded (GK/DEF): -1 pt (**also requires 60+ minutes played**, same rule as
  clean sheets — these two are the same "reward defensive minutes" family of rules)
- Bonus points (BPS-based): top 3 per match get 3/2/1
- Captain: 2x points / Vice-captain: 2x if captain doesn't play
- Defensive contribution points (verify current season thresholds)

## Chips (verify names/limits each season)
- Wildcard (x2)
- Free Hit (x1) — unlimited transfers for one GW, squad reverts after
- Bench Boost (x1) — bench points count
- Triple Captain (x1) — captain scores 3x

## Deadlines
- ~90 mins before first kickoff of the gameweek
- Prices change daily based on transfer activity

## Public API
Base: `https://fantasy.premierleague.com/api/`

| Endpoint | Purpose |
|---|---|
| `bootstrap-static/` | All players, teams, gameweeks, rules (source of truth) |
| `fixtures/` | Fixtures + difficulty ratings |
| `element-summary/{player_id}/` | Player fixture history & upcoming |
| `entry/{team_id}/` | Manager team overview |
| `entry/{team_id}/event/{event_id}/picks/` | Manager picks for a GW |
| `entry/{team_id}/history/` | Manager season history |
| `leagues-classic/{league_id}/standings/` | Classic league standings |
| `leagues-h2h/{league_id}/standings/` | H2H league standings |
| `event/{event_id}/live/` | Live scores for a GW |

No auth for read-only public data. No official rate limits documented — be conservative.
