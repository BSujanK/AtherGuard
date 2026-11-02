import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { GRID_FLAG, type Grid } from '../data/types'
import {
  alertsHandlers,
  cellAt,
  cellBody,
  forecastBody,
  forecastHistoryBody,
  gridToPayload,
  makeGrid,
  placeBody,
  syntheticGrid,
} from '../test/alertFixtures'
import { bytesToBase64, noDataMode, placesPayload, u32ToBase64 } from '../test/fixtures'
import Alerts from './Alerts'

vi.mock('../charts/EChart', () => ({
  default: ({ label }: { label: string }) => <div data-testid="chart" role="img" aria-label={label} />,
}))

const CELL = cellBody.cell_id
const HIMALAYA = cellAt(30.025, 80.025)
const rows = [
  { cell: CELL, risk: 4.52e-4, level: 3, confidence: 1 },
  { cell: CELL + 1, risk: 3e-5, level: 2, confidence: 0 },
  { cell: CELL - 10_000, risk: 1e-5, level: 1, confidence: 0 },
  { cell: HIMALAYA, risk: 2e-5, level: 2, confidence: 2 },
  { cell: HIMALAYA + 10_000, risk: 5e-6, level: 1, confidence: 1 },
  { cell: cellAt(12, 76), risk: 1e-8, level: 0, confidence: 0 },
]
const baseGrid = makeGrid(rows, '2024-07-30')

const mode = {
  mode: 'replay',
  set: 'case_wayanad_2024_samples',
  latest_date: '2024-07-30',
  dates: ['2024-07-29', '2024-07-30'],
  thresholds: cellBody.thresholds,
}

let grid: Grid = baseGrid
const cellRequests: string[] = []
const server = setupServer(
  http.get('*/api/mode', () => HttpResponse.json(mode)),
  http.get('*/api/grid', () => HttpResponse.json(gridToPayload(grid))),
  http.get('*/risk/cell/:id', ({ request }) => {
    cellRequests.push(new URL(request.url).search)
    return undefined
  }),
  ...alertsHandlers(),
)

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  grid = baseGrid
  cellRequests.length = 0
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function renderAlerts(path = '/alerts-why') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '/alerts-why', element: <Alerts /> }], { initialEntries: [path] })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, client }
}

const feedRows = () => screen.findAllByRole('listitem').then((items) => items.filter((li) => li.querySelector('button[data-index]')))
const rowCells = async () =>
  (await feedRows()).map((li) => /cell (\d+)/.exec(within(li).getByRole('button').getAttribute('aria-label') ?? '')![1])

describe('the feed', () => {
  it('lists the Watch and above cells, most severe first, with level, place, region, risk and confidence', async () => {
    renderAlerts()
    expect(await rowCells()).toEqual([String(CELL), String(CELL + 1), String(HIMALAYA), String(CELL - 10_000), String(HIMALAYA + 10_000)])
    const first = (await feedRows())[0]!
    expect(first).toHaveTextContent('Emergency')
    expect(first).toHaveTextContent(`Cell ${CELL}`)
    expect(first).toHaveTextContent('Western Ghats')
    expect(first).toHaveTextContent('1 in 2,200')
    expect(first).toHaveTextContent('45 per 100k cell-days')
    expect(first.querySelector('[title*="109× Watch"], [title*="Raw probability"]')).not.toBeNull()
    expect(first).toHaveTextContent('Degraded')
    expect(screen.getByText(/Lead D0/)).toHaveTextContent('6 cells scored, of which 1 Emergency, 2 Warning and 2 Watch.')
  })

  it('puts the raw probability only in a tooltip', async () => {
    renderAlerts()
    const first = (await feedRows())[0]!
    expect(first.querySelector('[title*="Raw probability"]')).not.toBeNull()
    expect(first).not.toHaveTextContent('0.000452')
  })

  it('sorts by the column chosen and reverses on a second click', async () => {
    renderAlerts()
    await feedRows()
    const sortRisk = screen.getByRole('button', { name: /Sort by risk/ })
    await userEvent.click(sortRisk)
    expect(sortRisk).toHaveAttribute('aria-pressed', 'true')
    expect(await rowCells()).toEqual([String(CELL), String(CELL + 1), String(HIMALAYA), String(CELL - 10_000), String(HIMALAYA + 10_000)])
    await userEvent.click(screen.getByRole('button', { name: /Sort by risk.*activate to reverse/ }))
    expect(await rowCells()).toEqual([String(HIMALAYA + 10_000), String(CELL - 10_000), String(HIMALAYA), String(CELL + 1), String(CELL)])
    await userEvent.click(screen.getByRole('button', { name: /Sort by region/ }))
    expect((await rowCells())[0]).toBe(String(HIMALAYA))
    await userEvent.click(screen.getByRole('button', { name: /Sort by confidence/ }))
    expect((await rowCells()).slice(-1)).toEqual([String(HIMALAYA)])
  })

  it('filters by level, including Normal on request', async () => {
    renderAlerts()
    await feedRows()
    const levels = screen.getByRole('group', { name: 'Levels' })
    await userEvent.click(within(levels).getByRole('button', { name: /^Emergency/ }))
    expect(await rowCells()).not.toContain(String(CELL))
    await userEvent.click(within(levels).getByRole('button', { name: /^Normal/ }))
    expect(await rowCells()).toContain(String(cellAt(12, 76)))
  })

  it('filters by region and searches by cell id', async () => {
    renderAlerts()
    await feedRows()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Region' }), 'himalaya')
    expect(await rowCells()).toEqual([String(HIMALAYA), String(HIMALAYA + 10_000)])
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Region' }), 'all')
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search by cell id' }), String(CELL))
    await waitFor(async () => expect(await rowCells()).toEqual([String(CELL)]))
    await userEvent.clear(screen.getByRole('searchbox'))
    await userEvent.type(screen.getByRole('searchbox'), '999999999999')
    expect(await screen.findByText('No cell matches these filters.')).toBeInTheDocument()
  })

  it('says so when no cell is at Watch or above', async () => {
    grid = makeGrid([{ cell: CELL, risk: 1e-8, level: 0 }], '2024-07-30')
    renderAlerts()
    expect(await screen.findByText('No cell is at Watch or above on this date.')).toBeInTheDocument()
  })

  it('moves through the rows with the arrow keys and opens one with Enter', async () => {
    const { router } = renderAlerts()
    const first = (await screen.findAllByRole('button', { name: /Open details/ }))[0]!
    first.focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Open details/ })[1]).toHaveFocus())
    await userEvent.keyboard('{End}')
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Open details/ }).at(-1)).toHaveFocus())
    await userEvent.keyboard('{Home}{Enter}')
    await waitFor(() => expect(router.state.location.search).toBe(`?cell=${CELL}&date=2024-07-30`))
  })

  it('offers the dates the API holds, and follows the one chosen', async () => {
    const { router } = renderAlerts()
    await feedRows()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Date' }), '2024-07-29')
    expect(router.state.location.search).toBe('?date=2024-07-29')
  })
})

