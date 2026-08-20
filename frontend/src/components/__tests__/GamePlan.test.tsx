import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GamePlanTimeline } from '../GamePlan'
import type { TeamPlanStep } from '../../api/types'

// Minimal fixture builder -- only the fields GamePlanTimeline actually reads
// vary per test; everything else gets a sane default.
function makeStep(overrides: Partial<TeamPlanStep> & { gameweek: number }): TeamPlanStep {
  return {
    formation: { GK: 1, DEF: 4, MID: 4, FWD: 2 },
    captain: 'Player A',
    vice_captain: 'Player B',
    starter_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    bench_ids: [12, 13, 14, 15],
    squad: Array.from({ length: 15 }, (_, i) => ({
      player_id: i + 1,
      name: `Player ${String.fromCharCode(65 + i)}`,
      position: (i === 0 ? 'GK' : i < 5 ? 'DEF' : i < 9 ? 'MID' : 'FWD') as 'GK' | 'DEF' | 'MID' | 'FWD',
      team: 'Team X',
      price: 5.0,
    })),
    transfers_in: [],
    transfers_out: [],
    transfers_in_names: [],
    transfers_out_names: [],
    hits_taken: 0,
    free_transfers_after: 1,
    bank_after: 0,
    expected_points: 50,
    expected_points_with_captain: 60,
    expected_points_after_hits: 50,
    expected_points_with_captain_after_hits: 60,
    ...overrides,
  }
}

describe('GamePlanTimeline gameweek-to-gameweek diffing', () => {
  it('shows no diff badges on the very first gameweek (nothing to compare against)', () => {
    render(<GamePlanTimeline plan={[makeStep({ gameweek: 1 })]} />)
    expect(screen.queryByTitle(/fixture\/form-driven swap/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/NEW/)).not.toBeInTheDocument()
  })

  it('flags a player promoted from bench to XI (and its mirror drop) as a "sub", no transfer involved', async () => {
    const gw1 = makeStep({ gameweek: 1 })
    // Player #11 (was starting) and #12 (was benched) swap places, no transfer.
    const gw2 = makeStep({
      gameweek: 2,
      starter_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12],
      bench_ids: [11, 13, 14, 15],
    })
    const user = userEvent.setup()
    render(<GamePlanTimeline plan={[gw1, gw2]} />)

    expect(screen.getByText('1 sub')).toBeInTheDocument()

    // Expand GW2 to see the inline IN/OUT tags
    await user.click(screen.getByText('GW2'))
    const inTag = screen.getByText('IN')
    const outTag = screen.getByText('OUT')
    expect(inTag).toBeInTheDocument()
    expect(outTag).toBeInTheDocument()
  })

  it('does not flag a transferred-in player as a "sub" -- it is already called out as a transfer', async () => {
    const gw1 = makeStep({ gameweek: 1 })
    // Player #16 is brand new (transferred in), replacing benched #12 -- this
    // must NOT count as a bench-to-XI "sub" since it's a genuine transfer.
    const gw2 = makeStep({
      gameweek: 2,
      starter_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16],
      bench_ids: [11, 13, 14, 15],
      transfers_in: [16],
      transfers_out: [12],
      transfers_in_names: ['Player P'],
      transfers_out_names: ['Player L'],
      squad: [
        ...makeStep({ gameweek: 2 }).squad.filter((p) => p.player_id !== 12),
        { player_id: 16, name: 'Player P', position: 'FWD', team: 'Team X', price: 5.0 },
      ],
    })
    render(<GamePlanTimeline plan={[gw1, gw2]} />)
    expect(screen.queryByTitle(/fixture\/form-driven swap/i)).not.toBeInTheDocument()
  })

  it('flags a formation change in the header', () => {
    const gw1 = makeStep({ gameweek: 1, formation: { GK: 1, DEF: 4, MID: 4, FWD: 2 } })
    const gw2 = makeStep({ gameweek: 2, formation: { GK: 1, DEF: 3, MID: 5, FWD: 2 } })
    render(<GamePlanTimeline plan={[gw1, gw2]} />)
    expect(screen.getByText('4-4-2→3-5-2')).toBeInTheDocument()
  })

  it('shows the previous bench slot when sub-priority order reshuffles with the same 4 bench players', async () => {
    const gw1 = makeStep({ gameweek: 1, bench_ids: [12, 13, 14, 15] })
    const gw2 = makeStep({ gameweek: 2, bench_ids: [12, 14, 13, 15] }) // 13 and 14 swapped
    const user = userEvent.setup()
    render(<GamePlanTimeline plan={[gw1, gw2]} />)
    await user.click(screen.getByText('GW2'))
    expect(screen.getByText('(was #3)')).toBeInTheDocument() // Player N (id 14) was slot 3, now slot 2
  })
})
