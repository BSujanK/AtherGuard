import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { describeCell } from '../components/map/HoverCard'
import { decodeGrid } from '../data/api'
import { GRID_FLAG } from '../data/types'
import { resetMapState, useMapState } from '../state/map'
import { apiHandlers, bytesToBase64, f32ToBase64, gridPayload, noDataMode, placesPayload, replayMode } from '../test/fixtures'
import { mapHandlers, rainPayload } from '../test/mapFixtures'
import LiveMap from './LiveMap'

const env = vi.hoisted(() => ({ webgl: false, reduced: false }))

vi.mock('../lib/motion', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/motion')>()),
  webglAvailable: () => env.webgl,
  prefersReducedMotion: () => env.reduced,
}))

const server = setupServer(...mapHandlers(), ...apiHandlers())

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  env.webgl = false
  env.reduced = true
  resetMapState()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function renderMap(path = '/map') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/map', element: <LiveMap /> },
      { path: '/alerts-why', element: <p>alerts view</p> },
    ],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const controls = () => screen.findByRole('region', { name: 'Map controls' })

describe('renderer choice', () => {
  it('draws the 2D fallback map when WebGL is missing', async () => {
    env.webgl = false
    renderMap()
    await controls()
    expect(screen.getByTestId('map-2d')).toBeInTheDocument()
  })

  it('leaves the map to the shared 3D canvas when WebGL is available', async () => {
    env.webgl = true
    renderMap()
    await controls()
    expect(screen.queryByTestId('map-2d')).not.toBeInTheDocument()
  })
})

describe('lead switch', () => {
  it('disables a forecast lead the API answers 404 for and shows the reason', async () => {
    renderMap()
    const panel = await controls()
    const d1 = within(panel).getByRole('radio', { name: 'D+1' })
    await waitFor(() => expect(d1).toBeDisabled())
    expect(within(panel).getByRole('radio', { name: 'D+3' })).toBeDisabled()
    expect(within(panel).getByRole('radio', { name: 'D0' })).toBeEnabled()
    expect(within(panel).getByRole('radio', { name: 'D0' })).toBeChecked()
    const note = await screen.findByText(/^D\+1, D\+2, D\+3:/)
    expect(note).toHaveTextContent("D+1, D+2, D+3: replay set 'case_test_set' holds lead 0 only")
  })

  it('asks the API only for the leads /api/mode offers, so a replay set causes no 404s', async () => {
    const asked: number[] = []
    server.use(
      http.get('*/api/grid', ({ request }) => {
        asked.push(Number(new URL(request.url).searchParams.get('lead')))
        return undefined
      }),
    )
    renderMap('/map?lead=3')
    await controls()
    await screen.findByText(/D\+3 has no data/)
    expect(new Set(asked)).toEqual(new Set([0]))
  })

  it('enables a lead that has data and labels forecasts as less certain', async () => {
    const asked: number[] = []
    server.use(
      http.get('*/api/mode', () =>
        HttpResponse.json({ ...replayMode, mode: 'live', set: 'live', leads: { '2024-08-04': [0], '2024-08-05': [0, 2] } }),
      ),
      http.get('*/api/grid', ({ request }) => {
        const lead = Number(new URL(request.url).searchParams.get('lead'))
        asked.push(lead)
        return lead === 2 ? HttpResponse.json({ ...gridPayload, lead: 2 }) : undefined
      }),
    )
    renderMap()
    const panel = await controls()
    await waitFor(() => expect(within(panel).getByRole('radio', { name: 'D+2' })).toBeEnabled())
    await waitFor(() => expect(within(panel).getByRole('radio', { name: 'D+1' })).toBeDisabled())
    expect(await screen.findByText(/D\+1, D\+3: the 2024-08-05 run has no forecast for this lead/)).toBeInTheDocument()
    expect(asked).not.toContain(1)
    expect(asked).not.toContain(3)
    expect(screen.getByText(/D\+1 to D\+3 are forecasts/)).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('radio', { name: 'D+2' }))
    expect(useMapState.getState().lead).toBe(2)
  })

  it('falls back to D0 with a notice when the chosen lead has no data', async () => {
    renderMap('/map?lead=1')
    expect(await screen.findByText(/D\+1 has no data for 5 Aug 2024.*Showing D0/)).toBeInTheDocument()
    expect(useMapState.getState().lead).toBe(0)
  })
})

