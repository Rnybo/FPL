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

export default function PlayerShirt({ player, size }: { player: Player; size: number }) {
  const [failed, setFailed] = useState(false)
  const url = shirtUrl(player.team_code, player.position)
  if (!url || failed) return <Shirt size={size} className="text-slate-400" strokeWidth={1.5} />
  return <img src={url} alt="" width={size} height={size} onError={() => setFailed(true)} className="object-contain" />
}
