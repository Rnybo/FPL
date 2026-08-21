import { useMemo, useState } from 'react'
import { ChevronsUpDown, HelpCircle } from 'lucide-react'
import { usePerformance, usePlayers, useFixtures } from '../api/hooks'
import PlayerShirt from '../components/PlayerShirt'
import PlayerStatusTag from '../components/PlayerStatusTag'
import SetPieceTags from '../components/SetPieceTags'
import PlayerDetailModal from '../components/PlayerDetailModal'
import type { PlayerPerformance as PlayerPerf, PerformanceSeasonStats, Player } from '../api/types'

type Position = 'ALL' | 'GK' | 'DEF' | 'MID' | 'FWD'
type SeasonKey = 'last' | 'current' | 'sustained'
type Basis = 'total' | 'per90'
type SortField =
  | 'name' | 'team' | 'price' | 'ownership' | 'minutes'
  | 'goals' | 'xg' | 'goalsDelta'
  | 'assists' | 'xa' | 'assistsDelta'
  | 'gi' | 'xgi' | 'giDelta'
  | 'defcon' | 'bonus' | 'bps' | 'ict' | 'influence' | 'creativity' | 'threat'

// Every stat that has a "total this season" AND a "per-90 rate" flavor --
// lets the Total/Per-90 toggle swap ALL of these columns at once from one
// place, rather than branching in every single cell.
const DUAL_STATS: Record<string, { total: keyof PerformanceSeasonStats; per90: keyof PerformanceSeasonStats }> = {
  goals: { total: 'goals', per90: 'goals_per90' },
  xg: { total: 'xg', per90: 'xg_per90' },
  goalsDelta: { total: 'goals_minus_xg', per90: 'goals_minus_xg_per90' },
  assists: { total: 'assists', per90: 'assists_per90' },
  xa: { total: 'xa', per90: 'xa_per90' },
  assistsDelta: { total: 'assists_minus_xa', per90: 'assists_minus_xa_per90' },
  gi: { total: 'gi', per90: 'gi_per90' },
  xgi: { total: 'xgi', per90: 'xgi_per90' },
  giDelta: { total: 'gi_minus_xgi', per90: 'gi_minus_xgi_per90' },
  defcon: { total: 'defensive_contribution', per90: 'defensive_contribution_per90' },
  bonus: { total: 'bonus', per90: 'bonus_per90' },
  bps: { total: 'bps', per90: 'bps_per90' },
  ict: { total: 'ict_index', per90: 'ict_index_per90' },
  influence: { total: 'influence', per90: 'influence_per90' },
  creativity: { total: 'creativity', per90: 'creativity_per90' },
  threat: { total: 'threat', per90: 'threat_per90' },
}

// Each help-icon tooltip, in one place so headers stay short. Only applied
// to the analytical stats -- Player/Team/Pos/Price are self-explanatory.
const STAT_HELP: Record<string, string> = {
  ownership: 'Percentage of FPL managers who currently own this player.',
  minutes: 'Total minutes played -- more minutes means a more reliable sample for the rate stats alongside it.',
  goals: 'Goals actually scored.',
  xg: 'Expected Goals -- the likelihood of scoring based on shot quality and quantity, excluding penalty/rebound luck. Shows whether a goal return is sustainable.',
  goalsDelta: 'Goals minus xG. Positive = finishing above expectation (may regress); negative = below expectation (may improve).',
  assists: 'Assists actually recorded.',
  xa: 'Expected Assists -- the likelihood a pass leads to a goal, based on the quality of chances created.',
  assistsDelta: 'Assists minus xA. Positive = over-performing as a creator; negative = under-performing.',
  gi: 'Goal Involvements -- goals plus assists.',
  xgi: 'Expected Goal Involvements -- xG plus xA.',
  giDelta: 'Goal Involvements minus xGI -- the headline over-/under-performance number, combining finishing and creating.',
  defcon: 'Defensive Contribution -- clearances/blocks/interceptions/tackles for defenders (plus recoveries for MID/FWD). Counts toward FPL\u2019s DefCon bonus points.',
  bonus: 'Total FPL bonus points awarded.',
  bps: 'Bonus Points System score -- the underlying match rating FPL uses to award bonus points.',
  ict: 'ICT Index -- FPL\u2019s combined Influence + Creativity + Threat score, used to help spot in-form players.',
  influence: 'How much a player has affected a single match, via goals, assists, defensive actions and more.',
  creativity: 'How much a player creates goalscoring chances for teammates.',
  threat: 'How likely a player is to score, based on shots, positioning and attacking involvement.',
}

function ordinal(n: number): string {
  const v = n % 100
  if (v >= 11 && v <= 13) return `${n}th`
  switch (n % 10) {
    case 1: return `${n}st`
    case 2: return `${n}nd`
    case 3: return `${n}rd`
    default: return `${n}th`
  }
}