describe('thousands of rows', () => {
  it('renders only the rows in view, and the rows at the scroll position after scrolling', async () => {
    grid = syntheticGrid(5000, '2024-07-30')
    renderAlerts()
    const scroller = await screen.findByTestId('feed-scroller')
    const total = Number(screen.getAllByRole('listitem')[0]!.getAttribute('aria-setsize'))
    expect(total).toBeGreaterThan(2000)
    const initial = screen.getAllByRole('listitem')
    expect(initial.length).toBeLessThan(40)
    expect(initial[0]).toHaveAttribute('aria-posinset', '1')

    fireEvent.scroll(scroller, { target: { scrollTop: 60 * 1500 } })
    const scrolled = await screen.findAllByRole('listitem')
    expect(scrolled.length).toBeLessThan(40)
    expect(Number(scrolled[0]!.getAttribute('aria-posinset'))).toBeGreaterThan(1480)
    expect(screen.getByText(/cells$/, { selector: 'p' })).toHaveTextContent(/of 5,000 cells/)
  })
})

describe('new alerts', () => {
  it('highlights the cells that reached Watch with a refreshed run and announces them politely', async () => {
    const { client } = renderAlerts()
    await feedRows()
    expect(screen.getByTestId('new-alerts-live')).toHaveTextContent('')
    expect(screen.getByTestId('new-alerts-live')).toHaveAttribute('aria-live', 'polite')
    const added = cellAt(13, 76)
    grid = makeGrid([...rows, { cell: added, risk: 6e-5, level: 3, confidence: 0 }], '2024-07-30')
    await act(() => client.invalidateQueries({ queryKey: ['grid'] }))
    await waitFor(() =>
      expect(screen.getByTestId('new-alerts-live')).toHaveTextContent('1 new alert at Watch or above since the last run.'),
    )
    const fresh = (await feedRows()).find((li) => li.querySelector('[data-fresh="true"]'))!
    expect(fresh).toHaveTextContent(`Cell ${added}`)
    expect(fresh).toHaveTextContent('New')
    expect(screen.getByText('1 new')).toBeInTheDocument()
  })

  it('does not flag anything on the first load', async () => {
    renderAlerts()
    await feedRows()
    expect(document.querySelector('[data-fresh]')).toBeNull()
    expect(screen.getByTestId('new-alerts-live')).toBeEmptyDOMElement()
  })
})

