import { X } from 'lucide-react'
import type { TeamRecentForm, TeamLastSeasonStats, TeamOpponentEntry } from '../api/types'

// Click-through detail for a team on Team Scout -- the main table only has
// room for the ONE home/away split that's actually relevant to a team's
// next fixture (see FixtureSwing.tsx); this shows the FULL picture: both
// home and away recent form, last season's real record by venue, and
// favorable/unfavorable opponents.
export default function TeamDetailModal({ team, recentForm, lastSeasonStats, onClose }: {
  team: string
  recentForm?: TeamRecentForm
  lastSeasonStats?: TeamLastSeasonStats
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 bg-slate-900/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`${team} detail`}
    >
      <div
        className="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 sm:p-5 border-b border-slate-100">
          <h2 className="text-lg sm:text-xl font-bold text-slate-900">{team}</h2>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg p-1.5">
            <X size={18} />
          </button>
        </div>

        <div className="p-5">
          <p className="text-xs font-semibold text-slate-500 tracking-wide mb-1">RECENT FORM</p>
          <p className="text-[11px] text-slate-400 mb-2">Last 5 real games -- spans last season's closing games if the current season doesn't have 5 of its own yet.</p>
          <div className="grid grid-cols-2 gap-3 mb-6">
            <FormCard label="HOME" games={recentForm?.home_games ?? 0} gf={recentForm?.home_gf_per_game ?? null} ga={recentForm?.home_ga_per_game ?? null} />
            <FormCard label="AWAY" games={recentForm?.away_games ?? 0} gf={recentForm?.away_gf_per_game ?? null} ga={recentForm?.away_ga_per_game ?? null} />
          </div>

          <p className="text-xs font-semibold text-slate-500 tracking-wide mb-1">LAST SEASON</p>
          {lastSeasonStats ? (
            <>
              <p className="text-[11px] text-slate-400 mb-2">{lastSeasonStats.games_home + lastSeasonStats.games_away} real games</p>
              <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden mb-5">
                <thead>
                  <tr className="bg-slate-100 text-left text-slate-500">
                    <th className="px-3 py-1.5 font-semibold"></th>
                    <th className="px-3 py-1.5 text-right font-semibold">Home</th>
                    <th className="px-3 py-1.5 text-right font-semibold">Away</th>
                    <th className="px-3 py-1.5 text-right font-semibold">Total</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-t border-slate-100">
                    <td className="px-3 py-1.5 text-slate-500">Goals scored</td>
                    <td className="px-3 py-1.5 text-right font-medium text-slate-800">{lastSeasonStats.goals_for_home}</td>
                    <td className="px-3 py-1.5 text-right font-medium text-slate-800">{lastSeasonStats.goals_for_away}</td>
                    <td className="px-3 py-1.5 text-right font-bold text-slate-900">{lastSeasonStats.goals_for_home + lastSeasonStats.goals_for_away}</td>
                  </tr>
                  <tr className="border-t border-slate-100 bg-slate-50">
                    <td className="px-3 py-1.5 text-slate-500">Goals conceded</td>
                    <td className="px-3 py-1.5 text-right font-medium text-slate-800">{lastSeasonStats.goals_against_home}</td>
                    <td className="px-3 py-1.5 text-right font-medium text-slate-800">{lastSeasonStats.goals_against_away}</td>
                    <td className="px-3 py-1.5 text-right font-bold text-slate-900">{lastSeasonStats.goals_against_home + lastSeasonStats.goals_against_away}</td>
                  </tr>
                  <tr className="border-t border-slate-100">
                    <td className="px-3 py-1.5 text-slate-500">Clean sheets</td>
                    <td className="px-3 py-1.5 text-right font-medium text-slate-800">{lastSeasonStats.clean_sheets_home}</td>
                    <td className="px-3 py-1.5 text-right font-medium text-slate-800">{lastSeasonStats.clean_sheets_away}</td>
                    <td className="px-3 py-1.5 text-right font-bold text-emerald-700">{lastSeasonStats.clean_sheets_total}</td>
                  </tr>
                </tbody>
              </table>

              <p className="text-[11px] text-slate-400 mb-3">
                Favorable/unfavorable opponents, by average goal difference last season. Gameweek in
                parentheses is when they next meet this season, if already scheduled.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <OpponentTable title="Favorable opponents" entries={lastSeasonStats.favorable_opponents} tone="emerald" />
                <OpponentTable title="Unfavorable opponents" entries={lastSeasonStats.unfavorable_opponents} tone="red" />
              </div>
            </>
          ) : (
            <p className="text-xs text-slate-400">No last-season data (e.g. newly promoted).</p>
          )}
        </div>
      </div>
    </div>
  )
}

function FormCard({ label, games, gf, ga }: { label: string; games: number; gf: number | null; ga: number | null }) {
  return (
    <div className="border border-slate-200 rounded-lg p-3">
      <p className="text-[11px] font-semibold text-slate-500 tracking-wide mb-1.5">{label}</p>
      {games > 0 ? (
        <>
          <p className="text-sm text-slate-700">GF/game: <span className="font-bold text-emerald-700">{gf}</span></p>
          <p className="text-sm text-slate-700">GA/game: <span className="font-bold text-red-600">{ga}</span></p>
          <p className="text-[11px] text-slate-400 mt-1">{games} game{games === 1 ? '' : 's'}</p>
        </>
      ) : (
        <p className="text-xs text-slate-400">No data</p>
      )}
    </div>
  )
}

function OpponentTable({ title, entries, tone }: { title: string; entries: TeamOpponentEntry[]; tone: 'emerald' | 'red' }) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-500 tracking-wide mb-2">{title.toUpperCase()}</p>
      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="px-3 py-1.5 font-semibold">Opponent</th>
            <th className="px-3 py-1.5 text-right font-semibold">Avg GD</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={e.opponent} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
              <td className="px-3 py-1.5 text-slate-800">
                {e.opponent}
                {e.next_gw != null && <span className="text-slate-400"> (GW{e.next_gw})</span>}
              </td>
              <td className={`px-3 py-1.5 text-right font-semibold ${tone === 'emerald' ? 'text-emerald-700' : 'text-red-600'}`}>
                {e.avg_goal_diff > 0 ? '+' : ''}{e.avg_goal_diff.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
