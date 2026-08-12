import { X } from 'lucide-react'
import PlayerShirt from './PlayerShirt'
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

// Per-gameweek card color band, keyed off xP magnitude -- same rough banding
// as the screenshot reference (darker green = more points), not tied to any
// fixed scale since xP range varies a lot by position.
function gwCardColor(xp: number): string {
  if (xp >= 9) return 'bg-emerald-700 text-white'
  if (xp >= 6) return 'bg-emerald-500 text-white'
  if (xp >= 3) return 'bg-emerald-300 text-emerald-950'
  if (xp > 0) return 'bg-emerald-100 text-emerald-900'
  return 'bg-slate-100 text-slate-500'
}

/** For a given team, gw -> "[H]OPP" / "[A]OPP" label -- same fixture data
 * PlayerScout already fetches for the FDR strip, just reshaped per-team-per-gw
 * instead of an ordered difficulty list. */
function buildOpponentLabel(fixtures: Fixture[], team: string, gw: number): string | null {
  const match = fixtures.find(
    (f) => f.gw === gw && (f.home_team === team || f.away_team === team)
  )
  if (!match) return null
  const isHome = match.home_team === team
  const opponent = isHome ? match.away_team : match.home_team
  return `[${isHome ? 'H' : 'A'}]${opponent.slice(0, 3).toUpperCase()}`
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
        <div className="flex items-start justify-between p-5 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <PlayerShirt player={player} size={48} />
            <div>
              <h2 className="text-xl font-bold text-slate-900">{player.name}</h2>
              <div className="flex gap-4 mt-1">
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

        {/* Per-gameweek cards */}
        {gameweeks.length > 0 && (
          <div className="grid gap-2 p-5 pb-2" style={{ gridTemplateColumns: `repeat(${Math.min(gameweeks.length, 5)}, minmax(0, 1fr))` }}>
            {gameweeks.map((g) => {
              const oppLabel = buildOpponentLabel(fixtures, player.team, g.gw)
              return (
                <div key={g.gw} className="rounded-xl bg-slate-50 border border-slate-100 p-2.5 text-center">
                  <p className="text-[11px] font-medium text-slate-500 mb-1.5">GW{g.gw}</p>
                  <div className={`rounded-lg py-2.5 text-lg font-bold ${gwCardColor(g.xP)}`}>
                    {g.xP.toFixed(1)}
                  </div>
                  {oppLabel && <p className="text-[11px] text-slate-400 mt-1.5">{oppLabel}</p>}
                </div>
              )
            })}
          </div>
        )}

        {/* Historic stats + prediction breakdown */}
        <div className="grid grid-cols-2 gap-5 p-5">
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
