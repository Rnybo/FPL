import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import type { LastSeasonBreakdown } from '../api/types'

// Matches this app's existing Tailwind palette (emerald/amber/slate/red --
// see PlayerScout/SquadBuilder/CaptainPicks) so this chart doesn't introduce
// a new visual language, just extends the existing one.
const EMERALD = '#059669'
const AMBER = '#d97706'
const SLATE = '#94a3b8'
const SLATE_DARK = '#334155'
const RED = '#dc2626'

const COMPONENT_LABELS: Record<string, string> = {
  goals: 'Goals', assists: 'Assists', bonus: 'Bonus', appearance: 'Appearance',
  clean_sheet: 'Clean sheet', defcon: 'Def. contribution', saves: 'Saves',
  cards: 'Cards', conceded: 'Conceded', penalties: 'Penalties',
}

// Replaces raw variance/std_dev (feedback: not intuitive) with something
// visual -- each bar is one real game he STARTED (see backend's
// last_season_breakdown docstring for why `starts`, not `minutes > 0`), with
// reference lines showing his average across his best 25%/50%/75%/all games.
// Reading top-to-bottom: "best 25%" is his ceiling tier, "overall" is what
// you get across everything including blanks -- the gap between them IS the
// variance, shown as a gap instead of a number.
export default function LastSeasonChart({ breakdown }: { breakdown: LastSeasonBreakdown }) {
  const { games, percentile_averages: pct, points_by_component } = breakdown

  const componentData = Object.entries(points_by_component)
    .filter(([, v]) => v !== 0)
    .map(([key, value]) => ({ name: COMPONENT_LABELS[key] ?? key, value }))
    .sort((a, b) => b.value - a.value)

  return (
    <div>
      <p className="text-xs font-semibold text-slate-500 tracking-wide mb-1">POINTS PER GAME STARTED</p>
      <p className="text-[11px] text-slate-400 mb-2">
        Each bar is one game he started. Dashed lines are his average across his best 25%, 50%,
        75%, and all of those games -- the gap between "best 25%" and "overall" is his ceiling vs. typical.
      </p>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={games} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
          <XAxis dataKey="gw" tick={{ fontSize: 11, fill: '#94a3b8' }} tickFormatter={(gw) => `${gw}`} />
          <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} width={28} allowDecimals={false} />
          <Tooltip
            formatter={(value) => [`${value} pts`, 'Points']}
            labelFormatter={(gw) => `Gameweek ${gw}`}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
          />
          <ReferenceLine y={pct.top25} stroke={EMERALD} strokeDasharray="4 4"
            label={{ value: `Best 25%: ${pct.top25}`, position: 'insideTopRight', fill: EMERALD, fontSize: 11 }} />
          <ReferenceLine y={pct.top50} stroke={AMBER} strokeDasharray="4 4"
            label={{ value: `Best 50%: ${pct.top50}`, position: 'insideTopRight', fill: AMBER, fontSize: 11 }} />
          <ReferenceLine y={pct.top75} stroke={SLATE} strokeDasharray="4 4"
            label={{ value: `Best 75%: ${pct.top75}`, position: 'insideTopRight', fill: SLATE, fontSize: 11 }} />
          <ReferenceLine y={pct.overall} stroke={SLATE_DARK} strokeDasharray="2 2"
            label={{ value: `Overall: ${pct.overall}`, position: 'insideBottomRight', fill: SLATE_DARK, fontSize: 11 }} />
          <Bar dataKey="points" radius={[3, 3, 0, 0]}>
            {games.map((g, i) => (
              <Cell key={i} fill={g.points >= pct.overall ? EMERALD : SLATE} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <p className="text-xs font-semibold text-slate-500 tracking-wide mt-5 mb-1">WHERE HIS POINTS CAME FROM</p>
      <p className="text-[11px] text-slate-400 mb-2">Total real points by source, games he started last season.</p>
      <ResponsiveContainer width="100%" height={Math.max(120, componentData.length * 28)}>
        <BarChart data={componentData} layout="vertical" margin={{ top: 0, right: 24, left: 4, bottom: 0 }}>
          <XAxis type="number" tick={{ fontSize: 11, fill: '#94a3b8' }} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#475569' }} width={92} />
          <Tooltip formatter={(value) => [`${value} pts`, '']}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }} />
          <Bar dataKey="value" radius={[0, 3, 3, 0]}>
            {componentData.map((d, i) => (
              <Cell key={i} fill={d.value >= 0 ? EMERALD : RED} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
