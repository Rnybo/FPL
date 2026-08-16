import { useState } from 'react'
import { X } from 'lucide-react'
import PlayerShirt from './PlayerShirt'
import { FDR_COLORS } from './FdrStrip'
import LastSeasonChart from './LastSeasonChart'
import MonthlyPointsBoxPlot from './MonthlyPointsBoxPlot'
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
  const [view, setView] = useState<'prediction' | 'lastSeason' | 'statistics'>('prediction')
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
            xP column explicitly labelled so the number's meaning is unambiguous.
            Same 5-row pagination as OpponentFixtureHistoryTable below -- a
            wide GW range (e.g. GW1-20) would otherwise dump 20+ rows here. */}
        {gameweeks.length > 0 && (
          <FixturesTable gameweeks={gameweeks} fixtures={fixtures} team={player.team} />
        )}

        {/* View switch: this window's prediction breakdown, last season's real
            statistical profile, or opponent/FDR history -- underline-tab style
            (bold colored underline + colored label on the active one, muted
            gray otherwise) so which view is showing is unambiguous at a
            glance, not just a subtly-different pill shade. */}
        <div className="flex gap-6 px-5 pt-4 border-b border-slate-200">
          <TabButton active={view === 'prediction'} onClick={() => setView('prediction')}>
            This window
          </TabButton>
          <TabButton active={view === 'lastSeason'} onClick={() => setView('lastSeason')}>
            Last season stats
          </TabButton>
          <TabButton active={view === 'statistics'} onClick={() => setView('statistics')}>
            Statistics
          </TabButton>
        </div>

        {view === 'prediction' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 p-5">
            <div>
              <p className="text-xs font-semibold text-slate-500 tracking-wide mb-1">HISTORIC STATS</p>
              <p className="text-[11px] text-slate-400 mb-2">2025-26 Premier League season</p>
              {player.historic ? (
                <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
                  <tbody>
                    <StatTr label="Mins" value={player.historic.minutes} />
                    <StatTr label="Goals" value={player.historic.goals} />
                    <StatTr label="Assists" value={player.historic.assists} />
                    <StatTr label="xG" value={player.historic.xg.toFixed(2)} />
                    <StatTr label="xA" value={player.historic.xa.toFixed(2)} />
                    {player.last_season_stats && (
                      <StatTr label="Total points" value={player.last_season_stats.total_points} strong />
                    )}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-slate-400">No 2025-26 data (new to the Premier League).</p>
              )}
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-500 tracking-wide mb-1">
                BREAKDOWN OF PREDICTIONS
              </p>
              <p className="text-[11px] text-slate-400 mb-2">
                GW{gameweeks[0]?.gw ?? '?'}{gameweeks.length > 1 ? `-${gameweeks[gameweeks.length - 1].gw}` : ''}
              </p>
              {breakdownEntries.length > 0 ? (
                <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
                  <tbody>
                    {breakdownEntries.map(([key, value]) => (
                      <StatTr key={key} label={BREAKDOWN_LABELS[key]}
                        value={`${value >= 0 ? '+' : ''}${value.toFixed(2)}`}
                        negative={value < 0} />
                    ))}
                    <tr className="border-t border-slate-200 bg-slate-50">
                      <td className="px-3 py-1.5 text-sm font-semibold text-slate-900">Total xP</td>
                      <td className="px-3 py-1.5 text-right text-base font-bold text-emerald-700">{player.xP.toFixed(2)}</td>
                    </tr>
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-slate-400">No meaningful contribution from any component.</p>
              )}
            </div>
          </div>
        )}

        {view === 'lastSeason' && (
          <LastSeasonStatsView stats={player.last_season_stats} breakdown={player.last_season_breakdown}
            fixtureHistory={player.points_vs_opponent_last_season} />
        )}

        {view === 'statistics' && <OpponentStatsView stats={player.opponent_stats} monthly={player.points_by_month} />}
      </div>
    </div>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`text-sm font-semibold pb-2.5 border-b-2 -mb-px transition-colors ${
        active ? 'border-emerald-600 text-emerald-700' : 'border-transparent text-slate-400 hover:text-slate-600'
      }`}
    >
      {children}
    </button>
  )
}

