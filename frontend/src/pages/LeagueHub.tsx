import { useState } from 'react'
import { Search } from 'lucide-react'
import { useLeague } from '../api/hooks'

export default function LeagueHub() {
  const [input, setInput] = useState('')
  const [leagueId, setLeagueId] = useState<number | null>(null)
  const { data, isLoading, isError, error } = useLeague(leagueId)

  function load() {
    const id = Number(input.trim())
    if (input.trim() && Number.isInteger(id) && id > 0) setLeagueId(id)
  }

  return (
    <div className="p-3 sm:p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">League Hub</h1>
      <p className="text-slate-500 text-sm mb-4">
        Enter a classic mini-league ID to see its current standings -- the number in your
        league's "Standings" page URL (fantasy.premierleague.com/leagues/<b>THIS NUMBER</b>/standings/c).
      </p>

      <div className="flex gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search size={15} className="absolute left-2.5 top-2.5 text-slate-400" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="League ID, e.g. 314"
            inputMode="numeric"
            className="w-full pl-8 pr-3 py-1.5 text-sm border border-slate-300 rounded-md"
          />
        </div>
        <button onClick={load}
          className="text-sm font-medium px-4 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700">
          Load
        </button>
      </div>

      {leagueId === null && (
        <p className="text-slate-400 text-sm py-12 text-center">Enter a league ID above to load its standings.</p>
      )}

      {isLoading && <div className="text-slate-500 text-sm py-12 text-center">Loading standings...</div>}

      {isError && (
        <p className="text-red-600 text-sm py-6 text-center">
          Couldn't load league {leagueId}: {(error as Error).message}
        </p>
      )}

      {data && (
        <div>
          <h2 className="text-lg font-bold text-slate-900 mb-3">{data.league_name}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
              <thead>
                <tr className="bg-slate-100 text-left text-slate-500">
                  <th className="px-3 py-2 w-12">Rank</th>
                  <th className="px-3 py-2">Manager</th>
                  <th className="px-3 py-2">Team</th>
                  <th className="px-3 py-2 text-right">Points</th>
                </tr>
              </thead>
              <tbody>
                {data.standings.map((s, i) => (
                  <tr key={s.team_id} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
                    <td className="px-3 py-2 text-slate-500">{s.rank}</td>
                    <td className="px-3 py-2 text-slate-700">{s.manager_name}</td>
                    <td className="px-3 py-2 font-medium text-slate-900">{s.team_name}</td>
                    <td className="px-3 py-2 text-right font-semibold text-emerald-700">{s.total_points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.standings.length === 0 && (
            <p className="text-slate-400 text-sm py-6 text-center">No standings yet -- check back once the season's underway.</p>
          )}
        </div>
      )}
    </div>
  )
}
