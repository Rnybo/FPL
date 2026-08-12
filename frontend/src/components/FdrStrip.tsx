import type { Fixture } from '../api/types'

// Real FPL FDR color convention: 1 (easiest) green through 5 (hardest) red.
const FDR_COLORS: Record<number, string> = {
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

export default function FdrStrip({ difficulties, max = 8 }: { difficulties: number[]; max?: number }) {
  const shown = difficulties.slice(0, max)
  if (shown.length === 0) return <span className="text-xs text-slate-300">—</span>
  return (
    <div className="flex gap-0.5">
      {shown.map((d, i) => (
        <div key={i} title={`FDR ${d}`} className={`w-4 h-4 rounded-sm ${FDR_COLORS[d] ?? 'bg-slate-200'}`} />
      ))}
    </div>
  )
}
