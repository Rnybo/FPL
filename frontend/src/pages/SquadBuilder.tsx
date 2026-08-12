import { useEffect, useMemo, useState } from 'react'
import { Search, X, Plus, Wand2, RotateCcw, UserPlus, Lock, Unlock, Trash2 } from 'lucide-react'
import { usePlayers, useOptimalSquad } from '../api/hooks'
import { apiGet } from '../api/client'
import PlayerShirt from '../components/PlayerShirt'
import CaptainPicks from '../components/CaptainPicks'
import type { Player, OptimalSquad } from '../api/types'

const BUDGET = 100.0
const MAX_PER_CLUB = 3
const SLOT_POSITIONS = [
  'GK', 'GK',
  'DEF', 'DEF', 'DEF', 'DEF', 'DEF',
  'MID', 'MID', 'MID', 'MID', 'MID',
  'FWD', 'FWD', 'FWD',
] as const

function toSlots(squad: Player[]): (number | null)[] {
  const byPos: Record<string, number[]> = { GK: [], DEF: [], MID: [], FWD: [] }
  ;[...squad].sort((a, b) => b.xP - a.xP).forEach((p) => byPos[p.position]?.push(p.player_id))
  return SLOT_POSITIONS.map((pos) => (byPos[pos].length ? byPos[pos].shift()! : null))
}

// Mirrors optimise.py's FORMATION_LIMITS / best_lineup EXACTLY -- same greedy
// algorithm (players are interchangeable within a position for a FIXED
// formation, so top-N-by-xP is provably optimal, not an approximation --
// see optimise.py's module docstring). Computed client-side rather than via
// an API round-trip so switching formations or editing the squad by hand is
// instant; the backend's /api/squad/optimal and /api/squad/lineup still
// accept an equivalent ?formation= param for when the OPTIMIZER itself needs
// to target a specific formation (see callOptimizer below).
const FORMATION_BOUNDS = { DEF: [3, 5], MID: [2, 5], FWD: [1, 3] } as const

function validFormationStrings(): string[] {
  const out: string[] = []
  for (let d = FORMATION_BOUNDS.DEF[0]; d <= FORMATION_BOUNDS.DEF[1]; d++)
    for (let m = FORMATION_BOUNDS.MID[0]; m <= FORMATION_BOUNDS.MID[1]; m++)
      for (let f = FORMATION_BOUNDS.FWD[0]; f <= FORMATION_BOUNDS.FWD[1]; f++)
        if (d + m + f === 10) out.push(`${d}-${m}-${f}`)
  return out
}

function parseFormationString(s: string): Record<string, number> {
  const [d, m, f] = s.split('-').map(Number)
  return { GK: 1, DEF: d, MID: m, FWD: f }
}

type ClientLineup = {
  formation: Record<string, number>
  starterIds: number[]
  benchIds: number[]
  captainId: number
  viceId: number
  expectedPoints: number
}

function lineupForFormation(squad: Player[], formation: Record<string, number>): ClientLineup | null {
  const starters: Player[] = []
  for (const pos of ['GK', 'DEF', 'MID', 'FWD'] as const) {
    const n = formation[pos]
    const posPlayers = squad.filter((p) => p.position === pos).sort((a, b) => b.xP - a.xP).slice(0, n)
    if (posPlayers.length < n) return null
    starters.push(...posPlayers)
  }
  const starterIdSet = new Set(starters.map((p) => p.player_id))
  const bench = squad.filter((p) => !starterIdSet.has(p.player_id))
  const benchSorted = [
    ...bench.filter((p) => p.position !== 'GK').sort((a, b) => b.xP - a.xP),
    ...bench.filter((p) => p.position === 'GK'),
  ]
  const ranked = [...starters].sort((a, b) => b.xP - a.xP)
  return {
    formation,
    starterIds: starters.map((p) => p.player_id),
    benchIds: benchSorted.map((p) => p.player_id),
    captainId: ranked[0].player_id,
    viceId: ranked[1].player_id,
    expectedPoints: starters.reduce((sum, p) => sum + p.xP, 0),
  }
}

function computeLineup(squad: Player[], formation: Record<string, number> | null): ClientLineup | null {
  if (formation) return lineupForFormation(squad, formation)
  let best: ClientLineup | null = null
  for (const fStr of validFormationStrings()) {
    const candidate = lineupForFormation(squad, parseFormationString(fStr))
    if (candidate && (!best || candidate.expectedPoints > best.expectedPoints)) best = candidate
  }
  return best
}

