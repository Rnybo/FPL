import {
  BarChart, Bar, ScatterChart, Scatter, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import type { LastSeasonBreakdown } from '../api/types'

// Matches this app's existing Tailwind palette (emerald/amber/slate/red --
// see PlayerScout/SquadBuilder/CaptainPicks) so this chart doesn't introduce
// a new visual language, just extends the existing one.
const EMERALD = '#059669'
const SLATE = '#94a3b8'
const RED = '#dc2626'

const COMPONENT_LABELS: Record<string, string> = {
  goals: 'Goals', assists: 'Assists', bonus: 'Bonus', appearance: 'Appearance',
  clean_sheet: 'Clean sheet', defcon: 'Def. contribution', saves: 'Saves',
  cards: 'Cards', conceded: 'Conceded', penalties: 'Penalties',
}

// Replaces raw variance/std_dev (feedback: not intuitive) with something
// visual -- each dot is one real game he STARTED (see backend's
// last_season_breakdown docstring for why `starts`, not `minutes > 0`).
// No tooltip on hover (removed per feedback -- recharts' default scatter
// tooltip shows a separate row per axis, so even a custom formatter on the
// Y value left an unwanted raw "gw : N" row from the X axis alongside it;
// simplest fix was no tooltip at all rather than fighting that). No
// reference LINES either (removed per feedback: cramped) -- "Best 25%"/
// "Best 50%" are shown as plain values instead, named distinctly from the
// "Started"/"Ceiling" stat cards already above this chart in
// PlayerDetailModal so the two don't collide -- those are genuinely
// DIFFERENT numbers (Ceiling = single best game ALL SEASON; Best 25% =
// AVERAGE of his best quarter of games, a steadier "good week" figure, not
// an extreme). `pct.overall` is still used to color dots above/below his
// typical output when he starts.
export default function LastSeasonChart({ breakdown }: { breakdown: LastSeasonBreakdown }) {
  const { games, percentile_averages: pct, points_by_component } = breakdown

  const componentData = Object.entries(points_by_component)
    .filter(([, v]) => v !== 0)
    .map(([key, value]) => ({ name: COMPONENT_LABELS[key] ?? key, value }))
    .sort((a, b) => b.value - a.value)

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <p className="text-xs font-semibold text-slate-500 tracking-wide">POINTS PER GAME STARTED</p>
        <div className="flex gap-4">
          <ValueLabel label="Best 25%" value={pct.top25} />
          <ValueLabel label="Best 50%" value={pct.top50} />
        </div>
      </div>
      <p className="text-[11px] text-slate-400 mb-2">Each dot is one game he started.</p>
      <ResponsiveContainer width="100%" height={200}>
        <ScatterChart margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="gw" type="number" domain={['dataMin', 'dataMax']} allowDecimals={false}
            tick={{ fontSize: 11, fill: '#94a3b8' }} tickFormatter={(gw) => `${gw}`} />
          <YAxis dataKey="points" type="number" tick={{ fontSize: 11, fill: '#94a3b8' }} width={28} allowDecimals={false} />
          <Scatter data={games} dataKey="points" shape="circle">
            {games.map((g, i) => (
              <Cell key={i} fill={g.points >= pct.overall ? EMERALD : SLATE} />
            ))}
          </Scatter>
        </ScatterChart>
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

function ValueLabel({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <p className="text-[10px] text-slate-400 tracking-wide uppercase leading-none">{label}</p>
      <p className="text-sm font-bold text-emerald-700 leading-none">{value}</p>
    </div>
  )
}
