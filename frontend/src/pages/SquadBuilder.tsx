import { useEffect, useMemo, useState } from 'react'
import { Search, X, Plus, Wand2, RotateCcw, UserPlus } from 'lucide-react'
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

  const { data: playersData, isLoading: playersLoading } = usePlayers(gwStart, gwEnd)
  // Only used for the INITIAL squad on page load / when the GW range changes --
  // no lock feature anymore (removed per user feedback: it was auto-rebuilding
  // the whole squad unexpectedly). Both "build" actions below call the API
  // directly on demand instead.
  const { data: optimalData, isLoading: optimalLoading } = useOptimalSquad(gwStart, gwEnd, [])

  useEffect(() => {
    if (optimalData) setSlots(toSlots(optimalData.squad))
    setNotification(null)
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

  function removePlayer(p: Player) {
    setSlots((prev) => prev.map((id) => (id === p.player_id ? null : id)))
    setNotification(`${p.name} has been removed from your squad`)
    setPositionFilter(p.position) // mirrors real FPL: sidebar auto-filters to the vacated position
    setSearch('')
  }

  function addPlayer(p: Player) {
    const slotIndex = slots.findIndex((id, i) => id === null && SLOT_POSITIONS[i] === p.position)
    if (slotIndex === -1) return // no empty slot of this position -- shouldn't happen, guarded in UI too
    setSlots((prev) => prev.map((id, i) => (i === slotIndex ? p.player_id : id)))
    setNotification(`${p.name} has been added to your squad`)
  }

  async function callOptimizer(lockedIds: number[]) {
    const params = new URLSearchParams()
    if (gwStart) params.set('gw_start', String(gwStart))
    if (gwEnd) params.set('gw_end', String(gwEnd))
    if (lockedIds.length) params.set('locked', lockedIds.join(','))
    return apiGet<OptimalSquad>(`/api/squad/optimal?${params.toString()}`)
  }

  // Two distinct strategies, per user request:
  // 1. "Build from selected" -- keep everyone CURRENTLY in the squad fixed,
  //    let the optimizer fill any empty slots and pick the best starting XI
  //    from the result. Uses the same locked_player_ids mechanism the old
  //    per-player lock feature used, just applied to "whatever's currently
  //    selected" rather than a manually curated subset.
  // 2. "Build from scratch" -- ignore the current squad entirely, optimize
  //    everyone from zero. Both use the JOINT squad+lineup optimizer (see
  //    optimise.py), which correctly values a starting-XI place far above a
  //    bench place -- fixing a real bug where the old objective spent money
  //    on decent bench fillers instead of saving it for stronger starters.
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
    <div className="max-w-6xl mx-auto p-4 flex gap-4">
      <Sidebar
        search={search} setSearch={setSearch}
        positionFilter={positionFilter} setPositionFilter={setPositionFilter}
        sortKey={sortKey} setSortKey={setSortKey}
        candidates={candidates} onAdd={addPlayer}
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-4 mb-3">
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
          <div className="flex items-center gap-2 ml-auto text-xs text-slate-500">
            <label>GW</label>
            <input type="number" min={1} max={38} value={gwStart} onChange={(e) => setGwStart(Number(e.target.value))}
              className="border border-slate-300 rounded px-1.5 py-0.5 w-12" />
            <span>-</span>
            <input type="number" min={1} max={38} value={gwEnd} onChange={(e) => setGwEnd(Number(e.target.value))}
              className="border border-slate-300 rounded px-1.5 py-0.5 w-12" />
          </div>
        </div>

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
            <div className="bg-gradient-to-b from-emerald-500 to-emerald-600 rounded-lg p-4 pt-8 pb-10">
              {(['GK', 'DEF', 'MID', 'FWD'] as const).map((pos) => (
                <div key={pos} className="flex justify-center gap-3 mb-5 flex-wrap">
                  {slots.map((id, i) => {
                    if (SLOT_POSITIONS[i] !== pos) return null
                    const player = id ? playerById.get(id) : null
                    return player
                      ? <PlayerCard key={i} player={player} onRemove={() => removePlayer(player)} />
                      : <EmptySlotCard key={i} position={pos} />
                  })}
                </div>
              ))}
            </div>

            <div className="flex items-center justify-center gap-3 mt-4">
              <button onClick={buildFromSelected} disabled={building}
                className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-full border border-slate-300 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
                <Wand2 size={14} /> {building ? 'Building...' : 'Build optimum team'}
              </button>
              <button onClick={buildFromScratch} disabled={building}
                className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-full border border-slate-300 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
                <RotateCcw size={14} /> {building ? 'Building...' : 'Build from scratch'}
              </button>
              <span className="text-xs text-slate-400">
                {filledCount === 15 ? 'Squad complete' : `${15 - filledCount} slot(s) empty`}
              </span>
            </div>

            <CaptainPicks gw={gwStart} />
          </>
        )}
      </div>
    </div>
  )
}

function PlayerCard({ player, onRemove }: { player: Player; onRemove: () => void }) {
  return (
    <div className="relative bg-white rounded-lg shadow-sm w-[104px] pt-2 pb-2 flex flex-col items-center">
      <button onClick={onRemove} aria-label={`Remove ${player.name}`}
        className="absolute -top-2 -left-2 bg-slate-800 text-white rounded-full w-5 h-5 flex items-center justify-center hover:bg-red-600">
        <X size={12} />
      </button>
      <PlayerShirt player={player} size={34} />
      <p className="text-xs font-semibold text-slate-900 mt-1 truncate max-w-[96px]">{player.name}</p>
      <p className="text-[10px] text-slate-500 truncate max-w-[96px]">{player.team}</p>
      <div className="flex items-center gap-1 mt-0.5">
        <span className="text-[10px] bg-slate-100 text-slate-600 px-1 rounded">£{player.price.toFixed(1)}m</span>
        <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1 rounded font-semibold">{player.xP.toFixed(1)} xP</span>
      </div>
    </div>
  )
}

function EmptySlotCard({ position }: { position: string }) {
  return (
    <div className="w-[104px] h-[92px] rounded-lg border-2 border-dashed border-emerald-200 bg-emerald-400/20 flex flex-col items-center justify-center gap-1">
      <UserPlus size={22} className="text-emerald-50" />
      <p className="text-[11px] font-medium text-emerald-50">{position}</p>
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
    <div className="w-[300px] flex-shrink-0 border border-slate-200 rounded-lg overflow-hidden flex flex-col max-h-[calc(100vh-3rem)]">
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