// Captaincy doubles whoever scores most in a given week -- and that can be a
// DIFFERENT squad member week to week (form, fixtures, rotation all shift).
// This is the EXACT per-week version: for each gameweek, just look at who in
// the full 15-man squad actually has the biggest number that specific week,
// using the same per-gameweek breakdown already loaded for every player (see
// Player.gameweeks). Deliberately drawn from the WHOLE squad, not just this
// window's fixed starting XI -- a generally-weaker bench player can still
// have a genuine standout week worth captaining, and the backend's squad
// SELECTION already got a nudge toward keeping such players around (see
// CAPTAIN_CEILING_WEIGHT in backend/app/routers/squad.py).
type CaptaincyPlanEntry = { gw: number; captainId: number; captainName: string; xp: number }

function buildCaptaincyPlan(squad: Player[], gwStart: number, gwEnd: number): CaptaincyPlanEntry[] {
  const plan: CaptaincyPlanEntry[] = []
  for (let gw = gwStart; gw <= gwEnd; gw++) {
    let best: Player | null = null
    let bestXp = -Infinity
    for (const p of squad) {
      const gwXp = p.gameweeks?.find((g) => g.gw === gw)?.xP ?? 0
      if (gwXp > bestXp) {
        bestXp = gwXp
        best = p
      }
    }
    if (best) plan.push({ gw, captainId: best.player_id, captainName: best.name, xp: bestXp })
  }
  return plan
}

type SortKey = 'xP' | 'price' | 'name'
type PositionFilter = 'ALL' | Player['position']