describe('the detail drawer', () => {
  const link = `/alerts-why?cell=${CELL}&date=2024-07-30`

  it('opens from a deep link as a dialog and asks for the cell on that date and set', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByRole('heading', { level: 2, name: `Cell ${CELL}` })).toBeInTheDocument()
    await within(dialog).findByRole('heading', { level: 3, name: 'Level' })
    expect(cellRequests[0]).toBe('?date=2024-07-30&set=case_wayanad_2024_samples')
  })

  it('shows level, risk in the shared format, thresholds and the reasons in words', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('45 per 100k cell-days')
    expect(dialog).toHaveTextContent('109× Watch threshold')
    expect(dialog).toHaveTextContent('Likely range 33 to 63 per 100k cell-days')
    expect(dialog).toHaveTextContent('Watch 0.41, Warning 1.6, Emergency 3.7')
    const reasons = within(dialog).getByRole('list', { name: 'Why this level' })
    expect(within(reasons).getByText('Risk above the Emergency threshold')).toBeInTheDocument()
    expect(within(reasons).getByText('Heavy rain while gauges are untrusted')).toBeInTheDocument()
    expect(within(reasons).getByText('Held at a higher level')).toBeInTheDocument()
    expect(within(reasons).queryByText(/risk_above/)).toBeNull()
  })

  it('explains the confidence with its causes, including a cause it has no wording for', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    const causes = await within(dialog).findByRole('list', { name: 'Why confidence is reduced' })
    expect(within(causes).getByText('Rain sources disagree')).toBeInTheDocument()
    expect(within(causes).getByText('Gauges flagged nearby')).toBeInTheDocument()
    expect(within(causes).getByText('Made up cause')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('2 gauges within 100 km: 1 trusted, 1 flagged in the last 7 days (stuck zero), 0 behaving unusually.')
  })

  it('draws the SHAP bars and the rain sources, and says "not available" where a source is NaN', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    const charts = await within(dialog).findAllByTestId('chart')
    await waitFor(() => expect(within(dialog).getAllByTestId('chart').length).toBeGreaterThanOrEqual(4))
    const labels = within(dialog).getAllByTestId('chart').map((c) => c.getAttribute('aria-label'))
    expect(charts.length).toBeGreaterThan(0)
    expect(labels.find((l) => l?.startsWith('Top inputs'))).toContain('Rain, today raises risk by 1.11')
    expect(labels.find((l) => l?.startsWith('Top inputs'))).toContain('Today’s share of 3-day rain lowers risk by 0.47')
    expect(labels.find((l) => l?.startsWith('Rain today by source'))).toBe(
      'Rain today by source: CHIRPS not available, IMD 179.2 mm, Gauges 158.1 mm, GFS not available',
    )
    const facts = within(dialog).getByText('Rain today, by source').closest('section')!
    expect(within(facts).getAllByText('not available')).toHaveLength(2)
    expect(within(facts).getByText(/GFS forecast rain is only used for the D\+1 to D\+3 forecasts/)).toBeInTheDocument()
    expect(within(facts).getByText(/179\.2 mm/)).toBeInTheDocument()
  })

  it('charts the 30-day rain history and risk trend from the history endpoint', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getAllByTestId('chart').map((c) => c.getAttribute('aria-label'))).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/^Daily rain by source: 5 days to 2024-07-30/),
        expect.stringMatching(/^Daily risk per 100k cell-days: 5 days to 2024-07-30; latest 45 per 100k cell-days/),
      ]),
    ))
    expect(dialog).toHaveTextContent('5 days with a score, ending 30 Jul 2024')
  })

  it('draws the neighbourhood on a 2D canvas and lists the alerts around the cell', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    const canvas = await within(dialog).findByRole('img', { name: /Map of the 13 by 13 cells around cell/ })
    expect(canvas.tagName).toBe('CANVAS')
    expect(canvas).toHaveAccessibleName(/3 scored that day, 3 at Watch or above/)
    const nearby = within(dialog).getByText('Nearby cells at Watch or above').nextElementSibling as HTMLElement
    expect(within(nearby).getAllByRole('button')).toHaveLength(2)
  })

  it('opens a neighbouring cell from the neighbourhood list', async () => {
    const { router } = renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    const nearby = (await within(dialog).findByText('Nearby cells at Watch or above')).nextElementSibling as HTMLElement
    await userEvent.click(within(nearby).getAllByRole('button')[0]!)
    expect(router.state.location.search).toContain(`cell=${CELL + 1}`)
  })

  it('shows a clear empty state for a cell the store does not hold', async () => {
    renderAlerts('/alerts-why?cell=12345&date=2024-07-30')
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('No alert for this cell and date')).toBeInTheDocument()
    expect(dialog).toHaveTextContent("cell 12345 has no alert row on 2024-07-30 in set 'case_wayanad_2024_samples'")
    expect(within(dialog).queryByRole('list', { name: 'Why this level' })).toBeNull()
  })

  it('shows a clear empty state for a date the store does not hold', async () => {
    server.use(
      http.get('*/risk/cell/:id', () =>
        HttpResponse.json({ detail: 'no replay data for 2020-01-01 in set \'case_wayanad_2024_samples\'; available 2024-07-29..2024-07-30 (2 days)' }, { status: 404 }),
      ),
    )
    renderAlerts(`/alerts-why?cell=${CELL}&date=2020-01-01`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('No alert for this cell and date')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('no replay data for 2020-01-01')
    expect(await screen.findByText('No data for 1 Jan 2020')).toBeInTheDocument()
  })

  it('says when the cell id in the address is not a number', async () => {
    renderAlerts('/alerts-why?cell=abc&date=2024-07-30')
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { level: 2, name: 'Unknown cell' })).toBeInTheDocument()
    expect(within(dialog).getByText('Not a cell id')).toBeInTheDocument()
    expect(cellRequests).toEqual([])
  })

  it('shows the explanation, not an error, when only the history is missing', async () => {
    server.use(http.get('*/api/cells/:id/history', () => HttpResponse.json({ detail: 'cell has no rows in this window' }, { status: 404 })))
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('cell has no rows in this window')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('Emergency')
  })

  it('closes with Escape, drops the cell from the address and returns focus to the feed', async () => {
    const { router } = renderAlerts(link)
    await screen.findByRole('dialog')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(router.state.location.search).toBe('')
    await waitFor(() => expect(document.activeElement).toHaveAttribute('data-index', '0'))
  })

  it('closes with the close button and with a click on the scrim', async () => {
    renderAlerts(link)
    await userEvent.click(await screen.findByRole('button', { name: 'Close alert details' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('opens from a feed row, and returns focus to that row on close', async () => {
    const { router } = renderAlerts()
    const row = (await screen.findAllByRole('button', { name: /Open details/ }))[1]!
    await userEvent.click(row)
    expect(router.state.location.search).toBe(`?cell=${CELL + 1}&date=2024-07-30`)
    await screen.findByRole('dialog')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Open details/ })[1]).toHaveFocus())
  })

  it('moves focus into the dialog and keeps Tab and Shift+Tab inside it', async () => {
    renderAlerts(link)
    const dialog = await screen.findByRole('dialog')
    const close = within(dialog).getByRole('button', { name: 'Close alert details' })
    await waitFor(() => expect(close).toHaveFocus())
    await within(dialog).findByRole('heading', { level: 3, name: 'Level' })
    const inside = dialog.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex]:not([tabindex="-1"])')
    const last = inside[inside.length - 1]!
    last.focus()
    await userEvent.tab()
    expect(close).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(last).toHaveFocus()
    // Focus dropped on the page body by a click on plain text is pulled back in.
    ;(document.activeElement as HTMLElement).blur()
    await userEvent.tab()
    expect(dialog.contains(document.activeElement)).toBe(true)
  })
})

