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

export type PlayerStatusCode = 'a' | 'd' | 'i' | 's' | 'u'

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
  // Live availability -- optional (not every code path that builds a Player
  // populates it, e.g. test fixtures), components should treat a missing
  // status the same as 'a'/Available, matching the backend's own default
  // when a player has no live_player_status row at all (see
  // players.py's _status_by_player docstring).
  status?: PlayerStatusCode
  status_label?: string
  chance_of_playing_next_round?: number | null
  news?: string | null
  // Set-piece duty, e.g. ["Pen1", "DF2", "C/IF1"] -- Pen(alty)/DF(direct
  // free-kick)/C-IF(corner & indirect free-kick), number = order (1 =
  // primary taker). Straight from FPL's own bootstrap-static fields --
  // see apply_live_status_override.py's set_piece_roles. Empty array (not
  // missing) when the player has no set-piece duty at all.
  set_piece_roles?: string[]
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
  // Averages across the last TEAM_GOALS_VS_OPPONENT_SEASONS (3) complete
  // seasons -- not a single season's total -- so a *_games count of 0
  // means "never met at that venue in that span" (shown as "-"), and 1-3
  // means a real, if sometimes small, sample.
  home_gf: number | null
  home_ga: number | null
  home_games: number
  away_gf: number | null
  away_ga: number | null
  away_games: number
}

export interface TeamSetPieceTakerEntry {
  player_id: number | null
  name: string
  order: number
}

