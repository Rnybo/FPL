import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost, apiPut } from './client'
import type { PlayersResponse, ModelRun, FixturesResponse, OptimalSquad, CaptainPicksResponse, TeamOverview, TeamPlanResponse, LeagueResponse, SavedSquadSummary, SavedSquadDetail, PerformanceResponse } from './types'

export function usePlayers(gwStart?: number, gwEnd?: number) {
  const params = new URLSearchParams()
  if (gwStart) params.set('gw_start', String(gwStart))
  if (gwEnd) params.set('gw_end', String(gwEnd))
  const qs = params.toString()

  return useQuery({
    queryKey: ['players', gwStart, gwEnd],
    queryFn: () => apiGet<PlayersResponse>(`/api/players${qs ? `?${qs}` : ''}`),
  })
}

export function useModelRuns(modelType?: string) {
  const qs = modelType ? `?model_type=${encodeURIComponent(modelType)}` : ''
  return useQuery({
    queryKey: ['model-runs', modelType],
    queryFn: () => apiGet<{ runs: ModelRun[] }>(`/api/model-runs${qs}`),
  })
}

export function useFixtures(gw?: number, gwStart?: number, gwEnd?: number) {
  const params = new URLSearchParams()
  if (gw) params.set('gw', String(gw))
  if (gwStart) params.set('gw_start', String(gwStart))
  if (gwEnd) params.set('gw_end', String(gwEnd))
  const qs = params.toString()
  return useQuery({
    queryKey: ['fixtures', gw, gwStart, gwEnd],
    queryFn: () => apiGet<FixturesResponse>(`/api/fixtures${qs ? `?${qs}` : ''}`),
  })
}

export function useOptimalSquad(gwStart?: number, gwEnd?: number, lockedIds: number[] = []) {
  const params = new URLSearchParams()
  if (gwStart) params.set('gw_start', String(gwStart))
  if (gwEnd) params.set('gw_end', String(gwEnd))
  if (lockedIds.length) params.set('locked', lockedIds.join(','))
  const qs = params.toString()

  return useQuery({
    queryKey: ['squad-optimal', gwStart, gwEnd, lockedIds],
    queryFn: () => apiGet<OptimalSquad>(`/api/squad/optimal${qs ? `?${qs}` : ''}`),
    staleTime: 5 * 60 * 1000, // solver result, no need to refetch aggressively
  })
}


export function useSquadLineup(playerIds: number[], gwStart?: number, gwEnd?: number) {
  const params = new URLSearchParams()
  params.set('player_ids', playerIds.join(','))
  if (gwStart) params.set('gw_start', String(gwStart))
  if (gwEnd) params.set('gw_end', String(gwEnd))

  return useQuery({
    queryKey: ['squad-lineup', playerIds, gwStart, gwEnd],
    queryFn: () => apiGet<OptimalSquad>(`/api/squad/lineup?${params.toString()}`),
    enabled: playerIds.length === 15,
    staleTime: 60 * 1000,
  })
}

// The 'Drejebog' -- multi-gameweek playbook for a squad being BUILT here
// (not yet a real FPL team), see squad.py's GET /api/squad/plan. Only
// enabled once exactly 15 players are picked (a partial squad 400s).
export function useSquadPlan(
  playerIds: number[],
  options: { gwStart?: number; horizon?: number; freeTransfers?: number; allowHits?: boolean; budget?: number; minGain?: number } = {},
) {
  const { gwStart, horizon = 5, freeTransfers = 1, allowHits = false, budget = 100.0, minGain = 2.0 } = options
  const params = new URLSearchParams()
  params.set('player_ids', playerIds.join(','))
  if (gwStart) params.set('gw_start', String(gwStart))
  params.set('horizon', String(horizon))
  params.set('free_transfers', String(freeTransfers))
  params.set('allow_hits', String(allowHits))
  params.set('budget', String(budget))
  params.set('min_gain', String(minGain))

  return useQuery({
    queryKey: ['squad-plan', playerIds, gwStart, horizon, freeTransfers, allowHits, budget, minGain],
    queryFn: () => apiGet<TeamPlanResponse>(`/api/squad/plan?${params.toString()}`),
    enabled: playerIds.length === 15,
    retry: false,
    staleTime: 5 * 60 * 1000, // solver result, no need to refetch aggressively
  })
}

