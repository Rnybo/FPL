-- FPL Cache Database Schema
-- Local SQLite cache for historical + odds data and model iteration tracking

CREATE TABLE IF NOT EXISTS seasons (
    season_id   TEXT PRIMARY KEY,   -- e.g. '2023-24'
    start_date  TEXT,
    end_date    TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    team_id             INTEGER,
    season_id           TEXT,
    name                TEXT NOT NULL,
    strength_attack_home    REAL,
    strength_attack_away    REAL,
    strength_defence_home   REAL,
    strength_defence_away   REAL,
    PRIMARY KEY (team_id, season_id),
    FOREIGN KEY (season_id) REFERENCES seasons(season_id)
);

CREATE TABLE IF NOT EXISTS players (
    player_id       INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    position        TEXT,   -- GK / DEF / MID / FWD
    current_team_id INTEGER
);

CREATE TABLE IF NOT EXISTS player_season (
    player_id   INTEGER,
    season_id   TEXT,
    team_id     INTEGER,
    price_start REAL,
    price_end   REAL,
    PRIMARY KEY (player_id, season_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (season_id) REFERENCES seasons(season_id)
);

CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id      INTEGER PRIMARY KEY,
    season_id       TEXT,
    gw              INTEGER,
    home_team_id    INTEGER,
    away_team_id    INTEGER,
    kickoff_time    TEXT,
    home_difficulty INTEGER,
    away_difficulty INTEGER,
    home_goals      INTEGER,
    away_goals      INTEGER,
    finished        INTEGER,
    FOREIGN KEY (season_id) REFERENCES seasons(season_id)
);