export interface TeamSetPieceTakers {
  penalties: TeamSetPieceTakerEntry[]
  direct_freekicks: TeamSetPieceTakerEntry[]
  corners_and_indirect_freekicks: TeamSetPieceTakerEntry[]
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
  // [gw_start, gw_end] window, the opponent and AVERAGE goals scored/
  // conceded against that SAME opponent across the last 3 complete
  // seasons, home/away legs separate. Mirrors Player Scout's
  // points_vs_opponent_last_season, at team level. See
  // backend/app/routers/fixtures.py's _team_goals_vs_opponent.
  goals_vs_opponent: Record<string, TeamGoalsVsOpponentEntry[]>
  // Keyed by team name -- full penalty / direct free-kick / corner &
  // indirect free-kick order for that team, each ordered 1 (primary) first.
  // Live snapshot, not historical -- see backend's _set_piece_takers_by_team.
  set_piece_takers: Record<string, TeamSetPieceTakers>
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
  status?: PlayerStatusCode
  status_label?: string
  chance_of_playing_next_round?: number | null
  news?: string | null
  set_piece_roles?: string[]
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
  out_player_id?: number
  in_player_id?: number
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

// Multi-gameweek game plan -- see backend/app/routers/team.py's
// GET /{team_id}/plan (wraps optimise.plan_horizon; greedy round-by-round,
// no point hits -- see that function's own docstring).
export interface TeamPlanSquadEntry {
  player_id: number
  name: string
  position: 'GK' | 'DEF' | 'MID' | 'FWD'
  team: string
  price: number
}

export interface TeamPlanStep {
  gameweek: number
  formation: Record<string, number>
  captain: string
  vice_captain: string
  starter_ids: number[]
  bench_ids: number[]
  // Full squad for THIS round (name/team/position/price) -- needed to
  // render anyone the plan transferred in, who won't be in the original
  // GET /api/team picks list.
  squad: TeamPlanSquadEntry[]
  transfers_in: number[]
  transfers_out: number[]
  transfers_in_names: string[]
  transfers_out_names: string[]
  // The LAST `hits_taken` entries of transfers_in/out above are the paid
  // ones (-4 each) -- everything before that was free.
  hits_taken: number
  free_transfers_after: number
  bank_after: number
  // Raw lineup score, before any hit deduction.
  expected_points: number
  expected_points_with_captain: number
  // What you'd actually bank that gameweek once hits are subtracted --
  // use these for anything shown as "the" expected points for a round.
  expected_points_after_hits: number
  expected_points_with_captain_after_hits: number
}

export interface TeamPlanResponse {
  team_id: number
  gameweeks: number[]
  starting_bank: number
  starting_free_transfers: number
  allow_hits: boolean
  hit_cost: number
  plan: TeamPlanStep[]
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


// Player Performance tab -- see backend/app/routers/performance.py. One
// season block (last_season / current_season) shares this exact shape;
// current_season is null for any player with zero gameweek rows so far
// (pre-season, or a brand-new signing) rather than faked zeros -- see that
// router's docstring re: the season not having started yet.
export interface PerformanceSeasonStats {
  games: number
  starts: number | null
  minutes: number
  goals: number
  assists: number
  xg: number
  xa: number
  defensive_contribution: number
  bonus: number
  bps: number
  ict_index: number
  influence: number
  creativity: number
  threat: number
  gi: number
  xgi: number
  goals_minus_xg: number
  assists_minus_xa: number
  gi_minus_xgi: number
  goals_per90: number | null
  assists_per90: number | null
  xg_per90: number | null
  xa_per90: number | null
  gi_per90: number | null
  xgi_per90: number | null
  goals_minus_xg_per90: number | null
  assists_minus_xa_per90: number | null
  gi_minus_xgi_per90: number | null
  defensive_contribution_per90: number | null
  bonus_per90: number | null
  bps_per90: number | null
  ict_index_per90: number | null
  influence_per90: number | null
  creativity_per90: number | null
  threat_per90: number | null
  // Rank 1 = best/highest in the league (or within position). null for
  // anyone with 0 minutes that season -- not ranked, not "last place".
  goals_minus_xg_per90_rank_overall: number | null
  goals_minus_xg_per90_rank_position: number | null
  assists_minus_xa_per90_rank_overall: number | null
  assists_minus_xa_per90_rank_position: number | null
  gi_minus_xgi_per90_rank_overall: number | null
  gi_minus_xgi_per90_rank_position: number | null
  ict_index_per90_rank_overall: number | null
  ict_index_per90_rank_position: number | null
  influence_per90_rank_overall: number | null
  influence_per90_rank_position: number | null
  creativity_per90_rank_overall: number | null
  creativity_per90_rank_position: number | null
  threat_per90_rank_overall: number | null
  threat_per90_rank_position: number | null
  // GK-only counting stats (0/absent for outfield players) -- backs the
  // "Leaders" board's GK table.
  saves: number
  saves_per90: number | null
  clean_sheet: number
  clean_sheet_per90: number | null
  // DEFCON hit-rate/per-start -- null for GK (ineligible) or anyone with
  // zero starts in this view. defcon_starts is the started-game sample
  // size the other two (and the goals/assists pair below) are based on.
  // See performance.py's _per_start_stats.
  defcon_hit_rate: number | null
  defcon_per_start: number | null
  defcon_starts: number | null
  // Same "hit rate + per start" shape as DEFCON, but for goals/assists --
  // computed over STARTED games only, for every position.
  goals_hit_rate: number | null
  goals_per_start: number | null
  assists_hit_rate: number | null
  assists_per_start: number | null
  // "Offensive return" -- fraction of starts with >=1 goal OR assist (the
  // union, not a sum of the two hit rates above) and avg goals+assists per
  // start. Backs MID/FWD's combined attacking-return column.
  gi_hit_rate: number | null
  gi_per_start: number | null
  // Fraction of starts with a clean sheet, and a single per-start "weighted
  // return xP" blending goals/assists/clean-sheet/DEFCON by their ACTUAL
  // point value at this position (goal > assist > DEFCON; clean sheet
  // worth far more at GK/DEF than MID, zero at FWD). Not the real xP model
  // -- see performance.py's _per_start_stats.
  clean_sheet_hit_rate: number | null
  weighted_return_xp: number | null
  // Only present on the "sustained" (multi-season) entry -- how many
  // qualifying seasons (>= sustained_min_minutes_per_season each) were
  // summed into this player's numbers, and which ones. Absent on
  // last_season/current_season.
  qualifying_seasons?: number
  seasons_included?: string[]
}

export interface PlayerPerformance {
  player_id: number
  name: string
  position: 'GK' | 'DEF' | 'MID' | 'FWD'
  team: string
  team_code: number | null
  price: number
  ownership_pct: number | null
  last_season: PerformanceSeasonStats | null
  current_season: PerformanceSeasonStats | null
  // Multi-season robust view -- null unless the player has at least
  // sustained_min_seasons qualifying seasons (see PerformanceResponse).
  // Filters out a single lucky/unlucky season of G-xG noise -- see
  // backend/app/routers/performance.py's _sustained_aggregates docstring.
  sustained: PerformanceSeasonStats | null
  status?: PlayerStatusCode
  status_label?: string
  chance_of_playing_next_round?: number | null
  news?: string | null
  set_piece_roles?: string[]
}

export interface PerformanceResponse {
  last_season_id: string
  current_season_id: string
  sustained_seasons_available: string[]
  sustained_min_minutes_per_season: number
  sustained_min_seasons: number
  players: PlayerPerformance[]
}
