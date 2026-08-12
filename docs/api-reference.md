# FPL API Reference

Base URL: `https://fantasy.premierleague.com/api/`
No auth required for read-only endpoints. No official rate limit — throttle requests to be safe.

## Endpoints

### `GET bootstrap-static/`
The core dataset. Contains:
- `elements`: every player — id, team, position, price (`now_cost`, /10), total points,
  form, ict_index, selected_by_percent, minutes, goals, assists, xG/xA (`expected_goals`,
  `expected_assists` if available), status (injured/available)
- `teams`: club info, strength ratings (attack/defence, home/away)
- `events`: gameweek metadata (deadlines, is_current, is_next, finished)
- `element_types`: position definitions (GK/DEF/MID/FWD) and scoring rules per position

### `GET fixtures/`
All fixtures for the season. Each entry has team ids, kickoff time, finished status,
and `team_h_difficulty` / `team_a_difficulty` (FPL's own 1–5 difficulty rating).
Use `?event={gw}` to filter to one gameweek.

### `GET element-summary/{player_id}/`
Per-player detail:
- `history`: this season's match-by-match stats (minutes, goals, assists, xG, xA, bonus, etc.)
- `history_past`: previous seasons' summary stats
- `fixtures`: upcoming fixtures for that player's team

### `GET entry/{team_id}/`
A manager's team: overall rank, points, current squad value.

### `GET entry/{team_id}/event/{event_id}/picks/`
A manager's picks (11 + bench) for a specific gameweek, including captain/vice-captain and chip used.

### `GET entry/{team_id}/history/`
A manager's gameweek-by-gameweek history for the season plus past seasons summary.

### `GET leagues-classic/{league_id}/standings/` and `leagues-h2h/{league_id}/standings/`
League standings (paginated via `?page_standings=N`).

### `GET event/{event_id}/live/`
Live per-player stats for a gameweek (updates during matches).

## Notes for building the xP model
- `elements[].form` = avg points over last 5 GWs (good in-form signal)
- `elements[].ict_index`, `influence`, `creativity`, `threat` are FPL's own composite metrics
- `expected_goals`, `expected_assists`, `expected_goals_conceded` (xG/xA/xGC) are the best
  underlying-performance signals when available — more predictive than raw goals/assists
- Combine `element-summary` history with `fixtures` difficulty for a fixture-adjusted forecast