// Rank fields are always computed on the PER-90 rate server-side (fairer
// across different playing time -- see performance.py's _add_ranks
// docstring), regardless of whether the Total/Per-90 toggle is showing
// totals right now -- the tooltip says so explicitly.
function getRank(stats: PerformanceSeasonStats | null, field: SortField): { overall: number | null; position: number | null } | null {
  if (!stats) return null
  switch (field) {
    case 'goalsDelta': return { overall: stats.goals_minus_xg_per90_rank_overall, position: stats.goals_minus_xg_per90_rank_position }
    case 'assistsDelta': return { overall: stats.assists_minus_xa_per90_rank_overall, position: stats.assists_minus_xa_per90_rank_position }
    case 'giDelta': return { overall: stats.gi_minus_xgi_per90_rank_overall, position: stats.gi_minus_xgi_per90_rank_position }
    case 'ict': return { overall: stats.ict_index_per90_rank_overall, position: stats.ict_index_per90_rank_position }
    case 'influence': return { overall: stats.influence_per90_rank_overall, position: stats.influence_per90_rank_position }
    case 'creativity': return { overall: stats.creativity_per90_rank_overall, position: stats.creativity_per90_rank_position }
    case 'threat': return { overall: stats.threat_per90_rank_overall, position: stats.threat_per90_rank_position }
    default: return null
  }
}

function statsFor(p: PlayerPerf, season: SeasonKey): PerformanceSeasonStats | null {
  if (season === 'last') return p.last_season
  if (season === 'current') return p.current_season
  return p.sustained
}

function fieldValue(p: PlayerPerf, season: SeasonKey, field: SortField, basis: Basis): number | string {
  if (field === 'name') return p.name
  if (field === 'team') return p.team
  if (field === 'price') return p.price
  if (field === 'ownership') return p.ownership_pct ?? -1
  const stats = statsFor(p, season)
  if (field === 'minutes') return stats?.minutes ?? -1
  const dual = DUAL_STATS[field]
  if (dual && stats) {
    const key = basis === 'total' ? dual.total : dual.per90
    const v = stats[key]
    return typeof v === 'number' ? v : -Infinity
  }
  return -Infinity
}

function colorForDelta(v: number | null | undefined): string {
  if (v == null) return 'text-slate-300'
  if (v > 0) return 'text-emerald-700'
  if (v < 0) return 'text-red-600'
  return 'text-slate-500'
}

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null) return '\u2014'
  return v.toFixed(digits)
}

