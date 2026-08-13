import { Shield, Dice5 } from 'lucide-react'
import { useCaptainPicks } from '../api/hooks'
import { FDR_COLORS } from './FdrStrip'
import type { CaptainPick } from '../api/types'

// Two rankings of the SAME Monte Carlo simulation (see scripts/captain_simulation.py):
// "Safe" by mean simulated points, "Haul gamble" by P(>=10). Variance -- floor/ceiling --
// falls out of each player's own lambdas (a striker's high goal-lambda gives a fat right
// tail; a defender's clean-sheet/defcon odds are tight and bounded), not a separate model.
//
// Fixture + FDR shown alongside haul% deliberately -- a bare percentage doesn't say
// WHY it's high (see captain_simulation.py's top_captain_picks docstring): a defender's
// clean-sheet/defcon route and an attacker's goal-explosion route can produce the same
// number for very different reasons, and only one of those tends to repeat reliably.
export default function CaptainPicks({ gw }: { gw?: number }) {
  const { data, isLoading, error } = useCaptainPicks(gw)

  if (isLoading) return <div className="text-sm text-slate-500 py-6 text-center">Simulating captaincy options...</div>
  if (error || !data) return null

  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-slate-700 mb-2">Captain picks — GW{data.gw}</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <PickTable
          title="Safest"
          icon={<Shield size={14} className="text-emerald-600" />}
          rows={data.safe}
          highlightKey="mean"
        />
        <PickTable
          title="Haul gamble"
          icon={<Dice5 size={14} className="text-amber-600" />}
          rows={data.haul}
          highlightKey="p_haul"
        />
      </div>
    </div>
  )
}

function fdrTextColor(difficulty: number): string {
  return difficulty >= 4 ? 'text-white' : 'text-slate-900'
}

function PickTable({ title, icon, rows, highlightKey }: {
  title: string
  icon: React.ReactNode
  rows: CaptainPick[]
  highlightKey: 'mean' | 'p_haul'
}) {
  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <div className="flex items-center gap-1.5 bg-slate-50 px-3 py-1.5 border-b border-slate-100">
        {icon}
        <span className="text-xs font-semibold text-slate-700">{title}</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-400">
            <th className="text-left px-3 py-1 font-normal">Player</th>
            <th className="text-left px-2 py-1 font-normal">Fixture</th>
            <th className="text-right px-2 py-1 font-normal">xP</th>
            <th className="text-right px-2 py-1 font-normal">Floor</th>
            <th className="text-right px-2 py-1 font-normal">Ceiling</th>
            <th className="text-right px-3 py-1 font-normal">Haul %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-t border-slate-50">
              <td className="px-3 py-1.5 font-medium text-slate-900 truncate max-w-[110px]">{r.name}</td>
              <td className="px-2 py-1.5">
                <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold whitespace-nowrap ${FDR_COLORS[Math.round(r.fdr)] ?? 'bg-slate-200'} ${fdrTextColor(r.fdr)}`}>
                  {r.fixture}
                </span>
              </td>
              <td className={`text-right px-2 py-1.5 ${highlightKey === 'mean' ? 'font-semibold text-emerald-700' : 'text-slate-600'}`}>
                {r.mean.toFixed(1)}
              </td>
              <td className="text-right px-2 py-1.5 text-slate-500">{r.p10.toFixed(1)}</td>
              <td className="text-right px-2 py-1.5 text-slate-500">{r.p90.toFixed(1)}</td>
              <td className={`text-right px-3 py-1.5 ${highlightKey === 'p_haul' ? 'font-semibold text-amber-700' : 'text-slate-600'}`}>
                {(r.p_haul * 100).toFixed(0)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
