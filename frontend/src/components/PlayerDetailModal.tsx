import { X } from 'lucide-react'
import PlayerShirt from './PlayerShirt'
import { FDR_COLORS } from './FdrStrip'
import type { Player, XpBreakdown, Fixture } from '../api/types'

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

/** Text readable on both the light and dark ends of the FDR color scale
 * (FDR_COLORS 1/2 are light greens, 3 is light slate, 4/5 are darker). */
function fdrTextColor(difficulty: number): string {
  return difficulty >= 4 ? 'text-white' : 'text-slate-900'
}

/** For a given team+gw, find the matching fixture and return it from that
 * team's own perspective: opponent label, home/away, and FDR (the difficulty
 * of THIS fixture for THIS team, i.e. home_difficulty if they're home). Same
 * fixture data PlayerScout already fetches for its FDR strip. */
function fixtureFor(fixtures: Fixture[], team: string, gw: number): { oppLabel: string; difficulty: number } | null {
  const match = fixtures.find(
    (f) => f.gw === gw && (f.home_team === team || f.away_team === team)
  )
  if (!match) return null
  const isHome = match.home_team === team
  const opponent = isHome ? match.away_team : match.home_team
  const difficulty = isHome ? match.home_difficulty : match.away_difficulty
  return { oppLabel: `${isHome ? 'H' : 'A'} ${opponent.slice(0, 3).toUpperCase()}`, difficulty }
}

export default function PlayerDetailModal({ player, fixtures, onClose }: {
  player: Player
  fixtures: Fixture[]
  onClose: () => void
}) {
  const gameweeks = player.gameweeks ?? []
  const breakdownEntries = player.breakdown
    ? (Object.entries(player.breakdown) as [keyof XpBreakdown, number][])
        .filter(([, v]) => Math.abs(v) > 0.005)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    : []

  return (
    <div
      className="fixed inset-0 bg-slate-900/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`${player.name} detail`}
    >
      <div
        className="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-4 sm:p-5 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <PlayerShirt player={player} size={40} />
            <div>
              <h2 className="text-lg sm:text-xl font-bold text-slate-900">{player.name}</h2>
              <div className="flex gap-3 sm:gap-4 mt-1 flex-wrap">
                <Badge label="POS" value={player.position} />
                <Badge label="PRICE" value={`£${player.price.toFixed(1)}m`} />
                <Badge label="TEAM" value={player.team} />
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg p-1.5"
          >
            <X size={18} />
          </button>
        </div>

        {/* Per-gameweek fixtures table -- fixture cell colored by FDR (real FPL
            1=easiest green .. 5=hardest red convention, see FdrStrip.tsx),
            xP column explicitly labelled so the number's meaning is unambiguous. */}
        {gameweeks.length > 0 && (
          <div className="px-5 pt-5 pb-2">
            <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
              <thead>
                <tr className="bg-slate-100">
                  <th className="text-left font-semibold text-slate-600 px-3 py-2">GW</th>
                  <th className="text-left font-semibold text-slate-600 px-3 py-2">Fixture (FDR)</th>
                  <th className="text-right font-semibold text-slate-600 px-3 py-2">
                    xP <span className="font-normal text-slate-400">(projected points)</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {gameweeks.map((g, i) => {
                  const fx = fixtureFor(fixtures, player.team, g.gw)
                  return (
                    <tr key={g.gw} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
                      <td className="px-3 py-2 text-slate-500">{g.gw}</td>
                      <td className="px-3 py-2">
                        {fx ? (
                          <span className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${FDR_COLORS[fx.difficulty] ?? 'bg-slate-200'} ${fdrTextColor(fx.difficulty)}`}>
                            {fx.oppLabel}
                          </span>
                        ) : (
                          <span className="text-slate-300 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-bold text-slate-900">{g.xP.toFixed(1)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Historic stats + prediction breakdown */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 p-5">
          <div>
            <p className="text-xs font-semibold text-slate-500 tracking-wide mb-3">HISTORIC STATS</p>
            <p className="text-[11px] text-slate-400 mb-2">2025-26 Premier League season</p>
            {player.historic ? (
              <div className="space-y-2">
                <StatRow label="Mins" value={player.historic.minutes} />
                <StatRow label="Goals" value={player.historic.goals} />
                <StatRow label="Assists" value={player.historic.assists} />
                <StatRow label="xG" value={player.historic.xg.toFixed(2)} />
                <StatRow label="xA" value={player.historic.xa.toFixed(2)} />
              </div>
            ) : (
              <p className="text-xs text-slate-400">No 2025-26 data (new to the Premier League).</p>
            )}
          </div>

          <div>
            <p className="text-xs font-semibold text-slate-500 tracking-wide mb-3">
              BREAKDOWN OF PREDICTIONS
            </p>
            <p className="text-[11px] text-slate-400 mb-2">
              GW{gameweeks[0]?.gw ?? '?'}{gameweeks.length > 1 ? `-${gameweeks[gameweeks.length - 1].gw}` : ''}
            </p>
            {breakdownEntries.length > 0 ? (
              <div className="space-y-2">
                {breakdownEntries.map(([key, value]) => (
                  <StatRow key={key} label={BREAKDOWN_LABELS[key]}
                    value={`${value >= 0 ? '+' : ''}${value.toFixed(2)}`}
                    negative={value < 0} />
                ))}
                <div className="pt-2 mt-2 border-t border-slate-100 flex justify-between items-baseline">
                  <span className="text-sm font-semibold text-slate-900">Total xP</span>
                  <span className="text-base font-bold text-emerald-700">{player.xP.toFixed(2)}</span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-400">No meaningful contribution from any component.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-slate-400 tracking-wide">{label}</p>
      <p className="text-sm font-semibold text-slate-800">{value}</p>
    </div>
  )
}

function StatRow({ label, value, negative }: { label: string; value: string | number; negative?: boolean }) {
  return (
    <div className="flex justify-between items-baseline text-sm">
      <span className="text-slate-500">{label}</span>
      <span className={`font-medium ${negative ? 'text-red-600' : 'text-slate-800'}`}>{value}</span>
    </div>
  )
}