export function useCaptainPicks(gw?: number) {
  const qs = gw ? `?gw=${gw}` : ''
  return useQuery({
    queryKey: ['captain-picks', gw],
    queryFn: () => apiGet<CaptainPicksResponse>(`/api/captain/picks${qs}`),
    staleTime: 5 * 60 * 1000, // Monte Carlo result, no need to refetch aggressively
  })
}

// Hits the live FPL API server-side (see team.py) -- can be slow/rate-limited,
// so only fetches once a team id has actually been entered (enabled).
export function useTeam(teamId: number | null) {
  return useQuery({
    queryKey: ['team', teamId],
    queryFn: () => apiGet<TeamOverview>(`/api/team/${teamId}`),
    enabled: teamId != null,
    retry: false, // an invalid/unknown team id shouldn't retry against the live API
  })
}

export function useLeague(leagueId: number | null) {
  return useQuery({
    queryKey: ['league', leagueId],
    queryFn: () => apiGet<LeagueResponse>(`/api/league/${leagueId}`),
    enabled: leagueId != null,
    retry: false,
  })
}

// Multi-gameweek game plan (see team.py's GET /{team_id}/plan). Only enabled
// once the caller knows the squad is published and fully matched (same
// `enabled` gate useTeam's data.squad_published/data.lineup already tells
// the caller) -- calling this before that would 409.
export function useTeamPlan(
  teamId: number | null,
  options: { horizon?: number; freeTransfers?: number; allowHits?: boolean; minGain?: number; enabled?: boolean } = {},
) {
  const { horizon = 5, freeTransfers = 1, allowHits = false, minGain = 2.0, enabled = true } = options
  const params = new URLSearchParams()
  params.set('horizon', String(horizon))
  params.set('free_transfers', String(freeTransfers))
  params.set('allow_hits', String(allowHits))
  params.set('min_gain', String(minGain))
  return useQuery({
    queryKey: ['team-plan', teamId, horizon, freeTransfers, allowHits, minGain],
    queryFn: () => apiGet<TeamPlanResponse>(`/api/team/${teamId}/plan?${params.toString()}`),
    enabled: teamId != null && enabled,
    retry: false,
    staleTime: 5 * 60 * 1000, // solver result, no need to refetch aggressively
  })
}

// Squad Builder's "save as draft" -- list is always fresh (no staleTime) since
// the whole point is seeing your own just-made save/rename/delete reflected
// immediately, and invalidating it after every mutation below is exactly
// what makes that automatic without any manual refetch() calls at the call site.
export function useSavedSquads() {
  return useQuery({
    queryKey: ['saved-squads'],
    queryFn: () => apiGet<{ squads: SavedSquadSummary[] }>('/api/saved-squads'),
  })
}

export function useSavedSquad(squadId: number | null) {
  return useQuery({
    queryKey: ['saved-squad', squadId],
    queryFn: () => apiGet<SavedSquadDetail>(`/api/saved-squads/${squadId}`),
    enabled: squadId != null,
  })
}

export function useCreateSavedSquad() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; player_ids: number[]; locked_player_ids: number[] }) =>
      apiPost<SavedSquadDetail>('/api/saved-squads', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['saved-squads'] }),
  })
}

export function useUpdateSavedSquad() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; player_ids?: number[]; locked_player_ids?: number[] }) =>
      apiPut<SavedSquadDetail>(`/api/saved-squads/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['saved-squads'] }),
  })
}

// Player Performance tab -- gw-window independent (backed by the same
// in-process cache pattern as usePlayers' backend, see performance.py), so
// no gw params here, unlike usePlayers.
export function usePerformance() {
  return useQuery({
    queryKey: ['performance'],
    queryFn: () => apiGet<PerformanceResponse>('/api/performance'),
  })
}

export function useDeleteSavedSquad() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/saved-squads/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['saved-squads'] }),
  })
}
