// Small pill tags for set-piece duty (e.g. "Pen1", "DF2", "C/IF1") -- see
// backend's set_piece_roles (apply_live_status_override.py) for the exact
// format: Pen(alty) / DF (direct free-kick) / C-IF (corner & indirect
// free-kick), number = order within that duty (1 = primary taker). Color-
// coded by category so multiple tags read at a glance; hover spells out
// the full meaning. Renders nothing for a player with no set-piece duty.
function roleColor(role: string): string {
  if (role.startsWith('Pen')) return 'bg-violet-100 text-violet-700'
  if (role.startsWith('DF')) return 'bg-blue-100 text-blue-700'
  return 'bg-teal-100 text-teal-700' // C/IF
}

function roleTitle(role: string): string {
  const order = role.match(/\d+$/)?.[0] ?? ''
  if (role.startsWith('Pen')) return `Penalty taker, order ${order} (1 = primary)`
  if (role.startsWith('DF')) return `Direct free-kick taker, order ${order} (1 = primary)`
  return `Corner & indirect free-kick taker, order ${order} (1 = primary)`
}

export default function SetPieceTags({ roles }: { roles?: string[] }) {
  if (!roles || roles.length === 0) return null
  return (
    <span className="inline-flex gap-1 ml-1.5 align-middle">
      {roles.map((role) => (
        <span
          key={role}
          title={roleTitle(role)}
          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${roleColor(role)}`}
        >
          {role}
        </span>
      ))}
    </span>
  )
}
