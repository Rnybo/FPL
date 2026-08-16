import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FixtureSwing from '../FixtureSwing'
import * as hooks from '../../api/hooks'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// GW1 is FINISHED (in the past) -- must NOT influence the "current gw"
// default, which should land on GW2 (the earliest UNPLAYED gameweek).
// Easy FC faces easy opponents (FDR 1, 2) in GW2-3; Hard FC faces hard
// opponents (FDR 5, 4) in the same window -- a clear, unambiguous swing.
// Blank FC only has a fixture in GW1 (finished) -- none at all inside the
// default upcoming window, so it should show "No fixtures in this range"
// and sort last regardless of direction.
const MOCK_FIXTURES = {
  season: '2026-27',
  fixtures: [
    { fixture_id: 1, gw: 1, kickoff_time: '2026-08-01T14:00:00Z', finished: 1,
      home_team: 'Blank FC', away_team: 'Filler United', home_difficulty: 3, away_difficulty: 3,
      home_goals: 1, away_goals: 1 },
    { fixture_id: 2, gw: 2, kickoff_time: '2026-08-08T14:00:00Z', finished: 0,
      home_team: 'Easy FC', away_team: 'Filler United', home_difficulty: 1, away_difficulty: 3,
      home_goals: null, away_goals: null },
    { fixture_id: 3, gw: 2, kickoff_time: '2026-08-08T16:00:00Z', finished: 0,
      home_team: 'Filler Rovers', away_team: 'Hard FC', home_difficulty: 3, away_difficulty: 5,
      home_goals: null, away_goals: null },
    { fixture_id: 4, gw: 3, kickoff_time: '2026-08-15T14:00:00Z', finished: 0,
      home_team: 'Easy FC', away_team: 'Filler Rovers', home_difficulty: 2, away_difficulty: 3,
      home_goals: null, away_goals: null },
    { fixture_id: 5, gw: 3, kickoff_time: '2026-08-15T16:00:00Z', finished: 0,
      home_team: 'Hard FC', away_team: 'Filler United', home_difficulty: 4, away_difficulty: 3,
      home_goals: null, away_goals: null },
  ],
}

describe('FixtureSwing', () => {
  it('shows a loading state', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: undefined, isLoading: true, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows an error state', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({
      data: undefined, isLoading: false, isError: true, error: new Error('network down'),
    } as never)
    renderWithClient(<FixtureSwing />)
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
  })

  it('defaults the GW range to the earliest UNPLAYED gameweek onward, ignoring finished GW1', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const [fromInput, toInput] = screen.getAllByRole('spinbutton')
    expect(fromInput).toHaveValue(2) // NOT 1 -- GW1 is already finished
    expect(toInput).toHaveValue(9) // 2 + DEFAULT_WINDOW(8) - 1
  })

  it('ranks teams by average FDR ascending (easiest run first) by default', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    const rows = screen.getAllByRole('row').slice(1) // skip header
    const easyRowIndex = rows.findIndex((r) => within(r).queryByText('Easy FC'))
    const hardRowIndex = rows.findIndex((r) => within(r).queryByText('Hard FC'))
    expect(easyRowIndex).toBeGreaterThanOrEqual(0)
    expect(hardRowIndex).toBeGreaterThan(easyRowIndex) // Easy FC's easier run ranks above Hard FC's

    const easyRow = rows[easyRowIndex]
    expect(within(easyRow).getByText('1.50')).toBeInTheDocument() // (1 + 2) / 2
    const hardRow = rows[hardRowIndex]
    expect(within(hardRow).getByText('4.50')).toBeInTheDocument() // (5 + 4) / 2
  })

  it('a team with no fixtures in the window shows "No fixtures in this range" and sorts last', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    const blankRow = screen.getByText('Blank FC').closest('tr')!
    expect(within(blankRow).getByText(/no fixtures in this range/i)).toBeInTheDocument()
    expect(within(blankRow).getByText('—')).toBeInTheDocument()

    const rows = screen.getAllByRole('row').slice(1)
    expect(rows[rows.length - 1]).toHaveTextContent('Blank FC') // always last, both sort directions
  })

  it('clicking the Avg FDR header reverses the ranking -- hardest run first', async () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /avg fdr/i }))

    const rows = screen.getAllByRole('row').slice(1)
    const easyRowIndex = rows.findIndex((r) => within(r).queryByText('Easy FC'))
    const hardRowIndex = rows.findIndex((r) => within(r).queryByText('Hard FC'))
    expect(hardRowIndex).toBeLessThan(easyRowIndex) // now Hard FC (harder run) ranks first
  })

  it('narrowing the GW range via Apply recomputes the average for just that window', async () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const user = userEvent.setup()

    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '2') // narrow to JUST GW2
    await user.click(screen.getByRole('button', { name: /apply/i }))

    const easyRow = screen.getByText('Easy FC').closest('tr')!
    expect(within(easyRow).getByText('1.00')).toBeInTheDocument() // only GW2's FDR 1 now, not averaged with GW3
  })

  it('each fixture cell has a tooltip identifying the gameweek, opponent, and venue', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    const easyRow = screen.getByText('Easy FC').closest('tr')!
    // Easy FC's first fixture in the window: GW2, home vs Filler United, FDR 1.
    const cell = within(easyRow).getByTitle('GW2: vs Filler United (FDR 1)')
    expect(cell).toBeInTheDocument()
  })
})
