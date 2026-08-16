import { useMemo, useState } from 'react'
import { ChevronsUpDown, Check } from 'lucide-react'
import { useFixtures } from '../api/hooks'
import FdrStrip, { buildTeamFixtureList } from '../components/FdrStrip'
import TeamDetailModal from '../components/TeamDetailModal'

// Default lookahead when nothing's been explicitly picked -- matches the
// FDR strip's own wrap width elsewhere in the app, so "one row" == "the
// default view" for visual consistency.
const DEFAULT_WINDOW = 8

type SortField = 'avgFdr' | 'nextCs' | 'gf' | 'ga'

// "Which teams have the best run of fixtures coming up" -- a standalone,
// team-centric view, distinct from Player Scout's per-player FDR column.
// Fetches the WHOLE season's fixtures once (no gw filter) and does the FDR
// windowing/sorting client-side -- no backend changes needed for that part,
// this reuses the exact same /api/fixtures data Player Scout already has,
// just grouped and ranked by TEAM instead of shown alongside individual
// players. Clean-sheet %, recent form, last-season stats, and goals-vs-
// opponent DO rely on backend additions (see fixtures.py's
// home/away_clean_sheet_prob, recent_form, last_season_team_stats,
// goals_vs_opponent).
export default function FixtureSwing() {
  const { data, isLoading, isError, error } = useFixtures()
  const fixtures = useMemo(() => data?.fixtures ?? [], [data])
  const recentForm = data?.recent_form ?? {}
  const lastSeasonTeamStats = data?.last_season_team_stats ?? {}
  const goalsVsOpponent = data?.goals_vs_opponent ?? {}

  const [selectedTeam, setSelectedTeam] = useState<string | null>(null)

  // "Now" = the earliest gameweek with at least one unplayed fixture --
  // falls back to 1 if the whole season's fixtures are already finished (end
  // of season) or before any fixture data has loaded at all.
  const currentGw = useMemo(() => {
    const unplayed = fixtures.filter((f) => !f.finished).map((f) => f.gw)
    return unplayed.length > 0 ? Math.min(...unplayed) : 1
  }, [fixtures])

  // null = "track the auto default (current gw onward)" -- becomes a fixed
  // number only once the person actually types something, same pattern as
  // Player Scout's GW filter (draft state + explicit Apply/Enter to commit,
  // rather than refetching/recomputing on every keystroke).
  const [gwStart, setGwStart] = useState<number | null>(null)
  const [gwEnd, setGwEnd] = useState<number | null>(null)
  const effectiveStart = gwStart ?? currentGw
  const effectiveEnd = gwEnd ?? currentGw + DEFAULT_WINDOW - 1

  const [draftGwStart, setDraftGwStart] = useState<number | null>(null)
  const [draftGwEnd, setDraftGwEnd] = useState<number | null>(null)
  const effectiveDraftStart = draftGwStart ?? effectiveStart
  const effectiveDraftEnd = draftGwEnd ?? effectiveEnd
  const hasPendingChange = effectiveDraftStart !== effectiveStart || effectiveDraftEnd !== effectiveEnd

  function applyGwRange() {
    setGwStart(effectiveDraftStart)
    setGwEnd(effectiveDraftEnd)
  }
  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') applyGwRange()
  }

  const [sortField, setSortField] = useState<SortField>('avgFdr')
  // FDR: lower is better, so ascending ("easiest first") is the natural
  // default. Everything else here (clean sheet %, goals scored) is "higher
  // is better", and goals conceded is "lower is better" -- each column's OWN
  // first click below picks whichever direction actually means "best team
  // first" for that specific stat, same reasoning as Player Scout's FDR
  // column defaulting to ascending while everything else defaults to desc.
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  function sortByColumn(field: SortField) {
    if (field === sortField) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir(field === 'avgFdr' || field === 'ga' ? 'asc' : 'desc')
    }
  }

  const teamFixtureList = useMemo(() => buildTeamFixtureList(fixtures), [fixtures])

  const teamRows = useMemo(() => {
    const rows = Object.entries(teamFixtureList).map(([team, entries]) => {
      const inWindow = entries
        .filter((e) => e.gw >= effectiveStart && e.gw <= effectiveEnd)
        .sort((a, b) => a.gw - b.gw)
      const avgFdr = inWindow.length > 0
        ? inWindow.reduce((s, e) => s + e.difficulty, 0) / inWindow.length
        : null
      // "Next CS%" = the clean-sheet chance for the team's NEXT fixture
      // WITHIN this window (the first one chronologically) -- contextual to
      // whatever range is selected, same as everything else on this page.
      const nextCs = inWindow.find((e) => e.cleanSheetProb != null)?.cleanSheetProb ?? null

      // Next opponent + goals scored/conceded against that SAME opponent
      // last season, whichever leg (home/away) matches the actual upcoming
      // venue -- goalsVsOpponent is already gw-window-scoped and ordered by
      // gw server-side, so its first entry IS the next fixture in range.
      const vsOppRows = goalsVsOpponent[team] ?? []
      const next = vsOppRows[0]
      const nextOpponent = next?.opponent ?? null
      const nextVenue: 'H' | 'A' | null = next?.venue_now ?? null
      const nextGoalsFor = next
        ? (next.venue_now === 'H' ? next.home_gf_last_season : next.away_gf_last_season)
        : null
      const nextGoalsAgainst = next
        ? (next.venue_now === 'H' ? next.home_ga_last_season : next.away_ga_last_season)
        : null

      return { team, entries: inWindow, avgFdr, nextCs, nextOpponent, nextVenue, nextGoalsFor, nextGoalsAgainst }
    })
    return rows.sort((a, b) => {
      const va = sortField === 'avgFdr' ? a.avgFdr
        : sortField === 'nextCs' ? a.nextCs
        : sortField === 'gf' ? a.nextGoalsFor
        : a.nextGoalsAgainst
      const vb = sortField === 'avgFdr' ? b.avgFdr
        : sortField === 'nextCs' ? b.nextCs
        : sortField === 'gf' ? b.nextGoalsFor
        : b.nextGoalsAgainst
      // Teams with no data for the ACTIVE sort column sort last regardless
      // of direction -- there's nothing to rank them by on that axis.
      if (va == null) return 1
      if (vb == null) return -1
      return sortDir === 'asc' ? va - vb : vb - va
    })
  }, [teamFixtureList, effectiveStart, effectiveEnd, sortField, sortDir, goalsVsOpponent])

  // Double/blank gameweeks -- only upcoming ones (gw >= currentGw), and only
  // gameweeks that actually HAVE a double or blank for at least one team
  // (most gameweeks are entirely normal -- no point listing those).
  const dgwBgw = useMemo(() => {
    const allTeams = Object.keys(teamFixtureList)
    const upcomingGws = [...new Set(fixtures.filter((f) => f.gw >= currentGw).map((f) => f.gw))].sort((a, b) => a - b)
    const result: { gw: number; doubles: string[]; blanks: string[] }[] = []
    for (const gw of upcomingGws) {
      const countByTeam: Record<string, number> = {}
      for (const t of allTeams) countByTeam[t] = 0
      for (const f of fixtures) {
        if (f.gw !== gw) continue
        countByTeam[f.home_team] = (countByTeam[f.home_team] ?? 0) + 1
        countByTeam[f.away_team] = (countByTeam[f.away_team] ?? 0) + 1
      }
      const doubles = allTeams.filter((t) => countByTeam[t] >= 2)
      const blanks = allTeams.filter((t) => countByTeam[t] === 0)
      if (doubles.length > 0 || blanks.length > 0) result.push({ gw, doubles, blanks })
    }
    return result
  }, [fixtures, currentGw, teamFixtureList])

  if (isLoading) return <div className="p-6 text-slate-500">Loading fixtures...</div>
  if (isError) return <div className="p-6 text-red-600">Failed to load: {(error as Error).message}</div>

  return (
    <div className="p-3 sm:p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Team Scout</h1>
      <p className="text-slate-500 text-sm mb-4">
        Which teams have the best run of fixtures coming up -- pick players from the top of this list,
        avoid the bottom. Ranked over GW{effectiveStart}
        {effectiveEnd !== effectiveStart ? `-${effectiveEnd}` : ''}. "Next" shows who they play next in this
        range, and how many goals they scored/conceded against that SAME opponent last season (home/away as
        relevant) -- click a team for the full breakdown across every gameweek in this range, plus last
        season's complete home/away record.
      </p>

      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">From GW</label>
          <input type="number" min={1} max={38} value={effectiveDraftStart}
            onChange={(e) => setDraftGwStart(Number(e.target.value))}
            onKeyDown={handleKeyDown}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">To GW</label>
          <input type="number" min={1} max={38} value={effectiveDraftEnd}
            onChange={(e) => setDraftGwEnd(Number(e.target.value))}
            onKeyDown={handleKeyDown}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" />
        </div>
        <button onClick={applyGwRange} disabled={!hasPendingChange}
          className={`flex items-center gap-1 text-sm font-medium px-3 py-1 rounded-md border ${
            hasPendingChange
              ? 'bg-emerald-600 border-emerald-600 text-white hover:bg-emerald-700'
              : 'bg-slate-50 border-slate-200 text-slate-300 cursor-default'
          }`}>
          <Check size={14} /> Apply
        </button>
      </div>

      <div className="overflow-x-auto -mx-3 sm:mx-0 px-3 sm:px-0">
      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden min-w-[820px]">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="py-2 pr-3 pl-3">Team</th>
            <th className="py-2 pr-3">Fixtures</th>
            <SortHeader field="avgFdr" label="Avg FDR" sortField={sortField} sortDir={sortDir} onClick={sortByColumn} />
            <SortHeader field="nextCs" label="Next CS%" sortField={sortField} sortDir={sortDir} onClick={sortByColumn} muted />
            <th className="py-2 pr-3">Next opponent</th>
            <SortHeader field="gf" label="Next (goals)" sortField={sortField} sortDir={sortDir} onClick={sortByColumn} muted />
            <SortHeader field="ga" label="Next (conceded)" sortField={sortField} sortDir={sortDir} onClick={sortByColumn} muted />
          </tr>
        </thead>
        <tbody>
          {teamRows.map((row, i) => (
            <tr key={row.team} onClick={() => setSelectedTeam(row.team)}
              className={`border-t border-slate-100 cursor-pointer hover:bg-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
              <td className="py-2 pr-3 pl-3 font-medium text-slate-900">{row.team}</td>
              <td className="py-2 pr-3">
                {row.entries.length > 0 ? (
                  <FdrStrip
                    difficulties={row.entries.map((e) => e.difficulty)}
                    labels={row.entries.map((e) => `GW${e.gw}: ${e.isHome ? 'vs' : '@'} ${e.opponent} (FDR ${e.difficulty})`)}
                  />
                ) : (
                  <span className="text-xs text-slate-300">No fixtures in this range</span>
                )}
              </td>
              <td className="py-2 pr-3 text-right font-semibold text-slate-700">
                {row.avgFdr != null ? row.avgFdr.toFixed(2) : '—'}
              </td>
              <td className="py-2 pr-3 text-right text-slate-500">
                {row.nextCs != null ? `${(row.nextCs * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="py-2 pr-3 text-slate-600">
                {row.nextOpponent ? (
                  <>{row.nextOpponent} <span className="text-[10px] text-slate-400">({row.nextVenue})</span></>
                ) : '—'}
              </td>
              <td className="py-2 pr-3 text-right text-slate-500">
                {row.nextGoalsFor != null ? row.nextGoalsFor : '—'}
              </td>
              <td className="py-2 pr-3 text-right text-slate-500">
                {row.nextGoalsAgainst != null ? row.nextGoalsAgainst : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {teamRows.length === 0 && <p className="text-slate-400 text-sm py-6 text-center">No fixture data yet.</p>}

      {dgwBgw.length > 0 && (
        <div className="mt-6">
          <h2 className="text-sm font-semibold text-slate-700 mb-1">Double &amp; Blank Gameweeks</h2>
          <p className="text-xs text-slate-400 mb-2">
            Upcoming gameweeks where at least one team plays twice (double) or not at all (blank) --
            worth timing a wildcard/free hit around.
          </p>
          <div className="space-y-1.5">
            {dgwBgw.map(({ gw, doubles, blanks }) => (
              <div key={gw} className="text-sm border border-slate-200 rounded-lg px-3 py-2">
                <span className="font-semibold text-slate-900">GW{gw}</span>
                {doubles.length > 0 && (
                  <span className="ml-3 text-emerald-700">
                    Double: {doubles.join(', ')}
                  </span>
                )}
                {blanks.length > 0 && (
                  <span className="ml-3 text-red-600">
                    Blank: {blanks.join(', ')}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {selectedTeam && (
        <TeamDetailModal
          team={selectedTeam}
          recentForm={recentForm[selectedTeam]}
          lastSeasonStats={lastSeasonTeamStats[selectedTeam]}
          goalsVsOpponent={goalsVsOpponent[selectedTeam] ?? []}
          onClose={() => setSelectedTeam(null)}
        />
      )}
    </div>
  )
}

function SortHeader({ field, label, sortField, sortDir, onClick, muted }: {
  field: SortField
  label: string
  sortField: SortField
  sortDir: 'asc' | 'desc'
  onClick: (field: SortField) => void
  muted?: boolean
}) {
  const isActive = field === sortField
  return (
    <th className="py-2 pr-3 text-right">
      <button onClick={(e) => { e.stopPropagation(); onClick(field) }}
        className={`flex items-center gap-1 ml-auto font-medium ${
          isActive ? 'text-slate-900' : muted ? 'text-slate-400 hover:text-slate-900' : 'text-slate-500 hover:text-slate-900'
        }`}>
        {label}
        {isActive ? (
          <span className="text-[10px]">{sortDir === 'asc' ? '↑' : '↓'}</span>
        ) : (
          <ChevronsUpDown size={11} className="text-slate-300" />
        )}
      </button>
    </th>
  )
}
