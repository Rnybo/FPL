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
//
// Easy FC faces easy opponents (FDR 1, 2) in GW2-3; Hard FC faces hard
// opponents (FDR 5, 4) in the same window -- a clear, unambiguous swing.
// Blank FC only has a fixture in GW1 (finished) -- none at all inside the
// default upcoming window, so it should show "No fixtures in this range"
// and sort last regardless of direction.
//
// GW4: Easy FC plays TWICE (a double), Hard FC plays ZERO times (a blank) --
// backs the Double & Blank Gameweeks calendar section.
//
// recent_form below is deliberately set up so Easy FC's NEXT fixture (GW2)
// is HOME and only has home-split data, while Hard FC's NEXT fixture (GW2)
// is AWAY and only has away-split data -- exercises BOTH the "(H)" and
// "(A)" contextual paths on the main table.
const MOCK_FIXTURES = {
  season: '2026-27',
  fixtures: [
    { fixture_id: 1, gw: 1, kickoff_time: '2026-08-01T14:00:00Z', finished: 1,
      home_team: 'Blank FC', away_team: 'Filler United', home_difficulty: 3, away_difficulty: 3,
      home_goals: 1, away_goals: 1, home_clean_sheet_prob: null, away_clean_sheet_prob: null },
    { fixture_id: 2, gw: 2, kickoff_time: '2026-08-08T14:00:00Z', finished: 0,
      home_team: 'Easy FC', away_team: 'Filler United', home_difficulty: 1, away_difficulty: 3,
      home_goals: null, away_goals: null, home_clean_sheet_prob: 0.6, away_clean_sheet_prob: 0.1 },
    { fixture_id: 3, gw: 2, kickoff_time: '2026-08-08T16:00:00Z', finished: 0,
      home_team: 'Filler Rovers', away_team: 'Hard FC', home_difficulty: 3, away_difficulty: 5,
      home_goals: null, away_goals: null, home_clean_sheet_prob: 0.3, away_clean_sheet_prob: 0.05 },
    { fixture_id: 4, gw: 3, kickoff_time: '2026-08-15T14:00:00Z', finished: 0,
      home_team: 'Easy FC', away_team: 'Filler Rovers', home_difficulty: 2, away_difficulty: 3,
      home_goals: null, away_goals: null, home_clean_sheet_prob: 0.5, away_clean_sheet_prob: 0.15 },
    { fixture_id: 5, gw: 3, kickoff_time: '2026-08-15T16:00:00Z', finished: 0,
      home_team: 'Hard FC', away_team: 'Filler United', home_difficulty: 4, away_difficulty: 3,
      home_goals: null, away_goals: null, home_clean_sheet_prob: 0.2, away_clean_sheet_prob: 0.25 },
    { fixture_id: 8, gw: 4, kickoff_time: '2026-08-22T14:00:00Z', finished: 0,
      home_team: 'Easy FC', away_team: 'Filler United', home_difficulty: 2, away_difficulty: 3,
      home_goals: null, away_goals: null, home_clean_sheet_prob: null, away_clean_sheet_prob: null },
    { fixture_id: 9, gw: 4, kickoff_time: '2026-08-22T16:00:00Z', finished: 0,
      home_team: 'Filler Rovers', away_team: 'Easy FC', home_difficulty: 3, away_difficulty: 2,
      home_goals: null, away_goals: null, home_clean_sheet_prob: null, away_clean_sheet_prob: null },
  ],
  recent_form: {
    'Easy FC': { home_gf_per_game: 3.0, home_ga_per_game: 0.0, home_games: 1, away_gf_per_game: null, away_ga_per_game: null, away_games: 0 },
    'Hard FC': { home_gf_per_game: null, home_ga_per_game: null, home_games: 0, away_gf_per_game: 0.5, away_ga_per_game: 2.5, away_games: 1 },
  },
  last_season_team_stats: {
    'Easy FC': {
      goals_for_home: 40, goals_for_away: 20, goals_against_home: 10, goals_against_away: 25,
      clean_sheets_home: 10, clean_sheets_away: 3, clean_sheets_total: 13,
      games_home: 19, games_away: 19,
      favorable_opponents: [{ opponent: 'Hard FC', avg_goal_diff: 3.0, games: 2, next_gw: 5 }],
      unfavorable_opponents: [{ opponent: 'Filler Rovers', avg_goal_diff: -1.0, games: 2, next_gw: null }],
    },
  },
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

    // Easy FC's window (default GW2-9) includes GW2(FDR1), GW3(FDR2), and
    // GW4's DOUBLE (FDR2 + FDR2) = (1+2+2+2)/4 = 1.75. Hard FC's window
    // includes GW2(FDR5), GW3(FDR4) only -- no GW4 fixture at all (a blank)
    // = (5+4)/2 = 4.50.
    const easyRow = rows[easyRowIndex]
    expect(within(easyRow).getByText('1.75')).toBeInTheDocument()
    const hardRow = rows[hardRowIndex]
    expect(within(hardRow).getByText('4.50')).toBeInTheDocument()
  })

  it('a team with no fixtures in the window shows "No fixtures in this range" and sorts last', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    const blankRow = screen.getByText('Blank FC').closest('tr')!
    expect(within(blankRow).getByText(/no fixtures in this range/i)).toBeInTheDocument()

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
    expect(within(easyRow).getByText('1.00')).toBeInTheDocument() // only GW2's FDR 1 now, not averaged with GW3/GW4
  })

  it('each fixture cell has a tooltip identifying the gameweek, opponent, and venue', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    const easyRow = screen.getByText('Easy FC').closest('tr')!
    // Easy FC's first fixture in the window: GW2, home vs Filler United, FDR 1.
    const cell = within(easyRow).getByTitle('GW2: vs Filler United (FDR 1)')
    expect(cell).toBeInTheDocument()
  })

  it('shows each team\'s next clean-sheet %, sourced from the fixture nearest the start of the window', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    const easyRow = screen.getByText('Easy FC').closest('tr')!
    expect(within(easyRow).getByText('60%')).toBeInTheDocument() // GW2 home_clean_sheet_prob 0.6

    const hardRow = screen.getByText('Hard FC').closest('tr')!
    expect(within(hardRow).getByText('5%')).toBeInTheDocument() // GW2 away_clean_sheet_prob 0.05
  })

  it('sorting by Next CS% ranks by clean-sheet chance, highest first by default', async () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /next cs%/i }))
    const rows = screen.getAllByRole('row').slice(1)
    const easyRowIndex = rows.findIndex((r) => within(r).queryByText('Easy FC'))
    const hardRowIndex = rows.findIndex((r) => within(r).queryByText('Hard FC'))
    expect(easyRowIndex).toBeLessThan(hardRowIndex) // 60% ranks above 5%
  })

  it('GF (next)/GA (next) show whichever venue split matches each team\'s actual next fixture, with an (H)/(A) badge', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    // Easy FC's next fixture (GW2) is HOME -> shows the home split.
    const easyRow = screen.getByText('Easy FC').closest('tr')!
    expect(within(easyRow).getByText('3.00')).toBeInTheDocument()
    expect(within(easyRow).getByText('0.00')).toBeInTheDocument()
    expect(within(easyRow).getAllByText('(H)').length).toBeGreaterThan(0)

    // Hard FC's next fixture (GW2) is AWAY -> shows the away split, not home.
    const hardRow = screen.getByText('Hard FC').closest('tr')!
    expect(within(hardRow).getByText('0.50')).toBeInTheDocument()
    expect(within(hardRow).getByText('2.50')).toBeInTheDocument()
    expect(within(hardRow).getAllByText('(A)').length).toBeGreaterThan(0)
  })

  it('a team with no recent_form entry at all shows "—" for GF (next)/GA (next), not a crash', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    // Blank FC has no entry in recent_form at all (see MOCK_FIXTURES).
    const blankRow = screen.getByText('Blank FC').closest('tr')!
    const cells = within(blankRow).getAllByRole('cell')
    expect(cells[cells.length - 2]).toHaveTextContent('—') // GF (next)
    expect(cells[cells.length - 1]).toHaveTextContent('—') // GA (next)
  })

  it('lists upcoming double and blank gameweeks', () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)

    expect(screen.getByText(/double & blank gameweeks/i)).toBeInTheDocument()
    const gw4Row = screen.getByText('GW4').closest('div')!
    expect(within(gw4Row).getByText(/easy fc/i)).toBeInTheDocument() // double
    expect(within(gw4Row).getByText(/hard fc/i)).toBeInTheDocument() // blank
  })

  it('omits the Double & Blank Gameweeks section entirely when there are none upcoming', () => {
    // A deliberately isolated, minimal dataset -- reusing MOCK_FIXTURES
    // filtered down would still show Blank FC as "blank" in GW2/GW3 (it
    // only ever plays in GW1), which isn't what this test is about. Two
    // teams, one gameweek, each playing exactly once -- genuinely nothing
    // to report.
    const cleanFixtures = {
      season: '2026-27',
      fixtures: [
        { fixture_id: 100, gw: 1, kickoff_time: '2026-08-08T14:00:00Z', finished: 0,
          home_team: 'Team A', away_team: 'Team B', home_difficulty: 3, away_difficulty: 3,
          home_goals: null, away_goals: null, home_clean_sheet_prob: null, away_clean_sheet_prob: null },
      ],
    }
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: cleanFixtures, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    expect(screen.queryByText(/double & blank gameweeks/i)).not.toBeInTheDocument()
  })

  it('clicking a team row opens its detail modal with full home/away form and last-season stats', async () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const user = userEvent.setup()

    await user.click(screen.getByText('Easy FC'))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Easy FC' })).toBeInTheDocument()

    // Last season stats made it into the modal
    expect(within(dialog).getByText('40')).toBeInTheDocument() // goals_for_home
    expect(within(dialog).getByText('13')).toBeInTheDocument() // clean_sheets_total
    expect(within(dialog).getByText(/hard fc/i)).toBeInTheDocument() // favorable opponent
    expect(within(dialog).getByText(/filler rovers/i)).toBeInTheDocument() // unfavorable opponent
  })

  it('closes the team detail modal', async () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const user = userEvent.setup()

    await user.click(screen.getByText('Easy FC'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.click(screen.getByLabelText('Close'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('a team with no last_season_team_stats entry shows the empty state in its detail modal, not a crash', async () => {
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<FixtureSwing />)
    const user = userEvent.setup()

    await user.click(screen.getByText('Hard FC')) // no last_season_team_stats entry in the mock
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/no last-season data/i)).toBeInTheDocument()
  })
})
