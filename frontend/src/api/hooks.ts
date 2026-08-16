import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost, apiPut } from './client'
import type { PlayersResponse, ModelRun, FixturesResponse, OptimalSquad, CaptainPicksResponse, TeamOverview, LeagueResponse, SavedSquadSummary, SavedSquadDetail } from './types'

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

export function useDeleteSavedSquad() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/saved-squads/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['saved-squads'] }),
  })
}
