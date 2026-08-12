import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SquadBuilder from '../SquadBuilder'
import * as hooks from '../../api/hooks'
import * as client from '../../api/client'
import type { Player } from '../../api/types'

function makePlayer(overrides: Partial<Player>): Player {
  return { player_id: 0, name: '', position: 'MID', team: 'Team', price: 5.0, xP: 3.0, ...overrides }
}

// 15 players, matching SLOT_POSITIONS exactly: 2 GK, 5 DEF, 5 MID, 3 FWD.
const FULL_SQUAD: Player[] = [
  makePlayer({ player_id: 1, name: 'Matz Sels', position: 'GK', team: 'Team A', xP: 4.0 }),
  makePlayer({ player_id: 2, name: 'Backup Keeper', position: 'GK', team: 'Team B', xP: 1.5 }),
  makePlayer({ player_id: 3, name: 'Def One', position: 'DEF', team: 'Team C', xP: 4.5 }),
  makePlayer({ player_id: 4, name: 'Def Two', position: 'DEF', team: 'Team D', xP: 4.2 }),
  makePlayer({ player_id: 5, name: 'Def Three', position: 'DEF', team: 'Team E', xP: 3.8 }),
  makePlayer({ player_id: 6, name: 'Def Four', position: 'DEF', team: 'Team F', xP: 2.5 }),
  makePlayer({ player_id: 7, name: 'Def Five', position: 'DEF', team: 'Team G', xP: 2.1 }),
  makePlayer({ player_id: 8, name: 'Mid One', position: 'MID', team: 'Team H', xP: 5.0 }),
  makePlayer({ player_id: 9, name: 'Mid Two', position: 'MID', team: 'Team I', xP: 4.8 }),
  makePlayer({ player_id: 10, name: 'Mid Three', position: 'MID', team: 'Team J', xP: 4.6 }),
  makePlayer({ player_id: 11, name: 'Mid Four', position: 'MID', team: 'Team K', xP: 4.4 }),
  makePlayer({ player_id: 12, name: 'Mid Five', position: 'MID', team: 'Team L', xP: 4.2 }),
  makePlayer({ player_id: 13, name: 'Erling Haaland', position: 'FWD', team: 'Man City', price: 15.5, xP: 6.2 }),
  makePlayer({ player_id: 14, name: 'Fwd Two', position: 'FWD', team: 'Team M', xP: 5.5 }),
  makePlayer({ player_id: 15, name: 'Fwd Three', position: 'FWD', team: 'Team N', xP: 2.0 }),
]

const MOCK_PLAYERS = {
  run_id: 1,
  players: [
    ...FULL_SQUAD,
    makePlayer({ player_id: 100, name: 'Mohamed Salah', position: 'MID', team: 'Liverpool', price: 13.0, xP: 5.8 }),
    makePlayer({ player_id: 101, name: 'Pool FWD Replacement', position: 'FWD', team: 'Team O', price: 5.0, xP: 3.5 }),
    makePlayer({ player_id: 102, name: 'Ultra Expensive Striker', position: 'FWD', team: 'Team P', price: 35.0, xP: 8.0 }),
  ],
}

function mockOptimal(overrides = {}) {
  return {
    run_id: 1, gw_start: 1, gw_end: 5, locked_player_ids: [],
    total_cost: 85.5, total_xp: 59.3,
    squad: FULL_SQUAD,
    lineup: {
      formation: { GK: 1, DEF: 3, MID: 5, FWD: 2 },
      captain: 'Erling Haaland', vice_captain: 'Fwd Two',
      expected_points: 51.2, expected_points_with_captain: 57.4,
      starters: [], bench: [], starter_ids: [], bench_ids: [],
    },
    ...overrides,
  }
}

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient()
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

function mockHooks(overrides = {}) {
  vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
  vi.spyOn(hooks, 'useOptimalSquad').mockReturnValue({ data: mockOptimal(overrides), isLoading: false, isError: false } as never)
  // Mocked at the hook level, not via client.apiGet, so it's unaffected by the
  // apiGet spies some tests below set up to catch the optimizer's own direct
  // fetch call -- those would otherwise feed this hook squad-shaped data instead
  // (see docs/GOTCHAS.md-style note: this is exactly that kind of silent-overwrite
  // trap, just via a shared mock instead of a shared dataframe column).
  vi.spyOn(hooks, 'useCaptainPicks').mockReturnValue({
    data: { gw: 1, safe: [], haul: [] }, isLoading: false, error: null,
  } as never)
}