export default function PlayerPerformance() {
  const { data, isLoading, isError, error } = usePerformance()
  // Full projection data (xP, breakdown, fixtures history) purely to power
  // the shirt icon + detail modal, matching Player Scout's exact click
  // experience -- /api/performance itself stays lean (no xP model coupling).
  const { data: playersData } = usePlayers()
  const { data: fixturesData } = useFixtures()
  const playerById = useMemo(
    () => new Map((playersData?.players ?? []).map((p) => [p.player_id, p])),
    [playersData]
  )
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null)
  const [season, setSeason] = useState<SeasonKey>('last')
  const [basis, setBasis] = useState<Basis>('per90')
  const [position, setPosition] = useState<Position>('ALL')
  const [team, setTeam] = useState('ALL')
  const [search, setSearch] = useState('')
  // Default excludes small-sample noise (a 20-minute cameo can show a wild
  // per-90 rate) -- 450 mins is the common "5 full matches" convention FPL
  // analysts use for rate stats to mean something. Fully overridable.
  const [minMinutes, setMinMinutes] = useState('450')
  const [sortField, setSortField] = useState<SortField>('giDelta')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  // "Leaders" is a separate board (grouped by price bracket, à la the
  // community "DEFCON Leaders" tables) rather than another sortable column
  // in the main table -- it needs its own layout, so it's a whole
  // alternate view of the same filtered player pool, not a table variant.
  const [viewMode, setViewMode] = useState<'table' | 'leaders'>('table')

  const teams = useMemo(() => [...new Set((data?.players ?? []).map((p) => p.team))].sort(), [data])

  // Shared by both views -- search/team/min-minutes apply the same way
  // whether you're looking at the sortable table or the Leaders board.
  // Position is deliberately NOT applied here: the table wants exactly the
  // selected position (or everyone), but Leaders always groups by position
  // internally (one board per position, or all four when "ALL" is picked),
  // so it needs the pre-position-filter pool to do that grouping itself.
  const filteredPlayers = useMemo(() => {
    if (!data) return []
    let players = data.players
    if (team !== 'ALL') players = players.filter((p) => p.team === team)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      players = players.filter((p) => p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
    }
    const min = minMinutes === '' ? null : Number(minMinutes)
    if (min !== null) {
      players = players.filter((p) => (statsFor(p, season)?.minutes ?? 0) >= min)
    }
    return players
  }, [data, team, search, minMinutes, season])

  const rows = useMemo(() => {
    let players = filteredPlayers
    if (position !== 'ALL') players = players.filter((p) => p.position === position)
    return [...players].sort((a, b) => {
      const av = fieldValue(a, season, sortField, basis)
      const bv = fieldValue(b, season, sortField, basis)
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
      return sortDir === 'desc' ? -cmp : cmp
    })
  }, [filteredPlayers, position, season, sortField, basis, sortDir])

  function sortByColumn(field: SortField) {
    if (field === sortField) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortField(field)
      setSortDir(field === 'name' || field === 'team' ? 'asc' : 'desc')
    }
  }

  if (isLoading) return <div className="p-6 text-slate-500">Loading performance data...</div>
  if (isError) return <div className="p-6 text-red-600">Failed to load: {(error as Error).message}</div>

  const seasonId = season === 'last' ? data?.last_season_id : data?.current_season_id
  const seasonHasAnyData = rows.some((p) => statsFor(p, season) != null)

  return (
    <div className="p-3 sm:p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Player Performance</h1>
      <p className="text-slate-500 text-sm mb-4">
        Actual output vs. underlying expected stats -- spot who's over- or under-performing their numbers.
      </p>

      <div className="flex items-center gap-4 mb-3 flex-wrap">
        {/* Season -- underline-tab style, matching PlayerDetailModal's view switch */}
        <div className="flex gap-4 border-b border-slate-200">
          <button onClick={() => setSeason('last')}
            className={`text-sm font-semibold pb-2 border-b-2 -mb-px ${season === 'last' ? 'border-emerald-600 text-emerald-700' : 'border-transparent text-slate-400 hover:text-slate-600'}`}>
            Last season {data ? `(${data.last_season_id})` : ''}
          </button>
          <button onClick={() => setSeason('current')}
            className={`text-sm font-semibold pb-2 border-b-2 -mb-px ${season === 'current' ? 'border-emerald-600 text-emerald-700' : 'border-transparent text-slate-400 hover:text-slate-600'}`}>
            This season {data ? `(${data.current_season_id})` : ''}
          </button>
          <button onClick={() => setSeason('sustained')}
            className={`text-sm font-semibold pb-2 border-b-2 -mb-px ${season === 'sustained' ? 'border-emerald-600 text-emerald-700' : 'border-transparent text-slate-400 hover:text-slate-600'}`}>
            Sustained ({data ? `${data.sustained_min_seasons}+` : '2+'} seasons)
          </button>
        </div>

        {/* Table / Leaders -- which board shape, independent of season */}
        <div className="flex rounded-md border border-slate-300 overflow-hidden text-xs">
          <button onClick={() => setViewMode('table')}
            className={`px-2.5 py-1.5 font-medium ${viewMode === 'table' ? 'bg-emerald-600 text-white' : 'bg-white text-slate-500 hover:bg-slate-50'}`}>
            Table
          </button>
          <button onClick={() => setViewMode('leaders')}
            className={`px-2.5 py-1.5 font-medium border-l border-slate-300 ${viewMode === 'leaders' ? 'bg-emerald-600 text-white' : 'bg-white text-slate-500 hover:bg-slate-50'}`}>
            Leaders
          </button>
        </div>

        {/* Total / Per-90 -- only meaningful for the sortable table; the
            Leaders board always shows season totals (starts, hit rate,
            goals, etc.), same convention as the reference community
            "DEFCON Leaders" tables it's modeled on. */}
        {viewMode === 'table' && (
        <div className="flex rounded-md border border-slate-300 overflow-hidden text-xs">
          <button onClick={() => setBasis('total')}
            className={`px-2.5 py-1.5 font-medium ${basis === 'total' ? 'bg-emerald-600 text-white' : 'bg-white text-slate-500 hover:bg-slate-50'}`}>
            Season total
          </button>
          <button onClick={() => setBasis('per90')}
            className={`px-2.5 py-1.5 font-medium border-l border-slate-300 ${basis === 'per90' ? 'bg-emerald-600 text-white' : 'bg-white text-slate-500 hover:bg-slate-50'}`}>
            Per 90
          </button>
        </div>
        )}
      </div>

      <div className="flex gap-3 mb-4 flex-wrap">
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
          {teams.map((t) => (<option key={t} value={t}>{t}</option>))}
        </select>
        <div className="flex items-center gap-1.5">
          <label className="text-sm text-slate-500">Min mins</label>
          <input type="number" step="90" min="0" value={minMinutes}
            onChange={(e) => setMinMinutes(e.target.value)}
            className="border border-slate-300 rounded-md px-2 py-1.5 text-sm w-20" />
        </div>
      </div>

      {season === 'sustained' && data && (
        <p className="text-sm text-slate-500 bg-slate-100 border border-slate-200 rounded-md px-3 py-2 mb-4">
          Sums each player's totals across every season (of {data.sustained_seasons_available[0]}{'\u2013'}{data.sustained_seasons_available[data.sustained_seasons_available.length - 1]}) where they cleared {data.sustained_min_minutes_per_season} minutes,
          {' '}and only shows a number once they have at least {data.sustained_min_seasons} such seasons -- filters out a single lucky or unlucky
          {' '}season of over-/under-performance variance. Hover the season count for exactly which seasons counted.
        </p>
      )}

      {season !== 'sustained' && !seasonHasAnyData && (
        <p className="text-sm text-slate-500 bg-slate-100 border border-slate-200 rounded-md px-3 py-2 mb-4">
          No gameweeks have been played yet for {seasonId} -- this view fills in automatically once the season gets underway.
        </p>
      )}

      {viewMode === 'table' && (
      <>
      {/* Table is wider than the page (min-w-1400px) -- this hint plus the
          sticky player column and edge fade below make the horizontal scroll
          discoverable instead of the table just looking "cut off". */}
      <p className="text-xs text-slate-400 mb-1.5 flex items-center gap-1">
        Scroll sideways to see all columns <span aria-hidden>→</span>
      </p>
      <div className="relative">
        <div className="overflow-x-auto -mx-3 sm:mx-0 px-3 sm:px-0">
        <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden min-w-[1400px]">
          <thead>
            <tr className="bg-slate-100 text-left text-slate-500">
              <Th field="name" label="Player" align="left" sortField={sortField} sortDir={sortDir} onClick={sortByColumn} sticky />
              <th className="py-2 pr-3">Team</th>
              <th className="py-2 pr-3">Pos</th>
              <Th field="price" label="£" align="right" sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="ownership" label="Own %" align="right" help={STAT_HELP.ownership} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              {season === 'sustained' && <th className="py-2 pr-3 text-right">Szns</th>}
              <Th field="minutes" label="Mins" align="right" help={STAT_HELP.minutes} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="goals" label="Goals" align="right" help={STAT_HELP.goals} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="xg" label="xG" align="right" help={STAT_HELP.xg} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="goalsDelta" label="G-xG" align="right" help={STAT_HELP.goalsDelta} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} emphasize />
              <Th field="assists" label="Assists" align="right" help={STAT_HELP.assists} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="xa" label="xA" align="right" help={STAT_HELP.xa} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="assistsDelta" label="A-xA" align="right" help={STAT_HELP.assistsDelta} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} emphasize />
              <Th field="gi" label="GI" align="right" help={STAT_HELP.gi} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="xgi" label="xGI" align="right" help={STAT_HELP.xgi} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="giDelta" label="GI-xGI" align="right" help={STAT_HELP.giDelta} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} emphasize />
              <Th field="defcon" label="DefCon" align="right" help={STAT_HELP.defcon} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="bonus" label="Bonus" align="right" help={STAT_HELP.bonus} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="bps" label="BPS" align="right" help={STAT_HELP.bps} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="ict" label="ICT" align="right" help={STAT_HELP.ict} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="influence" label="Infl" align="right" help={STAT_HELP.influence} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="creativity" label="Crea" align="right" help={STAT_HELP.creativity} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
              <Th field="threat" label="Threat" align="right" help={STAT_HELP.threat} sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <PerformanceRow key={p.player_id} player={p} season={season} basis={basis} index={i}
                shirtPlayer={playerById.get(p.player_id)}
                onClick={() => {
                  const full = playerById.get(p.player_id)
                  if (full) setSelectedPlayer(full)
                }} />
            ))}
          </tbody>
        </table>
        </div>
        {/* Right-edge fade -- signals there are more columns off-screen */}
        <div className="pointer-events-none absolute top-0 right-0 bottom-0 w-6 bg-gradient-to-l from-slate-50 to-transparent" />
      </div>
      {rows.length === 0 && <p className="text-slate-400 text-sm py-6 text-center">No players match.</p>}
      </>
      )}

      {viewMode === 'leaders' && (
        <LeadersBoard players={filteredPlayers} season={season} position={position}
          playerById={playerById} onSelectPlayer={setSelectedPlayer} />
      )}

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

