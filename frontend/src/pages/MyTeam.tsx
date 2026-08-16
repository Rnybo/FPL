import { useState } from 'react'
import { Search } from 'lucide-react'
import { useTeam } from '../api/hooks'
import PlayerShirt from '../components/PlayerShirt'
import type { TeamPick } from '../api/types'

const POSITION_ORDER = ['GK', 'DEF', 'MID', 'FWD'] as const

export default function MyTeam() {
  const [input, setInput] = useState('')
  const [teamId, setTeamId] = useState<number | null>(null)
  const { data, isLoading, isError, error } = useTeam(teamId)

  function load() {
    const id = Number(input.trim())
    if (input.trim() && Number.isInteger(id) && id > 0) setTeamId(id)
  }

  return (
    <div className="p-3 sm:p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">My Team</h1>
      <p className="text-slate-500 text-sm mb-4">
        Enter your real FPL team ID to see your actual squad, our own best lineup for it, and
        personalized transfer suggestions -- your team ID is the number in your "Points" page URL
        (fantasy.premierleague.com/entry/<b>THIS NUMBER</b>/event/...).
      </p>

      <div className="flex gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search size={15} className="absolute left-2.5 top-2.5 text-slate-400" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="Team ID, e.g. 1234567"
            inputMode="numeric"
            className="w-full pl-8 pr-3 py-1.5 text-sm border border-slate-300 rounded-md"
          />
        </div>
        <button onClick={load}
          className="text-sm font-medium px-4 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700">
          Load
        </button>
      </div>

      {teamId === null && (
        <p className="text-slate-400 text-sm py-12 text-center">Enter a team ID above to load your squad.</p>
      )}

      {isLoading && <div className="text-slate-500 text-sm py-12 text-center">Loading your team...</div>}

      {isError && (
        <p className="text-red-600 text-sm py-6 text-center">
          Couldn't load team {teamId}: {(error as Error).message}
        </p>
      )}

      {data && <TeamView data={data} />}
    </div>
  )
}

function TeamView({ data }: { data: import('../api/types').TeamOverview }) {
  const pickById = new Map((data.picks ?? []).map((p) => [p.player_id, p]))

  return (
    <div>
      <div className="flex items-center gap-4 mb-4 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-slate-900">{data.team_name}</h2>
          <p className="text-sm text-slate-500">{data.manager_name}</p>
        </div>
        <div className="flex gap-3 ml-auto">
          {data.overall_rank != null && (
            <Badge label="Overall rank" value={data.overall_rank.toLocaleString()} />
          )}
          {data.total_points != null && <Badge label="Total points" value={String(data.total_points)} />}
          {data.bank != null && <Badge label="Bank" value={`£${data.bank.toFixed(1)}m`} />}
        </div>
      </div>

      {!data.squad_published && (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
          {data.note}
        </p>
      )}

      {data.squad_published && data.lineup && (
        <>
          <div className="bg-gradient-to-b from-emerald-500 to-emerald-600 rounded-lg p-2 sm:p-4 pt-6 sm:pt-8 pb-8 sm:pb-10 mb-4">
            <div aria-label="Starting XI">
              {POSITION_ORDER.map((pos) => {
                const idsInPos = data.lineup!.starter_ids.filter((id) => pickById.get(id)?.position === pos)
                if (idsInPos.length === 0) return null
                return (
                  <div key={pos} className="flex justify-center gap-1.5 sm:gap-3 mb-3 sm:mb-5 flex-wrap">
                    {idsInPos.map((id) => {
                      const player = pickById.get(id)!
                      return (
                        <TeamPlayerCard key={id} player={player}
                          isCaptain={player.name === data.lineup!.captain}
                          isVice={player.name === data.lineup!.vice_captain} />
                      )
                    })}
                  </div>
                )
              })}
            </div>
            <div aria-label="Bench" className="border-t border-emerald-400/40 mt-1 pt-3">
              <p className="text-center text-[10px] text-emerald-50 mb-2 font-semibold tracking-wide">BENCH</p>
              <div className="flex justify-center gap-1.5 sm:gap-3 flex-wrap">
                {data.lineup.bench_ids.map((id) => (
                  <TeamPlayerCard key={id} player={pickById.get(id)!} bench />
                ))}
              </div>
            </div>
          </div>

          <p className="text-sm text-slate-600 mb-6">
            Best XI expected points this window: <span className="font-semibold text-emerald-700">
              {data.lineup.expected_points.toFixed(1)}
            </span>{' '}
            (with captain boost: <span className="font-semibold text-emerald-700">
              {data.lineup.expected_points_with_captain.toFixed(1)}
            </span>)
          </p>

          <SuggestionsPanel suggestions={data.suggestions} />
        </>
      )}

      {data.squad_published && !data.lineup && (
        <p className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-md px-3 py-2">
          {data.note}
        </p>
      )}
    </div>
  )
}

function TeamPlayerCard({ player, isCaptain, isVice, bench }: {
  player: TeamPick
  isCaptain?: boolean
  isVice?: boolean
  bench?: boolean
}) {
  return (
    <div className={`relative bg-white rounded-lg shadow-sm w-[76px] sm:w-[104px] pt-2 pb-2 flex flex-col items-center ${bench ? 'opacity-80' : ''}`}>
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
      <span className="text-[9px] sm:text-[10px] bg-emerald-100 text-emerald-700 px-1 rounded font-semibold mt-0.5">
        {player.xP.toFixed(1)} xP
      </span>
    </div>
  )
}

function SuggestionsPanel({ suggestions }: { suggestions: import('../api/types').TransferSuggestion[] | null }) {
  if (!suggestions || suggestions.length === 0) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-1">Suggested transfers</h3>
        <p className="text-xs text-slate-400">No upgrade clears the minimum gain threshold right now -- your squad's in good shape.</p>
      </div>
    )
  }
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-700 mb-1">Suggested transfers</h3>
      <p className="text-xs text-slate-400 mb-2">
        Best single upgrade per outgoing player, using your real selling prices -- not a full
        multi-transfer re-optimization (see optimise.py's suggest_transfers).
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
          <thead>
            <tr className="bg-slate-100 text-left text-slate-500">
              <th className="px-3 py-2">Out</th>
              <th className="px-3 py-2">In</th>
              <th className="px-3 py-2">Pos</th>
              <th className="px-3 py-2 text-right">Gain (xP)</th>
              <th className="px-3 py-2 text-right">Cost change</th>
            </tr>
          </thead>
          <tbody>
            {suggestions.map((s, i) => (
              <tr key={i} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
                <td className="px-3 py-2 text-slate-700">{s.out_name}</td>
                <td className="px-3 py-2 font-medium text-slate-900">{s.in_name}</td>
                <td className="px-3 py-2 text-slate-500">{s.position}</td>
                <td className="px-3 py-2 text-right font-semibold text-emerald-700">+{s.gain.toFixed(1)}</td>
                <td className={`px-3 py-2 text-right ${s.cost_change > 0 ? 'text-red-600' : 'text-slate-600'}`}>
                  {s.cost_change >= 0 ? '+' : ''}£{s.cost_change.toFixed(1)}m
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-slate-400 tracking-wide">{label.toUpperCase()}</p>
      <p className="text-sm font-semibold text-slate-800">{value}</p>
    </div>
  )
}
