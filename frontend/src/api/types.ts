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

export interface Player {
  player_id: number
  name: string
  position: 'GK' | 'DEF' | 'MID' | 'FWD'
  team: string
  team_code?: number
  price: number
  xP: number
  breakdown?: XpBreakdown
  gameweeks?: GameweekXp[]
  historic?: HistoricStats | null
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
