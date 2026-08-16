import type { MonthlyPointsEntry, PointsByMonth } from '../api/types'

// Matches this app's existing palette (see LastSeasonChart.tsx).
const EMERALD = '#059669'
const EMERALD_LIGHT = '#d1fae5'
const SLATE = '#94a3b8'
const SLATE_DARK = '#334155'

// Points PER GAME by calendar month, box-plotted across each of the last
// N complete seasons (see backend's _monthly_points_per_game docstring):
// each month's box is built from up to N values -- one per season he
// actually played that month -- so a month he skipped in some season isn't
// counted as a 0, and a month with more fixtures than another doesn't
// outweigh it (both are rates, not totals). No native box-plot component in
// recharts, so this is hand-rolled SVG rather than fighting a bar-chart
// trick into looking like one.
export default function MonthlyPointsBoxPlot({ data }: { data: PointsByMonth }) {
  const { months } = data
  if (months.length === 0) {
    return <p className="text-xs text-slate-400">Not enough historical data yet.</p>
  }

  const width = 560
  const height = 220
  const padding = { top: 10, right: 12, bottom: 24, left: 30 }
  const plotW = width - padding.left - padding.right
  const plotH = height - padding.top - padding.bottom
  const bandWidth = plotW / months.length

  const allValues = months.flatMap((m) => m.values)
  const rawMax = Math.max(...allValues)
  const rawMin = Math.min(0, ...allValues) // baseline at 0 unless there's a genuine negative game
  // A little headroom above/below so the topmost/bottommost marks aren't
  // flush against the plot edge.
  const span = rawMax - rawMin || 1
  const yMax = rawMax + span * 0.08
  const yMin = rawMin - span * 0.08
  const yScale = (v: number) => padding.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH

  const gridTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => yMin + f * (yMax - yMin))

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto" role="img"
      aria-label="Points per game by month, box plot across recent seasons">
      {gridTicks.map((v, i) => {
        const y = yScale(v)
        return (
          <g key={i}>
            <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="#f1f5f9" />
            <text x={padding.left - 5} y={y + 3} textAnchor="end" fontSize={9} fill={SLATE}>{v.toFixed(1)}</text>
          </g>
        )
      })}
      {yMin < 0 && (
        <line x1={padding.left} x2={width - padding.right} y1={yScale(0)} y2={yScale(0)} stroke="#cbd5e1" strokeDasharray="2 2" />
      )}
      {months.map((m, i) => (
        <MonthBox key={m.month} entry={m} cx={padding.left + bandWidth * (i + 0.5)}
          boxWidth={Math.min(26, bandWidth * 0.55)} yScale={yScale} labelY={height - padding.bottom + 14} />
      ))}
    </svg>
  )
}

function MonthBox({ entry, cx, boxWidth, yScale, labelY }: {
  entry: MonthlyPointsEntry
  cx: number
  boxWidth: number
  yScale: (v: number) => number
  labelY: number
}) {
  const capWidth = boxWidth / 2.2
  const boxTop = yScale(entry.q3)
  const boxHeight = Math.max(1.5, yScale(entry.q1) - yScale(entry.q3))

  return (
    <g>
      <title>
        {entry.month}: median {entry.median} pts/game (min {entry.min}, max {entry.max}, {entry.n_seasons} season{entry.n_seasons === 1 ? '' : 's'})
      </title>
      {/* whisker */}
      <line x1={cx} x2={cx} y1={yScale(entry.max)} y2={yScale(entry.min)} stroke={SLATE} strokeWidth={1.25} />
      <line x1={cx - capWidth / 2} x2={cx + capWidth / 2} y1={yScale(entry.max)} y2={yScale(entry.max)} stroke={SLATE} strokeWidth={1.25} />
      <line x1={cx - capWidth / 2} x2={cx + capWidth / 2} y1={yScale(entry.min)} y2={yScale(entry.min)} stroke={SLATE} strokeWidth={1.25} />
      {/* box (Q1-Q3) */}
      <rect x={cx - boxWidth / 2} y={boxTop} width={boxWidth} height={boxHeight}
        fill={EMERALD_LIGHT} stroke={EMERALD} strokeWidth={1.5} />
      {/* median */}
      <line x1={cx - boxWidth / 2} x2={cx + boxWidth / 2} y1={yScale(entry.median)} y2={yScale(entry.median)} stroke={EMERALD} strokeWidth={2} />
      {/* one small dot per season, slightly spread so they don't fully overlap */}
      {entry.values.map((v, vi) => {
        const spread = entry.values.length > 1 ? (vi - (entry.values.length - 1) / 2) * 3.5 : 0
        return <circle key={vi} cx={cx + spread} cy={yScale(v)} r={1.6} fill={SLATE_DARK} opacity={0.55} />
      })}
      <text x={cx} y={labelY} textAnchor="middle" fontSize={10} fill="#64748b">{entry.month}</text>
    </g>
  )
}
