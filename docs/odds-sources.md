# Odds Data Sources

Two sources, used for different jobs — together they remove the "no free historical odds" gap.

## 1. Historical odds (training) — football-data.co.uk
**No limitation, no paywall, no API key.** Direct CSV downloads.
- https://www.football-data.co.uk/englandm.php
- Premier League CSV per season, back to 1993/94, e.g. `E0.csv` per season folder
- Contains match results + odds from multiple bookmakers (Bet365, Pinnacle, William Hill, etc.):
  match-result odds (1X2), Asian handicap odds, total-goals (over/under) odds
- Odds shown are typically closing odds (last before kickoff) — exactly what we want for training
  (avoids using odds that later moved and leaking info)
- Update cadence: current season file updated periodically through the season, so also usable
  for reasonably fresh in-season data, not just past seasons
- **This is now our primary source for historical odds features in the xP model.**

## 2. Live/upcoming odds (prediction-time) — The Odds API
Used going forward for current-gameweek predictions, not for training.
- Host: `https://api.the-odds-api.com`, sport key `soccer_epl`
- Free tier: 500 requests/month, h2h/spreads/totals markets
- Auth: `apiKey` query param (emailed on signup)
- Key endpoints:
  - `GET /v4/sports/soccer_epl/odds/?regions=uk&markets=h2h` — match result odds
  - `GET /v4/sports/soccer_epl/events` — fixture list with event ids (free)
  - `GET /v4/sports/soccer_epl/events/{eventId}/odds?markets=...` — player props where covered
- Quota cost = markets × regions; keep to 1 region + 1 market per call to conserve free quota
- Historical odds endpoint on this API is paid-only — we don't need it anymore since
  football-data.co.uk covers that for free

## Player-level markets (goalscorer, assist)
- Historical: not in football-data.co.uk (that's match-level only). If we need historical
  player-goalscorer odds for training, we'd need a different/paid source — for now, approximate
  player scoring probability from historical xG (already in the vaastav-inspired dataset, see
  `historical-data-source.md`) rather than odds.
- Live: available via The Odds API's event-odds endpoint, coverage varies by bookmaker/region.

## Network note (found while building Layer 1)
Both `the-odds-api.com` and `football-data.co.uk` are actively connection-reset from this
machine's network — looks like an ISP/network-level block on gambling-adjacent domains (common
in Denmark, which blocks unlicensed betting sites this way), not an application-level block.
`oddsportal.com` and `betexplorer.com` also fail the same way. `rapidapi.com` and
`api-sports.io` (API-Football) ARE reachable, so that's the fallback worth trying when we get to
the odds layer — either from a network without this restriction, or via a reachable provider.
This doesn't block Dixon-Coles (goals-only, no odds needed), so we proceeded with that first.

## Mapping teams between sources
football-data.co.uk uses its own team name strings (e.g. "Man United"), FPL API uses its own
team ids/names, The Odds API uses full team names (e.g. "Manchester United"). Will need a small
team-name mapping table in the pipeline to join across all three.
