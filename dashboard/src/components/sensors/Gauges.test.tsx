import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PALETTE } from '../../charts/theme'
import type { SensorStation } from '../../data/sources'
import type { Basemap } from '../../data/types'
import FaultList from './FaultList'
import GaugeMap from './GaugeMap'
import { isMostlyMissing } from './stations'
import { trustColor } from './trust'

const station = (id: string, over: Partial<SensorStation> = {}): SensorStation => ({
  station: id,
  name: `Gauge ${id}`,
  lat: 15,
  lon: 77,
  trust: 0.95,
  faultType: '',
  flagged: false,
  genuineExtreme: false,
  reasons: '',
  state: 'trusted',
  flagRateWindow: 0.02,
  ood: false,
  lastReading: null,
  ...over,
})

describe('GaugeMap', () => {
  const stations = [
    station('A', { trust: 1 }),
    station('B', { trust: 0.15, flagged: true, faultType: 'scale_drift', reasons: 'model;uncorroborated', state: 'uncertain' }),
    station('C', { trust: null, state: 'missing' }),
    station('FAR', { lon: 62 }),
  ]

  it('colours each gauge by trust from the palette and marks missing and flagged ones', () => {
    const { container } = render(<GaugeMap stations={stations} />)
    const dot = (id: string) => container.querySelector(`[data-station="${id}"] circle:not([class*="pulse"]):not([class*="hit"])`)!
    expect(dot('A')).toHaveAttribute('fill', PALETTE.cyan)
    expect(dot('B')).toHaveAttribute('fill', trustColor(0.15))
    expect(dot('C')).not.toHaveAttribute('fill')
    expect(container.querySelector('[data-station="C"]')).toHaveAttribute('data-missing', 'true')
    expect(container.querySelector('[data-station="B"]')).toHaveAttribute('data-flagged', 'true')
    expect(container.querySelectorAll('[data-flagged="true"] circle').length).toBe(3)
  })

  it('does not draw gauges outside the domain but says so', () => {
    const { container } = render(<GaugeMap stations={stations} />)
    expect(container.querySelector('[data-station="FAR"]')).toBeNull()
    expect(screen.getByText('1 gauge outside the mapped area not drawn')).toBeInTheDocument()
  })

  it('draws the national outlines of the base map as closed paths', () => {
    const basemap: Basemap = {
      rows: 1,
      cols: 1,
      lat0: 6,
      lon0: 68,
      step: 0.05,
      elev: new Float32Array([100]),
      mask: new Uint8Array([1]),
      outline: [
        { name: 'India', rings: [[[70, 10], [80, 10], [80, 20], [70, 10]]] },
        { name: 'Nepal', rings: [[[81, 28], [88, 28], [88, 30], [81, 28]]] },
      ],
    }
    const { container } = render(<GaugeMap stations={stations} terrain={basemap} />)
    const india = container.querySelector('[data-country="India"]')!
    expect(india.getAttribute('d')).toBe('M40.0 550.0L240.0 550.0L240.0 350.0L40.0 550.0Z')
    expect(container.querySelectorAll('[data-country]')).toHaveLength(2)
  })

  it('shows id, trust and fault type on hover and focus', () => {
    render(<GaugeMap stations={stations} />)
    const flagged = screen.getByRole('img', { name: 'Gauge B, trust 0.15, scale_drift' })
    fireEvent.pointerEnter(flagged)
    const tip = screen.getByRole('tooltip')
    expect(within(tip).getByText('B')).toBeInTheDocument()
    expect(within(tip).getByText('0.15')).toBeInTheDocument()
    expect(within(tip).getByText('scale_drift')).toBeInTheDocument()
    expect(within(tip).getByText('model, uncorroborated')).toBeInTheDocument()
    fireEvent.pointerLeave(flagged)
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.focus(flagged)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('says when a gauge without a value last reported, on hover and to screen readers', () => {
    const late = [
      station('L', { trust: null, state: 'missing', lastReading: '2026-10-12' }),
      station('N', { trust: null, state: 'missing', lat: 20 }),
    ]
    render(<GaugeMap stations={late} />)
    const reported = screen.getByRole('img', { name: 'Gauge L, trust no value, no fault, last reading 12 Oct 2026' })
    fireEvent.pointerEnter(reported)
    expect(within(screen.getByRole('tooltip')).getByText('Last reading')).toBeInTheDocument()
    expect(within(screen.getByRole('tooltip')).getByText('12 Oct 2026')).toBeInTheDocument()
    fireEvent.pointerLeave(reported)
    fireEvent.pointerEnter(screen.getByRole('img', { name: 'Gauge N, trust no value, no fault' }))
    expect(within(screen.getByRole('tooltip')).getByText('none in the recent window')).toBeInTheDocument()
  })

  it('shows no last-reading line for a gauge that has a value', () => {
    render(<GaugeMap stations={[station('A', { lastReading: '2026-10-16' })]} />)
    fireEvent.pointerEnter(screen.getByRole('img', { name: 'Gauge A, trust 0.95, no fault' }))
    expect(screen.queryByText('Last reading')).toBeNull()
  })

  it('makes only flagged gauges tab stops', () => {
    render(<GaugeMap stations={stations} />)
    expect(screen.getByRole('img', { name: /Gauge B/ })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('img', { name: /Gauge A/ })).toHaveAttribute('tabindex', '-1')
  })

  it('highlights a station chosen from outside', () => {
    render(<GaugeMap stations={stations} highlight="A" />)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Gauge A')
  })
})

describe('isMostlyMissing', () => {
  const gone = (id: string, lastReading: string | null = '2026-10-12') => station(id, { trust: null, state: 'missing', lastReading })

  it('is true when most gauges have no value and the table carries last-reading dates', () => {
    expect(isMostlyMissing([gone('A'), gone('B'), station('C')])).toBe(true)
  })

  it('is false when half or fewer are missing', () => {
    expect(isMostlyMissing([gone('A'), station('C')])).toBe(false)
  })

  it('is false for a replay table, which has no last-reading dates', () => {
    expect(isMostlyMissing([gone('A', null), gone('B', null), station('C')])).toBe(false)
  })

  it('is false for no gauges', () => {
    expect(isMostlyMissing([])).toBe(false)
  })
})

describe('FaultList', () => {
  const faulty = [
    station('Z', { trust: 0.4, faultType: 'offset_noise', flagged: true }),
    station('Y', { trust: 0.1, faultType: 'scale_drift', flagged: true }),
    station('X', { trust: null, faultType: 'dropout', flagged: true }),
  ]
  const names = () => screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[1]!.textContent)

  it('lists only gauges with a fault, worst trust first', () => {
    render(<FaultList stations={[station('OK'), ...faulty]} date="2024-08-05" />)
    expect(names()).toEqual(['Gauge YY', 'Gauge ZZ', 'Gauge XX'])
    expect(screen.getAllByText('5 Aug 2024')).toHaveLength(3)
  })

  it('sorts by column and flips direction on a second click', () => {
    render(<FaultList stations={faulty} date="2024-08-05" />)
    fireEvent.click(screen.getByRole('button', { name: /Fault type/ }))
    expect(names()).toEqual(['Gauge XX', 'Gauge ZZ', 'Gauge YY'])
    expect(screen.getByRole('columnheader', { name: /Fault type/ })).toHaveAttribute('aria-sort', 'ascending')
    fireEvent.click(screen.getByRole('button', { name: /Fault type/ }))
    expect(names()).toEqual(['Gauge YY', 'Gauge ZZ', 'Gauge XX'])
    expect(screen.getByRole('columnheader', { name: /Fault type/ })).toHaveAttribute('aria-sort', 'descending')
  })

  it('renders only the rows in view when the list is long', () => {
    const many = Array.from({ length: 600 }, (_, i) => station(`S${i}`, { trust: i / 1000, faultType: 'dropout', flagged: true }))
    render(<FaultList stations={many} date="2024-08-05" />)
    expect(screen.getByRole('table')).toHaveAttribute('aria-rowcount', '601')
    expect(screen.getAllByRole('row').length).toBeLessThan(20)
  })

  it('reports the hovered row to the caller', () => {
    const onActive = vi.fn()
    render(<FaultList stations={faulty} date="2024-08-05" onActive={onActive} />)
    fireEvent.pointerEnter(screen.getAllByRole('row')[1]!)
    expect(onActive).toHaveBeenCalledWith('Y')
  })

  it('says so when nothing is faulty', () => {
    render(<FaultList stations={[station('OK')]} date="2024-08-05" />)
    expect(screen.getByText(/No faults on 5 Aug 2024/)).toBeInTheDocument()
  })
})
