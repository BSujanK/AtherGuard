import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { noDataMode, replayMode, basemapPayload } from '../test/fixtures'
import Sensors from './Sensors'

vi.mock('../charts/EChart', () => ({
  default: ({ label }: { label: string }) => <div data-testid="chart" aria-label={label} />,
}))

const stationRow = (id: string, over: Record<string, unknown> = {}) => ({
  station: id,
  name: `Gauge ${id}`,
  lat: 15,
  lon: 77,
  trust: 0.95,
  fault_type: '',
  flagged: false,
  genuine_extreme: false,
  reasons: '',
  state: 'trusted',
  flag_rate_window: 0,
  ood: false,
  last_reading: null,
  ...over,
})

const sensorsBody = {
  date: '2024-08-05',
  set: 'case_test_set',
  n_stations: 3,
  state_counts: { trusted: 2, uncertain: 1 },
  stations: [
    stationRow('A'),
    stationRow('B'),
    stationRow('C', { trust: 0.2, flagged: true, fault_type: 'scale_drift', state: 'uncertain' }),
  ],
}

const available = {
  available: true,
  date: '2026-10-15',
  generated_utc: '2026-10-15T05:31:00+00:00',
  backtest: false,
  imd_day_inputs: null,
  sources: {
    gfs: { name: 'gfs', ok: true, valid_through: '2026-10-18T03:00:00+00:00', issued: '2026-10-15T00:00:00+00:00', latency_h: 4, error: null, state: 'ok' },
  },
}

const requests: string[] = []
const server = setupServer(
  http.get('*/api/mode', () => HttpResponse.json(replayMode)),
  http.get('*/api/basemap', () => HttpResponse.json(basemapPayload)),
  http.get('*/api/sources/status', () => HttpResponse.json({ available: false, reason: 'no live run yet (nothing under /data/live)' })),
  http.get('*/sensors', ({ request }) => {
    requests.push(new URL(request.url).searchParams.get('date') ?? '')
    return HttpResponse.json(sensorsBody)
  }),
)

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
// jsdom has no canvas; the relief backdrop skips drawing when there is no 2D context.
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})
afterEach(() => {
  server.resetHandlers()
  requests.length = 0
})
afterAll(() => server.close())

function renderView(path = '/sensors-sources') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '/sensors-sources', element: <Sensors /> }], { initialEntries: [path] })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe('Sensors view', () => {
  it('shows the empty source state and the gauges of the latest date side by side', async () => {
    renderView()
    expect(await screen.findByText('No live run yet')).toBeInTheDocument()
    expect(await screen.findByRole('group', { name: 'Map of 3 rain gauges coloured by trust' })).toBeInTheDocument()
    expect(requests).toEqual(['2024-08-05'])
    const counts = screen.getByRole('list', { name: 'Gauges by state' })
    expect(within(counts).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '2 trusted',
      '1 uncertain',
      '1 with a fault',
    ])
    expect(screen.getByRole('table', { name: 'Gauge faults' })).toBeInTheDocument()
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument()
  })

  it('charts source latency once a live run exists', async () => {
    server.use(http.get('*/api/sources/status', () => HttpResponse.json(available)))
    renderView()
    const chart = await screen.findByTestId('chart')
    expect(chart).toHaveAttribute('aria-label', expect.stringContaining('GFS 4.0 hours'))
    expect(screen.getByText(/History appears as daily runs accumulate/)).toBeInTheDocument()
    await screen.findByRole('group', { name: /rain gauges/ })
  })

  it('reads the date from the URL and offers every date in the store', async () => {
    renderView('/sensors-sources?date=2024-08-04')
    await screen.findByRole('group', { name: /rain gauges/ })
    expect(requests).toEqual(['2024-08-04'])
    const select = screen.getByRole('combobox', { name: 'Gauge date' })
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['5 Aug 2024', '4 Aug 2024'])
    expect(select).toHaveValue('2024-08-04')
  })

  it('changes the date from the selector', async () => {
    renderView()
    await screen.findByRole('group', { name: /rain gauges/ })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Gauge date' }), '2024-08-04')
    await screen.findByRole('group', { name: /rain gauges/ })
    expect(requests).toContain('2024-08-04')
  })

  it('explains a date the store does not hold with the API message, not an exception', async () => {
    server.use(
      http.get('*/sensors', () =>
        HttpResponse.json({ detail: 'no replay data for 2023-01-01 in the replay store; available 2018-01-01..2024-08-05' }, { status: 404 }),
      ),
    )
    renderView('/sensors-sources?date=2023-01-01')
    expect(await screen.findByText('No gauge data for 1 Jan 2023')).toBeInTheDocument()
    expect(screen.getByText(/available 2018-01-01\.\.2024-08-05/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('notes that gauge reports arrive late when most gauges have no value, and gives the last reading', async () => {
    const stale = {
      ...sensorsBody,
      date: '2026-10-16',
      set: 'live',
      state_counts: { missing: 2, trusted: 1 },
      stations: [
        stationRow('A', { trust: null, state: 'missing', last_reading: '2026-10-12' }),
        stationRow('B', { trust: null, state: 'missing', last_reading: '2026-10-09' }),
        stationRow('C', { last_reading: '2026-10-16' }),
      ],
    }
    server.use(http.get('*/sensors', () => HttpResponse.json(stale)))
    renderView()
    expect(
      await screen.findByText("Gauge reports reach GHCN 3–13 days late; the map shows each gauge's latest state."),
    ).toBeInTheDocument()
    await userEvent.hover(screen.getByRole('img', { name: /Gauge A, trust no value, no fault, last reading 12 Oct 2026/ }))
    expect(within(screen.getByRole('tooltip')).getByText('12 Oct 2026')).toBeInTheDocument()
  })

  it('has no lateness note when gauges have values', async () => {
    renderView()
    await screen.findByRole('group', { name: /rain gauges/ })
    expect(screen.queryByText(/reach GHCN/)).not.toBeInTheDocument()
  })

  it('shows the reason when the API holds the date but has no gauge table', async () => {
    const reason = 'No gauge table for 2026-10-16: GHCN-Daily gauges unavailable.'
    server.use(
      http.get('*/sensors', () =>
        HttpResponse.json({ date: '2026-10-16', set: 'live', n_stations: 0, state_counts: {}, stations: [], reason }),
      ),
    )
    renderView()
    expect(await screen.findByText('No gauge readings to show')).toBeInTheDocument()
    expect(screen.getByText(reason)).toBeInTheDocument()
    expect(document.querySelector('[data-sensors-reason]')).not.toBeNull()
    expect(screen.queryByRole('group', { name: /rain gauges/ })).not.toBeInTheDocument()
    expect(screen.getByText('No gauge data to list faults from.')).toBeInTheDocument()
  })

  it('says so, without a reason marker, when the API returns no gauges and no reason', async () => {
    server.use(
      http.get('*/sensors', () => HttpResponse.json({ date: '2024-08-05', set: 's', n_stations: 0, state_counts: {}, stations: [] })),
    )
    renderView()
    expect(await screen.findByText('The API returned no gauges for this date.')).toBeInTheDocument()
    expect(document.querySelector('[data-sensors-reason]')).toBeNull()
  })

  it('says there is no gauge data when the API has no data at all', async () => {
    server.use(http.get('*/api/mode', () => HttpResponse.json(noDataMode)))
    renderView()
    expect(await screen.findByText('No gauge data yet')).toBeInTheDocument()
    expect(requests).toEqual([])
    await screen.findByText('No live run yet')
  })
})
