// Types match backend/app/routers/*.py's actual response shapes exactly --
// keep these in sync if a router response changes.

export interface XpBreakdown {
  appearance_pts: number
  goal_pts: number
  assist_pts: number
  cs_pts: number
  conceded_penalty: number
  card_pen_pts: number
  pen_save_pts: number
  save_pts: number
  defcon_pts: number
  bonus_pts: number
}

export interface GameweekXp {
  gw: number
  xP: number
}

export interface HistoricStats {
  minutes: number
  goals: number
  assists: number
  xg: number
  xa: number
}

export interface LastSeasonStats {
  games: number
  starts: number | null
  start_pct: number | null
  total_points: number
  mean_points: number
  max_points: number
  min_points: number
  variance: number
  std_dev: number
}

export interface LastSeasonGamePoints {
  gw: number
  points: number
}

export interface LastSeasonPercentileAverages {
  top25: number
  top50: number
  top75: number
  overall: number
}

export interface LastSeasonPointsByComponent {
  appearance: number
  goals: number
  assists: number
  clean_sheet: number
  defcon: number
  bonus: number
  cards: number
  conceded: number
  saves: number
  penalties: number
}

export interface LastSeasonBreakdown {
  games: LastSeasonGamePoints[]
  percentile_averages: LastSeasonPercentileAverages
  points_by_component: LastSeasonPointsByComponent
}

export interface OutcomeProbabilities {
  goal_pts: number
  assist_pts: number
  cs_pts: number
  defcon_pts: number
}

export interface OpponentEntry {
  opponent: string
  avg_points: number
  games: number
  next_gw: number | null
}

export interface FdrTier {
  fdr: number
  avg_points: number
  games: number
}

export interface OpponentStats {
  best_opponents: OpponentEntry[]
  worst_opponents: OpponentEntry[]
  best_fdr: FdrTier
  worst_fdr: FdrTier
}

export interface MonthlyPointsEntry {
  month: string
  values: number[]
  min: number
  q1: number
  median: number
  q3: number
  max: number
  n_seasons: number
}

export interface PointsByMonth {
  months: MonthlyPointsEntry[]
  seasons_included: string[]
}

export interface OpponentFixtureHistoryEntry {
  gw: number
  opponent: string
  venue_now: 'H' | 'A'
  home_points_last_season: number | null
  away_points_last_season: number | null
}

export interface Player {
  player_id: number
  name: string
  position: 'GK' | 'DEF' | 'MID' | 'FWD'
  team: string
  team_code?: number
  price: number
  xP: number
  // Real ownership % and differential value (xP * (1 - ownership/100)) --
  // FPL is a relative game (rank vs other managers), so a high-xP player
  // everyone already owns gains you nothing over your rivals; a similarly-
  // good, low-owned pick is worth more strategically at the same xP.
  // ownership_pct is null only when genuinely missing (e.g. pre-season) --
  // differential still gets computed treating that as 0% owned.
  ownership_pct?: number | null
  differential?: number
  breakdown?: XpBreakdown
  gameweeks?: GameweekXp[]
  historic?: HistoricStats | null
  last_season_stats?: LastSeasonStats | null
  last_season_total_points?: number
  last_season_breakdown?: LastSeasonBreakdown | null
  prob?: OutcomeProbabilities | null
  opponent_stats?: OpponentStats | null
  points_by_month?: PointsByMonth | null
  points_vs_opponent_last_season?: OpponentFixtureHistoryEntry[] | null
}

export interface PlayersResponse {
  run_id: number | null
  gw_start?: number | null
  gw_end?: number | null
  players: Player[]
  note?: string
}

export interface ModelRun {
  run_id: number
  trained_at: string
  season_range: string
  position_group: string
  model_type: string
  notes: string
}

export interface Fixture {
  fixture_id: number
  gw: number
  kickoff_time: string
  finished: number
  home_team: string
  away_team: string
  home_difficulty: number
  away_difficulty: number
  home_goals: number | null
  away_goals: number | null
  // Each side's clean-sheet chance from the current prediction run --
  // null where the fixture is beyond that run's horizon (or long finished).
  // Backs Fixture Swing's clean-sheet ranking.
  home_clean_sheet_prob: number | null
  away_clean_sheet_prob: number | null
}