export default function SquadBuilder() {
  const [gwStart, setGwStart] = useState(1)
  const [gwEnd, setGwEnd] = useState(5)
  const [slots, setSlots] = useState<(number | null)[]>(new Array(15).fill(null))
  const [notification, setNotification] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [positionFilter, setPositionFilter] = useState<PositionFilter>('ALL')
  const [sortKey, setSortKey] = useState<SortKey>('xP')
  const [building, setBuilding] = useState(false)
  const [formation, setFormation] = useState<string | null>(null) // null = auto/optimal
  const [lockMode, setLockMode] = useState(false)
  const [lockedIds, setLockedIds] = useState<Set<number>>(new Set())

  const { data: playersData, isLoading: playersLoading } = usePlayers(gwStart, gwEnd)
  // Only used for the INITIAL squad on page load / when the GW range changes --
  // no lock feature anymore (removed per user feedback: it was auto-rebuilding
  // the whole squad unexpectedly). Both "build" actions below call the API
  // directly on demand instead.
  const { data: optimalData, isLoading: optimalLoading } = useOptimalSquad(gwStart, gwEnd, [])

  useEffect(() => {
    if (optimalData) setSlots(toSlots(optimalData.squad))
    setNotification(null)
    setLockedIds(new Set())
  }, [gwStart, gwEnd, optimalData?.run_id])

  const playerById = useMemo(() => {
    const map = new Map<number, Player>()
    playersData?.players.forEach((p) => map.set(p.player_id, p))
    return map
  }, [playersData])

  const squadPlayers = slots.map((id) => (id ? playerById.get(id) ?? null : null))
  const filledPlayers = squadPlayers.filter((p): p is Player => !!p)
  const totalCost = filledPlayers.reduce((sum, p) => sum + p.price, 0)
  const bank = BUDGET - totalCost
  const filledCount = filledPlayers.length

  const clubCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    filledPlayers.forEach((p) => { counts[p.team] = (counts[p.team] ?? 0) + 1 })
    return counts
  }, [filledPlayers])

  const isLoading = optimalLoading || playersLoading

  // Which 11 of the current 15 start, under whichever formation is selected
  // (or the auto-optimal one) -- recomputed instantly on any squad edit or
  // formation change, see computeLineup's comment for why this is client-side.
  const lineup = useMemo(() => {
    if (filledPlayers.length !== 15) return null
    return computeLineup(filledPlayers, formation ? parseFormationString(formation) : null)
  }, [filledPlayers, formation])

  // Per-gameweek captaincy plan for the CURRENT squad + selected GW range --
  // see buildCaptaincyPlan's comment for why it draws from the whole 15, not
  // just this window's fixed starting XI.
  const captaincyPlan = useMemo(() => {
    if (filledPlayers.length !== 15) return []
    return buildCaptaincyPlan(filledPlayers, gwStart, gwEnd)
  }, [filledPlayers, gwStart, gwEnd])

  // "Just missed the cut" -- top few players per position NOT currently in
  // the squad, so a close alternative is visible without having to hunt
  // through the full sidebar list. See swapIn() for the one-click swap.
  const nearMiss = useMemo(() => {
    if (!playersData) return {} as Record<string, Player[]>
    const squadIds = new Set(filledPlayers.map((p) => p.player_id))
    const byPos: Record<string, Player[]> = { GK: [], DEF: [], MID: [], FWD: [] }
    playersData.players.filter((p) => !squadIds.has(p.player_id)).forEach((p) => byPos[p.position]?.push(p))
    for (const pos in byPos) byPos[pos] = byPos[pos].sort((a, b) => b.xP - a.xP).slice(0, 4)
    return byPos
  }, [playersData, filledPlayers])

  function removePlayer(p: Player) {
    setSlots((prev) => prev.map((id) => (id === p.player_id ? null : id)))
    setLockedIds((prev) => {
      if (!prev.has(p.player_id)) return prev
      const next = new Set(prev)
      next.delete(p.player_id)
      return next
    })
    setNotification(`${p.name} has been removed from your squad`)
    setPositionFilter(p.position) // mirrors real FPL: sidebar auto-filters to the vacated position
    setSearch('')
  }

  // In lock mode, manually picking a player IS the signal that you want
  // them -- auto-locking them here means the padlock is only needed for
  // players the optimizer originally chose that you now want to protect,
  // not for every player you deliberately add yourself.
  function addPlayer(p: Player) {
    const slotIndex = slots.findIndex((id, i) => id === null && SLOT_POSITIONS[i] === p.position)
    if (slotIndex === -1) return // no empty slot of this position -- shouldn't happen, guarded in UI too
    setSlots((prev) => prev.map((id, i) => (i === slotIndex ? p.player_id : id)))
    if (lockMode) {
      setLockedIds((prev) => new Set(prev).add(p.player_id))
    }
    setNotification(`${p.name} has been added to your squad${lockMode ? ' and locked in' : ''}`)
  }

  // One-click "swap in" for a near-miss candidate: fills a genuinely empty
  // slot directly if there is one, otherwise bumps the weakest player in
  // that position (skipping locked players in lock mode -- a lock is a
  // promise not to touch that specific player, near-miss swaps included).
  // Same auto-lock-on-manual-pick behavior as addPlayer above.
  function swapIn(candidate: Player) {
    const emptySlotIndex = slots.findIndex((id, i) => id === null && SLOT_POSITIONS[i] === candidate.position)
    if (emptySlotIndex !== -1) {
      addPlayer(candidate) // already handles the lock-on-add
      return
    }
    const samePosition = filledPlayers.filter((p) => p.position === candidate.position)
    const swappable = lockMode ? samePosition.filter((p) => !lockedIds.has(p.player_id)) : samePosition
    if (swappable.length === 0) {
      setNotification(`All your ${candidate.position}s are locked -- unlock one first to swap`)
      return
    }
    const weakest = swappable.reduce((min, p) => (p.xP < min.xP ? p : min))
    setSlots((prev) => prev.map((id) => (id === weakest.player_id ? candidate.player_id : id)))
    if (lockMode) {
      setLockedIds((prev) => new Set(prev).add(candidate.player_id))
    }
    setNotification(`Swapped in ${candidate.name} for ${weakest.name}${lockMode ? ' and locked in' : ''}`)
  }

  function toggleLock(playerId: number) {
    setLockedIds((prev) => {
      const next = new Set(prev)
      if (next.has(playerId)) next.delete(playerId)
      else next.add(playerId)
      return next
    })
  }

  // Distinct from the "Build from scratch" buttons -- those still call the
  // OPTIMIZER for a fresh best team. This just empties the pitch, no API
  // call, so you can start a manual pick from nothing.
  function resetTeam() {
    setSlots(new Array(15).fill(null))
    setLockedIds(new Set())
    setNotification('Team reset -- pick players from the sidebar or build with the optimizer')
  }

  async function callOptimizer(ids: number[]) {
    const params = new URLSearchParams()
    if (gwStart) params.set('gw_start', String(gwStart))
    if (gwEnd) params.set('gw_end', String(gwEnd))
    if (ids.length) params.set('locked', ids.join(','))
    if (formation) params.set('formation', formation)
    return apiGet<OptimalSquad>(`/api/squad/optimal?${params.toString()}`)
  }

  // Two distinct strategies in FREE mode (per user request):
  // 1. "Build optimum team" -- keep everyone CURRENTLY in the squad fixed,
  //    let the optimizer fill any empty slots and pick the best starting XI
  //    from the result.
  // 2. "Build from scratch" -- ignore the current squad entirely, optimize
  //    everyone from zero.
  // Both use the JOINT squad+lineup optimizer (see optimise.py), which
  // correctly values a starting-XI place far above a bench place -- fixing a
  // real bug where the old objective spent money on decent bench fillers
  // instead of saving it for stronger starters.
  async function buildFromSelected() {
    setBuilding(true)
    try {
      const result = await callOptimizer(filledPlayers.map((p) => p.player_id))
      setSlots(toSlots(result.squad))
      setNotification('Built the optimum team from your current selection')
    } catch {
      setNotification('Could not build a valid squad from the current selection (budget/club rules conflict)')
    } finally {
      setBuilding(false)
    }
  }

  async function buildFromScratch() {
    setBuilding(true)
    try {
      const result = await callOptimizer([])
      setSlots(toSlots(result.squad))
      setNotification('Built a fresh optimum team from scratch')
    } catch {
      setNotification('Could not build a squad')
    } finally {
      setBuilding(false)
    }
  }

  // LOCK MODE's build action: only the EXPLICITLY locked players (via the
  // padlock toggle on each card) are preserved -- everyone else, whether
  // currently filled or empty, is fair game for the optimizer. This is
  // distinct from buildFromSelected above, which preserves EVERYONE currently
  // filled -- lock mode is for "I definitely want these specific N, surprise
  // me with the rest," not "keep my whole draft, just fill the gaps."
  async function buildAroundLocked() {
    setBuilding(true)
    try {
      const result = await callOptimizer(Array.from(lockedIds))
      setSlots(toSlots(result.squad))
      setNotification(
        lockedIds.size > 0
          ? `Built around ${lockedIds.size} locked player${lockedIds.size === 1 ? '' : 's'}`
          : 'Built a fresh optimum team (nothing was locked)'
      )
    } catch {
      setNotification('Could not build a valid squad with these locks (budget/club rules conflict)')
    } finally {
      setBuilding(false)
    }
  }

  // Candidates for the sidebar. Budget and club-limit violations are WARNINGS,
  // not blockers -- you can genuinely go over budget or stack a club beyond 3.
  // The only HARD constraint is structural: there must be an empty slot of
  // the right position to put them in.
  const candidates = useMemo(() => {
    if (!playersData) return []
    const q = search.trim().toLowerCase()
    return playersData.players
      .filter((p) => !slots.includes(p.player_id))
      .filter((p) => positionFilter === 'ALL' || p.position === positionFilter)
      .filter((p) => !q || p.name.toLowerCase().includes(q))
      .map((p) => {
        const overBudgetBy = p.price - bank
        const clubCount = clubCounts[p.team] ?? 0
        const hasEmptySlot = slots.some((id, i) => id === null && SLOT_POSITIONS[i] === p.position)
        const warnings: string[] = []
        if (overBudgetBy > 0.001) warnings.push(`£${overBudgetBy.toFixed(1)}m over budget`)
        if (clubCount >= MAX_PER_CLUB) warnings.push(`${p.team}: already ${MAX_PER_CLUB} in squad`)
        return { player: p, canAdd: hasEmptySlot, warning: warnings.join(' · ') }
      })
      .sort((a, b) => {
        if (sortKey === 'name') return a.player.name.localeCompare(b.player.name)
        return b.player[sortKey] - a.player[sortKey]
      })
  }, [playersData, slots, positionFilter, search, sortKey, bank, clubCounts])

  const budgetWarning = bank < -0.001
  const clubWarnings = Object.entries(clubCounts).filter(([, n]) => n > MAX_PER_CLUB).map(([team]) => team)

  return (
    <div className="max-w-6xl mx-auto p-3 sm:p-4 flex flex-col lg:flex-row gap-4">
      <Sidebar
        search={search} setSearch={setSearch}
        positionFilter={positionFilter} setPositionFilter={setPositionFilter}
        sortKey={sortKey} setSortKey={setSortKey}
        candidates={candidates} onAdd={addPlayer}
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-4 mb-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="bg-red-600 text-white text-sm font-bold px-2.5 py-1 rounded">{filledCount} / 15</span>
            <span className="text-xs text-slate-500">Players selected</span>
          </div>
          <div className="w-px h-6 bg-slate-200" />
          <div className="flex items-center gap-2">
            <span className={`text-white text-sm font-bold px-2.5 py-1 rounded ${bank < 0 ? 'bg-red-600' : 'bg-emerald-600'}`}>
              {bank < 0 ? '-' : ''}£{Math.abs(bank).toFixed(1)}m
            </span>
            <span className="text-xs text-slate-500">Bank</span>
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-slate-500">Formation</label>
            <select value={formation ?? 'auto'} onChange={(e) => setFormation(e.target.value === 'auto' ? null : e.target.value)}
              className="text-xs border border-slate-300 rounded-md px-2 py-1">
              <option value="auto">Auto (optimal)</option>
              {validFormationStrings().map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2 ml-auto text-xs text-slate-500">
            <label>GW</label>
            <input type="number" min={1} max={38} value={gwStart} onChange={(e) => setGwStart(Number(e.target.value))}
              className="border border-slate-300 rounded px-1.5 py-0.5 w-12" />
            <span>-</span>
            <input type="number" min={1} max={38} value={gwEnd} onChange={(e) => setGwEnd(Number(e.target.value))}
              className="border border-slate-300 rounded px-1.5 py-0.5 w-12" />
          </div>
        </div>

        {/* Mode switch, on its own row for visibility -- this fundamentally
            changes what "Build" does (see buildAroundLocked's docstring), so
            it needs to read as a deliberate, prominent choice, not a small
            settings toggle easy to miss or flip by accident.
            Off = "Optimal": the default, fully auto-built squad (every slot
            prefilled by the optimizer on load). On = "Build own + Optimal":
            lock in your own picks, the optimizer fills everything else. */}
        <div className="flex items-center justify-center gap-3 mb-4 py-2 bg-slate-50 rounded-lg border border-slate-200">
          <span className={`text-sm font-medium ${!lockMode ? 'text-slate-900' : 'text-slate-400'}`}>Optimal</span>
          <button
            role="switch"
            aria-checked={lockMode}
            aria-label="Toggle lock mode"
            onClick={() => setLockMode((v) => !v)}
            className={`relative inline-flex h-8 w-16 items-center rounded-full transition-colors ${lockMode ? 'bg-amber-500' : 'bg-slate-300'}`}
          >
            <span className={`inline-block h-6 w-6 transform rounded-full bg-white shadow transition-transform ${lockMode ? 'translate-x-9' : 'translate-x-1'}`} />
          </button>
          <span className={`text-sm font-medium ${lockMode ? 'text-amber-700' : 'text-slate-400'}`}>Build own + Optimal</span>
        </div>

        {lockMode && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 mb-2">
            Tap the padlock on any player to lock them in, then Build below -- everything else (filled or empty)
            is fair game for the optimizer. {lockedIds.size} player{lockedIds.size === 1 ? '' : 's'} currently locked.
          </p>
        )}

        {notification && (
          <div className="bg-indigo-950 text-white text-sm text-center rounded-md py-2 mb-2 flex items-center justify-center gap-2">
            {notification}
            <button onClick={() => setNotification(null)} aria-label="Dismiss notification" className="text-indigo-300 hover:text-white">
              <X size={14} />
            </button>
          </div>
        )}

        {(budgetWarning || clubWarnings.length > 0) && (
          <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-md py-2 px-3 mb-2">
            {budgetWarning && <p>⚠ Over budget by £{Math.abs(bank).toFixed(1)}m</p>}
            {clubWarnings.length > 0 && <p>⚠ Too many players from: {clubWarnings.join(', ')} (max {MAX_PER_CLUB} each)</p>}
          </div>
        )}

        {isLoading && <div className="text-slate-500 text-sm py-12 text-center">Loading squad...</div>}

        {!isLoading && (
          <>
            <div className="bg-gradient-to-b from-emerald-500 to-emerald-600 rounded-lg p-2 sm:p-4 pt-6 sm:pt-8 pb-8 sm:pb-10">
              {lineup ? (
                <>
                  <div aria-label="Starting XI">
                    {(['GK', 'DEF', 'MID', 'FWD'] as const).map((pos) => {
                      const idsInPos = lineup.starterIds.filter((id) => playerById.get(id)?.position === pos)
                      if (idsInPos.length === 0) return null
                      return (
                        <div key={pos} className="flex justify-center gap-1.5 sm:gap-3 mb-3 sm:mb-5 flex-wrap">
                          {idsInPos.map((id) => {
                            const player = playerById.get(id)!
                            return (
                              <PlayerCard key={id} player={player} onRemove={() => removePlayer(player)}
                                isCaptain={id === lineup.captainId} isVice={id === lineup.viceId}
                                locked={lockMode && lockedIds.has(id)}
                                onToggleLock={lockMode ? () => toggleLock(id) : undefined}
                              />
                            )
                          })}
                        </div>
                      )
                    })}
                  </div>
                  <div aria-label="Bench" className="border-t border-emerald-400/40 mt-1 pt-3">
                    <p className="text-center text-[10px] text-emerald-50 mb-2 font-semibold tracking-wide">BENCH</p>
                    <div className="flex justify-center gap-1.5 sm:gap-3 flex-wrap">
                      {lineup.benchIds.map((id) => {
                        const player = playerById.get(id)!
                        return (
                          <PlayerCard key={id} player={player} onRemove={() => removePlayer(player)} bench
                            locked={lockMode && lockedIds.has(id)}
                            onToggleLock={lockMode ? () => toggleLock(id) : undefined}
                          />
                        )
                      })}
                    </div>
                  </div>
                </>
              ) : (
                (['GK', 'DEF', 'MID', 'FWD'] as const).map((pos) => (
                  <div key={pos} className="flex justify-center gap-1.5 sm:gap-3 mb-3 sm:mb-5 flex-wrap">
                    {slots.map((id, i) => {
                      if (SLOT_POSITIONS[i] !== pos) return null
                      const player = id ? playerById.get(id) : null
                      return player
                        ? <PlayerCard key={i} player={player} onRemove={() => removePlayer(player)}
                            locked={lockMode && lockedIds.has(player.player_id)}
                            onToggleLock={lockMode ? () => toggleLock(player.player_id) : undefined}
                          />
                        : <EmptySlotCard key={i} position={pos} />
                    })}
                  </div>
                ))
              )}
            </div>

            <div className="flex items-center justify-center gap-3 mt-4 flex-wrap">
              {lockMode ? (
                <button onClick={buildAroundLocked} disabled={building}
                  className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-full border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 disabled:opacity-40 disabled:cursor-not-allowed">
                  <Lock size={14} /> {building ? 'Building...' : `Build around ${lockedIds.size} locked`}
                </button>
              ) : (
                <>
                  <button onClick={buildFromSelected} disabled={building}
                    className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-full border border-slate-300 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
                    <Wand2 size={14} /> {building ? 'Building...' : 'Build optimum team'}
                  </button>
                  <button onClick={buildFromScratch} disabled={building}
                    className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-full border border-slate-300 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
                    <RotateCcw size={14} /> {building ? 'Building...' : 'Build from scratch'}
                  </button>
                </>
              )}
              <button onClick={resetTeam} disabled={building}
                className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-full border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed">
                <Trash2 size={14} /> Reset team
              </button>
              <span className="text-xs text-slate-400">
                {filledCount === 15 ? 'Squad complete' : `${15 - filledCount} slot(s) empty`}
              </span>
            </div>

            <CaptaincyPlanPanel plan={captaincyPlan} />

            <NearMissPanel nearMiss={nearMiss} slots={slots} onSwap={swapIn} />

            <CaptainPicks gw={gwStart} />
          </>
        )}
      </div>
    </div>
  )
}

