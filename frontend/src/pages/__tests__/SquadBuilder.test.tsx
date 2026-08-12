import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
    expect(screen.getByText('Matz Sels')).toBeInTheDocument()
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

    expect(screen.getByText('Ultra Expensive Striker')).toBeInTheDocument()
    expect(screen.getByText(/over budget/i)).toBeInTheDocument()
    // Per user request: budget/club-limit violations warn, they don't block --
    // only a genuinely missing empty slot (a structural constraint) should.
    expect(screen.getByLabelText('Add Ultra Expensive Striker')).not.toBeDisabled()

    await user.click(screen.getByLabelText('Add Ultra Expensive Striker'))
    expect(screen.getByText(/over budget by/i)).toBeInTheDocument() // persistent banner
  })

  it('adding an eligible candidate fills the empty slot', async () => {
    mockHooks()
    renderWithClient(<SquadBuilder />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Remove Erling Haaland'))
    await user.click(screen.getByLabelText('Add Pool FWD Replacement'))

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
    await user.selectOptions(screen.getByDisplayValue('All positions'), 'FWD')
    expect(screen.getByText('Pool FWD Replacement')).toBeInTheDocument()
    expect(screen.queryByText('Mohamed Salah')).not.toBeInTheDocument()
  })

  it('shows a loading state while the squad is being fetched', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    vi.spyOn(hooks, 'useOptimalSquad').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    renderWithClient(<SquadBuilder />)
    expect(screen.getByText(/loading squad/i)).toBeInTheDocument()
  })
})
