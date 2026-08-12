# Local Data Storage / Cache

## Format: SQLite
One local file, `data/fpl_cache.db`, no server needed, easy for scripts and the webapp to both
read/write, and easy to query with SQL when iterating on features. Raw pulled files (CSVs from
football-data.co.uk, raw JSON from FPL API) are cached separately in `data/raw/` before being
loaded into the DB, so we never have to re-download during development.

## Folder layout
```
data/
├── fpl_cache.db        SQLite cache — the thing scripts/model code reads from
├── raw/                 Untouched downloaded files, cached so we don't re-hit APIs/sites
│   ├── fpl_api/          Raw JSON dumps per season/gameweek
│   ├── football_data_co_uk/   Raw odds CSVs per season
│   └── odds_api/         Raw live odds JSON snapshots (going forward)
└── README.md
```

## Schema (see `schema.sql` for the actual CREATE TABLE statements)

- **seasons** — season_id, label (e.g. "2023-24"), start_date, end_date
- **teams** — team_id, season_id, name, strength_attack_home/away, strength_defence_home/away
- **players** — player_id, name, position, current_team_id
- **player_season** — player_id, season_id, team_id, price_start, price_end (season-level)
- **fixtures** — fixture_id, season_id, gw, home_team_id, away_team_id, kickoff_time,
  home_difficulty, away_difficulty, home_goals, away_goals, finished
- **player_gameweek_stats** — the core table: player_id, fixture_id, season_id, gw, minutes,
  goals, assists, xg, xa, clean_sheet, goals_conceded, saves, penalties_saved,
  penalties_missed, yellow_cards, red_cards, own_goals, bonus, bps, total_points, ict_index,
  influence, creativity, threat, was_home, price_at_time
- **match_odds** — fixture_id, source, market (h2h/totals/etc), team_or_outcome, price,
  captured_at
- **player_odds** — fixture_id, player_id, source, market (anytime_scorer/assist/card/etc),
  price, captured_at
- **model_runs** — run_id, trained_at, season_range, position_group, model_type, notes
- **model_weights** — run_id, feature_name, weight/coefficient, position_group
- **model_predictions** — run_id, player_id, fixture_id, predicted_points, actual_points (filled
  in after the gameweek, for evaluating accuracy)

## Iterative learning support
`model_runs` + `model_weights` + `model_predictions` exist specifically so every training
iteration is kept, not overwritten — we can compare run N vs run N-1, see how learned weights
shift as more data/features are added, and check predicted-vs-actual accuracy per run over time.

## Status
Schema created and initialized as an empty DB, ready for scripts to populate. No data loaded yet.