function PlayerCard({ player, onRemove, isCaptain, isVice, locked, onToggleLock, bench }: {
  player: Player
  onRemove: () => void
  isCaptain?: boolean
  isVice?: boolean
  locked?: boolean
  onToggleLock?: () => void
  bench?: boolean
}) {
  return (
    <div className={`relative bg-white rounded-lg shadow-sm w-[76px] sm:w-[104px] pt-2 pb-2 flex flex-col items-center ${bench ? 'opacity-80' : ''}`}>
      <button onClick={onRemove} aria-label={`Remove ${player.name}`}
        className="absolute -top-2 -left-2 bg-slate-800 text-white rounded-full w-5 h-5 flex items-center justify-center hover:bg-red-600">
        <X size={12} />
      </button>
      {onToggleLock && (
        <button onClick={onToggleLock} aria-label={`${locked ? 'Unlock' : 'Lock'} ${player.name}`}
          className={`absolute -top-2 -right-2 rounded-full w-5 h-5 flex items-center justify-center ${
            locked ? 'bg-amber-500 text-white' : 'bg-slate-200 text-slate-500'
          }`}>
          {locked ? <Lock size={11} /> : <Unlock size={11} />}
        </button>
      )}
      {(isCaptain || isVice) && (
        <span className={`absolute -top-2 left-1/2 -translate-x-1/2 text-[9px] font-bold w-4 h-4 rounded-full flex items-center justify-center ${
          isCaptain ? 'bg-yellow-400 text-yellow-950' : 'bg-slate-300 text-slate-700'
        }`}>
          {isCaptain ? 'C' : 'V'}
        </span>
      )}
      <PlayerShirt player={player} size={26} />
      <p className="text-[10px] sm:text-xs font-semibold text-slate-900 mt-1 truncate max-w-[68px] sm:max-w-[96px]">{player.name}</p>
      <p className="text-[9px] sm:text-[10px] text-slate-500 truncate max-w-[68px] sm:max-w-[96px]">{player.team}</p>
      <div className="flex items-center gap-1 mt-0.5">
        <span className="text-[9px] sm:text-[10px] bg-slate-100 text-slate-600 px-1 rounded">£{player.price.toFixed(1)}m</span>
        <span className="text-[9px] sm:text-[10px] bg-emerald-100 text-emerald-700 px-1 rounded font-semibold">{player.xP.toFixed(1)} xP</span>
      </div>
    </div>
  )
}