describe('controls', () => {
  it('moves through the dates with the keyboard-operable scrubber', async () => {
    renderMap()
    const panel = await controls()
    const slider = await within(panel).findByRole('slider', { name: 'Date' })
    expect(slider).toHaveAttribute('aria-valuetext', '5 Aug 2024')
    fireEvent.change(slider, { target: { value: '0' } })
    expect(useMapState.getState().date).toBe('2024-08-04')
    expect(slider).toHaveAttribute('aria-valuetext', '4 Aug 2024')
  })

  it('filters levels and regions through labelled controls', async () => {
    renderMap()
    const panel = await controls()
    await userEvent.click(within(panel).getByRole('checkbox', { name: 'Normal' }))
    expect(useMapState.getState().levels).toEqual([false, true, true, true])
    await userEvent.click(within(panel).getByRole('radio', { name: 'Western Ghats' }))
    expect(useMapState.getState().region).toBe('western_ghats')
    expect(useMapState.getState().camera?.kind).toBe('region')
    await userEvent.click(within(panel).getByRole('button', { name: 'Reset view' }))
    expect(useMapState.getState().camera?.kind).toBe('reset')
  })
})

describe('watch columns and the legend', () => {
  it('keeps Watch columns off until asked, and turns them on and off with a labelled toggle', async () => {
    renderMap()
    const panel = await controls()
    const toggle = within(panel).getByRole('checkbox', { name: 'Watch columns' })
    expect(toggle).not.toBeChecked()
    expect(useMapState.getState().watchColumns).toBe(false)
    await userEvent.click(toggle)
    expect(useMapState.getState().watchColumns).toBe(true)
    expect(toggle).toBeChecked()
    await userEvent.click(toggle)
    expect(useMapState.getState().watchColumns).toBe(false)
  })

  it('says where risk is and is not modelled, with the count of scored cells', async () => {
    renderMap()
    const note = await screen.findByText(/^Not modelled:/)
    await waitFor(() =>
      expect(note).toHaveTextContent(
        'Not modelled: risk is computed for the Himalaya and Western Ghats hill cells (10); the rest of India is shown for context.',
      ),
    )
    expect(screen.getByText(/Columns mark Warning and Emergency/)).toHaveTextContent('Watch is the lime tint on the terrain')
  })
})

