import { useMemo, useState } from 'react'
import { ChevronsUpDown, Plus, X, Check } from 'lucide-react'
import { usePlayers, useFixtures } from '../api/hooks'
import PlayerShirt from '../components/PlayerShirt'
import FdrStrip, { buildFdrByTeam } from '../components/FdrStrip'
import PlayerDetailModal from '../components/PlayerDetailModal'
import type { Player, XpBreakdown, OutcomeProbabilities } from '../api/types'

const FDR_PER_ROW = 8 // wrap width for the FDR strip, not a fetch/lookahead limit --
                        // the actual range shown/fetched is whatever GW range is
                        // selected (see gwStart/gwEnd below); a selection wider
                        // than this wraps into multiple rows of FDR_PER_ROW each

type Position = 'ALL' | Player['position']
type SortField = 'xP' | 'price' | 'name' | 'valuePerPrice' | 'fdr' | 'lastSeasonPts' | 'ownership' | 'differential' | keyof XpBreakdown | `gw:${number}`
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
// All four also get a "(likelihood)" suffix from player.prob -- e.g. "2.65
// (0.60)" -- P(>=1 goal/assist/clean sheet/DefCon threshold hit) over the
// selected window (see PlayerRow below).
const COLUMN_KEYS: (keyof XpBreakdown)[] = ['goal_pts', 'assist_pts', 'cs_pts', 'defcon_pts']

// Labels for gw:N fields are computed on the fly (there's no fixed set of them --
// depends on the selected range), so this is a function, not a static Record like before.
function sortFieldLabel(field: SortField): string {
  if (field.startsWith('gw:')) return `GW${field.slice(3)}`
  const labels: Record<'xP' | 'price' | 'name' | 'valuePerPrice' | 'fdr' | 'lastSeasonPts' | 'ownership' | 'differential' | keyof XpBreakdown, string> = {
    xP: 'xP', price: 'Price', name: 'Name', valuePerPrice: 'xP/£m', fdr: 'FDR',
    lastSeasonPts: 'Total pts (last season)', ownership: 'Own %', differential: 'Diff',
    ...BREAKDOWN_LABELS,
  }
  return labels[field as keyof typeof labels]
}

// avgFdrByTeam: mean fixture difficulty over the SELECTED gameweek range
// (gwStart-gwEnd), LOWER = easier fixtures -- see buildFdrByTeam in
// FdrStrip.tsx for how it's derived. A team with no fixture data in the
// range (e.g. a blank across the whole selection) falls back to 3
// (neutral), so it doesn't artificially look like the easiest OR hardest
// run when sorted.
function fieldValue(p: Player, field: SortField, avgFdrByTeam: Record<string, number>): number | string {
  if (field === 'name') return p.name
  if (field === 'xP' || field === 'price') return p[field]
  if (field === 'valuePerPrice') return p.price > 0 ? p.xP / p.price : 0
  if (field === 'fdr') return avgFdrByTeam[p.team] ?? 3
  if (field === 'lastSeasonPts') return p.last_season_total_points ?? 0
  if (field === 'ownership') return p.ownership_pct ?? 0
  if (field === 'differential') return p.differential ?? p.xP
  if (field.startsWith('gw:')) {
    const gw = Number(field.slice(3))
    return p.gameweeks?.find((g) => g.gw === gw)?.xP ?? 0
  }
  return p.breakdown?.[field as keyof XpBreakdown] ?? 0
}

