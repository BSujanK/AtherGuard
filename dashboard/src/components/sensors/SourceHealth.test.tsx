import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { connectStream, type EventSourceLike, useStreamStatus } from '../../data/stream'
import SourceHealth from './SourceHealth'

class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = []
  onopen: ((e: Event) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  private listeners = new Map<string, Array<(e: MessageEvent<string>) => void>>()

  constructor() {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (e: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close() {}

  emit(type: string, data: unknown) {
    for (const l of this.listeners.get(type) ?? []) l(new MessageEvent(type, { data: JSON.stringify(data) }))
  }
}

const entry = (name: string, over: Record<string, unknown> = {}) => ({
  name,
  ok: true,
  valid_through: '2026-10-14T00:00:00+00:00',
  issued: '2026-10-14T04:30:00+00:00',
  latency_h: 4.5,
  error: null,
  state: 'ok',
  expected_valid_through: '2026-10-14T00:00:00+00:00',
  ...over,
})

const freshness = (over: Record<string, unknown> = {}) => ({
  available: true,
  date: '2026-10-15',
  generated_utc: '2026-10-15T05:31:00+00:00',
  backtest: false,
  data_cutoff_utc: null,
  imd_day_inputs: {
    D: { product: 'early_mapped+gfs_0_3h' },
    'D-1': { product: 'late+early_mapped' },
  },
  sources: {
    imerg_late: entry('imerg_late', { latency_h: 14.4 }),
    imerg_early: entry('imerg_early'),
    gfs: entry('gfs', { latency_h: 3.9 }),
    imd_rt: entry('imd_rt', { latency_h: 20 }),
    ghcn: entry('ghcn', { latency_h: 115.9 }),
  },
  ...over,
})

let body: Record<string, unknown> = freshness()
const server = setupServer(http.get('*/api/sources/status', () => HttpResponse.json(body)))

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  server.resetHandlers()
  body = freshness()
  FakeEventSource.instances = []
  act(() => useStreamStatus.setState({ state: 'connecting' }))
})
afterAll(() => server.close())

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SourceHealth />
    </QueryClientProvider>,
  )
  return client
}

describe('SourceHealth', () => {
  it('lists the five sources with status, times in IST and latency', async () => {
    renderPanel()
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('rowheader')[0]!.textContent)).toEqual([
      'IMERG Late',
      'IMERG Early',
      'GFS',
      'IMD real-time',
      'GHCN gauges',
    ])
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual(['ok', 'ok', 'ok', 'ok', 'ok'])
    const early = rows[1]!
    expect(within(early).getByText('14 Oct, 10:00')).toBeInTheDocument()
    expect(within(early).getByText('4.5')).toBeInTheDocument()
    expect(screen.getByTestId('rain-provenance')).toHaveTextContent(
      'D from early_mapped + gfs_0_3h; D-1 from late + early_mapped',
    )
  })

  it('shows the runner state and an em dash for missing latency and a failed source', async () => {
    body = freshness({
      sources: {
        ...freshness().sources,
        gfs: entry('gfs', { state: 'late', latency_h: null }),
        imd_rt: entry('imd_rt', { ok: false, state: 'failed', error: 'HTTPError: 503', valid_through: null, issued: null, latency_h: null }),
      },
    })
    renderPanel()
    await screen.findByRole('table')
    const gfs = document.querySelector('[data-source="gfs"]')!
    expect(gfs).toHaveAttribute('data-status', 'late')
    expect(within(gfs as HTMLElement).getAllByText('—').length).toBeGreaterThan(0)
    const imd = document.querySelector('[data-source="imd_rt"]') as HTMLElement
    expect(imd).toHaveAttribute('data-status', 'failed')
    expect(within(imd).getByText('HTTPError: 503')).toBeInTheDocument()
  })

  it('says plainly that no live run exists yet, with the API reason, and invents no rows', async () => {
    body = { available: false, reason: 'no live run yet (no freshness.json under /data/live)' }
    renderPanel()
    expect(await screen.findByText('No live run yet')).toBeInTheDocument()
    expect(screen.getByText('no live run yet (no freshness.json under /data/live)')).toBeInTheDocument()
    expect(screen.getByText(/first daily run \(11:00 IST\)/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('refreshes and pulses when the stream emits a sources event', async () => {
    const client = renderPanel()
    await screen.findByRole('table')
    const stream = connectStream(client, { factory: () => new FakeEventSource() })
    const es = FakeEventSource.instances[0]!
    act(() => es.onopen?.(new Event('open')))
    expect(document.querySelector('[data-source="gfs"]')).toHaveAttribute('data-status', 'ok')
    expect(screen.getByText('Live')).toHaveAttribute('data-flash', 'false')

    body = freshness({ sources: { ...freshness().sources, gfs: entry('gfs', { state: 'late', latency_h: 9 }) } })
    act(() => es.emit('sources', body))

    await waitFor(() => expect(document.querySelector('[data-source="gfs"]')).toHaveAttribute('data-status', 'late'))
    expect(await screen.findByText('Updated just now')).toHaveAttribute('data-flash', 'true')
    stream.close()
  })

  it('warns that figures may be stale while the stream reconnects', async () => {
    renderPanel()
    await screen.findByRole('table')
    act(() => useStreamStatus.setState({ state: 'reconnecting' }))
    expect(screen.getByText(/Live updates are paused/)).toBeInTheDocument()
  })

  it('shows an error state with a retry when the API is unreachable', async () => {
    server.use(http.get('*/api/sources/status', () => HttpResponse.error()))
    renderPanel()
    expect(await screen.findByText('Cannot reach the AetherGuard API')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