describe('SquadBuilder', () => {
  it('renders all 15 squad players on the pitch, plus budget/count', () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    expect(screen.getByText('15 / 15')).toBeInTheDocument()
    expect(screen.getByText(/£14\.5m/)).toBeInTheDocument() // 100 - 85.5
    expect(screen.getByText('Erling Haaland')).toBeInTheDocument()
    // getAllByText, not getByText -- these fixtures have no per-gameweek data
    // (gwXp ties at 0 for everyone), so the new captaincy draft plan's
    // tie-break also surfaces Matz Sels there in addition to the pitch. That
    // overlap is expected given flat mock data, not a rendering bug -- this
    // test only cares that he's rendered at all, not exactly where.
    expect(screen.getAllByText('Matz Sels').length).toBeGreaterThan(0)
  })

  it('removing a player empties that slot and shows a notification', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Remove Erling Haaland'))

    expect(screen.getByText(/erling haaland has been removed/i)).toBeInTheDocument()
    // Haaland legitimately reappears in the SIDEBAR as an addable candidate
    // (matches real FPL) -- check he's off the PITCH specifically via the
    // remove button, not via his name (which now also matches the sidebar row).
    expect(screen.queryByLabelText('Remove Erling Haaland')).not.toBeInTheDocument()
    expect(screen.getByText('14 / 15')).toBeInTheDocument()
    expect(screen.getByText(/£30\.0m/)).toBeInTheDocument() // budget freed up
  })

  it('sidebar shows over-budget candidates WITH a warning, but still allows adding them (warn, not block)', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Remove Erling Haaland'))

    // Scoped to the sidebar specifically -- "Just missed the cut" now also
    // surfaces the same near-miss players, so an unscoped query would find
    // two matches (a real, expected UI overlap, not a bug).
    const sidebar = screen.getByRole('complementary')
    expect(within(sidebar).getByText('Ultra Expensive Striker')).toBeInTheDocument()
    expect(within(sidebar).getByText(/over budget/i)).toBeInTheDocument()
    // Per user request: budget/club-limit violations warn, they don't block --
    // only a genuinely missing empty slot (a structural constraint) should.
    expect(within(sidebar).getByLabelText('Add Ultra Expensive Striker')).not.toBeDisabled()

    await user.click(within(sidebar).getByLabelText('Add Ultra Expensive Striker'))
    expect(screen.getByText(/over budget by/i)).toBeInTheDocument() // persistent banner
  })

  it('adding an eligible candidate fills the empty slot', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Remove Erling Haaland'))
    // Scoped to the sidebar -- the near-miss panel also has an "Add Pool FWD
    // Replacement" button once that slot is empty (same real overlap as above).
    const sidebar = screen.getByRole('complementary')
    await user.click(within(sidebar).getByLabelText('Add Pool FWD Replacement'))

    expect(screen.getByText(/pool fwd replacement has been added/i)).toBeInTheDocument()
    expect(screen.getByText('15 / 15')).toBeInTheDocument()
    expect(screen.queryByLabelText('Remove Erling Haaland')).not.toBeInTheDocument()
  })

  it('"Build optimum team" locks currently-filled players and lets the optimizer fill gaps', async () => {
    mockHooks()
    const filled = FULL_SQUAD.filter((p) => p.player_id !== 13)
    const apiSpy = vi.spyOn(client, 'apiGet').mockResolvedValue(mockOptimal({ squad: FULL_SQUAD }) as never)
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Remove Erling Haaland'))
    await user.click(screen.getByText(/build optimum team/i))

    expect(apiSpy).toHaveBeenCalled()
    const calledUrl = apiSpy.mock.calls[0][0] as string
    filled.forEach((p) => expect(calledUrl).toContain(String(p.player_id)))
  })

  it('"Build from scratch" calls the optimizer with NO locked players', async () => {
    mockHooks()
    const apiSpy = vi.spyOn(client, 'apiGet').mockResolvedValue(mockOptimal({ squad: FULL_SQUAD }) as never)
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByText(/build from scratch/i))

    expect(apiSpy).toHaveBeenCalled()
    const calledUrl = apiSpy.mock.calls[0][0] as string
    expect(calledUrl).not.toContain('locked=')
  })

  it('filtering the sidebar by position narrows the candidate list', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    // Scoped to the sidebar -- the position filter only affects the SIDEBAR's
    // candidate list, not the "Just missed the cut" panel (which intentionally
    // always shows all positions), so both names can legitimately appear
    // there regardless of this filter -- checking the sidebar specifically is
    // what this test is actually about.
    const sidebar = screen.getByRole('complementary')
    await user.selectOptions(within(sidebar).getByDisplayValue('All positions'), 'FWD')
    expect(within(sidebar).getByText('Pool FWD Replacement')).toBeInTheDocument()
    expect(within(sidebar).queryByText('Mohamed Salah')).not.toBeInTheDocument()
  })

  it('shows a loading state while the squad is being fetched', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    vi.spyOn(hooks, 'useOptimalSquad').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    renderWithClient(<SquadBuilder />)
    expect(screen.getByText(/loading squad/i)).toBeInTheDocument()
  })

  // The lineup (starters/bench/captain/vice) is computed CLIENT-SIDE from the
  // 15-player squad's own xP (see computeLineup in SquadBuilder.tsx) --
  // independent of whatever the mocked useOptimalSquad response's own
  // `lineup` field says. For FULL_SQUAD's actual xP values, the auto-optimal
  // formation is 3-5-2 (verified by hand: benching the 2 weakest DEF beats
  // any alternative shape) -- Haaland (6.2xP) captains, Fwd Two (5.5xP) vices.
  it('auto formation captains the highest-xP starter and vice-captains the 2nd', () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const starters = screen.getByLabelText('Starting XI')
    const haalandCard = within(starters).getByText('Erling Haaland').closest('div')!
    expect(within(haalandCard).getByText('C')).toBeInTheDocument()
    const viceCard = within(starters).getByText('Fwd Two').closest('div')!
    expect(within(viceCard).getByText('V')).toBeInTheDocument()
  })

  it('the 2 weakest defenders are benched under the auto-optimal 3-5-2 formation', () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const bench = screen.getByLabelText('Bench')
    expect(within(bench).getByText('Def Four')).toBeInTheDocument() // 2.5xP
    expect(within(bench).getByText('Def Five')).toBeInTheDocument() // 2.1xP
    const starters = screen.getByLabelText('Starting XI')
    expect(within(starters).queryByText('Def Four')).not.toBeInTheDocument()
  })

  it('selecting a specific formation moves a benched player into the starting XI', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    expect(within(screen.getByLabelText('Bench')).getByText('Def Five')).toBeInTheDocument()

    // 5-2-3 fits all 5 DEF as starters -- Def Five should move off the bench.
    await user.selectOptions(screen.getByDisplayValue('Auto (optimal)'), '5-2-3')

    expect(within(screen.getByLabelText('Starting XI')).getByText('Def Five')).toBeInTheDocument()
    expect(within(screen.getByLabelText('Bench')).queryByText('Def Five')).not.toBeInTheDocument()
  })

  it('lock mode shows a padlock on each card, and toggling it updates the locked count', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()

    const modeSwitch = screen.getByRole('switch', { name: /toggle lock mode/i })
    expect(modeSwitch).toHaveAttribute('aria-checked', 'false')
    expect(screen.queryByLabelText('Lock Erling Haaland')).not.toBeInTheDocument()

    await user.click(modeSwitch)
    expect(modeSwitch).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText(/0 players currently locked/)).toBeInTheDocument()

    await user.click(screen.getByLabelText('Lock Erling Haaland'))
    expect(screen.getByText(/1 player currently locked/)).toBeInTheDocument()
    expect(screen.getByLabelText('Unlock Erling Haaland')).toBeInTheDocument()
  })

  it('"Build around N locked" sends ONLY the explicitly-locked players, not the whole current squad', async () => {
    mockHooks()
    const apiSpy = vi.spyOn(client, 'apiGet').mockResolvedValue(mockOptimal({ squad: FULL_SQUAD }) as never)
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('switch', { name: /toggle lock mode/i }))
    await user.click(screen.getByLabelText('Lock Erling Haaland'))
    await user.click(screen.getByText(/build around 1 locked/i))

    expect(apiSpy).toHaveBeenCalled()
    const calledUrl = apiSpy.mock.calls[0][0] as string
    expect(calledUrl).toContain('locked=13') // Haaland's id -- ONLY his
    expect(calledUrl).not.toContain('locked=13,') // not followed by anyone else
  })

  it('in lock mode, manually adding a player via the sidebar locks them automatically', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()

    await user.click(screen.getByLabelText('Remove Erling Haaland')) // free up a FWD slot first
    await user.click(screen.getByRole('switch', { name: /toggle lock mode/i }))

    const sidebar = screen.getByRole('complementary')
    await user.click(within(sidebar).getByLabelText('Add Pool FWD Replacement'))

    expect(screen.getByText(/pool fwd replacement has been added to your squad and locked in/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Unlock Pool FWD Replacement')).toBeInTheDocument()
    expect(screen.getByText(/1 player currently locked/)).toBeInTheDocument()
  })

  it('in lock mode, swapping in a near-miss player also locks them automatically', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('switch', { name: /toggle lock mode/i }))
    await user.click(screen.getByLabelText('Swap in Ultra Expensive Striker'))

    expect(screen.getByText(/swapped in ultra expensive striker for fwd three and locked in/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Unlock Ultra Expensive Striker')).toBeInTheDocument()
  })

  it('in FREE mode (switch off), adding a player does NOT lock them', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()

    await user.click(screen.getByLabelText('Remove Erling Haaland'))
    const sidebar = screen.getByRole('complementary')
    await user.click(within(sidebar).getByLabelText('Add Pool FWD Replacement'))

    expect(screen.getByText(/pool fwd replacement has been added to your squad$/i)).toBeInTheDocument()
    // No padlocks exist at all outside lock mode -- confirms nothing got
    // silently locked in the background where it wouldn't even be visible.
    expect(screen.queryByLabelText('Unlock Pool FWD Replacement')).not.toBeInTheDocument()
  })

  it('Reset team empties every slot and clears locks', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('switch', { name: /toggle lock mode/i }))
    await user.click(screen.getByLabelText('Lock Erling Haaland'))
    await user.click(screen.getByText(/reset team/i))

    expect(screen.getByText('0 / 15')).toBeInTheDocument()
    expect(screen.queryByLabelText('Remove Erling Haaland')).not.toBeInTheDocument()
    expect(screen.getByText(/0 players currently locked/)).toBeInTheDocument()
  })

  it('swapping in a near-miss player when the position is full replaces the weakest starter there', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    // Squad is already full (15/15) -- FWD has no empty slot, so this must be
    // a genuine swap: Ultra Expensive Striker (8.0xP) should bump the weakest
    // current FWD, which is Fwd Three (2.0xP), not Haaland or Fwd Two.
    const nearMissSwapButton = screen.getByLabelText('Swap in Ultra Expensive Striker')
    await user.click(nearMissSwapButton)

    expect(screen.getByText(/swapped in ultra expensive striker for fwd three/i)).toBeInTheDocument()
    expect(screen.getByText('Ultra Expensive Striker')).toBeInTheDocument()
    expect(screen.queryByLabelText('Remove Fwd Three')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Remove Erling Haaland')).toBeInTheDocument() // untouched
  })

  it('the captaincy draft plan recommends a DIFFERENT captain per gameweek when each player has their own standout week', () => {
    // Haaland spikes GW1, Mid One spikes GW2 -- everyone else stays flat and
    // low. The plan should follow the spike, not default to one fixed player.
    // Both usePlayers AND useOptimalSquad need this data -- the actual Player
    // OBJECTS (with .gameweeks) come from usePlayers via playerById; the
    // optimal-squad mock only supplies the initial slot IDs.
    const variedSquad = FULL_SQUAD.map((p) => {
      if (p.player_id === 13) { // Erling Haaland
        return { ...p, gameweeks: [{ gw: 1, xP: 9.0 }, { gw: 2, xP: 1.0 }, { gw: 3, xP: 1.0 }, { gw: 4, xP: 1.0 }, { gw: 5, xP: 1.0 }] }
      }
      if (p.player_id === 8) { // Mid One
        return { ...p, gameweeks: [{ gw: 1, xP: 1.0 }, { gw: 2, xP: 9.5 }, { gw: 3, xP: 1.0 }, { gw: 4, xP: 1.0 }, { gw: 5, xP: 1.0 }] }
      }
      return { ...p, gameweeks: [1, 2, 3, 4, 5].map((gw) => ({ gw, xP: 0.5 })) }
    })
    const otherPlayers = MOCK_PLAYERS.players.filter((p) => !FULL_SQUAD.some((f) => f.player_id === p.player_id))
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({
      data: { ...MOCK_PLAYERS, players: [...variedSquad, ...otherPlayers] }, isLoading: false, isError: false,
    } as never)
    vi.spyOn(hooks, 'useOptimalSquad').mockReturnValue({ data: mockOptimal({ squad: variedSquad }), isLoading: false, isError: false } as never)
    vi.spyOn(hooks, 'useCaptainPicks').mockReturnValue({ data: { gw: 1, safe: [], haul: [] }, isLoading: false, error: null } as never)

    renderWithClient(<SquadBuilder />)

    const plan = screen.getByRole('region', { name: /captaincy draft plan/i })
    const rows = within(plan).getAllByRole('row').slice(1) // skip header

    expect(within(rows[0]).getByText('Erling Haaland')).toBeInTheDocument() // GW1
    expect(within(rows[0]).getByText('18.0')).toBeInTheDocument() // 9.0 doubled
    expect(within(rows[1]).getByText('Mid One')).toBeInTheDocument() // GW2
    expect(within(rows[1]).getByText('19.0')).toBeInTheDocument() // 9.5 doubled
  })
})