describe('states without data', () => {
  it('says so plainly when there is no live run and no replay set', async () => {
    server.use(http.get('*/api/mode', () => HttpResponse.json(noDataMode)))
    renderAlerts()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('explains a date that is not in the store and offers the latest', async () => {
    const { router } = renderAlerts('/alerts-why?date=2020-01-01')
    expect(await screen.findByText('No data for 1 Jan 2020')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show the latest date' }))
    expect(router.state.location.search).toBe('')
    expect(await screen.findAllByRole('button', { name: /Open details/ })).not.toHaveLength(0)
  })

  it('shows the API message when the day has no grid', async () => {
    server.use(http.get('*/api/grid', () => HttpResponse.json({ detail: 'no alert rows for 2024-07-30' }, { status: 404 })))
    renderAlerts()
    expect(await screen.findByText('No risk grid for 30 Jul 2024')).toBeInTheDocument()
    expect(screen.getByText('no alert rows for 2024-07-30')).toBeInTheDocument()
  })
})


describe('the feed for a rain-capped cell', () => {
  it('has no "About 1 in" sentence for the capped cell, and the other rows are unchanged', async () => {
    grid = makeGrid(rows.map((r) => (r.cell === CELL ? { ...r, flags: GRID_FLAG.capped } : r)), '2024-07-30')
    renderAlerts()
    const items = await feedRows()
    const capped = items.find((li) => li.textContent?.includes(`Cell ${CELL}`))!
    const button = within(capped).getByRole('button')
    expect(button).toHaveAccessibleName(/Too little recent rain for a rain-triggered landslide, so no chance is given/)
    expect(button).not.toHaveAccessibleName(/About 1 in/)
    expect(capped).toHaveTextContent('not used')
    expect(capped.querySelector('[title*="About 1 in"]')).toBeNull()
    expect(capped.querySelector('[title*="model estimate (not used for the level)"]')).not.toBeNull()
    const other = items.find((li) => li.textContent?.includes(`Cell ${CELL + 1}`))!
    expect(within(other).getByRole('button')).toHaveAccessibleName(/About 1 in 33,000 chance of a landslide/)
  })
})

describe('forecast leads', () => {
  const live = { ...mode, mode: 'live', set: 'live', leads: { '2024-07-29': [0], '2024-07-30': [0, 1, 2, 3] } }
  const d3Cell = cellAt(13.5, 76)
  const d3Grid = makeGrid([{ cell: d3Cell, risk: 9e-5, level: 3, confidence: 1 }, { cell: CELL, risk: 2e-5, level: 2, confidence: 1 }], '2024-07-30')
  const askedGrid: number[] = []
  const askedCell: string[] = []

  beforeEach(() => {
    askedGrid.length = 0
    askedCell.length = 0
    server.use(
      http.get('*/api/mode', () => HttpResponse.json(live)),
      http.get('*/api/grid', ({ request }) => {
        const lead = Number(new URL(request.url).searchParams.get('lead') ?? 0)
        askedGrid.push(lead)
        return HttpResponse.json(gridToPayload(lead === 3 ? { ...d3Grid, lead: 3 } : grid))
      }),
      http.get('*/risk/cell/:id', ({ request }) => {
        askedCell.push(new URL(request.url).search)
        return undefined
      }),
      http.get('*/api/cells/:id/history', () => HttpResponse.json(forecastHistoryBody)),
    )
  })

  it('opens the forecast of the lead in the address, not the assessment of today', async () => {
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=3`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Forecast for Fri 2 Aug (D+3), issued 30 Jul')).toBeInTheDocument()
    expect(askedCell[0]).toBe('?date=2024-07-30&set=live&lead=3')
    expect(dialog).toHaveTextContent('Depends on rain forecast (Watch–Emergency)')
    expect(within(dialog).getByTestId('odds')).toHaveTextContent('About 1 in 16,000 chance of a landslide in this 5 km cell on Fri 2 Aug.')
    await within(dialog).findByText('6.3 per 100k cell-days')
    expect(dialog).toHaveTextContent('Warning')
    expect(within(dialog).getByRole('radio', { name: 'D+3' })).toBeChecked()
  })

  it('asks for lead 0 only when the address has no lead, as before', async () => {
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('45 per 100k cell-days')
    expect(askedCell[0]).toBe('?date=2024-07-30&set=live')
    expect(within(dialog).getByRole('radio', { name: 'D0' })).toBeChecked()
    expect(dialog).not.toHaveTextContent('Depends on rain forecast')
    expect(within(dialog).getByTestId('odds')).toHaveTextContent('About 1 in 2,200 chance of a landslide in this 5 km cell today.')
  })

  it('switches the lead of the same cell, and the address follows', async () => {
    const { router } = renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('45 per 100k cell-days')
    await userEvent.click(within(dialog).getByRole('radio', { name: 'D+1' }))
    expect(router.state.location.search).toBe(`?cell=${CELL}&date=2024-07-30&lead=1`)
    expect(await within(dialog).findByText('Forecast for Wed 31 Jul (D+1), issued 30 Jul')).toBeInTheDocument()
    await within(dialog).findByText('2.1 per 100k cell-days')
    await userEvent.click(within(dialog).getByRole('radio', { name: 'D+3' }))
    expect(await within(dialog).findByText('Forecast for Fri 2 Aug (D+3), issued 30 Jul')).toBeInTheDocument()
    expect(askedCell.at(-1)).toBe('?date=2024-07-30&set=live&lead=3')
    await userEvent.click(within(dialog).getByRole('radio', { name: 'D0' }))
    expect(router.state.location.search).toBe(`?cell=${CELL}&date=2024-07-30`)
    expect(await within(dialog).findByText('45 per 100k cell-days')).toBeInTheDocument()
    expect(dialog).not.toHaveTextContent('Forecast for')
  })

  it('disables a lead the run did not publish', async () => {
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-29`)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('radio', { name: 'D+3' })).toBeDisabled()
    expect(within(dialog).getByRole('radio', { name: 'D0' })).toBeEnabled()
  })

  it('shows the GFS rain of the target day next to the rain observed through the run date', async () => {
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=3`)
    const dialog = await screen.findByRole('dialog')
    const facts = (await within(dialog).findByText('Rain behind this forecast')).closest('section')!
    await waitFor(() => expect(within(dialog).getAllByTestId('chart').length).toBeGreaterThanOrEqual(4))
    const labels = within(dialog).getAllByTestId('chart').map((c) => c.getAttribute('aria-label'))
    expect(labels).toContain(
      'Rain observed through the run date and forecast by GFS: IMERG 91.2 mm, IMD 82.5 mm, Gauges 79.4 mm, GFS 67.9 mm',
    )
    expect(within(facts).getByText(/GFS forecast rain for 2 Aug 2024/)).toBeInTheDocument()
    expect(within(facts).getByText(/82\.5 mm/)).toBeInTheDocument()
    for (const [weekday, mm] of [['Wed 31 Jul', '18.4'], ['Thu 1 Aug', '42.1'], ['Fri 2 Aug', '67.9']]) {
      expect(within(facts).getByText(`GFS ${weekday}`).nextElementSibling).toHaveTextContent(`${mm} mm`)
    }
    expect(dialog).toHaveTextContent('A forecast day has no gauge reading, IMD grid or satellite estimate yet')
  })

  it('charts the forecast points on the risk trend', async () => {
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=3`)
    const dialog = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(dialog).getAllByTestId('chart').map((c) => c.getAttribute('aria-label'))).toEqual(
        expect.arrayContaining([expect.stringMatching(/^Daily risk per 100k cell-days: .*forecast D\+1 2\.1 per 100k cell-days, D\+2 4\.2 .*D\+3 6\.3/)]),
      ),
    )
    expect(dialog).toHaveTextContent('The dashed line is the D+1 to D+3 forecast of the run of 30 Jul')
  })

  it('says what is missing for a run that predates per-lead detail, and still shows the level and risk', async () => {
    server.use(
      http.get('*/risk/cell/:id', ({ request }) =>
        new URL(request.url).searchParams.get('lead')
          ? HttpResponse.json(
              forecastBody(3, {
                shap: [],
                rain: { unit: 'mm/day', observed_date: '2024-07-30', observed: {}, forecast: [] },
                detail_missing: 'this run predates per-lead detail',
              }),
            )
          : undefined,
      ),
    )
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=3`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Some detail is missing: this run predates per-lead detail.')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('No input contributions are stored for this forecast: this run predates per-lead detail.')
    expect(dialog).toHaveTextContent('Warning')
    expect(dialog).toHaveTextContent('6.3 per 100k cell-days')
  })

  it('shows a clear state when the run has no forecast for that lead', async () => {
    server.use(
      http.get('*/risk/cell/:id', ({ request }) =>
        new URL(request.url).searchParams.get('lead')
          ? HttpResponse.json({ detail: 'live run 2024-07-30 has no lead-3 forecast (risk_D3.parquet not found)' }, { status: 404 })
          : undefined,
      ),
    )
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=3`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('No alert for this cell and date')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('has no lead-3 forecast')
  })

  it('lists the alerts of the forecast lead in the feed, and the address follows the selector', async () => {
    const { router } = renderAlerts()
    await feedRows()
    expect(askedGrid).toEqual([0])
    await userEvent.click(screen.getByRole('radio', { name: 'D+3' }))
    expect(router.state.location.search).toBe('?lead=3&date=2024-07-30')
    await waitFor(async () => expect(await rowCells()).toEqual([String(d3Cell), String(CELL)]))
    expect(askedGrid).toContain(3)
    expect(screen.getByText(/Lead D\+3: forecast for Fri 2 Aug, issued 30 Jul\. Each cell is Firm/)).toBeInTheDocument()
    expect(screen.queryByText('1 new')).toBeNull()
    await userEvent.click(screen.getByRole('radio', { name: 'D0' }))
    expect(router.state.location.search).toBe('?date=2024-07-30')
    await waitFor(async () => expect((await rowCells())[0]).toBe(String(CELL)))
  })

  it('opens a feed row at the lead being listed', async () => {
    const { router } = renderAlerts('/alerts-why?lead=3&date=2024-07-30')
    await waitFor(async () => expect((await rowCells())[0]).toBe(String(d3Cell)))
    await userEvent.click((await screen.findAllByRole('button', { name: /Open details/ }))[0]!)
    expect(router.state.location.search).toBe(`?lead=3&date=2024-07-30&cell=${d3Cell}`)
  })

  it('offers only the leads the run published', async () => {
    renderAlerts('/alerts-why?date=2024-07-29')
    await feedRows()
    expect(screen.getByRole('radio', { name: 'D+2' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'D0' })).toBeEnabled()
  })
})

