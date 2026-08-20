import { useState } from 'react'
import { Shirt } from 'lucide-react'
import type { Player } from '../api/types'

// FPL's real shirt CDN -- verified directly against the live site (see
// docs/GOTCHAS.md): goalkeepers use a "_1" suffix for their distinct kit.
function shirtUrl(teamCode: number | undefined, position: string): string | null {
  if (!teamCode) return null
  const suffix = position === 'GK' ? '_1' : ''
  return `https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${teamCode}${suffix}-66.png`
}

// Small overlay badge for injured/suspended/unavailable/doubtful players --
// matches the pitch-renderer convention this project's own build spec
// describes ("a red ! on unavailable players"). Reused for free across
// every surface that already renders a PlayerShirt (Player Scout, My Team,
// Squad Builder's pitch + sidebar, Player Detail modal) rather than
// reimplementing the highlight per page. `title` sits on this plain <span>
// (an ordinary HTML element, not the shirt's own inline SVG/img) so the
// native hover tooltip actually fires -- see the earlier help-icon tooltip
// fix in PlayerPerformance.tsx for why that distinction matters. No status
// at all (e.g. some test fixtures) or 'a'/Available renders nothing.
function StatusBadge({ player, size }: { player: Player; size: number }) {
  const status = player.status
  if (!status || status === 'a') return null
  const isOut = status === 'i' || status === 's' || status === 'u'
  const title = [player.status_label, player.news].filter(Boolean).join(' -- ') || player.status_label
  const badgeSize = Math.max(11, Math.round(size * 0.5))
  return (
    <span
      title={title}
      className={`absolute -top-1 -right-1 flex items-center justify-center rounded-full text-white font-bold leading-none ${
        isOut ? 'bg-red-600' : 'bg-amber-500'
      }`}
      style={{ width: badgeSize, height: badgeSize, fontSize: badgeSize * 0.65 }}
    >
      !
    </span>
  )
}

export default function PlayerShirt({ player, size }: { player: Player; size: number }) {
  const [failed, setFailed] = useState(false)
  const url = shirtUrl(player.team_code, player.position)
  return (
    <span className="relative inline-block" style={{ width: size, height: size }}>
      {!url || failed
        ? <Shirt size={size} className="text-slate-400" strokeWidth={1.5} />
        : <img src={url} alt="" width={size} height={size} onError={() => setFailed(true)} className="object-contain" />}
      <StatusBadge player={player} size={size} />
    </span>
  )
}
