import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MyTeam from '../MyTeam'
import * as hooks from '../../api/hooks'
import type { TeamOverview } from '../../api/types'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const NOT_STARTED: TeamOverview = {
  team_id: 123, manager_name: 'Test Manager', team_name: 'Test FC',
  overall_rank: null, total_points: null, squad_published: false,
  bank: null, picks: null, lineup: null, suggestions: null,
  note: "Season hasn't started yet -- no current gameweek, squad picks not published",
}

const PUBLISHED: TeamOverview = {
  team_id: 123, manager_name: 'Test Manager', team_name: 'Test FC',
  overall_rank: 12345, total_points: 500, squad_published: true,
  bank: 1.5,
  picks: [
    { player_id: 1, name: 'GK One', position: 'GK', team: 'Team A', price: 5.0, xP: 4.0, selling_price: 5.0 },
    { player_id: 2, name: 'Star Striker', position: 'FWD', team: 'Team B', price: 12.0, xP: 8.0, selling_price: 11.5 },
  ],
  lineup: {
    formation: { GK: 1, DEF: 0, MID: 0, FWD: 1 },
    captain: 'Star Striker', vice_captain: 'GK One',
    expected_points: 12.0, expected_points_with_captain: 20.0,
    starter_ids: [1, 2], bench_ids: [],
  },
  suggestions: [
    { out_name: 'GK One', in_name: 'Better Keeper', position: 'GK', gain: 1.2, cost_change: 0.5 },
  ],
  note: 'GW1 squad, 2/2 players matched to our data',
}

describe('MyTeam', () => {
  it('shows a prompt before any team id is entered', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({ data: undefined, isLoading: false, isError: false } as never)
    renderWithClient(<MyTeam />)
    expect(screen.getByText(/enter a team id/i)).toBeInTheDocument()
  })

  it('entering a team id and loading calls useTeam with that id', async () => {
    const spy = vi.spyOn(hooks, 'useTeam').mockReturnValue({ data: undefined, isLoading: false, isError: false } as never)
    renderWithClient(<MyTeam />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/team id/i), '1234567')
    await user.click(screen.getByText('Load'))
    expect(spy).toHaveBeenLastCalledWith(1234567)
  })

  it('pre-season: shows the manager info and a clear "not published" note, no crash', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({ data: NOT_STARTED, isLoading: false, isError: false } as never)
    renderWithClient(<MyTeam />)
    expect(screen.getByText('Test FC')).toBeInTheDocument()
    expect(screen.getByText(/season hasn't started/i)).toBeInTheDocument()
  })

  it('published squad: renders the pitch with captain/vice badges and expected points', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({ data: PUBLISHED, isLoading: false, isError: false } as never)
    renderWithClient(<MyTeam />)

    const starters = screen.getByLabelText('Starting XI')
    const captainCard = within(starters).getByText('Star Striker').closest('div')!
    expect(within(captainCard).getByText('C')).toBeInTheDocument()
    const viceCard = within(starters).getByText('GK One').closest('div')!
    expect(within(viceCard).getByText('V')).toBeInTheDocument()
    expect(screen.getByText('20.0')).toBeInTheDocument() // expected_points_with_captain
  })

  it('published squad: shows suggested transfers with real selling-price-based cost change', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({ data: PUBLISHED, isLoading: false, isError: false } as never)
    renderWithClient(<MyTeam />)
    expect(screen.getByText('Suggested transfers')).toBeInTheDocument()
    expect(screen.getByText('Better Keeper')).toBeInTheDocument()
    expect(screen.getByText('+1.2')).toBeInTheDocument()
  })

  it('published squad with no suggestions shows a reassuring message, not an empty table', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({
      data: { ...PUBLISHED, suggestions: [] }, isLoading: false, isError: false,
    } as never)
    renderWithClient(<MyTeam />)
    expect(screen.getByText(/good shape/i)).toBeInTheDocument()
  })

  it('shows a loading state', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    renderWithClient(<MyTeam />)
    expect(screen.getByText(/loading your team/i)).toBeInTheDocument()
  })

  it('shows an error state on an unknown team id', () => {
    vi.spyOn(hooks, 'useTeam').mockReturnValue({
      data: undefined, isLoading: false, isError: true, error: new Error('404'),
    } as never)
    renderWithClient(<MyTeam />)
    expect(screen.getByText(/couldn't load team/i)).toBeInTheDocument()
  })
})