export interface TeamRecentForm {
  // Home and away tracked SEPARATELY (not blended) -- a team's home form and
  // away form can genuinely differ, and their NEXT fixture is specifically
  // either home or away, so a single blended number would obscure whichever
  // split actually matters for it. null only when that team has zero real
  // games at that specific venue anywhere in the cache (extremely rare).
  home_gf_per_game: number | null
  home_ga_per_game: number | null
  home_games: number
  away_gf_per_game: number | null
  away_ga_per_game: number | null
  away_games: number
}

export interface TeamOpponentEntry {
  opponent: string
  avg_goal_diff: number
  games: number
  next_gw: number | null
}

export interface TeamLastSeasonStats {
  goals_for_home: number
  goals_for_away: number
  goals_against_home: number
  goals_against_away: number
  clean_sheets_home: number
  clean_sheets_away: number
  clean_sheets_total: number
  games_home: number
  games_away: number
  favorable_opponents: TeamOpponentEntry[]
  unfavorable_opponents: TeamOpponentEntry[]
}

export interface TeamGoalsVsOpponentEntry {
  gw: number
  opponent: string
  venue_now: 'H' | 'A'
  home_gf_last_season: number | null
  home_ga_last_season: number | null
  away_gf_last_season: number | null
  away_ga_last_season: number | null
}

export interface FixturesResponse {
  season: string
  fixtures: Fixture[]
  // Keyed by team name (current season) -- each team's last-5-REAL-games
  // form, spanning a season boundary if the current season doesn't have 5
  // finished games of its own yet (e.g. pre-season, before a ball's been
  // kicked -- falls back to last season's closing games rather than
  // showing nothing). See backend/app/routers/fixtures.py's
  // _recent_form_by_team docstring.
  recent_form: Record<string, TeamRecentForm>
  // Keyed by team name -- each team's FULL last-COMPLETE-season record
  // (goals/clean sheets by venue, favorable/unfavorable opponents). See
  // backend/app/routers/fixtures.py's _team_last_season_stats docstring.
  last_season_team_stats: Record<string, TeamLastSeasonStats>
  // Keyed by team name -- for each of THEIR fixtures in the requested
  // [gw_start, gw_end] window, the opponent and goals scored/conceded
  // against that SAME opponent last season, home/away legs separate.
  // Mirrors Player Scout's points_vs_opponent_last_season, at team level.
  // See backend/app/routers/fixtures.py's _team_goals_vs_opponent_last_season.
  goals_vs_opponent: Record<string, TeamGoalsVsOpponentEntry[]>
}

export interface OptimalSquad {
  run_id: number
  gw_start: number | null
  gw_end: number | null
  locked_player_ids: number[]
  total_cost: number
  total_xp: number
  squad: Player[]
  lineup: {
    formation: Record<string, number>
    captain: string
    vice_captain: string
    expected_points: number
    expected_points_with_captain: number
    starters: string[]
    bench: string[]
    starter_ids: number[]
    bench_ids: number[]
  }
}

export interface CaptainPick {
  name: string
  fixture: string
  fdr: number
  mean: number
  p10: number
  p90: number
  p_haul: number
  p_blank: number
}

export interface CaptainPicksResponse {
  gw: number
  safe: CaptainPick[]
  haul: CaptainPick[]
}

export interface TeamPick {
  player_id: number
  name: string
  position: 'GK' | 'DEF' | 'MID' | 'FWD'
  team: string
  team_code?: number
  price: number
  xP: number
  selling_price: number
}

export interface TeamLineup {
  formation: Record<string, number>
  captain: string
  vice_captain: string
  expected_points: number
  expected_points_with_captain: number
  starter_ids: number[]
  bench_ids: number[]
}

export interface TransferSuggestion {
  out_name: string
  in_name: string
  position: string
  gain: number
  cost_change: number
}

export interface TeamOverview {
  team_id: number
  manager_name: string
  team_name: string
  overall_rank: number | null
  total_points: number | null
  squad_published: boolean
  bank: number | null
  picks: TeamPick[] | null
  lineup: TeamLineup | null
  suggestions: TransferSuggestion[] | null
  note?: string
}

export interface LeagueStanding {
  rank: number
  manager_name: string
  team_name: string
  team_id: number
  total_points: number
}

export interface LeagueResponse {
  league_id: number
  league_name: string | null
  standings: LeagueStanding[]
}

export interface SavedSquadSummary {
  id: number
  name: string
  created_at: string
  updated_at: string
  player_count: number
}

export interface SavedSquadDetail {
  id: number
  name: string
  created_at: string
  updated_at: string
  player_ids: number[]
  locked_player_ids: number[]
}