describe('place names', () => {
  /** The test grid's first three cells labelled: CELL Wayanad (8 km), CELL + 1 a remote Nepal cell (32 km), HIMALAYA in Bhutan. */
  const labelled = () =>
    server.use(http.get('*/api/places', () => HttpResponse.json({ ...placesPayload, cells: u32ToBase64([CELL, CELL + 1, HIMALAYA]) })))

  it('shows the place as the main location text and the cell id under it', async () => {
    labelled()
    renderAlerts()
    await waitFor(async () => expect((await feedRows())[0]).toHaveTextContent('Mananthavady, Wayanad, Kerala'))
    const [first, remote, bhutan] = await feedRows()
    expect(first).toHaveTextContent(`Cell ${CELL} · 8 km from town centre`)
    expect(first!.querySelector('strong + span')).toHaveTextContent(`Cell ${CELL}`)
    expect(within(first!).getByRole('button')).toHaveAccessibleName(new RegExp(`cell ${CELL}, Mananthavady, Wayanad, Kerala, Western Ghats`))
    expect(remote).toHaveTextContent('Kathmandu, Bagmati Province, Nepal')
    expect(remote).toHaveTextContent('nearest town: Kathmandu (32 km)')
    expect(bhutan).toHaveTextContent('Thimphu, Bhutan')
    expect(bhutan).toHaveTextContent('<1 km from town centre')
  })

  it('searches by place, district and state, case-insensitively, and by cell id', async () => {
    labelled()
    renderAlerts()
    await waitFor(async () => expect((await feedRows())[0]).toHaveTextContent('Mananthavady'))
    const box = screen.getByRole('searchbox', { name: 'Search by place or cell id' })
    expect(box).toHaveAttribute('placeholder', 'e.g. Wayanad or 202851')
    await userEvent.type(box, 'wAyAnAd')
    await waitFor(async () => expect(await rowCells()).toEqual([String(CELL)]))
    await userEvent.clear(box)
    await userEvent.type(box, 'bagmati')
    await waitFor(async () => expect(await rowCells()).toEqual([String(CELL + 1)]))
    await userEvent.clear(box)
    await userEvent.type(box, 'bhutan')
    await waitFor(async () => expect(await rowCells()).toEqual([String(HIMALAYA)]))
    await userEvent.clear(box)
    await userEvent.type(box, String(CELL + 1))
    await waitFor(async () => expect(await rowCells()).toEqual([String(CELL + 1)]))
    await userEvent.clear(box)
    await userEvent.type(box, 'nowhere')
    expect(await screen.findByText('No cell matches these filters.')).toBeInTheDocument()
  })

  it('names the cell in the drawer header and keeps the id and the coordinates', async () => {
    labelled()
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('heading', { level: 2, name: 'Mananthavady, Wayanad, Kerala' })).toBeInTheDocument()
    expect(dialog).toHaveTextContent(`Cell ${CELL} · 8 km from town centre · 11.43°N, 76.13°E · Western Ghats`)
  })

  it('falls back to the label the API sent with the cell when the table is missing', async () => {
    server.use(http.get('*/risk/cell/:id', () => HttpResponse.json({ ...cellBody, place: placeBody })))
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('heading', { level: 2, name: 'Kalpatta, Wayanad, Kerala' })).toBeInTheDocument()
  })

  it('credits GeoNames under the feed when there are place names', async () => {
    labelled()
    renderAlerts()
    expect(await screen.findByText('Place names: GeoNames (CC BY 4.0)')).toBeInTheDocument()
  })

  it('shows coordinates, searches by id only and credits nobody when the API has no place table', async () => {
    renderAlerts()
    const [first] = await feedRows()
    expect(first).toHaveTextContent(`Cell ${CELL}`)
    expect(first).toHaveTextContent(/°N, .*°E/)
    expect(first).not.toHaveTextContent('from town centre')
    expect(screen.getByRole('searchbox', { name: 'Search by cell id' })).toBeInTheDocument()
    expect(screen.queryByText(/GeoNames/)).toBeNull()
  })
})