CREATE TABLE IF NOT EXISTS player_gameweek_stats (
    player_id           INTEGER,
    fixture_id          INTEGER,
    season_id           TEXT,
    gw                  INTEGER,
    minutes             INTEGER,
    goals               INTEGER,
    assists             INTEGER,
    xg                  REAL,
    xa                  REAL,
    clean_sheet         INTEGER,
    goals_conceded      INTEGER,
    saves               INTEGER,
    penalties_saved     INTEGER,
    penalties_missed    INTEGER,
    yellow_cards        INTEGER,
    red_cards           INTEGER,
    own_goals           INTEGER,
    bonus               INTEGER,
    bps                 INTEGER,
    total_points        INTEGER,
    ict_index           REAL,
    influence           REAL,
    creativity          REAL,
    threat              REAL,
    was_home            INTEGER,
    price_at_time       REAL,
    PRIMARY KEY (player_id, fixture_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

CREATE TABLE IF NOT EXISTS match_odds (
    fixture_id      INTEGER,
    source          TEXT,   -- 'football_data_co_uk' or 'the_odds_api'
    market          TEXT,   -- 'h2h', 'totals', 'clean_sheet', etc.
    team_or_outcome TEXT,
    price           REAL,
    captured_at     TEXT,
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

CREATE TABLE IF NOT EXISTS player_odds (
    fixture_id  INTEGER,
    player_id   INTEGER,
    source      TEXT,
    market      TEXT,   -- 'anytime_scorer', 'assist', 'card', 'penalty', etc.
    price       REAL,
    captured_at TEXT,
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

CREATE TABLE IF NOT EXISTS model_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    trained_at   TEXT,
    season_range TEXT,   -- e.g. '2021-22..2025-26'
    position_group TEXT, -- 'GK','DEF','MID','FWD'
    model_type   TEXT,   -- 'ridge','lasso','lightgbm',...
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS model_weights (
    run_id       INTEGER,
    feature_name TEXT,
    weight       REAL,
    position_group TEXT,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id)
);

CREATE TABLE IF NOT EXISTS model_predictions (
    run_id           INTEGER,
    player_id        INTEGER,
    fixture_id       INTEGER,
    predicted_points REAL,
    actual_points    REAL,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

-- Added for Layer 1 (Dixon-Coles team goal model) -- see docs/model-architecture.md
CREATE TABLE IF NOT EXISTS team_strength (
    run_id      INTEGER,
    team_name   TEXT,
    attack      REAL,
    defence     REAL,
    as_of_date  TEXT,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id)
);

-- Added for Layer 1 odds blending -- see docs/model-architecture.md
CREATE TABLE IF NOT EXISTS match_probabilities (
    run_id            INTEGER,
    fixture_id        INTEGER,
    source            TEXT,   -- 'model', 'market', or 'blend'
    home_win          REAL,
    draw              REAL,
    away_win          REAL,
    home_clean_sheet  REAL,
    away_clean_sheet  REAL,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

-- Added for Layer 4 defensive contribution -- only populated from 2025-26 onward,
-- FPL did not track these per-player before that season (verified empirically).
ALTER TABLE player_gameweek_stats ADD COLUMN tackles INTEGER;
ALTER TABLE player_gameweek_stats ADD COLUMN clearances_blocks_interceptions INTEGER;
ALTER TABLE player_gameweek_stats ADD COLUMN recoveries INTEGER;
ALTER TABLE player_gameweek_stats ADD COLUMN defensive_contribution INTEGER;

-- Added for live team-news signal (see docs/model-architecture.md, item 1 of the
-- known gap analysis). NOT backtestable against history -- FPL's live status/news
-- fields aren't preserved historically anywhere we have access to, so this table
-- only accumulates value going forward from whenever we start polling.
CREATE TABLE IF NOT EXISTS live_player_status (
    player_id                   INTEGER,
    fpl_element_id               INTEGER,
    web_name                     TEXT,
    team_name                    TEXT,
    status                       TEXT,   -- a=available, d=doubtful, i=injured, s=suspended, u=unavailable
    chance_of_playing_this_round INTEGER,
    chance_of_playing_next_round INTEGER,
    news                         TEXT,
    news_added                   TEXT,
    captured_at                  TEXT,
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

-- Added for xP transparency (see docs/model-architecture.md's "never a black box" principle).
-- Mirrors model_predictions exactly (same run_id/player_id/fixture_id) so any gameweek-range
-- aggregation that sums predicted_points can sum these components too, and the two will always
-- add up consistently since they're persisted from the SAME row in predict_upcoming.py.
CREATE TABLE IF NOT EXISTS xp_breakdown (
    run_id              INTEGER,
    player_id           INTEGER,
    fixture_id          INTEGER,
    appearance_pts      REAL,
    goal_pts            REAL,
    assist_pts          REAL,
    cs_pts              REAL,
    conceded_penalty    REAL,
    card_pen_pts        REAL,
    pen_save_pts        REAL,
    save_pts            REAL,
    defcon_pts          REAL,
    bonus_pts           REAL,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

-- Added for captaincy Monte Carlo simulation (see docs/GOTCHAS.md / captain_simulation.py).
-- Raw per-fixture rate/probability inputs -- NOT points -- so the simulator can sample
-- goal/assist counts and clean-sheet/defcon events rather than working from already-summed
-- expectations in xp_breakdown (which can't be cleanly un-summed back into p_played vs
-- p_60plus for MID/FWD). Populated only by predict_upcoming.py (live captaincy is a
-- forward-looking decision; historical backtest rows in combine_xp.py don't need this).
CREATE TABLE IF NOT EXISTS captain_sim_inputs (
    run_id          INTEGER,
    player_id       INTEGER,
    fixture_id      INTEGER,
    position        TEXT,
    p_played        REAL,   -- P(player takes any part)
    p_60plus        REAL,   -- P(player reaches 60+ minutes) -- gates clean sheet/conceded
    lambda_goal     REAL,   -- expected goal count this fixture
    lambda_assist   REAL,   -- expected assist count this fixture
    p_clean_sheet   REAL,   -- P(team keeps a clean sheet), independent of minutes
    p_defcon        REAL,   -- P(defensive-contribution threshold met)
    lambda_saves    REAL,   -- expected save count (GK only, else 0)
    expected_bonus  REAL,   -- kept deterministic in the sim -- bonus is a relative
                            -- in-match rank (see Layer 5), not something with its own
                            -- clean marginal distribution to sample from
    minor_pts_fixed REAL,   -- cards + pen-miss + pen-save + conceded-goals penalty,
                            -- added deterministically per sample (small magnitude,
                            -- not worth a separate stochastic model -- see captain_simulation.py)
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

-- True "started the match" flag from source data (merged_gw.csv's own `starts`
-- column, added by FPL's API partway through history -- NULL for 2021-22,
-- which predates it, same handling as xg/xa for that season). Previously only
-- `minutes` was persisted, which can't distinguish "started, subbed at 30'"
-- from "never started, came on as a sub" -- exactly the distinction needed
-- for a real start-percentage stat (see docs re: captaincy model improvements).
ALTER TABLE player_gameweek_stats ADD COLUMN starts INTEGER;

-- Added for Squad Builder's "save as draft" feature. Only player_ids are
-- stored -- xP/price/everything else is ALWAYS re-resolved live against
-- current predictions on load, never frozen, so a draft saved weeks ago
-- reflects TODAY's model, not a stale one (matches this app's "never a
-- black box, always current" principle elsewhere). Solo single-user app, no
-- auth (see docs/build-spec-inspiration.md) -- no owner/user_id column.
CREATE TABLE IF NOT EXISTS saved_squads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    player_ids  TEXT NOT NULL,   -- JSON array of player_ids, up to 15
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Which of a saved squad's players were LOCKED (Squad Builder's lock mode)
-- at save time, so reloading a draft restores that too -- previously only
-- player_ids was saved, so reloading a draft that had locks silently forgot
-- them, making a follow-up "Optimize with bank" run fully unconstrained
-- instead of respecting whatever the person had actually locked in.
-- JSON array, default '[]' so pre-existing rows (saved before this column
-- existed) just mean "nothing was locked," not a NULL/missing-data case.
ALTER TABLE saved_squads ADD COLUMN locked_player_ids TEXT NOT NULL DEFAULT '[]';