function EmptySlotCard({ position }: { position: string }) {
  return (
    <div className="w-[76px] sm:w-[104px] h-[76px] sm:h-[92px] rounded-lg border-2 border-dashed border-emerald-200 bg-emerald-400/20 flex flex-col items-center justify-center gap-1">
      <UserPlus size={18} className="text-emerald-50 sm:w-[22px] sm:h-[22px]" />
      <p className="text-[10px] sm:text-[11px] font-medium text-emerald-50">{position}</p>
    </div>
  )
}

const POSITION_LABELS: Record<string, string> = { GK: 'Goalkeepers', DEF: 'Defenders', MID: 'Midfielders', FWD: 'Forwards' }

function CaptaincyPlanPanel({ plan }: { plan: CaptaincyPlanEntry[] }) {
  if (plan.length === 0) return null
  return (
    <div role="region" aria-label="Captaincy draft plan" className="mt-6">
      <h3 className="text-sm font-semibold text-slate-700 mb-1">Captaincy draft plan</h3>
      <p className="text-xs text-slate-400 mb-2">
        Best captain from your squad, gameweek by gameweek -- captaincy doubles whoever's biggest that
        week, so the right pick can (and should) change week to week, not stay fixed on one player.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
          <thead>
            <tr className="bg-slate-100 text-left text-slate-500">
              <th className="px-3 py-2">GW</th>
              <th className="px-3 py-2">Recommended captain</th>
              <th className="px-3 py-2 text-right">Their xP</th>
              <th className="px-3 py-2 text-right">With captain boost (2x)</th>
            </tr>
          </thead>
          <tbody>
            {plan.map((entry, i) => (
              <tr key={entry.gw} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
                <td className="px-3 py-2 text-slate-500">{entry.gw}</td>
                <td className="px-3 py-2 font-medium text-slate-900">{entry.captainName}</td>
                <td className="px-3 py-2 text-right text-slate-700">{entry.xp.toFixed(1)}</td>
                <td className="px-3 py-2 text-right font-bold text-emerald-700">{(entry.xp * 2).toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function NearMissPanel({ nearMiss, slots, onSwap }: {
  nearMiss: Record<string, Player[]>
  slots: (number | null)[]
  onSwap: (p: Player) => void
}) {
  const positions = (['GK', 'DEF', 'MID', 'FWD'] as const).filter((pos) => (nearMiss[pos] ?? []).length > 0)
  if (positions.length === 0) return null
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-slate-700 mb-1">Just missed the cut</h3>
      <p className="text-xs text-slate-400 mb-2">
        Close alternatives by position -- swap one in if your gut says otherwise.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {positions.map((pos) => {
          const hasEmptySlot = slots.some((id, i) => id === null && SLOT_POSITIONS[i] === pos)
          return (
            <div key={pos} className="border border-slate-200 rounded-lg overflow-hidden">
              <div className="bg-slate-50 px-3 py-1.5 border-b border-slate-100">
                <span className="text-xs font-semibold text-slate-700">{POSITION_LABELS[pos]}</span>
              </div>
              {nearMiss[pos].map((p) => (
                <div key={p.player_id} className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-50 last:border-0">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-slate-900 truncate">{p.name}</p>
                    <p className="text-[10px] text-slate-400 truncate">{p.team} · £{p.price.toFixed(1)}m</p>
                  </div>
                  <span className="text-xs font-semibold text-emerald-700 flex-shrink-0">{p.xP.toFixed(1)}</span>
                  <button onClick={() => onSwap(p)} aria-label={`${hasEmptySlot ? 'Add' : 'Swap in'} ${p.name}`}
                    className="flex-shrink-0 text-[10px] px-1.5 py-1 rounded-md bg-slate-100 text-slate-600 hover:bg-emerald-100 hover:text-emerald-700">
                    {hasEmptySlot ? 'Add' : 'Swap'}
                  </button>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Sidebar({ search, setSearch, positionFilter, setPositionFilter, sortKey, setSortKey, candidates, onAdd }: {
  search: string
  setSearch: (s: string) => void
  positionFilter: PositionFilter
  setPositionFilter: (p: PositionFilter) => void
  sortKey: SortKey
  setSortKey: (s: SortKey) => void
  candidates: { player: Player; canAdd: boolean; warning: string }[]
  onAdd: (p: Player) => void
}) {
  return (
    // Stacked full-width on mobile (matches the flex-col page layout above);
    // fixed 300px + height-capped-with-internal-scroll only kicks in at lg,
    // once it's sitting beside the pitch instead of above/below it.
    <div role="complementary" aria-label="Candidate players"
      className="w-full lg:w-[300px] flex-shrink-0 border border-slate-200 rounded-lg overflow-hidden flex flex-col lg:max-h-[calc(100vh-3rem)]">
      <div className="p-3 border-b border-slate-100">
        <div className="relative mb-2">
          <Search size={15} className="absolute left-2.5 top-2.5 text-slate-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search"
            className="w-full pl-8 pr-8 py-1.5 text-sm border border-slate-300 rounded-md" />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-600">
              <X size={15} />
            </button>
          )}
        </div>
        <div className="flex gap-1.5 flex-wrap">
          <select value={positionFilter} onChange={(e) => setPositionFilter(e.target.value as PositionFilter)}
            className="text-xs border border-slate-300 rounded-md px-2 py-1">
            <option value="ALL">All positions</option>
            <option value="GK">Goalkeepers</option>
            <option value="DEF">Defenders</option>
            <option value="MID">Midfielders</option>
            <option value="FWD">Forwards</option>
          </select>
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="text-xs border border-slate-300 rounded-md px-2 py-1">
            <option value="xP">Sort: xP</option>
            <option value="price">Sort: Price</option>
            <option value="name">Sort: Name</option>
          </select>
        </div>
      </div>

      <div className="bg-gradient-to-r from-sky-400 to-indigo-500 text-white text-xs text-center py-1.5">
        {candidates.length} player{candidates.length === 1 ? '' : 's'} shown
      </div>

      <div className="overflow-y-auto flex-1">
        {candidates.map(({ player: p, canAdd, warning }) => (
          <div key={p.player_id} className={`flex items-center gap-2 px-3 py-2 border-b border-slate-50 ${!canAdd ? 'opacity-50' : ''}`}>
            <PlayerShirt player={p} size={22} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-900 truncate">{p.name}</p>
              <p className={`text-[11px] truncate ${warning ? 'text-red-500' : 'text-slate-400'}`}>
                {p.team} · {p.position}{warning && ` · ${warning}`}
              </p>
            </div>
            <div className="text-right flex-shrink-0">
              <p className="text-xs text-slate-600">£{p.price.toFixed(1)}m</p>
              <p className="text-xs font-semibold text-emerald-700">{p.xP.toFixed(1)}</p>
            </div>
            <button onClick={() => onAdd(p)} disabled={!canAdd} aria-label={`Add ${p.name}`}
              className="flex-shrink-0 w-6 h-6 rounded-full bg-slate-100 text-slate-600 flex items-center justify-center hover:bg-emerald-100 hover:text-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-slate-100">
              <Plus size={14} />
            </button>
          </div>
        ))}
        {candidates.length === 0 && <p className="text-xs text-slate-400 text-center py-6">No players match.</p>}
      </div>
    </div>
  )
}