describe('states without data', () => {
  it('says so plainly when there is no live run and no replay set', async () => {
    server.use(...apiHandlers(noDataMode))
    renderMap()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Map controls' })).not.toBeInTheDocument()
  })

  it('explains a date that is not in the store and offers the latest', async () => {
    renderMap('/map?date=2020-01-01')
    expect(await screen.findByText(/No data for 1 Jan 2020 in case_test_set/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show the latest date' }))
    expect(useMapState.getState().date).toBeNull()
    await waitFor(() => expect(screen.queryByText(/No data for 1 Jan 2020/)).not.toBeInTheDocument())
  })

  it('shows the API message when the day has no grid', async () => {
    server.use(
      http.get('*/api/grid', () => HttpResponse.json({ detail: 'no alert rows for 2024-08-05' }, { status: 404 })),
    )
    renderMap()
    expect(await screen.findByText(/No risk grid for 5 Aug 2024: no alert rows for 2024-08-05/)).toBeInTheDocument()
  })

  it('says the rain layer has no data when the API has no rain field', async () => {
    server.use(http.get('*/api/rain', () => HttpResponse.json({ detail: 'no feature table' }, { status: 404 })))
    renderMap()
    expect(await screen.findByText(/the API has no rain field for this date/)).toBeInTheDocument()
  })
})

describe('legend rain sentence', () => {
  const withRain = (over: Record<string, unknown>) =>
    server.use(http.get('*/api/rain', () => HttpResponse.json({ ...rainPayload, ...over })))

  it('names the source the replay set says it used', async () => {
    withRain({ rain_sources: ['imd', 'chirps_aligned'] })
    renderMap()
    expect(await screen.findByText(/from IMD gauge-based grid and CHIRPS satellite estimate/)).toBeInTheDocument()
  })

  it('names IMERG for a live set', async () => {
    withRain({ set: 'live', column: 'irain_acc_1', rain_sources: ['imerg'] })
    renderMap()
    expect(await screen.findByText(/from NASA IMERG \(satellite\)/)).toBeInTheDocument()
  })

  it('stays neutral when the API names no source', async () => {
    renderMap()
    const note = await screen.findByText(/Rain streaks follow/)
    expect(note).toHaveTextContent("Rain streaks follow the day's 1-day rain (mm/day); none where it did not rain.")
    expect(note.textContent).not.toMatch(/blended|IMERG|IMD/)
  })
})

describe('risk convention', () => {
  it('adds the multiple of the Watch threshold to the hover card when the API reports thresholds', async () => {
    const thresholds = { watch: 0.1, warning: 0.3, emergency: 0.6, source: 'card.alert_levels' }
    server.use(http.get('*/api/mode', () => HttpResponse.json({ ...replayMode, thresholds })))
    renderMap()
    await controls()
    await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    act(() => useMapState.getState().setHover({ cell: 107, x: 100, y: 120 }))
    const card = await screen.findByTestId('hover-card')
    expect(card).toHaveTextContent('50,000 per 100k cell-days')
    expect(card).toHaveTextContent('5× Watch threshold')
    expect(screen.getByText('50,000 per 100k cell-days', { selector: 'dd' })).toHaveAttribute('title', expect.stringContaining('Raw probability 0.500'))
  })
})

describe('a cell capped by the rain trigger', () => {
  const cappedGrid = () =>
    server.use(
      http.get('*/api/grid', () =>
        HttpResponse.json({ ...gridPayload, flags: bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 0, 0, 0, GRID_FLAG.capped])) }),
      ),
    )

  it('has no "About 1 in" sentence in its hover card, and labels the risk as the model estimate', async () => {
    cappedGrid()
    renderMap()
    await controls()
    await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    act(() => useMapState.getState().setHover({ cell: 109, x: 100, y: 120 }))
    const card = await screen.findByTestId('hover-card')
    expect(card).toHaveTextContent('Too little recent rain for a rain-triggered landslide, so no chance is given')
    expect(card).toHaveTextContent('model estimate (not used for the level)')
    expect(card).not.toHaveTextContent('About 1 in')
    act(() => useMapState.getState().setHover({ cell: 108, x: 100, y: 120 }))
    expect(await screen.findByTestId('hover-card')).toHaveTextContent('About 1 in 2 chance of a landslide')
  })

  it('has no "About 1 in" sentence in the top alerts list', async () => {
    cappedGrid()
    renderMap()
    const list = await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    const [capped, next] = within(list).getAllByRole('button', { hidden: true })
    expect(capped).toHaveTextContent('not used')
    expect(capped).not.toHaveTextContent('1 in 1')
    expect(capped!.querySelector('[title*="Too little recent rain"]')).toHaveAttribute(
      'title',
      expect.stringContaining('model estimate (not used for the level)'),
    )
    expect(capped!.querySelector('[title*="About 1 in"]')).toBeNull()
    expect(next).toHaveTextContent('1 in 2')
  })
})

describe('text alternative and click-through', () => {
  it('lists the top alerts as buttons, highest first, and opens one on click', async () => {
    const router = renderMap()
    const list = await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    const items = within(list).getAllByRole('button', { hidden: true })
    expect(items).toHaveLength(6)
    expect(items[0]).toHaveAccessibleName(/Cell 109,.*Emergency, risk 90,000 per 100k cell-days, Insufficient confidence/)
    await userEvent.click(screen.getByText(/Top alerts on the map/))
    await userEvent.click(items[0]!)
    await waitFor(() => expect(router.state.location.pathname).toBe('/alerts-why'))
    expect(router.state.location.search).toBe('?cell=109&date=2024-08-05')
  })
})

describe('click-through of a forecast', () => {
  const liveWithForecast = [
    http.get('*/api/mode', () =>
      HttpResponse.json({ ...replayMode, mode: 'live', set: 'live', leads: { '2024-08-04': [0], '2024-08-05': [0, 3] } }),
    ),
    http.get('*/api/grid', ({ request }) => {
      const lead = Number(new URL(request.url).searchParams.get('lead'))
      return lead === 3 ? HttpResponse.json({ ...gridPayload, lead: 3 }) : undefined
    }),
  ]

  it('opens the detail of the lead on the map, with the run date', async () => {
    server.use(...liveWithForecast)
    const router = renderMap('/map?lead=3')
    await controls()
    await waitFor(() => expect(useMapState.getState().lead).toBe(3))
    const list = await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    await userEvent.click(screen.getByText(/Top alerts on the map/))
    await userEvent.click(within(list).getAllByRole('button', { hidden: true })[0]!)
    await waitFor(() => expect(router.state.location.pathname).toBe('/alerts-why'))
    expect(router.state.location.search).toBe('?cell=109&date=2024-08-05&lead=3')
  })

  it('does not add a lead to the address for D0', async () => {
    const router = renderMap()
    const list = await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    await userEvent.click(screen.getByText(/Top alerts on the map/))
    await userEvent.click(within(list).getAllByRole('button', { hidden: true })[0]!)
    await waitFor(() => expect(router.state.location.pathname).toBe('/alerts-why'))
    expect(router.state.location.search).not.toContain('lead')
  })
})

