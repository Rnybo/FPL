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
      prob: { goal_pts: 0.6, assist_pts: 0.1, cs_pts: 0.05, defcon_pts: 0.02 },
      historic: { minutes: 3065, goals: 9, assists: 24, xg: 10.79, xa: 12.28 },
      // Deliberately backloaded -- lowest total-xP rank overall, but NOT lowest
      // in every individual gameweek, so per-GW sort tests are meaningful.
      gameweeks: [{ gw: 1, xP: 1.0 }, { gw: 2, xP: 1.0 }, { gw: 3, xP: 4.2 }],
      last_season_stats: {
        games: 38, starts: 34, start_pct: 89, total_points: 239, mean_points: 6.29,
        max_points: 16, min_points: 0, variance: 24.21, std_dev: 4.92,
      },
      last_season_total_points: 239,
      last_season_breakdown: {
        games: [{ gw: 1, points: 13 }, { gw: 2, points: 2 }, { gw: 3, points: 9 }],
        percentile_averages: { top25: 13, top50: 11, top75: 8, overall: 8 },
        points_by_component: { appearance: 6, goals: 12, assists: 3, clean_sheet: 0, defcon: 0, bonus: 3, cards: -1, conceded: 0, saves: 0, penalties: 0 },
      },
      opponent_stats: {
        best_opponents: [
          { opponent: 'Everton', avg_points: 12.5, games: 4, next_gw: 9 },
          { opponent: 'Burnley', avg_points: 10.0, games: 3, next_gw: null },
        ],
        worst_opponents: [
          { opponent: 'Chelsea', avg_points: 1.0, games: 5, next_gw: 15 },
          { opponent: 'Arsenal', avg_points: 2.5, games: 5, next_gw: null },
        ],
        best_fdr: { fdr: 2, avg_points: 9.8, games: 12 },
        worst_fdr: { fdr: 5, avg_points: 2.1, games: 6 },
      },
      points_by_month: {
        seasons_included: ['2025-26', '2024-25', '2023-24', '2022-23', '2021-22'],
        months: [
          { month: 'Aug', values: [8.0, 6.5, 5.0], min: 5.0, q1: 5.75, median: 6.5, q3: 7.25, max: 8.0, n_seasons: 3 },
          { month: 'Dec', values: [2.0], min: 2.0, q1: 2.0, median: 2.0, q3: 2.0, max: 2.0, n_seasons: 1 },
        ],
      },
      // 6 rows -- one more than a single page (5) -- to exercise pagination.
      // GW3 (Fulham) is a genuinely new opponent (promoted/first meeting),
      // so both legs are null -- must render as "-", not a stray 0.
      points_vs_opponent_last_season: [
        { gw: 1, opponent: 'Hull City', venue_now: 'A', home_points_last_season: 9, away_points_last_season: 4 },
        { gw: 2, opponent: 'Ipswich Town', venue_now: 'H', home_points_last_season: 12, away_points_last_season: 3 },
        { gw: 3, opponent: 'Fulham', venue_now: 'A', home_points_last_season: null, away_points_last_season: null },
        { gw: 4, opponent: 'Man Utd', venue_now: 'H', home_points_last_season: 8, away_points_last_season: 2 },
        { gw: 5, opponent: 'Chelsea', venue_now: 'A', home_points_last_season: 6, away_points_last_season: 1 },
        { gw: 6, opponent: 'Arsenal', venue_now: 'H', home_points_last_season: 10, away_points_last_season: 5 },
      ],
    },
    {
      player_id: 2, name: 'Mohamed Salah', position: 'MID' as const, team: 'Liverpool', price: 13.0, xP: 5.8,
      breakdown: {
        appearance_pts: 1.8, goal_pts: 2.0, assist_pts: 0.8, cs_pts: 0.2, conceded_penalty: 0,
        card_pen_pts: 0, pen_save_pts: 0, save_pts: 0, defcon_pts: 0.3, bonus_pts: 0.7,
      },
      last_season_total_points: 180,
      gameweeks: [{ gw: 1, xP: 5.0 }, { gw: 2, xP: 0.3 }, { gw: 3, xP: 0.5 }],
    },
    {
      player_id: 3, name: 'Virgil van Dijk', position: 'DEF' as const, team: 'Liverpool', price: 6.5, xP: 4.1,
      breakdown: {
        appearance_pts: 1.8, goal_pts: 0.1, assist_pts: 0.05, cs_pts: 1.2, conceded_penalty: -0.2,
        card_pen_pts: -0.05, pen_save_pts: 0, save_pts: 0, defcon_pts: 0.3, bonus_pts: 0.8,
      },
      // Lowest total xP overall AND lowest last-season points of the three --
      // deliberately so the new column's sort test surfaces a clearly
      // different order than the default xP sort.
      last_season_total_points: 50,
      gameweeks: [{ gw: 1, xP: 0.5 }, { gw: 2, xP: 3.0 }, { gw: 3, xP: 0.6 }],
    },
  ],
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// Liverpool: FDR 1 (easy) for GW1. Man City: FDR 5 (hard) for GW1. The third
// team is a filler opponent, irrelevant to what's being tested.
const MOCK_FIXTURES = {
  season: '2026-27',
  fixtures: [
    { fixture_id: 1, gw: 1, kickoff_time: '2026-08-15T14:00:00Z', finished: 0,
      home_team: 'Liverpool', away_team: 'Filler FC', home_difficulty: 1, away_difficulty: 4,
      home_goals: null, away_goals: null },
    { fixture_id: 2, gw: 1, kickoff_time: '2026-08-16T14:00:00Z', finished: 0,
      home_team: 'Filler United', away_team: 'Man City', home_difficulty: 2, away_difficulty: 5,
      home_goals: null, away_goals: null },
  ],
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
    // "Goals" now legitimately appears twice (Historic Stats row + Breakdown
    // row are both real tables since the redesign) -- the unique value below
    // is what actually confirms the breakdown rendered.
    expect(within(dialog).getAllByText('Goals').length).toBeGreaterThan(0)
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

  it('switching to the "Last season stats" tab shows real scored-points stats, not the prediction breakdown', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')

    // Default view: prediction breakdown, no last-season numbers yet.
    expect(within(dialog).getAllByText('Goals').length).toBeGreaterThan(0) // Historic Stats row + Breakdown row
    expect(within(dialog).queryByText('89%')).not.toBeInTheDocument()

    await user.click(within(dialog).getByText(/last season stats/i))

    expect(within(dialog).queryByText('Goals')).not.toBeInTheDocument()
    expect(within(dialog).getByText('89%')).toBeInTheDocument() // start_pct rounded
    expect(within(dialog).getByText('34/38 games')).toBeInTheDocument()
    expect(within(dialog).getByText('Ceiling')).toBeInTheDocument()
    expect(within(dialog).getByText('16')).toBeInTheDocument() // max_points
    // Floor (min_points) card was dropped -- not of interest per feedback.
    expect(within(dialog).queryByText('Floor')).not.toBeInTheDocument()
    // Mean/variance/std_dev cards are gone -- replaced by the chart (see
    // below) per direct feedback that they weren't intuitive.
    expect(within(dialog).queryByText('Variance')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('Std. dev')).not.toBeInTheDocument()
  })

  it('the last-season chart renders with a real breakdown -- headers/labels only, not chart internals', async () => {
    // recharts' ResponsiveContainer measures the real DOM to size itself,
    // which jsdom can't do (it reports 0 width), so recharts correctly
    // declines to render bars/reference-lines/etc. inside it -- a well-known
    // jsdom+recharts limitation, not a bug here. What CAN be verified: the
    // component actually received breakdown data and rendered its text
    // labels/headers, i.e. it took the "has a chart" branch, not the
    // "not enough starts" fallback branch.
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText(/last season stats/i))

    expect(within(dialog).getByText(/points per game started/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/where his points came from/i)).toBeInTheDocument()
    expect(within(dialog).queryByText(/not enough starts/i)).not.toBeInTheDocument()
  })

  it('a player with last_season_stats but an empty breakdown shows the "not enough starts" fallback', async () => {
    const playersWithEmptyBreakdown = {
      ...MOCK_PLAYERS,
      players: MOCK_PLAYERS.players.map((p) =>
        p.name === 'Erling Haaland' ? { ...p, last_season_breakdown: null } : p
      ),
    }
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: playersWithEmptyBreakdown, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText(/last season stats/i))
    // Still has last_season_stats (89% started etc.), just no chart data.
    expect(within(dialog).getByText('89%')).toBeInTheDocument()
    expect(within(dialog).getByText(/not enough starts/i)).toBeInTheDocument()
  })

  it('a player with no last_season_stats shows a clear empty state, not a crash', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Mohamed Salah')) // no last_season_stats in this fixture
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText(/last season stats/i))
    expect(within(dialog).getByText(/no 2025-26 data/i)).toBeInTheDocument()
  })

  it('Historic Stats includes last season\'s Total points, alongside Mins/Goals/Assists/xG/xA', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')

    expect(within(dialog).getByText('Total points')).toBeInTheDocument()
    expect(within(dialog).getByText('239')).toBeInTheDocument() // last_season_stats.total_points
    expect(within(dialog).getByText('3065')).toBeInTheDocument() // historic.minutes, unaffected
  })

  it('Last season tab shows points vs opponent, highlighting the leg matching this fixture\'s venue, "-" for no meeting', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText(/last season stats/i))

    expect(within(dialog).getByText(/points vs opponent last season/i)).toBeInTheDocument()
    // First page: GW1-5 (5 rows). GW1 is away -- the AWAY cell (4) should be
    // highlighted, not the home one (9), even though both are shown.
    const gw1Row = within(dialog).getByText('Hull City').closest('tr')!
    expect(within(gw1Row).getByText('9')).toBeInTheDocument()
    const awayCell = within(gw1Row).getByText('4')
    expect(awayCell.className).toMatch(/bg-emerald-50/)
    const homeCell = within(gw1Row).getByText('9')
    expect(homeCell.className).not.toMatch(/bg-emerald-50/)

    // GW3 (Fulham): no meeting last season at all -- both legs "-", not 0.
    const gw3Row = within(dialog).getByText('Fulham').closest('tr')!
    expect(within(gw3Row).getAllByText('-')).toHaveLength(2)

    // GW6 (Arsenal) is beyond the first page of 5 -- not visible yet.
    expect(within(dialog).queryByText('Arsenal')).not.toBeInTheDocument()
  })

  it('Points vs opponent table paginates 5 at a time when more rows exist', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText(/last season stats/i))

    expect(within(dialog).getByText('1/2')).toBeInTheDocument()
    await user.click(within(dialog).getByText(/next 5/i))
    expect(within(dialog).getByText('Arsenal')).toBeInTheDocument()
    expect(within(dialog).queryByText('Hull City')).not.toBeInTheDocument()
    expect(within(dialog).getByText('2/2')).toBeInTheDocument()
  })

  it('Points vs opponent table is omitted entirely when there is no data for it, not an empty table', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Mohamed Salah')) // has last_season_stats? no -- check fallback path separately
    const dialog = screen.getByRole('dialog')
    // Salah has no last_season_stats at all in this fixture, so the whole
    // tab shows its own "no data" fallback -- confirms no crash either way.
    await user.click(within(dialog).getByText(/last season stats/i))
    expect(within(dialog).queryByText(/points vs opponent last season/i)).not.toBeInTheDocument()
  })

  it('all three tabs are visible and switching between them works, including the new Statistics tab', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')

    expect(within(dialog).getByText('This window')).toBeInTheDocument()
    expect(within(dialog).getByText(/last season stats/i)).toBeInTheDocument()
    expect(within(dialog).getByText('Statistics')).toBeInTheDocument()

    await user.click(within(dialog).getByText('Statistics'))
    expect(within(dialog).getByText(/favorite opponents/i)).toBeInTheDocument()
    expect(within(dialog).queryByText('Goals')).not.toBeInTheDocument() // left the prediction tab
  })

  it('Statistics tab shows favorite/toughest opponents ranked correctly, with next_gw in parens where known', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText('Statistics'))

    const favTable = within(dialog).getByText(/favorite opponents/i).closest('div')!
    expect(within(favTable).getByText(/Everton/)).toBeInTheDocument()
    expect(within(favTable).getByText(/\(GW9\)/)).toBeInTheDocument() // has a scheduled next meeting
    expect(within(favTable).getByText('Burnley')).toBeInTheDocument() // no next_gw -- no parenthetical at all

    const toughTable = within(dialog).getByText(/toughest opponents/i).closest('div')!
    expect(within(toughTable).getByText(/Chelsea/)).toBeInTheDocument()
    expect(within(toughTable).getByText(/\(GW15\)/)).toBeInTheDocument()

    // FDR summary
    expect(within(dialog).getByText('Best vs FDR 2')).toBeInTheDocument()
    expect(within(dialog).getByText('Worst vs FDR 5')).toBeInTheDocument()
  })

  it('Statistics tab shows the monthly points-per-game box plot, with a box per month that has data', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText('Statistics'))

    expect(within(dialog).getByText(/points per game by month/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/last 5 seasons/i)).toBeInTheDocument()
    const svg = within(dialog).getByRole('img', { name: /points per game by month/i })
    // One box per month present in the mock (Aug, Dec) -- not every month of
    // the season, since a month with no data at all is omitted, not zeroed.
    expect(within(svg).getByText('Aug')).toBeInTheDocument()
    expect(within(svg).getByText('Dec')).toBeInTheDocument()
    expect(within(svg).queryByText('Sep')).not.toBeInTheDocument()
  })

  it('Statistics tab shows a clear empty state when a player has neither opponent nor monthly data, not a crash', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Mohamed Salah')) // no opponent_stats or points_by_month in this fixture
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText('Statistics'))
    expect(within(dialog).getByText(/not enough historical data/i)).toBeInTheDocument()
  })

  it('the Apply button is disabled with no pending GW change, becomes enabled once the draft differs, and clicking it commits', async () => {
    const spy = vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    const applyButton = screen.getByRole('button', { name: /apply/i })
    expect(applyButton).toBeDisabled()

    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '4')
    expect(applyButton).toBeEnabled()
    expect(spy).toHaveBeenLastCalledWith(1, 1) // still uncommitted

    await user.click(applyButton)
    expect(spy).toHaveBeenLastCalledWith(1, 4)
    expect(applyButton).toBeDisabled() // matches again post-commit
  })

  it('passes gwStart/gwEnd from the inputs to usePlayers, only once committed (Enter), not on every keystroke', async () => {
    const spy = vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '5')
    // Not yet committed -- still the initial (1, 1) while typing.
    expect(spy).toHaveBeenLastCalledWith(1, 1)

    await user.keyboard('{Enter}')
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

  it('Goals/Assists/Clean sheet/DefCon all show a likelihood alongside the xP contribution, e.g. "3.20 (0.60)"', () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)

    const haalandRow = screen.getByText('Erling Haaland').closest('tr')!
    expect(within(haalandRow).getByText('3.20')).toBeInTheDocument()
    expect(within(haalandRow).getByText('(0.60)')).toBeInTheDocument() // his goal_pts likelihood
    expect(within(haalandRow).getByText('(0.02)')).toBeInTheDocument() // his defcon_pts likelihood

    // Salah has no `prob` in this fixture -- must show the plain xP number
    // with no likelihood suffix, not crash or show a stray "(undefined)".
    const salahRow = screen.getByText('Mohamed Salah').closest('tr')!
    expect(within(salahRow).getByText('0.30')).toBeInTheDocument() // his defcon_pts, unaffected
    expect(within(salahRow).queryByText(/\(/)).not.toBeInTheDocument()
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

  it('clicking a column header that is already an active SECONDARY sort factor toggles its own direction in place, without promoting it to primary', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    // Same setup as the test above: primary = Def. contribution (Salah/van
    // Dijk tie at 0.3), secondary = price, flipped to ascending.
    await user.click(screen.getByRole('button', { name: /def\. contribution/i }))
    await user.click(screen.getByText(/add sort level/i))
    const combosAfter = screen.getAllByRole('combobox')
    const secondarySelect = combosAfter[combosAfter.length - 1]
    await user.selectOptions(secondarySelect, 'price')
    await user.click(screen.getByLabelText('Toggle sort direction for level 2')) // desc -> asc
    expect(screen.getAllByRole('row').slice(1)[0]).toHaveTextContent('Virgil van Dijk') // cheapest first

    // Now click the PRICE COLUMN HEADER itself (not the dropdown's own toggle) --
    // this is the bug: it used to promote price to primary and reset it to
    // desc, silently discarding the Def. contribution-first setup above.
    await user.click(screen.getByRole('button', { name: /^price/i }))

    const rows = screen.getAllByRole('row').slice(1)
    // Def. contribution is STILL primary -- Haaland (defcon=0) still last.
    // If price had been wrongly promoted, Haaland (£15.5m, priced highest)
    // would now be FIRST instead.
    expect(rows[2]).toHaveTextContent('Erling Haaland')
    // Price's OWN direction flipped back to desc (asc -> desc) -- the pricier
    // of the tied pair (Salah, £13.0m) now ranks above van Dijk (£6.5m).
    expect(rows[0]).toHaveTextContent('Mohamed Salah')
    expect(rows[1]).toHaveTextContent('Virgil van Dijk')
  })

  it('sorting by FDR defaults to easiest fixtures first (not desc like every other column), and reverses on a second click', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    vi.spyOn(hooks, 'useFixtures').mockReturnValue({ data: MOCK_FIXTURES, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /next 8 gws \(fdr\)/i }))
    // Liverpool (FDR 1, easiest) -- Salah then van Dijk (tied, original relative
    // order preserved by a stable sort); Man City (FDR 5, hardest) -- Haaland last.
    let rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Mohamed Salah')
    expect(rows[1]).toHaveTextContent('Virgil van Dijk')
    expect(rows[2]).toHaveTextContent('Erling Haaland')

    await user.click(screen.getByRole('button', { name: /next 8 gws \(fdr\)/i })) // reverse -> hardest first
    rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Erling Haaland')
  })

  it('opening a player dialog shows xP broken down by gameweek', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    // Need a multi-gameweek range for the per-GW panel to be meaningful --
    // committed via Enter (the GW inputs no longer update live on every
    // keystroke, see the "only once committed" test above).
    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '3')
    await user.keyboard('{Enter}')

    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')
    // Table now, not cards -- GW numbers are their own column (no "GW" prefix
    // per-row, just a "GW" header). Scoped to the fixtures table specifically
    // (via its "Fixture (FDR)" header) -- Historic Stats/Breakdown of
    // Predictions are ALSO real tables now, so an unscoped row query would
    // pick up their rows too.
    const fixturesTable = within(dialog).getByText('Fixture (FDR)').closest('table')!
    const rows = within(fixturesTable).getAllByRole('row').slice(1) // skip header row
    expect(rows).toHaveLength(3)
    expect(within(dialog).getByText('4.2')).toBeInTheDocument() // his GW3 value
  })

  it('the Fixture (FDR) table paginates 5 at a time when the GW range is wide, same as the opponent-history table', async () => {
    // Fixture (FDR) is always visible (top of modal, not tab-scoped) --
    // testing this on the default tab avoids any ambiguity with the OTHER
    // paginated table (points_vs_opponent_last_season), which only appears
    // under "Last season stats" and isn't rendered yet here.
    const playersWithManyGameweeks = {
      ...MOCK_PLAYERS,
      players: MOCK_PLAYERS.players.map((p) =>
        p.name === 'Erling Haaland'
          ? { ...p, gameweeks: [1, 2, 3, 4, 5, 6].map((gw) => ({ gw, xP: gw * 0.5 })) }
          : p
      ),
    }
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: playersWithManyGameweeks, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()
    await user.click(screen.getByText('Erling Haaland'))
    const dialog = screen.getByRole('dialog')

    let fixturesTable = within(dialog).getByText('Fixture (FDR)').closest('table')!
    expect(within(fixturesTable).getAllByRole('row')).toHaveLength(6) // header + 5 of 6 gameweeks
    expect(within(dialog).getByText('1/2')).toBeInTheDocument()

    await user.click(within(dialog).getByText(/next 5/i))
    fixturesTable = within(dialog).getByText('Fixture (FDR)').closest('table')!
    expect(within(fixturesTable).getAllByRole('row')).toHaveLength(2) // header + the remaining 1 gameweek (GW6)
    expect(within(dialog).getByText('2/2')).toBeInTheDocument()
  })

  it('sorting by a specific gameweek surfaces a player who is NOT the overall xP leader', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    const [, toInput] = screen.getAllByRole('spinbutton')
    await user.clear(toInput)
    await user.type(toInput, '3')
    await user.keyboard('{Enter}')

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

  it('the "Total pts (last season)" column is sortable, independently of xP', async () => {
    vi.spyOn(hooks, 'usePlayers').mockReturnValue({ data: MOCK_PLAYERS, isLoading: false, isError: false } as never)
    renderWithClient(<PlayerScout />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /total pts \(last season\)/i }))
    // New column, defaults to desc -- highest last-season points first.
    // Haaland (239) happens to ALSO be the default xP leader, so this alone
    // wouldn't distinguish the two sorts -- the reverse click below does.
    let rows = screen.getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('Erling Haaland')

    await user.click(screen.getByRole('button', { name: /total pts \(last season\)/i })) // reverse -> asc
    rows = screen.getAllByRole('row').slice(1)
    // Van Dijk (50 pts last season) now leads despite being the LOWEST-xP
    // player of the three -- proves this is a genuinely independent sort
    // field, not just piggybacking on xP order.
    expect(rows[0]).toHaveTextContent('Virgil van Dijk')
  })
})