export default function PlayerScout() {
  const [gwStart, setGwStart] = useState(1)
  const [gwEnd, setGwEnd] = useState(1)
  // Local DRAFT values for the two GW inputs, decoupled from gwStart/gwEnd
  // above (which are what actually drives the fetch). Every fetch here can
  // genuinely take a few real seconds -- see backend/app/routers/players.py's
  // caching comments -- so updating on every keystroke/arrow-click, the
  // previous behavior, meant typing "12" into a field fired a slow request
  // for "1" and then immediately another for "12". Standard pattern for a
  // range filter backing an expensive fetch (see e.g. any e-commerce price
  // filter): edit freely, commit explicitly -- Enter or the Apply button --
  // rather than firing on every intermediate keystroke.
  const [draftGwStart, setDraftGwStart] = useState(1)
  const [draftGwEnd, setDraftGwEnd] = useState(1)
  const hasPendingGwChange = draftGwStart !== gwStart || draftGwEnd !== gwEnd

  function applyGwRange() {
    setGwStart(draftGwStart)
    setGwEnd(draftGwEnd)
  }
  function handleGwKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') applyGwRange()
  }

  const [position, setPosition] = useState<Position>('ALL')
  const [team, setTeam] = useState<string>('ALL')
  const [priceMin, setPriceMin] = useState<string>('')
  const [priceMax, setPriceMax] = useState<string>('')
  const [search, setSearch] = useState('')
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null)
  const [sortLevels, setSortLevels] = useState<SortLevel[]>([{ field: 'xP', dir: 'desc' }])

  const { data, isLoading, isError, error } = usePlayers(gwStart, gwEnd)
  // Exactly the SELECTED range now, not a fixed 8-gw lookahead independent of
  // it -- the FDR column shows/sorts by whichever gameweeks are actually
  // chosen, wrapping into rows of FDR_PER_ROW if that's a wide range (see
  // FdrStrip.tsx).
  const { data: fixturesData } = useFixtures(undefined, gwStart, gwEnd)
  const fdrByTeam = useMemo(
    () => buildFdrByTeam(fixturesData?.fixtures ?? []),
    [fixturesData]
  )
  const avgFdrByTeam = useMemo(() => {
    const out: Record<string, number> = {}
    for (const [t, difficulties] of Object.entries(fdrByTeam)) {
      if (difficulties.length > 0) out[t] = difficulties.reduce((s, d) => s + d, 0) / difficulties.length
    }
    return out
  }, [fdrByTeam])

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
        const av = fieldValue(a, field, avgFdrByTeam)
        const bv = fieldValue(b, field, avgFdrByTeam)
        const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
        if (cmp !== 0) return dir === 'desc' ? -cmp : cmp
      }
      return 0
    })
  }, [data, position, team, priceMin, priceMax, search, sortLevels, avgFdrByTeam])

  // Available "sort by this specific gameweek's xP" options -- depends on the
  // selected range, so computed fresh rather than a fixed list like the other fields.
  const gwOptions = useMemo(() => {
    const opts: SortField[] = []
    for (let gw = gwStart; gw <= gwEnd; gw++) opts.push(`gw:${gw}` as SortField)
    return opts
  }, [gwStart, gwEnd])
  const allSortFields = ['xP', 'price', 'name', 'valuePerPrice', 'fdr', 'lastSeasonPts', 'ownership', 'differential', ...COLUMN_KEYS, ...gwOptions] as SortField[]

  // Clicking a column header:
  // - If it's a genuinely NEW sort dimension (not currently active at any
  //   rank), start FRESH with just this one field as the sole sort --
  //   clearing whatever was there before, rather than silently piling it on
  //   top. Piling on was the root cause of a real bug: click one header,
  //   then build a SECOND level via the dropdown below -- the leftover
  //   PREVIOUS primary was still lurking as an invisible tiebreaker ahead of
  //   the level just built. Since most numeric fields (xP, price) are
  //   near-continuous across ~500+ real players, that leftover level
  //   silently resolved almost every tie by itself, so the deliberately-
  //   configured second factor never actually got reached in practice.
  //   Multi-level sorting is still fully available via "+ Add sort level"
  //   below, just opt-in instead of automatic.
  // - If it's ALREADY an active level -- primary OR secondary -- just flip
  //   ITS OWN direction in place, at its EXISTING rank, rather than
  //   promoting it to primary (a separate bug: that also silently discarded
  //   any tiebreaker order already set up via the dropdown below).
  function sortByColumn(field: SortField) {
    setSortLevels((levels) => {
      const idx = levels.findIndex((l) => l.field === field)
      if (idx === -1) {
        const dir: 'asc' | 'desc' = field === 'fdr' ? 'asc' : 'desc'
        return [{ field, dir }]
      }
      return levels.map((l, i) => (i === idx ? { ...l, dir: l.dir === 'desc' ? 'asc' : 'desc' } : l))
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
          <input type="number" min={1} max={38} value={draftGwStart}
            onChange={(e) => setDraftGwStart(Number(e.target.value))}
            onKeyDown={handleGwKeyDown}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">To GW</label>
          <input type="number" min={1} max={38} value={draftGwEnd}
            onChange={(e) => setDraftGwEnd(Number(e.target.value))}
            onKeyDown={handleGwKeyDown}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" />
        </div>
        {/* Only lit up emerald once there's something to actually apply --
            otherwise a plain, unobtrusive button, so it doesn't look like a
            constant demand for action when the range already matches what's
            loaded. Pressing Enter in either field above does the same thing. */}
        <button onClick={applyGwRange} disabled={!hasPendingGwChange}
          className={`flex items-center gap-1 text-sm font-medium px-3 py-1 rounded-md border ${
            hasPendingGwChange
              ? 'bg-emerald-600 border-emerald-600 text-white hover:bg-emerald-700'
              : 'bg-slate-50 border-slate-200 text-slate-300 cursor-default'
          }`}>
          <Check size={14} /> Apply
        </button>
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
              {(['xP', 'price', 'name', 'valuePerPrice', 'fdr', 'lastSeasonPts', 'ownership', 'differential', ...COLUMN_KEYS] as SortField[]).map((f) => (
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
      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden min-w-[720px]">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="py-2 pr-3 pl-3 w-8"></th>
            <SortableHeader field="name" label="Player" sortLevels={sortLevels} onClick={sortByColumn} align="left" />
            <th className="py-2 pr-3">Team</th>
            <th className="py-2 pr-3">Pos</th>
            <SortableHeader field="price" label="Price" sortLevels={sortLevels} onClick={sortByColumn} align="right" />
            {/* xP leads the numeric columns -- the whole page's reason to exist,
                so it sits right where you land, no scrolling needed, and reads
                visually heavier than everything after it (see the emphasize
                prop + the matching td below). Value stays immediately next to
                it (it's literally derived from xP) but deliberately plain --
                one clear focal column reads better than two competing ones. */}
            <SortableHeader field="xP" label="xP" sortLevels={sortLevels} onClick={sortByColumn} align="right" emphasize />
            <SortableHeader field="valuePerPrice" label="xP/£m" sortLevels={sortLevels} onClick={sortByColumn} align="right" />
            <SortableHeader field="lastSeasonPts" label="Total pts (last season)" sortLevels={sortLevels} onClick={sortByColumn} align="right" muted />
            {/* Ownership + differential -- FPL is a relative game (rank vs
                other managers), so these sit right after the "how good is
                this pick" cluster: a high-xP player everyone owns is worth
                less strategically than an equally-good, low-owned one. */}
            <SortableHeader field="ownership" label="Own %" sortLevels={sortLevels} onClick={sortByColumn} align="right" muted />
            <SortableHeader field="differential" label="Diff" sortLevels={sortLevels} onClick={sortByColumn} align="right" muted />
            <SortableHeader field="fdr" label={`GW${gwStart}${gwEnd !== gwStart ? `-${gwEnd}` : ''} (FDR)`} sortLevels={sortLevels} onClick={sortByColumn} align="left" />
            {COLUMN_KEYS.map((key) => (
              <SortableHeader key={key} field={key} label={BREAKDOWN_LABELS[key]} sortLevels={sortLevels} onClick={sortByColumn} align="right" muted />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <PlayerRow key={p.player_id} player={p} index={i}
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

function SortableHeader({ field, label, sortLevels, onClick, align, emphasize, muted }: {
  field: SortField
  label: string
  sortLevels: SortLevel[]
  onClick: (field: SortField) => void
  align: 'left' | 'right'
  emphasize?: boolean
  muted?: boolean
}) {
  const levelIndex = sortLevels.findIndex((l) => l.field === field)
  const isActive = levelIndex !== -1
  return (
    <th className={`py-2 pr-3 ${align === 'right' ? 'text-right' : ''} ${emphasize ? 'bg-emerald-50/60' : ''}`}>
      <button onClick={() => onClick(field)}
        className={`flex items-center gap-1 ${align === 'right' ? 'ml-auto' : ''} ${
          emphasize
            ? 'text-emerald-800 font-bold text-sm hover:text-emerald-900'
            : isActive
              ? `${muted ? 'text-slate-500' : 'text-slate-900'} font-medium hover:text-slate-900`
              : `${muted ? 'text-slate-400' : 'text-slate-500'} hover:text-slate-900`
        }`}>
        {label}
        {isActive ? (
          <span className="text-[10px]">
            {sortLevels[levelIndex].dir === 'desc' ? '↓' : '↑'}
            {sortLevels.length > 1 && <sup>{levelIndex + 1}</sup>}
          </span>
        ) : (
          <ChevronsUpDown size={11} className={emphasize ? 'text-emerald-300' : 'text-slate-300'} />
        )}
      </button>
    </th>
  )
}

function PlayerRow({ player, fdr, onClick, index }: {
  player: Player
  fdr: number[]
  onClick: () => void
  index: number
}) {
  return (
    <tr onClick={onClick}
        className={`border-t border-slate-100 hover:bg-slate-100 cursor-pointer ${index % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
      <td className="py-2 pr-3 pl-3"><PlayerShirt player={player} size={22} /></td>
      <td className="py-2 pr-3 font-medium text-slate-900">{player.name}</td>
      <td className="py-2 pr-3 text-slate-600">{player.team}</td>
      <td className="py-2 pr-3">
        <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
          {player.position}
        </span>
      </td>
      <td className="py-2 pr-3 text-right text-slate-600">£{player.price.toFixed(1)}m</td>
      {/* The focal number on this whole page -- bigger, bolder, and set
          against a tinted background so it reads as THE answer, not just
          another column, and doesn't require scrolling to reach. */}
      <td className="py-2 pr-3 text-right bg-emerald-50/60">
        <span className="inline-block px-2.5 py-1 rounded-md bg-emerald-100 text-emerald-800 font-bold text-base">
          {player.xP.toFixed(2)}
        </span>
      </td>
      <td className="py-2 pr-3 text-right text-slate-600">
        {player.price > 0 ? (player.xP / player.price).toFixed(2) : '—'}
      </td>
      <td className="py-2 pr-3 text-right text-slate-500">
        {player.last_season_total_points ?? 0}
      </td>
      <td className="py-2 pr-3 text-right text-slate-500">
        {player.ownership_pct != null ? `${player.ownership_pct.toFixed(1)}%` : '—'}
      </td>
      <td className="py-2 pr-3 text-right text-slate-500">
        {(player.differential ?? player.xP).toFixed(2)}
      </td>
      <td className="py-2 pr-3"><FdrStrip difficulties={fdr} perRow={FDR_PER_ROW} /></td>
      {COLUMN_KEYS.map((key) => {
        const value = player.breakdown?.[key] ?? 0
        // COLUMN_KEYS is always exactly the 4 keys OutcomeProbabilities has
        // (goal_pts/assist_pts/cs_pts/defcon_pts) -- a subset of the full
        // 10-key XpBreakdown -- so this cast is safe, just not something
        // plain structural typing can verify on its own from `key`'s wider
        // (keyof XpBreakdown) type.
        const prob = player.prob?.[key as keyof OutcomeProbabilities]
        return (
          <td key={key} className={`py-2 pr-3 text-right ${value < 0 ? 'text-red-600' : 'text-slate-400'}`}>
            {value.toFixed(2)}
            {prob != null && <span className="text-slate-300"> ({prob.toFixed(2)})</span>}
          </td>
        )
      })}
    </tr>
  )
}