describe('place names', () => {
  const withPlaces = () => server.use(http.get('*/api/places', () => HttpResponse.json(placesPayload)))

  it('names the hovered cell and says how far its place is, keeping the coordinates', async () => {
    withPlaces()
    renderMap()
    await controls()
    await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    await waitFor(() => expect(screen.getByText('Place names: GeoNames (CC BY 4.0)')).toBeInTheDocument())
    act(() => useMapState.getState().setHover({ cell: 107, x: 100, y: 120 }))
    const card = await screen.findByTestId('hover-card')
    expect(card).toHaveTextContent('Mananthavady, Wayanad, Kerala')
    expect(card).toHaveTextContent('8 km from town centre · 89.')
    expect(card).toHaveTextContent('°S')
  })

  it('says "nearest town" for a remote cell and names Nepal and Bhutan', async () => {
    withPlaces()
    renderMap()
    await controls()
    await waitFor(() => expect(screen.getByText('Place names: GeoNames (CC BY 4.0)')).toBeInTheDocument())
    act(() => useMapState.getState().setHover({ cell: 108, x: 100, y: 120 }))
    const card = await screen.findByTestId('hover-card')
    expect(card).toHaveTextContent('Kathmandu, Bagmati Province, Nepal')
    expect(card).toHaveTextContent('nearest town: Kathmandu (32 km)')
    act(() => useMapState.getState().setHover({ cell: 109, x: 100, y: 120 }))
    await waitFor(() => expect(screen.getByTestId('hover-card')).toHaveTextContent('Thimphu, Bhutan'))
  })

  it('lists the top alerts by place and keeps the cell id in the accessible name', async () => {
    withPlaces()
    renderMap()
    const list = await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    await waitFor(() => expect(within(list).getAllByRole('button', { hidden: true })[0]).toHaveAccessibleName(/^Cell 109, Thimphu, Bhutan, Emergency/))
    expect(within(list).getAllByRole('button', { hidden: true })[1]).toHaveTextContent('Kathmandu, Bagmati Province, Nepal')
  })

  it('asks for the place table once, however many cells are hovered', async () => {
    let requests = 0
    server.use(
      http.get('*/api/places', () => {
        requests += 1
        return HttpResponse.json(placesPayload)
      }),
    )
    renderMap()
    await controls()
    await waitFor(() => expect(screen.getByText('Place names: GeoNames (CC BY 4.0)')).toBeInTheDocument())
    for (const cell of [107, 108, 109, 107]) {
      act(() => useMapState.getState().setHover({ cell, x: 100, y: 120 }))
      await screen.findByTestId('hover-card')
    }
    expect(requests).toBe(1)
  })

  it('falls back to coordinates, without an attribution, when the API has no place table', async () => {
    renderMap()
    await controls()
    await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    act(() => useMapState.getState().setHover({ cell: 107, x: 100, y: 120 }))
    const card = await screen.findByTestId('hover-card')
    expect(card).toHaveTextContent(/°S, .*°W/)
    expect(card).not.toHaveTextContent('from town centre')
    expect(screen.queryByText(/GeoNames/)).not.toBeInTheDocument()
  })
})