// Same pagination pattern as OpponentFixtureHistoryTable below -- 5 rows at a
// time, since a wide GW range (e.g. GW1-20) would otherwise dump 20+ rows
// into this table. Local page state naturally resets whenever this modal is
// reopened for a (possibly different) player -- see that component's
// docstring for why (PlayerScout fully unmounts this modal on close).
function FixturesTable({ gameweeks, fixtures, team }: {
  gameweeks: NonNullable<Player['gameweeks']>
  fixtures: Fixture[]
  team: string
}) {
  const [page, setPage] = useState(0)
  const pageSize = 5
  const totalPages = Math.ceil(gameweeks.length / pageSize)
  const shown = gameweeks.slice(page * pageSize, page * pageSize + pageSize)

  return (
    <div className="px-5 pt-5 pb-2">
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-2 mb-1.5">
          <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
            className="text-[11px] font-medium text-slate-500 hover:text-slate-800 disabled:opacity-30 disabled:cursor-not-allowed">
            ← Previous 5
          </button>
          <span className="text-[10px] text-slate-400">{page + 1}/{totalPages}</span>
          <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
            className="text-[11px] font-medium text-slate-500 hover:text-slate-800 disabled:opacity-30 disabled:cursor-not-allowed">
            Next 5 →
          </button>
        </div>
      )}
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
          {shown.map((g, i) => {
            const fx = fixtureFor(fixtures, team, g.gw)
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
  )
}

// Real scored points last season -- see backend's last_season_breakdown
// docstring for the full reconstruction/validation notes. Mean/max/min are
// simple enough to keep as numbers; variance/std_dev were dropped per
// direct feedback that they weren't intuitive, replaced with the chart
// below (the gap between the "best 25%" and "overall" reference lines IS
// the variance, shown visually instead of as an abstract number).
function LastSeasonStatsView({ stats, breakdown, fixtureHistory }: {
  stats: Player['last_season_stats']
  breakdown: Player['last_season_breakdown']
  fixtureHistory: Player['points_vs_opponent_last_season']
}) {
  if (!stats) {
    return (
      <div className="p-5">
        <p className="text-xs text-slate-400">No 2025-26 data (new to the Premier League).</p>
      </div>
    )
  }
  return (
    <div className="p-5">
      <p className="text-[11px] text-slate-400 mb-4">
        Real points actually scored, 2025-26 Premier League season -- {stats.games} games
      </p>
      <div className="grid grid-cols-2 gap-3 mb-5">
        <StatCard label="Started" value={stats.start_pct != null ? `${stats.start_pct.toFixed(0)}%` : '—'}
          sub={stats.starts != null ? `${stats.starts}/${stats.games} games` : undefined} />
        <StatCard label="Ceiling" value={stats.max_points} sub="best game" highlight="emerald" />
      </div>
      {breakdown && breakdown.games.length > 0 ? (
        <LastSeasonChart breakdown={breakdown} />
      ) : (
        <p className="text-xs text-slate-400">Not enough starts last season for a chart.</p>
      )}
      {fixtureHistory && fixtureHistory.length > 0 && (
        <div className="mt-5">
          <OpponentFixtureHistoryTable entries={fixtureHistory} />
        </div>
      )}
    </div>
  )
}

// For each fixture in the CURRENTLY SELECTED gameweek range (Player Scout's
// From/To GW inputs), what he scored against that SAME opponent last
// season -- home leg and away leg reported separately, since a club meets
// each opponent once at each venue. The venue matching THIS fixture is
// highlighted (emerald) -- "the same fixture, one year on". A leg with no
// meeting at all last season (promoted opponent, or he wasn't at this club
// yet) shows "-", never a misleading 0.
//
// Paginated 5 rows at a time rather than strictly mirroring the selected GW
// range 1:1: a wide range (e.g. GW1-20) would otherwise dump 20+ rows into
// one table. Local page state naturally resets whenever this modal is
// reopened for a (possibly different) player, since PlayerScout fully
// unmounts it on close (selectedPlayer -> null) rather than swapping props
// on a live instance.
function OpponentFixtureHistoryTable({ entries }: { entries: NonNullable<Player['points_vs_opponent_last_season']> }) {
  const [page, setPage] = useState(0)
  const pageSize = 5
  const totalPages = Math.ceil(entries.length / pageSize)
  const shown = entries.slice(page * pageSize, page * pageSize + pageSize)

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1 flex-wrap gap-2">
        <p className="text-xs font-semibold text-slate-500 tracking-wide">POINTS VS OPPONENT LAST SEASON</p>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
              className="text-[11px] font-medium text-slate-500 hover:text-slate-800 disabled:opacity-30 disabled:cursor-not-allowed">
              ← Previous 5
            </button>
            <span className="text-[10px] text-slate-400">{page + 1}/{totalPages}</span>
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}
              className="text-[11px] font-medium text-slate-500 hover:text-slate-800 disabled:opacity-30 disabled:cursor-not-allowed">
              Next 5 →
            </button>
          </div>
        )}
      </div>
      <p className="text-[11px] text-slate-400 mb-2">
        For each fixture in your selected gameweek range, what he scored against that same opponent last
        season -- highlighted cell is the leg (home/away) matching this fixture's venue. "-" means they
        didn't meet at that venue last season.
      </p>
      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="px-3 py-1.5 font-semibold">GW</th>
            <th className="px-3 py-1.5 font-semibold">Opponent</th>
            <th className="px-3 py-1.5 font-semibold">Venue</th>
            <th className="px-3 py-1.5 text-right font-semibold">Home (last season)</th>
            <th className="px-3 py-1.5 text-right font-semibold">Away (last season)</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((e, i) => (
            <tr key={`${e.gw}-${e.opponent}`} className={`border-t border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}`}>
              <td className="px-3 py-1.5 text-slate-500">{e.gw}</td>
              <td className="px-3 py-1.5 text-slate-800">{e.opponent}</td>
              <td className="px-3 py-1.5 text-slate-500">{e.venue_now}</td>
              <td className={`px-3 py-1.5 text-right ${e.venue_now === 'H' ? 'bg-emerald-50 font-bold text-emerald-700' : 'text-slate-600'}`}>
                {e.home_points_last_season ?? '-'}
              </td>
              <td className={`px-3 py-1.5 text-right ${e.venue_now === 'A' ? 'bg-emerald-50 font-bold text-emerald-700' : 'text-slate-600'}`}>
                {e.away_points_last_season ?? '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatCard({ label, value, sub, highlight }: {
  label: string
  value: string | number
  sub?: string
  highlight?: 'emerald' | 'red'
}) {
  const valueColor = highlight === 'emerald' ? 'text-emerald-700' : highlight === 'red' ? 'text-red-600' : 'text-slate-900'
  return (
    <div className="border border-slate-100 rounded-lg p-3">
      <p className="text-[10px] text-slate-400 tracking-wide uppercase">{label}</p>
      <p className={`text-lg font-bold ${valueColor}`}>{value}</p>
      {sub && <p className="text-[10px] text-slate-400 mt-0.5">{sub}</p>}
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

function StatTr({ label, value, negative, strong }: {
  label: string
  value: string | number
  negative?: boolean
  strong?: boolean
}) {
  return (
    <tr className={`border-t border-slate-100 first:border-t-0 ${strong ? 'bg-slate-50' : ''}`}>
      <td className={`px-3 py-1.5 text-slate-500 ${strong ? 'font-semibold text-slate-700' : ''}`}>{label}</td>
      <td className={`px-3 py-1.5 text-right font-medium ${negative ? 'text-red-600' : strong ? 'font-bold text-slate-900' : 'text-slate-800'}`}>
        {value}
      </td>
    </tr>
  )
}

// "Favorite"/"toughest" opponents -- average REAL points over the LAST 5
// encounters specifically against each one (clubs meet ~2x/season, so this
// naturally reaches back across seasons for most players -- see backend's
// _opponent_stats docstring), plus best/worst FDR tier from ALL historical
// games at that difficulty. next_gw in parens is the upcoming gameweek this
// player's CURRENT team already has scheduled against that same opponent,
// when the fixture list reaches that far -- omitted otherwise (e.g. a
// relegated former opponent, or too far out to be scheduled yet). Also
// includes a monthly points-per-game box plot across recent seasons -- see
// MonthlyPointsBoxPlot.tsx and backend's _monthly_points_per_game.
function OpponentStatsView({ stats, monthly }: {
  stats: Player['opponent_stats']
  monthly: Player['points_by_month']
}) {
  if (!stats && !monthly) {
    return (
      <div className="p-5">
        <p className="text-xs text-slate-400">Not enough historical data yet for opponent statistics.</p>
      </div>
    )
  }
  return (
    <div className="p-5">
      {stats && (
        <>
          <p className="text-[11px] text-slate-400 mb-4">
            Based on real points scored in his last 5 meetings with each opponent, across all available seasons.
            Gameweek in parentheses is when he next faces them this season, if already scheduled.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-5">
            <OpponentTable title="Favorite opponents" entries={stats.best_opponents} tone="emerald" />
            <OpponentTable title="Toughest opponents" entries={stats.worst_opponents} tone="red" />
          </div>
          <div className="grid grid-cols-2 gap-3 mb-6">
            <StatCard label={`Best vs FDR ${stats.best_fdr.fdr}`} value={stats.best_fdr.avg_points}
              sub={`avg pts, ${stats.best_fdr.games} game${stats.best_fdr.games === 1 ? '' : 's'}`} highlight="emerald" />
            <StatCard label={`Worst vs FDR ${stats.worst_fdr.fdr}`} value={stats.worst_fdr.avg_points}
              sub={`avg pts, ${stats.worst_fdr.games} game${stats.worst_fdr.games === 1 ? '' : 's'}`} highlight="red" />
          </div>
        </>
      )}

      {monthly && (
        <div>
          <p className="text-xs font-semibold text-slate-500 tracking-wide mb-1">POINTS PER GAME BY MONTH</p>
          <p className="text-[11px] text-slate-400 mb-2">
            Last {monthly.seasons_included.length} season{monthly.seasons_included.length === 1 ? '' : 's'}
            {' '}({monthly.seasons_included[monthly.seasons_included.length - 1]} to {monthly.seasons_included[0]}) --
            {' '}each box is the spread across seasons of his points-PER-GAME in that month (games he didn't
            play don't count against it, and months with more fixtures don't get extra weight -- every value
            is a rate, not a total). Dots are individual seasons; the line in the box is the median.
          </p>
          <MonthlyPointsBoxPlot data={monthly} />
        </div>
      )}
    </div>
  )
}

function OpponentTable({ title, entries, tone }: {
  title: string
  entries: NonNullable<Player['opponent_stats']>['best_opponents']
  tone: 'emerald' | 'red'
}) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-500 tracking-wide mb-2">{title.toUpperCase()}</p>
      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
        <thead>
          <tr className="bg-slate-100 text-left text-slate-500">
            <th className="px-3 py-1.5 font-semibold">Opponent</th>
            <th className="px-3 py-1.5 text-right font-semibold">Avg pts</th>
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
                {e.avg_points.toFixed(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