describe('certainty, source and capped reasons (spec section 12)', () => {
  const forecastWith = (over: Record<string, unknown>) =>
    server.use(
      http.get('*/risk/cell/:id', ({ request }) =>
        new URL(request.url).searchParams.get('lead') ? HttpResponse.json(forecastBody(2, over)) : undefined,
      ),
    )

  it('calls a forecast cell Firm and says why, instead of "less certain"', async () => {
    forecastWith({ certainty: 'firm', level_min: 2, level_max: 2 })
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=2`)
    const dialog = await screen.findByRole('dialog')
    const line = await within(dialog).findByTestId('certainty')
    expect(line).toHaveTextContent('Firm')
    expect(line).toHaveTextContent('set by rain already fallen')
    expect(dialog).not.toHaveTextContent('less certain')
  })

  it('names the ECMWF source with its licence in the drawer', async () => {
    forecastWith({
      forecast_source: {
        source: 'ecmwf_hres',
        label: 'ECMWF IFS HRES (CC BY 4.0)',
        mapped: true,
        fallback: false,
        cycle: '2024-07-29T12:00:00+00:00',
        attribution: 'Contains ECMWF open data (IFS), licensed CC BY 4.0',
      },
    })
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=2`)
    const dialog = await screen.findByRole('dialog')
    const facts = (await within(dialog).findByText('Rain behind this forecast')).closest('section')!
    expect(within(facts).getByText('Forecast rain').nextElementSibling).toHaveTextContent(
      'ECMWF IFS HRES (CC BY 4.0) Bias-corrected to the satellite rain scale. Contains ECMWF open data (IFS), licensed CC BY 4.0.',
    )
    expect(within(facts).getByText('ECMWF Thu 1 Aug')).toBeInTheDocument()
  })

  it('says the GFS fallback was used', async () => {
    forecastWith({ forecast_source: { source: 'gfs', label: 'GFS fallback', mapped: false, fallback: true, cycle: null, attribution: null } })
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30&lead=2`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('GFS fallback')).toBeInTheDocument()
  })

  it('explains a capped level in plain words with the rain and the trigger', async () => {
    server.use(
      http.get('*/risk/cell/:id', ({ request }) =>
        new URL(request.url).searchParams.get('lead')
          ? undefined
          : HttpResponse.json({
              ...cellBody,
              level: 1,
              level_name: 'Watch',
              raw_level: 'Watch',
              reason_codes: ['risk_above_emergency', 'no_recent_rain'],
              rain_rule: { passed: false, exempt: false, capped: true, window_days: 7, rain_mm: 0, minimum_mm: 11.5, capped_to: 'Watch' },
            }),
      ),
    )
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByTestId('capped-reason')).toHaveTextContent(
      'Model risk is in the Emergency range, but there was no rain in the last 7 days (rain trigger: 11.5 mm), so the level is capped at Watch.',
    )
    expect(dialog).toHaveTextContent('Capped: no recent rain')
  })

  it('gives no chance for a capped cell, and shows its figures as the model estimate', async () => {
    server.use(
      http.get('*/risk/cell/:id', ({ request }) =>
        new URL(request.url).searchParams.get('lead')
          ? undefined
          : HttpResponse.json({
              ...cellBody,
              level: 1,
              level_name: 'Watch',
              reason_codes: ['risk_above_emergency', 'no_recent_rain'],
              rain_rule: { passed: false, exempt: false, capped: true, window_days: 7, rain_mm: 10.8, minimum_mm: 11.5, capped_to: 'Watch' },
            }),
      ),
    )
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    const odds = await within(dialog).findByTestId('odds')
    expect(odds).toHaveTextContent(
      "Too little recent rain for a rain-triggered landslide, so no chance is given (the model's 1 in 2,200 estimate is not used).",
    )
    expect(dialog).not.toHaveTextContent('About 1 in')
    expect(dialog).toHaveTextContent('model estimate (not used for the level)45 per 100k cell-days')
    expect(dialog).toHaveTextContent(/× Watch threshold, model estimate \(not used for the level\)/)
    expect(dialog).toHaveTextContent('Likely range of the model estimate (not used for the level)')
  })

  it('keeps the odds and notes the ensemble when it disagrees', async () => {
    server.use(
      http.get('*/risk/cell/:id', ({ request }) =>
        new URL(request.url).searchParams.get('lead') ? undefined : HttpResponse.json({ ...cellBody, confidence_causes: ['ensemble_disagrees'] }),
      ),
    )
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByTestId('odds')).toHaveTextContent(
      'About 1 in 2,200 chance of a landslide in this 5 km cell on Tue 30 Jul (most of the 20 ensemble models put it lower).',
    )
    expect(dialog).not.toHaveTextContent('model estimate (not used for the level)')
  })

  it('shows no capped line for a cell that was not capped', async () => {
    renderAlerts(`/alerts-why?cell=${CELL}&date=2024-07-30`)
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('45 per 100k cell-days')
    expect(within(dialog).queryByTestId('capped-reason')).toBeNull()
  })

  it('offers "Firm only" on a forecast lead and lists just the firm cells', async () => {
    const forecastGrid = {
      ...baseGrid,
      lead: 3,
      certainty: Uint8Array.from(Array.from(baseGrid.cells, (c) => (c === CELL ? 1 : c === CELL + 1 ? 2 : 1))),
      levelMin: Uint8Array.from(Array.from(baseGrid.cells, () => 1)),
      levelMax: Uint8Array.from(Array.from(baseGrid.cells, (c) => (c === CELL + 1 ? 3 : 1))),
    }
    const bytes = (view: Uint8Array) => bytesToBase64(view)
    server.use(
      http.get('*/api/mode', () => HttpResponse.json({ ...mode, leads: { '2024-07-30': [0, 3] } })),
      http.get('*/api/grid', ({ request }) =>
        HttpResponse.json(
          new URL(request.url).searchParams.get('lead') === '3'
            ? {
                ...gridToPayload(forecastGrid),
                certainty: bytes(forecastGrid.certainty),
                level_min: bytes(forecastGrid.levelMin),
                level_max: bytes(forecastGrid.levelMax),
                forecast: { source: 'ecmwf_hres', label: 'ECMWF IFS HRES (CC BY 4.0)', mapped: false, fallback: false, cycle: null, attribution: 'Contains ECMWF open data (IFS), licensed CC BY 4.0' },
              }
            : gridToPayload(baseGrid),
        ),
      ),
    )
    renderAlerts('/alerts-why?lead=3&date=2024-07-30')
    const before = await rowCells()
    expect(before).toContain(String(CELL + 1))
    const chip = await screen.findByRole('button', { name: /Firm only/ })
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(chip)
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    await waitFor(async () => expect(await rowCells()).not.toContain(String(CELL + 1)))
    expect(await rowCells()).toContain(String(CELL))
    expect(screen.getByText(/Forecast rain: ECMWF IFS HRES \(CC BY 4\.0\)\./)).toBeInTheDocument()
    expect(screen.getByText('Contains ECMWF open data (IFS), licensed CC BY 4.0.')).toBeInTheDocument()
    const first = (await feedRows())[0]!
    expect(first).toHaveTextContent('Firm')
  })

  it('has no Firm-only filter at lead 0', async () => {
    renderAlerts()
    await feedRows()
    expect(screen.queryByRole('button', { name: /Firm only/ })).toBeNull()
  })
})