describe('hover card content', () => {
  it('describes a cell with id, place, level, risk and confidence', () => {
    const info = describeCell(decodeGrid(gridPayload), 109)
    expect(info).toMatchObject({ cell: 109, level: 3, levelName: 'Emergency', confidence: 'Insufficient' })
    expect(info!.risk.primary).toBe('90,000 per 100k cell-days')
    expect(info!.risk.secondary).toBeNull()
    expect(info!.location.primary).toMatch(/^\d+\.\d{2}°S, \d+\.\d{2}°W$/)
    expect(info!.location.secondary).toBeNull()
  })

  it('says the risk in words, with the day', () => {
    const grid = decodeGrid(gridPayload)
    expect(describeCell(grid, 109, null, null, true)!.odds!.sentence).toBe('About 1 in 1 chance of a landslide in this 5 km cell today')
    expect(describeCell(grid, 109)!.odds!.sentence).toMatch(/cell on Mon 5 Aug$/)
    expect(describeCell(grid, 109)!.certainty).toBeNull()
  })

  it('gives no chance for a rain-capped cell, and shows its risk as the model estimate', () => {
    const grid = decodeGrid({ ...gridPayload, flags: bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 0, 0, 0, GRID_FLAG.capped])) })
    const info = describeCell(grid, 109, null, null, true)!
    expect(info.capped).toBe(true)
    expect(info.odds!.short).toBe('not used')
    expect(info.odds!.sentence).not.toContain('About 1 in')
    expect(info.risk.primary).toBe('90,000 per 100k cell-days')
    expect(describeCell(grid, 108, null, null, true)).toMatchObject({ capped: false, odds: { short: '1 in 2' } })
  })

  it('keeps the odds and adds the ensemble note when the ensemble disagrees', () => {
    const flags = bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 0, 0, 0, GRID_FLAG.ensembleDisagrees]))
    const info = describeCell(decodeGrid({ ...gridPayload, flags }), 109, null, null, true)!
    expect(info.odds!.sentence).toBe(
      'About 1 in 1 chance of a landslide in this 5 km cell today (most of the 20 ensemble models put it lower)',
    )
  })

  it('has no probability line for a cell without risk', () => {
    const grid = decodeGrid({ ...gridPayload, risk: f32ToBase64([0, 0.02, 0.03, 0.04, 0.2, 0.25, 0.3, 0.5, 0.6, NaN]) })
    expect(describeCell(grid, 100)!.odds).toBeNull()
    expect(describeCell(grid, 109)!.odds).toBeNull()
  })

  it('names Firm or Depends and the rain source for a forecast cell', () => {
    const grid = decodeGrid({
      ...gridPayload,
      lead: 2,
      certainty: bytesToBase64(new Uint8Array([1, 1, 1, 1, 1, 1, 1, 1, 2, 2])),
      level_min: bytesToBase64(new Uint8Array([0, 0, 0, 0, 1, 1, 1, 2, 1, 1])),
      level_max: bytesToBase64(new Uint8Array([0, 0, 0, 0, 1, 1, 1, 2, 2, 3])),
      forecast: { source: 'ecmwf_hres', label: 'ECMWF IFS HRES (CC BY 4.0)', mapped: false, fallback: false, cycle: null, attribution: 'a' },
    })
    expect(describeCell(grid, 107)!.certainty).toMatchObject({ headline: 'Firm', why: 'set by rain already fallen' })
    expect(describeCell(grid, 109)!.certainty!.headline).toBe('Depends on rain forecast (Watch–Emergency)')
  })

  it('is null for a cell the grid does not hold', () => {
    expect(describeCell(decodeGrid(gridPayload), 5)).toBeNull()
  })

  it('shows the hovered cell next to the pointer', async () => {
    renderMap()
    await controls()
    await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    act(() => useMapState.getState().setHover({ cell: 107, x: 100, y: 120 }))
    const card = await screen.findByTestId('hover-card')
    expect(card).toHaveTextContent('Warning')
    expect(card).toHaveTextContent('Cell 107')
    expect(card).toHaveTextContent('50,000 per 100k cell-days')
    expect(card).toHaveTextContent('Degraded')
    expect(card).not.toHaveTextContent(/Raised|Held/)
  })

  it('says why a flagged cell is above its risk band', async () => {
    const flags = bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 0, 1, 2, 5]))
    server.use(http.get('*/api/grid', () => HttpResponse.json({ ...gridPayload, flags })))
    renderMap()
    await controls()
    await screen.findByRole('list', { name: 'Top alerts', hidden: true })
    act(() => useMapState.getState().setHover({ cell: 107, x: 100, y: 120 }))
    expect(await screen.findByTestId('hover-card')).toHaveTextContent('Raised: heavy rain while sources disagree')
    act(() => useMapState.getState().setHover({ cell: 108, x: 100, y: 120 }))
    await waitFor(() =>
      expect(screen.getByTestId('hover-card')).toHaveTextContent('Held at a higher level from yesterday'),
    )
    act(() => useMapState.getState().setHover({ cell: 109, x: 100, y: 120 }))
    await waitFor(() => expect(screen.getByTestId('hover-card')).toHaveTextContent('Raised: heavy rain while gauges are untrusted'))
  })

  it('describes the reasons of a cell from the grid flags', () => {
    const grid = decodeGrid({ ...gridPayload, flags: bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 0, 3, 0, 0])) })
    expect(describeCell(grid, 107)!.reasons).toEqual([
      'Raised: heavy rain while sources disagree',
      'Held at a higher level from yesterday',
    ])
    expect(describeCell(grid, 106)!.reasons).toEqual([])
    expect(describeCell(decodeGrid(gridPayload), 107)!.reasons).toEqual([])
  })
})
