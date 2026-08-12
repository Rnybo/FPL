import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PlayerScout from '../PlayerScout'
import * as hooks from '../../api/hooks'

const MOCK_PLAYERS = {
  run_id: 1,
  gw_start: 1,
  gw_end: 1,
  players: [
    {
      player_id: 1, name: 'Erling Haaland', position: 'FWD' as const, team: 'Man City', price: 15.5, xP: 6.2,
      breakdown: {
        appearance_pts: 1.8, goal_pts: 3.2, assist_pts: 0.1, cs_pts: 0, conceded_penalty: 0,
        card_pen_pts: -0.1, pen_save_pts: 0, save_pts: 0, defcon_pts: 0, bonus_pts: 1.2,
      },
      // Deliberately backloaded -- lowest total-xP rank overall, but NOT lowest
      // in every individual gameweek, so per-GW sort tests are meaningful.
      gameweeks: [{ gw: 1, xP: 1.0 }, { gw: 2, xP: 1.0 }, { gw: 3, xP: 4.2 }],
    },
    {
      player_id: 2, name: 'Mohamed Salah', position: 'MID' as const, team: 'Liverpool', price: 13.0, xP: 5.8,
      breakdown: {
        appearance_pts: 1.8, goal_pts: 2.0, assist_pts: 0.8, cs_pts: 0.2, conceded_penalty: 0,
        card_pen_pts: 0, pen_save_pts: 0, save_pts: 0, defcon_pts: 0.3, bonus_pts: 0.7,
      },
      gameweeks: [{ gw: 1, xP: 5.0 }, { gw: 2, xP: 0.3 }, { gw: 3, xP: 0.5 }],
    },
    {
      player_id: 3, name: 'Virgil van Dijk', position: 'DEF' as const, team: 'Liverpool', price: 6.5, xP: 4.1,
      breakdown: {
        appearance_pts: 1.8, goal_pts: 0.1, assist_pts: 0.05, cs_pts: 1.2, conceded_penalty: -0.2,
        card_pen_pts: -0.05, pen_save_pts: 0, save_pts: 0, defcon_pts: 0.3, bonus_pts: 0.8,
      },
      // Lowest total xP overall, but the BEST single gameweek (GW2) of any player --
      // the case the new per-gameweek sort is specifically meant to surface.
      gameweeks: [{ gw: 1, xP: 0.5 }, { gw: 2, xP: 3.0 }, { gw: 3, xP: 0.6 }],
    },
  ],
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('PlayerScout', () => {
  it('renders all players sorted by xP descending by default', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const rows = screen.getAllByRole('row').slice(1) // skip header row
    expect(rows[0]).toHaveTextContent('Erling Haaland')
    expect(rows[2]).toHaveTextContent('Virgil van Dijk')
  })

  it('filters by search text (name)', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/search player or team/i), 'salah')
    expect(screen.getByText('Mohamed Salah')).toBeInTheDocument()
    expect(screen.queryByText('Erling Haaland')).not.toBeInTheDocument()
  })

  it('filters by position', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.selectOptions(screen.getAllByRole('combobox')[0], 'DEF')
    expect(screen.getByText('Virgil van Dijk')).toBeInTheDocument()
    expect(screen.queryByText('Erling Haaland')).not.toBeInTheDocument()
  })

  it('shows loading state', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    renderWithClient(<PlayerScout />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows error state', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({
      data: undefined, isLoading: false, isError: true, error: new Error('network down'),
    } as never)
    renderWithClient(<PlayerScout />)
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
  })

  it('clicking a player row opens a detail dialog with its xP breakdown', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Goals')).toBeInTheDocument()
    expect(within(dialog).getByText('+3.20')).toBeInTheDocument()
  })

  it('closing the dialog removes it', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    await user.click(screen.getByText('Erling Haaland'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.click(screen.getByLabelText('Close'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('breakdown omits near-zero components', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByText('Clean sheet')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('Saves')).not.toBeInTheDocument()
  })

  it('passes gwStart/gwEnd from the inputs to usePlayers', async () => {
    const spy = vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '5')

    expect(spy).toHaveBeenLastCalledWith(1, 5)
  })

  it('the four breakdown columns are always visible, no toggle needed', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)

    expect(screen.getByRole('columnheader', { name: 'Goals' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Assists' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Clean sheet' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Def. contribution' })).toBeInTheDocument()

    const salahRow = screen.getByText('Mohamed Salah').closest('tr')!
    expect(within(salahRow).getByText('0.30')).toBeInTheDocument() // defcon_pts, visible with no click needed
  })

  it('clicking a column header sorts by it, and clicking again reverses direction', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /def\. contribution/i }))
    let rows = screen.getAllByRole('row').slice(1)
    // Salah and van Dijk tie at defcon_pts=0.3 (both > Haaland's 0) -- either
    // could legitimately lead, but Haaland (0) must be last.
    expect(rows[2]).toHaveTextContent('Erling Haaland')

    await user.click(screen.getByRole('button', { name: /def\. contribution/i })) // reverse
    rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Erling Haaland')
  })

  it('filters by team', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.selectOptions(screen.getByDisplayValue('All teams'), 'Man City')
    expect(screen.getByText('Erling Haaland')).toBeInTheDocument()
    expect(screen.queryByText('Mohamed Salah')).not.toBeInTheDocument()
  })

  it('filters by price range', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('Min'), '10')
    // Haaland (15.5) and Salah (13.0) pass; van Dijk (6.5) is filtered out
    expect(screen.getByText('Erling Haaland')).toBeInTheDocument()
    expect(screen.getByText('Mohamed Salah')).toBeInTheDocument()
    expect(screen.queryByText('Virgil van Dijk')).not.toBeInTheDocument()
  })

  it('a second sort level breaks ties from the first (e.g. DefCon then price)', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()


    // Primary: click the Def. contribution header (Salah and van Dijk tie at
    // 0.3, both ahead of Haaland's 0). Secondary: price ascending, to break
    // that tie -- van Dijk (£6.5m) should rank above Salah (£13.0m) despite
    // equal DefCon. The header click is the simpler, now-primary mechanism
    // for setting sort; the dropdown builder still handles the secondary tiebreaker.
    await user.click(screen.getByRole('button', { name: /def\. contribution/i }))
    await user.click(screen.getByText(/add sort level/i))

    const combosAfter = screen.getAllByRole('combobox')
    const secondarySelect = combosAfter[combosAfter.length - 1] // the newly-added level's select
    await user.selectOptions(secondarySelect, 'price')
    await user.click(screen.getByLabelText('Toggle sort direction for level 2')) // desc -> asc

    const rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Virgil van Dijk')
    expect(rows[1]).toHaveTextContent('Mohamed Salah')
    expect(rows[2]).toHaveTextContent('Erling Haaland')
  })

  it('opening a player dialog shows xP broken down by gameweek', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    // Need a multi-gameweek range for the per-GW panel to be meaningful
    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '3')

    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    // Table now, not cards -- GW numbers are their own column (no "GW" prefix
    // per-row, just a "GW" header), so check the row structure + values instead.
    const rows = within(dialog).getAllByRole('row').slice(1) // skip header row
    expect(rows).toHaveLength(3)
    expect(within(dialog).getByText('4.2')).toBeInTheDocument() // his GW3 value
  })

  it('sorting by a specific gameweek surfaces a player who is NOT the overall xP leader', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '3')

    // Default sort (overall xP) has Haaland first. Van Dijk has the LOWEST
    // overall xP but the single BEST gameweek (GW2, 3.0) of anyone -- sorting
    // by GW2 specifically should surface him first instead.
    let rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Erling Haaland')

    const primarySelect = screen.getAllByRole('combobox').find(
      (el) => within(el as HTMLElement).queryByText('GW2')
    )!
    await user.selectOptions(primarySelect, 'gw:2')

    rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Virgil van Dijk')
  })
})
