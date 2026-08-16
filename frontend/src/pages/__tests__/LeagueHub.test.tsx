import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LeagueHub from '../LeagueHub'
import * as hooks from '../../api/hooks'
import type { LeagueResponse } from '../../api/types'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const MOCK_LEAGUE: LeagueResponse = {
  league_id: 314, league_name: 'Test Mini League',
  standings: [
    { rank: 1, manager_name: 'Alice A', team_name: 'Alice FC', team_id: 111, total_points: 250 },
    { rank: 2, manager_name: 'Bob B', team_name: 'Bob United', team_id: 222, total_points: 240 },
  ],
}

describe('LeagueHub', () => {
  it('shows a prompt before any league id is entered', () => {
    vi.spyOn(hooks, 'useLeague').mockReturnValue({ data: undefined, isLoading: false, isError: false } as never)
    renderWithClient(<LeagueHub />)
    expect(screen.getByText(/enter a league id/i)).toBeInTheDocument()
  })

  it('entering a league id and loading calls useLeague with that id', async () => {
    const spy = vi.spyOn(hooks, 'useLeague').mockReturnValue({ data: undefined, isLoading: false, isError: false } as never)
    renderWithClient(<LeagueHub />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/league id/i), '314')
    await user.click(screen.getByText('Load'))
    expect(spy).toHaveBeenLastCalledWith(314)
  })

  it('renders ranked standings once loaded', () => {
    vi.spyOn(hooks, 'useLeague').mockReturnValue({ data: MOCK_LEAGUE, isLoading: false, isError: false } as never)
    renderWithClient(<LeagueHub />)
    expect(screen.getByText('Test Mini League')).toBeInTheDocument()
    const rows = screen.getAllByRole('row').slice(1) // skip header
    expect(rows[0]).toHaveTextContent('Alice FC')
    expect(rows[0]).toHaveTextContent('250')
    expect(rows[1]).toHaveTextContent('Bob United')
  })

  it('shows a loading state', () => {
    vi.spyOn(hooks, 'useLeague').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    renderWithClient(<LeagueHub />)
    expect(screen.getByText(/loading standings/i)).toBeInTheDocument()
  })

  it('shows an error state on an unknown league id', () => {
    vi.spyOn(hooks, 'useLeague').mockReturnValue({
      data: undefined, isLoading: false, isError: true, error: new Error('404'),
    } as never)
    renderWithClient(<LeagueHub />)
    expect(screen.getByText(/couldn't load league/i)).toBeInTheDocument()
  })
})