function Th({ field, label, align, help, sortField, sortDir, onClick, emphasize, sticky }: {
  field: SortField
  label: string
  align: 'left' | 'right'
  help?: string
  sortField: SortField
  sortDir: 'asc' | 'desc'
  onClick: (field: SortField) => void
  emphasize?: boolean
  sticky?: boolean
}) {
  const isActive = field === sortField
  return (
    <th className={`py-2 pr-3 ${align === 'right' ? 'text-right' : ''} ${emphasize ? 'bg-emerald-50/60' : ''} ${sticky ? 'sticky left-0 z-20 bg-slate-100 pl-3 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.15)]' : ''}`}>
      <div className={`flex items-center gap-1 ${align === 'right' ? 'justify-end' : ''}`}>
        <button onClick={() => onClick(field)}
          className={`flex items-center gap-1 ${
            emphasize
              ? 'text-emerald-800 font-bold hover:text-emerald-900'
              : isActive
                ? 'text-slate-900 font-medium hover:text-slate-900'
                : 'text-slate-500 hover:text-slate-900'
          }`}>
          {label}
          {isActive ? (
            <span className="text-[10px]">{sortDir === 'desc' ? '\u2193' : '\u2191'}</span>
          ) : (
            <ChevronsUpDown size={11} className="text-slate-300" />
          )}
        </button>
        {help && (
          // title on a wrapping <span>, not on <HelpCircle> itself -- lucide
          // icons render as an inline <svg>, and most browsers (Chrome
          // included) don't fire the native hover tooltip from a `title`
          // attribute set directly on a root <svg> element. It needs to sit
          // on an ordinary HTML element instead.
          <span title={help} className="shrink-0 cursor-help">
            <HelpCircle size={12} className="text-slate-300 hover:text-slate-500" />
          </span>
        )}
      </div>
    </th>
  )
}

