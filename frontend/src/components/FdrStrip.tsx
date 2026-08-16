import type { Fixture } from '../api/types'

// Real FPL FDR color convention: 1 (easiest) green through 5 (hardest) red.
// Exported so other components (e.g. PlayerDetailModal's fixture table) reuse
// the exact same convention instead of redefining their own color scale.
export const FDR_COLORS: Record<number, string> = {
  1: 'bg-emerald-500', 2: 'bg-emerald-300', 3: 'bg-slate-300', 4: 'bg-orange-400', 5: 'bg-red-500',
}

/** Builds a team -> ordered difficulty list from a fixtures list. Each
 * fixture contributes its difficulty FROM THAT TEAM'S perspective (home_difficulty
 * if they're home, away_difficulty if away) -- a double gameweek naturally
 * produces two entries for that team, which is correct: they play twice. */
export function buildFdrByTeam(fixtures: Fixture[]): Record<string, number[]> {
  const byTeam: Record<string, number[]> = {}
  const sorted = [...fixtures].sort((a, b) => a.kickoff_time.localeCompare(b.kickoff_time))
  for (const f of sorted) {
    ;(byTeam[f.home_team] ??= []).push(f.home_difficulty)
    ;(byTeam[f.away_team] ??= []).push(f.away_difficulty)
  }
  return byTeam
}

// Wraps into rows of `perRow` (default 8) rather than truncating -- shows
// EVERY selected gameweek's difficulty, however many there are, e.g. GW1-16
// selected renders as two rows of 8 (GW1-8, then GW9-16), not just the
// first 8 with the rest silently dropped.
export default function FdrStrip({ difficulties, perRow = 8 }: { difficulties: number[]; perRow?: number }) {
  if (difficulties.length === 0) return <span className="text-xs text-slate-300">—</span>
  const rows: number[][] = []
  for (let i = 0; i < difficulties.length; i += perRow) {
    rows.push(difficulties.slice(i, i + perRow))
  }
  return (
    <div className="flex flex-col gap-0.5">
      {rows.map((row, r) => (
        <div key={r} className="flex gap-0.5">
          {row.map((d, i) => (
            <div key={i} title={`FDR ${d}`} className={`w-4 h-4 rounded-sm ${FDR_COLORS[d] ?? 'bg-slate-200'}`} />
          ))}
        </div>
      ))}
    </div>
  )
}
