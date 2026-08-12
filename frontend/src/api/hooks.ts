import { useQuery } from '@tanstack/react-query'
import { apiGet } from './client'
import type { PlayersResponse, ModelRun, Fixture, OptimalSquad, CaptainPicksResponse } from './types'

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
    queryFn: () => apiGet<{ season: string; fixtures: Fixture[] }>(`/api/fixtures${qs ? `?${qs}` : ''}`),
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