function DeltaCell({ stats, field, basis, position }: {
  stats: PerformanceSeasonStats | null
  field: SortField
  basis: Basis
  position: string
}) {
  const dual = DUAL_STATS[field]
  const value = stats ? (stats[basis === 'total' ? dual.total : dual.per90] as number | null) : null
  const rank = getRank(stats, field)
  const digits = basis === 'total' ? 1 : 2
  const rankText = rank && rank.overall != null
    ? `Rank ${ordinal(rank.overall)} overall${rank.position != null ? ` \u00b7 ${ordinal(rank.position)} among ${position}` : ''} (by per-90 rate)`
    : 'Not enough minutes to rank'
  return (
    <td className={`py-2 pr-3 text-right font-semibold bg-emerald-50/30 ${colorForDelta(value)}`}
        title={rankText}>
      {value != null ? `${value > 0 ? '+' : ''}${value.toFixed(digits)}` : '\u2014'}
    </td>
  )
}

function StatCell({ stats, field, basis }: { stats: PerformanceSeasonStats | null; field: SortField; basis: Basis }) {
  const dual = DUAL_STATS[field]
  const value = stats ? (stats[basis === 'total' ? dual.total : dual.per90] as number | null) : null
  const digits = basis === 'total' ? (field === 'bps' || field === 'ict' || field === 'influence' || field === 'creativity' || field === 'threat' || field === 'bonus' || field === 'goals' || field === 'assists' || field === 'gi' || field === 'defcon' ? 0 : 2) : 2
  return <td className="py-2 pr-3 text-right text-slate-600">{fmt(value, digits)}</td>
}

function ICTCell({ stats, field, basis, position }: {
  stats: PerformanceSeasonStats | null
  field: SortField
  basis: Basis
  position: string
}) {
  const dual = DUAL_STATS[field]
  const value = stats ? (stats[basis === 'total' ? dual.total : dual.per90] as number | null) : null
  const rank = getRank(stats, field)
  const rankText = rank && rank.overall != null
    ? `Rank ${ordinal(rank.overall)} overall \u00b7 ${ordinal(rank.position ?? 0)} among ${position} (by per-90 rate)`
    : 'Not enough minutes to rank'
  return (
    <td className="py-2 pr-3 text-right text-slate-600" title={rankText}>
      {fmt(value, basis === 'total' ? 0 : 2)}
    </td>
  )
}

