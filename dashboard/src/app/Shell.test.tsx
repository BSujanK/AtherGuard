import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { act } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { useStreamStatus } from '../data/stream'
import { apiHandlers, noDataMode, replayMode } from '../test/fixtures'
import { mapHandlers } from '../test/mapFixtures'
import { routes } from './router'

const NEXT_RUN = '2026-10-16T11:00:00+05:30'

const server = setupServer(...mapHandlers(), ...apiHandlers({ ...replayMode, next_run: NEXT_RUN }))

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})
afterEach(() => {
  server.resetHandlers()
  act(() => useStreamStatus.setState({ state: 'connecting' }))
})
afterAll(() => server.close())

function renderApp(path = '/map') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

/** Wait for the mode and grid requests to land so no request is in flight when the test ends. */
async function settled() {
  await screen.findByRole('list', { name: 'Cells by risk level' })
}

describe('Shell with replay data', () => {
  it('renders the three navigation items on their own routes', async () => {
    renderApp()
    const nav = screen.getByRole('navigation', { name: 'Views' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Live map', 'Alerts', 'Sensors & sources'])
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/map', '/alerts-why', '/sensors-sources'])
    expect(within(nav).getByRole('link', { name: 'Live map' })).toHaveAttribute('aria-current', 'page')
    await settled()
  })

  it('shows the data mode, set, dates, next run and counts from the API', async () => {
    renderApp()
    const strip = screen.getByRole('banner', { name: 'Data status' })
    expect(await within(strip).findByText('Replay')).toBeInTheDocument()
    expect(within(strip).getByText('case_test_set')).toBeInTheDocument()
    expect(within(strip).getByText('5 Aug 2024')).toBeInTheDocument()
    expect(within(strip).getByText('11:00 IST, 16 Oct')).toBeInTheDocument()

    const levels = await within(strip).findByRole('list', { name: 'Cells by risk level' })
    expect(within(levels).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '4 Normal',
      '3 Watch',
      '2 Warning',
      '1 Emergency',
    ])
    const confidence = within(strip).getByRole('list', { name: 'Cells by confidence' })
    expect(within(confidence).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '6 High',
      '3 Degraded',
      '1 Insufficient',
    ])
  })

  it('shows the next run from the API, not a fixed label', async () => {
    server.use(...apiHandlers({ ...replayMode, next_run: '2026-10-17T07:45:00+05:30' }))
    renderApp()
    const strip = screen.getByRole('banner', { name: 'Data status' })
    expect(await within(strip).findByText('07:45 IST, 17 Oct')).toBeInTheDocument()
    expect(within(strip).queryByText(/09:30/)).not.toBeInTheDocument()
    await settled()
  })

  it('says the next run is unknown when the API does not report one', async () => {
    server.use(...mapHandlers(), ...apiHandlers(replayMode))
    renderApp()
    const strip = screen.getByRole('banner', { name: 'Data status' })
    const fact = (await within(strip).findByText('Next run')).closest('span')!
    expect(fact).toHaveTextContent('Next run n/a')
    await settled()
  })

  it('redirects the home path to the live map', async () => {
    const router = renderApp('/')
    expect(router.state.location.pathname).toBe('/map')
    expect(await screen.findByRole('heading', { level: 1, name: 'Live map' })).toBeInTheDocument()
    await settled()
  })

  it('opens each view at its own path', async () => {
    renderApp('/alerts-why')
    expect(await screen.findByRole('heading', { level: 1, name: 'Alerts' })).toBeInTheDocument()
    await settled()
  })

  it('says so when a route does not exist', async () => {
    renderApp('/nowhere')
    await settled()
    expect(screen.getByText('That page does not exist')).toBeInTheDocument()
  })

  it('flags a dropped live-update stream in the status strip', async () => {
    renderApp()
    await settled()
    act(() => useStreamStatus.setState({ state: 'reconnecting' }))
    const strip = screen.getByRole('banner', { name: 'Data status' })
    expect(within(strip).getByRole('status')).toHaveTextContent('Reconnecting to live updates')
  })
})

describe('Shell on a day without risk scores', () => {
  const live = {
    mode: 'live' as const,
    set: 'live',
    latest_date: '2026-11-01',
    dates: ['2026-10-31', '2026-11-01'],
    scored_share: 0,
    last_scored_date: '2026-10-31',
    next_run: NEXT_RUN,
  }

  it('warns that the levels are held, naming both dates', async () => {
    server.use(...apiHandlers(live))
    renderApp()
    const strip = screen.getByRole('banner', { name: 'Data status' })
    const notice = await within(strip).findByTestId('no-scores-notice')
    expect(notice).toHaveTextContent(
      'No new risk scores for 1 Nov 2026: satellite rain not yet available. Levels are held from 31 Oct 2026.',
    )
    expect(notice).toHaveAttribute('role', 'status')
    await settled()
  })

  it('does not name a source day when no day was ever scored', async () => {
    server.use(...apiHandlers({ ...live, last_scored_date: null }))
    renderApp()
    const notice = await within(screen.getByRole('banner', { name: 'Data status' })).findByTestId('no-scores-notice')
    expect(notice).toHaveTextContent('No new risk scores for 1 Nov 2026: satellite rain not yet available. Levels are held from earlier days.')
    await settled()
  })

  it.each([0.5, 0.99, null])('shows no warning when the share scored is %s', async (share) => {
    server.use(...apiHandlers({ ...live, scored_share: share }))
    renderApp()
    await settled()
    expect(screen.queryByTestId('no-scores-notice')).toBeNull()
  })

  it('shows no warning without a share, as for a replay set or an older API', async () => {
    renderApp()
    await settled()
    expect(screen.queryByTestId('no-scores-notice')).toBeNull()
  })
})

describe('Shell without data', () => {
  it('shows a plain empty state when the mode is none', async () => {
    server.use(...apiHandlers(noDataMode))
    renderApp('/map')
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Live map' })).toBeInTheDocument()
    const strip = screen.getByRole('banner', { name: 'Data status' })
    expect(within(strip).getByText('No data')).toBeInTheDocument()
    expect(within(strip).queryByRole('list', { name: 'Cells by risk level' })).not.toBeInTheDocument()
  })

  it('explains when the API cannot be reached and offers a retry', async () => {
    server.use(http.get('*/api/mode', () => HttpResponse.error()))
    renderApp('/map')
    expect(await screen.findByText('Cannot reach the AetherGuard API')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
