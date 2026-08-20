import type { PlayerStatusCode } from '../api/types'

// Any player-shaped object with the optional live-availability fields --
// Player, TeamPick, and PlayerPerformance all structurally match this,
// so one shared tag component covers every table (Player Scout, Player
// Performance) that shows player rows as plain text rather than via
// PlayerShirt (which gets its own overlay badge -- see PlayerShirt.tsx).
interface StatusLike {
  status?: PlayerStatusCode
  status_label?: string
  chance_of_playing_next_round?: number | null
  news?: string | null
}

// Compact inline tag next to a player's name -- deliberately more visible
// than PlayerShirt's small corner badge, since a data table gets scanned
// quickly and a tiny badge is easy to miss. "OUT" (red) for injured/
// suspended/unavailable; the doubtful percentage (or "?" if FPL hasn't
// given one) in amber otherwise. Renders nothing for a fully available
// player, or one with no status data at all (e.g. a test fixture).
export default function PlayerStatusTag({ player }: { player: StatusLike }) {
  const status = player.status
  if (!status || status === 'a') return null
  const isOut = status === 'i' || status === 's' || status === 'u'
  const title = [player.status_label, player.news].filter(Boolean).join(' -- ') || player.status_label
  const label = isOut
    ? 'OUT'
    : player.chance_of_playing_next_round != null
      ? `${player.chance_of_playing_next_round}%`
      : '?'
  return (
    <span
      title={title}
      className={`inline-block ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold align-middle ${
        isOut ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
      }`}
    >
      {label}
    </span>
  )
}