function PerformanceRow({ player, season, basis, index, shirtPlayer, onClick }: {
  player: PlayerPerf
  season: SeasonKey
  basis: Basis
  index: number
  shirtPlayer?: Player
  onClick?: () => void
}) {
  const stats = statsFor(player, season)
  return (
    <tr onClick={onClick}
        className={`border-t border-slate-100 hover:bg-slate-100 ${onClick ? 'cursor-pointer' : ''} ${index % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
      <td className={`py-2 pr-3 pl-3 font-medium text-slate-900 sticky left-0 z-10 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.15)] ${index % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
        <span className="inline-flex items-center gap-1.5">
          {shirtPlayer && <PlayerShirt player={shirtPlayer} size={20} />}
          {player.name}
        </span>
        <PlayerStatusTag player={player} />
        <SetPieceTags roles={player.set_piece_roles} />
      </td>
      <td className="py-2 pr-3 text-slate-600">{player.team}</td>
      <td className="py-2 pr-3">
        <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
          {player.position}
        </span>
      </td>
      <td className="py-2 pr-3 text-right text-slate-600">£{player.price.toFixed(1)}m</td>
      <td className="py-2 pr-3 text-right text-slate-500">{player.ownership_pct != null ? `${player.ownership_pct.toFixed(1)}%` : '\u2014'}</td>
      {season === 'sustained' && (
        <td className="py-2 pr-3 text-right text-slate-500"
            title={stats?.seasons_included ? `Seasons counted: ${stats.seasons_included.join(', ')}` : 'Not enough qualifying seasons'}>
          {stats?.qualifying_seasons ?? '\u2014'}
        </td>
      )}
      <td className="py-2 pr-3 text-right text-slate-500">{stats?.minutes ?? '\u2014'}</td>
      <StatCell stats={stats} field="goals" basis={basis} />
      <StatCell stats={stats} field="xg" basis={basis} />
      <DeltaCell stats={stats} field="goalsDelta" basis={basis} position={player.position} />
      <StatCell stats={stats} field="assists" basis={basis} />
      <StatCell stats={stats} field="xa" basis={basis} />
      <DeltaCell stats={stats} field="assistsDelta" basis={basis} position={player.position} />
      <StatCell stats={stats} field="gi" basis={basis} />
      <StatCell stats={stats} field="xgi" basis={basis} />
      <DeltaCell stats={stats} field="giDelta" basis={basis} position={player.position} />
      <StatCell stats={stats} field="defcon" basis={basis} />
      <StatCell stats={stats} field="bonus" basis={basis} />
      <StatCell stats={stats} field="bps" basis={basis} />
      <ICTCell stats={stats} field="ict" basis={basis} position={player.position} />
      <ICTCell stats={stats} field="influence" basis={basis} position={player.position} />
      <ICTCell stats={stats} field="creativity" basis={basis} position={player.position} />
      <ICTCell stats={stats} field="threat" basis={basis} position={player.position} />
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Leaders board -- grouped by price bracket, modeled on the community
// "DEFCON Leaders" reference tables (one board per position: DEF/MID/FWD
// lead with DEFCON hit-rate + attacking returns, GK leads with clean
// sheets/saves since DEFCON doesn't apply there).
// ---------------------------------------------------------------------------

const POSITION_ORDER: Position[] = ['GK', 'DEF', 'MID', 'FWD']
const POSITION_LABEL: Record<Position, string> = { ALL: 'All', GK: 'Goalkeepers', DEF: 'Defenders', MID: 'Midfielders', FWD: 'Forwards' }

// FPL prices are already in 0.5m steps -- one board per exact price point,
// all the way up (no collapsing the top of the market into a single "£X+"
// bucket) so a £15.5m Haaland gets his own table rather than being lumped
// in with every other premium.
function priceBracketKey(price: number): number {
  return price
}
function priceBracketLabel(price: number): string {
  return `£${price.toFixed(1)}m`
}

// Green heatmap intensity for a 0-1 rate -- darker = higher, same visual
// language as the reference tables' hit-rate shading. A flat step function
// (not a continuous gradient) keeps the bands easy to eyeball at a glance.
function heatCellClass(v: number | null | undefined): string {
  if (v == null) return 'text-slate-400'
  if (v >= 0.6) return 'bg-emerald-300/70 text-emerald-950 font-semibold'
  if (v >= 0.45) return 'bg-emerald-200/70 text-emerald-900 font-semibold'
  if (v >= 0.3) return 'bg-emerald-100/70 text-emerald-800'
  if (v >= 0.15) return 'bg-emerald-50 text-emerald-700'
  return 'text-slate-600'
}

function pct(v: number | null | undefined): string {
  return v == null ? '\u2014' : `${Math.round(v * 100)}%`
}

function LeadersBoard({ players, season, position, playerById, onSelectPlayer }: {
  players: PlayerPerf[]
  season: SeasonKey
  position: Position
  playerById: Map<number, Player>
  onSelectPlayer: (p: Player) => void
}) {
  const positionsToShow = position === 'ALL' ? POSITION_ORDER : [position]
  const anyData = players.some((p) => statsFor(p, season) != null)

  if (!anyData) {
    return (
      <p className="text-sm text-slate-500 bg-slate-100 border border-slate-200 rounded-md px-3 py-2">
        No qualifying players for this season/filter combination yet.
      </p>
    )
  }

  return (
    <div className="space-y-8">
      {positionsToShow.map((pos) => (
        <PositionLeaderboard key={pos} pos={pos} players={players.filter((p) => p.position === pos)} season={season}
          playerById={playerById} onSelectPlayer={onSelectPlayer} />
      ))}
    </div>
  )
}

// Every column the Leaders board can sort by -- 'name'/'starts'/'clean_sheet'
// map straight onto player/stats fields; the rest match PerformanceSeasonStats
// keys 1:1, so leaderValue below can read them generically instead of a
// per-field switch.
type LeaderSortField =
  | 'name' | 'starts' | 'clean_sheet' | 'saves'
  | 'defcon_hit_rate' | 'defcon_per_start'
  | 'goals_hit_rate' | 'goals_per_start'
  | 'assists_hit_rate' | 'assists_per_start'
  | 'gi_hit_rate' | 'gi_per_start'
  | 'weighted_return_xp'

type LeaderRow = { player: PlayerPerf; stats: PerformanceSeasonStats }

function leaderValue(row: LeaderRow, field: LeaderSortField): number | string {
  if (field === 'name') return row.player.name
  const v = row.stats[field]
  return typeof v === 'number' ? v : -Infinity
}

function LeaderTh({ field, label, align, sortField, sortDir, onClick }: {
  field: LeaderSortField
  label: string
  align: 'left' | 'right'
  sortField: LeaderSortField
  sortDir: 'asc' | 'desc'
  onClick: (field: LeaderSortField) => void
}) {
  const isActive = field === sortField
  return (
    <th className={`py-1.5 px-2 font-medium ${align === 'right' ? 'text-right' : 'text-left'}`}>
      <button onClick={() => onClick(field)}
        className={`flex items-center gap-0.5 ${align === 'right' ? 'ml-auto' : ''} ${isActive ? 'text-slate-900 font-semibold' : 'text-slate-500 hover:text-slate-800'}`}>
        {label}
        {isActive ? (
          <span className="text-[9px]">{sortDir === 'desc' ? '\u2193' : '\u2191'}</span>
        ) : (
          <ChevronsUpDown size={10} className="text-slate-300 shrink-0" />
        )}
      </button>
    </th>
  )
}

function PositionLeaderboard({ pos, players, season, playerById, onSelectPlayer }: {
  pos: Position
  players: PlayerPerf[]
  season: SeasonKey
  playerById: Map<number, Player>
  onSelectPlayer: (p: Player) => void
}) {
  // Weighted return xP is the headline "who's actually worth their price"
  // number for every position -- default sort everywhere. Clicking any
  // other header re-sorts every bracket by that column instead.
  const [sortField, setSortField] = useState<LeaderSortField>('weighted_return_xp')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function onSort(field: LeaderSortField) {
    if (field === sortField) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortField(field)
      setSortDir(field === 'name' ? 'asc' : 'desc')
    }
  }

  const brackets = useMemo(() => {
    const withStats = players
      .map((p) => ({ player: p, stats: statsFor(p, season) }))
      .filter((r): r is LeaderRow => r.stats != null && (r.stats.starts ?? 0) > 0)

    const groups = new Map<number, { label: string; rows: typeof withStats }>()
    for (const row of withStats) {
      const key = priceBracketKey(row.player.price)
      if (!groups.has(key)) groups.set(key, { label: priceBracketLabel(row.player.price), rows: [] })
      groups.get(key)!.rows.push(row)
    }

    return [...groups.entries()]
      .sort((a, b) => b[0] - a[0])
      .map(([, g]) => ({
        ...g,
        rows: [...g.rows].sort((a, b) => {
          const av = leaderValue(a, sortField)
          const bv = leaderValue(b, sortField)
          const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
          return sortDir === 'desc' ? -cmp : cmp
        }),
      }))
  }, [players, season, sortField, sortDir])

  if (brackets.length === 0) {
    return (
      <div>
        <h2 className="text-base font-bold text-slate-800 mb-2">{POSITION_LABEL[pos]}</h2>
        <p className="text-sm text-slate-400">No qualifying players.</p>
      </div>
    )
  }

  return (
    <div>
      <h2 className="text-base font-bold text-slate-800 mb-3 pb-1 border-b border-slate-200">{POSITION_LABEL[pos]}</h2>
      {/* GK's 4-metric table stays compact enough for 2 columns; DEF/MID/FWD
          now carry 6 metric columns (DEFCON + goals + assists, each as a
          hit-rate/per-start pair) -- a 2-up grid would squeeze those into
          unreadably narrow cards, so they go full-width, one bracket per row. */}
      <div className={`grid grid-cols-1 gap-4 ${pos === 'GK' ? 'md:grid-cols-2' : ''}`}>
        {brackets.map((bracket) => (
          <div key={bracket.label} className="border border-slate-200 rounded-lg overflow-hidden">
            <div className="bg-slate-800 text-white text-sm font-bold px-3 py-1.5">{bracket.label}</div>
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-100 text-slate-500 text-left">
                  <LeaderTh field="name" label="Player" align="left" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                  <LeaderTh field="starts" label="Starts" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                  {/* Clean sheets matter for defenders' points (4pts) in a
                      way they don't for MID/FWD (1pt/0pts) -- shown only on
                      the DEF board, not as a general outfield column. */}
                  {pos === 'DEF' && <LeaderTh field="clean_sheet" label="Clean sheets" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />}
                  {/* Headline summary column for every position -- goals/
                      assists/clean-sheet/DEFCON blended by their real point
                      value at this position, not just a raw event count. */}
                  <LeaderTh field="weighted_return_xp" label="Weighted return xP" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                  {pos === 'GK' ? (
                    <>
                      <LeaderTh field="clean_sheet" label="Clean sheets" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      <LeaderTh field="saves" label="Saves" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                    </>
                  ) : (
                    <>
                      <LeaderTh field="defcon_hit_rate" label="DEFCON hit rate" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      <LeaderTh field="defcon_per_start" label="DEFCON p/start" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      <LeaderTh field="goals_hit_rate" label="Goal hit rate" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      <LeaderTh field="goals_per_start" label="Goals p/start" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      <LeaderTh field="assists_hit_rate" label="Assist hit rate" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      <LeaderTh field="assists_per_start" label="Assists p/start" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                      {/* Combined attacking return (goal OR assist) --
                          only meaningful as its own column for the two
                          positions built to create/finish chances. */}
                      {(pos === 'MID' || pos === 'FWD') && (
                        <>
                          <LeaderTh field="gi_hit_rate" label="Offensive return rate" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                          <LeaderTh field="gi_per_start" label="Offensive return p/start" align="right" sortField={sortField} sortDir={sortDir} onClick={onSort} />
                        </>
                      )}
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {bracket.rows.map(({ player, stats }, i) => {
                  const fullPlayer = playerById.get(player.player_id)
                  return (
                  <tr key={player.player_id} onClick={fullPlayer ? () => onSelectPlayer(fullPlayer) : undefined}
                      className={`border-t border-slate-100 ${fullPlayer ? 'cursor-pointer hover:bg-slate-100' : ''} ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
                    <td className="py-1.5 px-2 font-medium text-slate-900">
                      <span className="inline-flex items-center gap-1.5">
                        {fullPlayer && <PlayerShirt player={fullPlayer} size={18} />}
                        {player.name}
                      </span>
                      <PlayerStatusTag player={player} />
                    </td>
                    <td className="py-1.5 px-2 text-right text-slate-600">{stats.starts ?? '\u2014'}</td>
                    {pos === 'DEF' && <td className="py-1.5 px-2 text-right text-slate-600">{stats.clean_sheet ?? '\u2014'}</td>}
                    <td className="py-1.5 px-2 text-right font-semibold text-slate-900">{fmt(stats.weighted_return_xp, 2)}</td>
                    {pos === 'GK' ? (
                      <>
                        <td className="py-1.5 px-2 text-right text-slate-600">{stats.clean_sheet ?? '\u2014'}</td>
                        <td className="py-1.5 px-2 text-right text-slate-600">{stats.saves ?? '\u2014'}</td>
                      </>
                    ) : (
                      <>
                        <td className={`py-1.5 px-2 text-right ${heatCellClass(stats.defcon_hit_rate)}`}
                            title={stats.defcon_starts != null ? `Based on ${stats.defcon_starts} started games` : undefined}>
                          {pct(stats.defcon_hit_rate)}
                        </td>
                        <td className="py-1.5 px-2 text-right text-slate-600">{fmt(stats.defcon_per_start, 1)}</td>
                        <td className={`py-1.5 px-2 text-right ${heatCellClass(stats.goals_hit_rate)}`}
                            title={stats.defcon_starts != null ? `Based on ${stats.defcon_starts} started games` : undefined}>
                          {pct(stats.goals_hit_rate)}
                        </td>
                        <td className="py-1.5 px-2 text-right text-slate-600">{fmt(stats.goals_per_start, 2)}</td>
                        <td className={`py-1.5 px-2 text-right ${heatCellClass(stats.assists_hit_rate)}`}
                            title={stats.defcon_starts != null ? `Based on ${stats.defcon_starts} started games` : undefined}>
                          {pct(stats.assists_hit_rate)}
                        </td>
                        <td className="py-1.5 px-2 text-right text-slate-600">{fmt(stats.assists_per_start, 2)}</td>
                        {(pos === 'MID' || pos === 'FWD') && (
                          <>
                            <td className={`py-1.5 px-2 text-right ${heatCellClass(stats.gi_hit_rate)}`}
                                title={stats.defcon_starts != null ? `Based on ${stats.defcon_starts} started games` : undefined}>
                              {pct(stats.gi_hit_rate)}
                            </td>
                            <td className="py-1.5 px-2 text-right text-slate-600">{fmt(stats.gi_per_start, 2)}</td>
                          </>
                        )}
                      </>
                    )}
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  )
}
