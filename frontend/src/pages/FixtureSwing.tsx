import { useMemo, useState } from 'react'
import { ChevronsUpDown, Check } from 'lucide-react'
import { useFixtures } from '../api/hooks'
import FdrStrip, { buildTeamFixtureList } from '../components/FdrStrip'

// Default lookahead when nothing's been explicitly picked -- matches the
// FDR strip's own wrap width elsewhere in the app, so "one row" == "the
// default view" for visual consistency.
const DEFAULT_WINDOW = 8

// "Which teams have the best run of fixtures coming up" -- a standalone,
// team-centric view, distinct from Player Scout's per-player FDR column.
// Fetches the WHOLE season's fixtures once (no gw filter) and does all the
// windowing/sorting client-side -- no backend changes needed, this reuses
// the exact same /api/fixtures data Player Scout already has, just grouped
// and ranked by TEAM instead of shown alongside individual players.
export default function FixtureSwing() {
  const { data, isLoading, isError, error } = useFixtures()
  const fixtures = useMemo(() => data?.fixtures ?? [], [data])

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

  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc') // easiest run first by default

  const teamFixtureList = useMemo(() => buildTeamFixtureList(fixtures), [fixtures])

  const teamRows = useMemo(() => {
    const rows = Object.entries(teamFixtureList).map(([team, entries]) => {
      const inWindow = entries
        .filter((e) => e.gw >= effectiveStart && e.gw <= effectiveEnd)
        .sort((a, b) => a.gw - b.gw)
      const avgFdr = inWindow.length > 0
        ? inWindow.reduce((s, e) => s + e.difficulty, 0) / inWindow.length
        : null
      return { team, entries: inWindow, avgFdr }
    })
    return rows.sort((a, b) => {
      // Teams with no fixtures in the window (a full blank) sort last
      // regardless of direction -- there's nothing to rank them by.
      if (a.avgFdr == null) return 1
      if (b.avgFdr == null) return -1
      return sortDir === 'asc' ? a.avgFdr - b.avgFdr : b.avgFdr - a.avgFdr
    })
  }, [teamFixtureList, effectiveStart, effectiveEnd, sortDir])

  if (isLoading) return <div className="p-6 text-slate-500">Loading fixtures...</div>
  if (isError) return <div className="p-6 text-red-600">Failed to load: {(error as Error).message}</div>

  return (
    <div className="p-3 sm:p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Fixture Swing</h1>
      <p className="text-slate-500 text-sm mb-4">
        Which teams have the best run of fixtures coming up -- pick players from the top of this list,
        avoid the bottom. Ranked by average FDR over GW{effectiveStart}
        {effectiveEnd !== effectiveStart ? `-${effectiveEnd}` : ''}.
      </p>

      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">From GW</label>
          <input type="number" min={1} max={38} value={effectiveDraftStart}
            onChange={(e) => setDraftGwStart(Number(e.target.value))}
            onKeyDown={handleKeyDown}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16" />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-500">To GW</label>
          <input type="number" min={1} max={38} value={effectiveDraftEnd}
            onChange={(e) => setDraftGwEnd(Number(e.target.value))}
            onKeyDown={handleKeyDown}
            className="border border-slate-300 rounded-md px-2 py-1 text-sm w-16" />
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

      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="py-2 pr-3 pl-3">Team</th>
            <th className="py-2 pr-3">Fixtures</th>
            <th className="py-2 pr-4 text-right">
              <button onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                className="flex items-center gap-1 ml-auto font-medium text-slate-900 hover:text-slate-900">
                Avg FDR
                <span className="text-[10px]">
                  {sortDir === 'asc' ? '↑' : '↓'}
                </span>
                <ChevronsUpDown size={11} className="text-slate-300" />
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          {teamRows.map((row, i) => (
            <tr key={row.team} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
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
              <td className="py-2 pr-4 text-right font-semibold text-slate-700">
                {row.avgFdr != null ? row.avgFdr.toFixed(2) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {teamRows.length === 0 && <p className="text-slate-400 text-sm py-6 text-center">No fixture data yet.</p>}
    </div>
  )
}
