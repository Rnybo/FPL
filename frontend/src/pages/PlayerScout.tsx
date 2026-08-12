import { useMemo, useState } from 'react'
import { ChevronsUpDown, Plus, X } from 'lucide-react'
import { usePlayers, useFixtures } from '../api/hooks'
import PlayerShirt from '../components/PlayerShirt'
import FdrStrip, { buildFdrByTeam } from '../components/FdrStrip'
import PlayerDetailModal from '../components/PlayerDetailModal'
import type { Player, XpBreakdown } from '../api/types'

const FDR_LOOKAHEAD = 8 // gameweeks of fixture difficulty to show, independent of
                          // the xP optimization window -- lets you see a team's
                          // fixtures staying easy even beyond a short selected range

type Position = 'ALL' | Player['position']
type SortField = 'xP' | 'price' | 'name' | 'valuePerPrice' | keyof XpBreakdown | `gw:${number}`
type SortLevel = { field: SortField; dir: 'asc' | 'desc' }

const BREAKDOWN_LABELS: Record<keyof XpBreakdown, string> = {
  appearance_pts: 'Appearance',
  goal_pts: 'Goals',
  assist_pts: 'Assists',
  cs_pts: 'Clean sheet',
  conceded_penalty: 'Conceded',
  card_pen_pts: 'Cards',
  pen_save_pts: 'Pen. save',
  save_pts: 'Saves',
  defcon_pts: 'Def. contribution',
  bonus_pts: 'Bonus',
}
// Always shown as table columns now (no toggle) -- per user request. The full
// BREAKDOWN_LABELS set above still backs the expanded per-row panel (click a row).
const COLUMN_KEYS: (keyof XpBreakdown)[] = ['goal_pts', 'assist_pts', 'cs_pts', 'defcon_pts']

// Labels for gw:N fields are computed on the fly (there's no fixed set of them --
// depends on the selected range), so this is a function, not a static Record like before.
function sortFieldLabel(field: SortField): string {
  if (field.startsWith('gw:')) return `GW${field.slice(3)}`
  const labels: Record<'xP' | 'price' | 'name' | 'valuePerPrice' | keyof XpBreakdown, string> = {
    xP: 'xP', price: 'Price', name: 'Name', valuePerPrice: 'Value (xP/£m)', ...BREAKDOWN_LABELS,
  }
  return labels[field as keyof typeof labels]
}

function fieldValue(p: Player, field: SortField): number | string {
  if (field === 'name') return p.name
  if (field === 'xP' || field === 'price') return p[field]
  if (field === 'valuePerPrice') return p.price > 0 ? p.xP / p.price : 0
  if (field.startsWith('gw:')) {
    const gw = Number(field.slice(3))
    return p.gameweeks?.find((g) => g.gw === gw)?.xP ?? 0
  }
  return p.breakdown?.[field as keyof XpBreakdown] ?? 0
}

export default function PlayerScout() {
  const [gwStart, setGwStart] = useState(1)
  const [gwEnd, setGwEnd] = useState(1)
  const [position, setPosition] = useState<Position>('ALL')
  const [team, setTeam] = useState<string>('ALL')
  const [priceMin, setPriceMin] = useState<string>('')
  const [priceMax, setPriceMax] = useState<string>('')
  const [search, setSearch] = useState('')
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null)
  const [sortLevels, setSortLevels] = useState<SortLevel[]>([{ field: 'xP', dir: 'desc' }])

  const { data, isLoading, isError, error } = usePlayers(gwStart, gwEnd)
  const { data: fixturesData } = useFixtures(undefined, gwStart, gwStart + FDR_LOOKAHEAD - 1)
  const fdrByTeam = useMemo(
    () => buildFdrByTeam(fixturesData?.fixtures ?? []),
    [fixturesData]
  )

  const teams = useMemo(
    () => [...new Set((data?.players ?? []).map((p) => p.team))].sort(),
    [data]
  )

  const rows = useMemo(() => {
    if (!data) return []
    let players = data.players
    if (position !== 'ALL') players = players.filter((p) => p.position === position)
    if (team !== 'ALL') players = players.filter((p) => p.team === team)
    const min = priceMin === '' ? null : Number(priceMin)
    const max = priceMax === '' ? null : Number(priceMax)
    if (min !== null) players = players.filter((p) => p.price >= min)
    if (max !== null) players = players.filter((p) => p.price <= max)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      players = players.filter((p) => p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
    }
    return [...players].sort((a, b) => {
      for (const { field, dir } of sortLevels) {
        const av = fieldValue(a, field)
        const bv = fieldValue(b, field)
        const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
        if (cmp !== 0) return dir === 'desc' ? -cmp : cmp
      }
      return 0
    })
  }, [data, position, team, priceMin, priceMax, search, sortLevels])

  // Available "sort by this specific gameweek's xP" options -- depends on the
  // selected range, so computed fresh rather than a fixed list like the other fields.
  const gwOptions = useMemo(() => {
    const opts: SortField[] = []
    for (let gw = gwStart; gw <= gwEnd; gw++) opts.push(`gw:${gw}` as SortField)
    return opts
  }, [gwStart, gwEnd])
  const allSortFields = ['xP', 'price', 'name', 'valuePerPrice', ...COLUMN_KEYS, ...gwOptions] as SortField[]

  // Clicking a column header: if it's already the primary sort, flip
  // direction; otherwise promote it to primary (desc first), keeping any
  // OTHER existing levels as secondary tiebreakers -- the "Add sort level"
  // builder below still works for adding those tiebreakers explicitly.
  function sortByColumn(field: SortField) {
    setSortLevels((levels) => {
      const isPrimary = levels[0]?.field === field
      const newDir: 'asc' | 'desc' = isPrimary && levels[0].dir === 'desc' ? 'asc' : 'desc'
      const rest = levels.filter((l) => l.field !== field)
      return [{ field, dir: newDir }, ...rest]
    })
  }

  function addSortLevel() {
    const unused = allSortFields.find((f) => !sortLevels.some((l) => l.field === f))
    if (unused) setSortLevels([...sortLevels, { field: unused, dir: 'desc' }])
  }
  function updateSortLevel(i: number, patch: Partial<SortLevel>) {
    setSortLevels(sortLevels.map((l, idx) => (idx === i ? { ...l, ...patch } : l)))
  }
  function removeSortLevel(i: number) {
    setSortLevels(sortLevels.filter((_, idx) => idx !== i))
  }

  if (isLoading) return <div className="p-6 text-slate-500">Loading players...</div>
  if (isError) return <div className="p-6 text-red-600">Failed to load: {(error as Error).message}</div>

  return (
    <div className="p-3 sm:p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Player Scout</h1>
      <p className="text-slate-500 text-sm mb-4">
        Predicted xP for GW{gwStart}{gwEnd !== gwStart ? `-${gwEnd}` : ''} (run #{data?.run_id}) —
        click a row to see exactly where the number comes from.
      </p>

      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">From GW</label>
          <input type="number" min={1} max={38} value={gwStart}
            onChange={(e) => setGwStart(Number(e.target.value))}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16" />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">To GW</label>
          <input type="number" min={1} max={38} value={gwEnd}
            onChange={(e) => setGwEnd(Number(e.target.value))}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16" />
        </div>
      </div>

      <div className="flex gap-3 mb-3 flex-wrap">
        <input
          type="text"
          placeholder="Search player or team..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-slate-300 rounded-md px-3 py-1.5 text-sm flex-1 min-w-[180px]"
        />
        <select
          value={position}
          onChange={(e) => setPosition(e.target.value as Position)}
          className="border border-slate-300 rounded-md px-3 py-1.5 text-sm"
        >
          {(['ALL', 'GK', 'DEF', 'MID', 'FWD'] as Position[]).map((p) => (
            <option key={p} value={p}>{p === 'ALL' ? 'All positions' : p}</option>
          ))}
        </select>
        <select
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          className="border border-slate-300 rounded-md px-3 py-1.5 text-sm"
        >
          <option value="ALL">All teams</option>
          {teams.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <div className="flex items-center gap-1.5">
          <label className="text-sm text-slate-500">£</label>
          <input type="number" step="0.5" placeholder="Min" value={priceMin}
            onChange={(e) => setPriceMin(e.target.value)}
            className="border border-slate-300 rounded-md px-2 py-1.5 text-sm w-20" />
          <span className="text-slate-400">–</span>
          <input type="number" step="0.5" placeholder="Max" value={priceMax}
            onChange={(e) => setPriceMax(e.target.value)}
            className="border border-slate-300 rounded-md px-2 py-1.5 text-sm w-20" />
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="text-xs text-slate-500">Sort priority:</span>
        {sortLevels.map((level, i) => (
          <div key={i} className="flex items-center gap-1 bg-slate-100 rounded-md px-1.5 py-1">
            <span className="text-xs text-slate-400">{i + 1}.</span>
            <select value={level.field} onChange={(e) => updateSortLevel(i, { field: e.target.value as SortField })}
              className="text-xs bg-transparent">
              {(['xP', 'price', 'name', 'valuePerPrice', ...COLUMN_KEYS] as SortField[]).map((f) => (
                <option key={f} value={f}>{sortFieldLabel(f)}</option>
              ))}
              {gwOptions.length > 0 && (
                <optgroup label="Gameweeks">
                  {gwOptions.map((f) => (
                    <option key={f} value={f}>{sortFieldLabel(f)}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <button onClick={() => updateSortLevel(i, { dir: level.dir === 'desc' ? 'asc' : 'desc' })}
              className="text-xs text-slate-500 hover:text-slate-800" aria-label={`Toggle sort direction for level ${i + 1}`}>
              {level.dir === 'desc' ? '↓' : '↑'}
            </button>
            {sortLevels.length > 1 && (
              <button onClick={() => removeSortLevel(i)} aria-label={`Remove sort level ${i + 1}`}
                className="text-slate-400 hover:text-red-600">
                <X size={12} />
              </button>
            )}
          </div>
        ))}
        {sortLevels.length < allSortFields.length && (
          <button onClick={addSortLevel} className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800 px-1.5 py-1">
            <Plus size={12} /> Add sort level
          </button>
        )}
      </div>

      {/* Horizontal scroll on narrow screens rather than squeezing columns --
          this table has a lot of always-visible columns by design (see
          COLUMN_KEYS comment above), so on phone width the right move is a
          swipeable table, not hiding data. */}
      <div className="overflow-x-auto -mx-3 sm:mx-0 px-3 sm:px-0">
      <table className="w-full text-sm border-collapse min-w-[720px]">
        <thead>
          <tr className="text-left text-slate-500 border-b border-slate-200">
            <th className="py-2 pr-3 w-8"></th>
            <SortableHeader field="name" label="Player" sortLevels={sortLevels} onClick={sortByColumn} align="left" />
            <th className="py-2 pr-3">Team</th>
            <th className="py-2 pr-3">Pos</th>
            <SortableHeader field="price" label="Price" sortLevels={sortLevels} onClick={sortByColumn} align="right" />
            <th className="py-2 pr-3">Next {FDR_LOOKAHEAD} GWs (FDR)</th>
            {COLUMN_KEYS.map((key) => (
              <SortableHeader key={key} field={key} label={BREAKDOWN_LABELS[key]} sortLevels={sortLevels} onClick={sortByColumn} align="right" />
            ))}
            <SortableHeader field="xP" label="xP" sortLevels={sortLevels} onClick={sortByColumn} align="right" />
            <SortableHeader field="valuePerPrice" label="Value" sortLevels={sortLevels} onClick={sortByColumn} align="right" />
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <PlayerRow key={p.player_id} player={p}
              fdr={fdrByTeam[p.team] ?? []}
              onClick={() => setSelectedPlayer(p)} />
          ))}
        </tbody>
      </table>
      </div>
      {rows.length === 0 && <p className="text-slate-400 text-sm py-6 text-center">No players match.</p>}
      {selectedPlayer && (
        <PlayerDetailModal
          player={selectedPlayer}
          fixtures={fixturesData?.fixtures ?? []}
          onClose={() => setSelectedPlayer(null)}
        />
      )}
    </div>
  )
}

function SortableHeader({ field, label, sortLevels, onClick, align }: {
  field: SortField
  label: string
  sortLevels: SortLevel[]
  onClick: (field: SortField) => void
  align: 'left' | 'right'
}) {
  const levelIndex = sortLevels.findIndex((l) => l.field === field)
  const isActive = levelIndex !== -1
  return (
    <th className={`py-2 pr-3 ${align === 'right' ? 'text-right' : ''}`}>
      <button onClick={() => onClick(field)}
        className={`flex items-center gap-1 hover:text-slate-900 ${align === 'right' ? 'ml-auto' : ''} ${isActive ? 'text-slate-900 font-medium' : 'text-slate-500'}`}>
        {label}
        {isActive ? (
          <span className="text-[10px]">
            {sortLevels[levelIndex].dir === 'desc' ? '↓' : '↑'}
            {sortLevels.length > 1 && <sup>{levelIndex + 1}</sup>}
          </span>
        ) : (
          <ChevronsUpDown size={11} className="text-slate-300" />
        )}
      </button>
    </th>
  )
}

function PlayerRow({ player, fdr, onClick }: {
  player: Player
  fdr: number[]
  onClick: () => void
}) {
  return (
    <tr onClick={onClick}
        className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer">
      <td className="py-2 pr-3"><PlayerShirt player={player} size={22} /></td>
      <td className="py-2 pr-3 font-medium text-slate-900">{player.name}</td>
      <td className="py-2 pr-3 text-slate-600">{player.team}</td>
      <td className="py-2 pr-3">
        <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
          {player.position}
        </span>
      </td>
      <td className="py-2 pr-3 text-right text-slate-600">£{player.price.toFixed(1)}m</td>
      <td className="py-2 pr-3"><FdrStrip difficulties={fdr} /></td>
      {COLUMN_KEYS.map((key) => {
        const value = player.breakdown?.[key] ?? 0
        return (
          <td key={key} className={`py-2 pr-3 text-right ${value < 0 ? 'text-red-600' : 'text-slate-700'}`}>
            {value.toFixed(2)}
          </td>
        )
      })}
      <td className="py-2 pr-3 text-right font-semibold text-emerald-700">{player.xP.toFixed(2)}</td>
      <td className="py-2 text-right text-slate-600">
        {player.price > 0 ? (player.xP / player.price).toFixed(2) : '—'}
      </td>
    </tr>
  )
}
