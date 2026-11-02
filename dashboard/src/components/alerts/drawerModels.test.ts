import { describe, expect, it } from 'vitest'
import { parseCellDetail } from '../../data/api'
import { cellAt, cellBody, forecastBody, makeGrid } from '../../test/alertFixtures'
import { rainRows } from './evidence'
import { cellAtPoint, NEIGHBOUR_RADIUS, neighbourhood } from './neighbourhood'

describe('rain by source', () => {
  it('lists satellite, IMD, gauges and GFS in that order, with the numbers the API gave', () => {
    const rows = rainRows(parseCellDetail(cellBody))
    expect(rows.map((r) => [r.key, r.label, r.value])).toEqual([
      ['satellite', 'CHIRPS', null],
      ['imd', 'IMD', 179.23580932617188],
      ['gauges', 'Gauges', 158.13038635253906],
      ['gfs', 'GFS', null],
    ])
  })

  it('says why a value is missing instead of showing zero', () => {
    const [satellite, , , gfs] = rainRows(parseCellDetail(cellBody))
    expect(satellite!.missing).toMatch(/CHIRPS has no value/)
    expect(gfs!.missing).toMatch(/only used for the D\+1 to D\+3 forecasts/)
  })

  it('names the satellite slot IMERG in a live set and marks the source the model used', () => {
    const rows = rainRows(parseCellDetail({ ...cellBody, set: 'live' }))
    expect(rows[0]!.label).toBe('IMERG')
    expect(rows[1]!.detail).toMatch(/the rain the model used/)
  })

  it('reports every source as missing when the API has none', () => {
    const rows = rainRows(parseCellDetail({ ...cellBody, sources: {} }))
    expect(rows.map((r) => r.value)).toEqual([null, null, null, null])
  })
})

describe('rain by source for a forecast', () => {
  const rows = (lead: number, over: Record<string, unknown> = {}) => rainRows(parseCellDetail(forecastBody(lead, over)))

  it('puts the observed rain through the run date next to the GFS rain of the target day', () => {
    expect(rows(3).map((r) => [r.key, r.value])).toEqual([
      ['satellite', 91.2],
      ['imd', 82.5],
      ['gauges', 79.4],
      ['gfs', 67.9],
    ])
    expect(rows(1)[3]!.value).toBe(18.4)
  })

  it('dates what was observed and what is forecast', () => {
    const [satellite, , , gfs] = rows(2)
    expect(satellite!.detail).toBe('IMERG satellite estimate at the cell on 30 Jul 2024')
    expect(gfs!.detail).toBe('GFS forecast rain for 1 Aug 2024')
  })

  it('keeps a missing GFS total missing and says why, never zero', () => {
    const none = rows(3, { rain: { unit: 'mm/day', observed_date: '2024-07-30', observed: {}, forecast: [] } })
    expect(none.map((r) => r.value)).toEqual([null, null, null, null])
    expect(none[3]!.missing).toBe('GFS has no forecast rain for this cell on 2 Aug 2024')
    const old = rows(3, { rain: null, detail_missing: 'this run predates per-lead detail' })
    expect(old[3]!.missing).toMatch(/predates per-lead detail/)
  })
})

describe('neighbourhood', () => {
  const centre = cellAt(11.5, 76)
  const grid = makeGrid([
    { cell: centre, risk: 4e-4, level: 3 },
    { cell: centre + 1, risk: 3e-5, level: 2 },
    { cell: centre - 10_000, risk: 1e-5, level: 1 },
    { cell: centre + 10_000 + 1, risk: 1e-8, level: 0 },
    { cell: centre + 500_000, risk: 1e-5, level: 1 },
  ])

  it('is a square around the centre with north at the top', () => {
    const n = neighbourhood(grid, centre)
    const side = 2 * NEIGHBOUR_RADIUS + 1
    expect(n.cells).toHaveLength(side * side)
    expect(n.cells[0]).toMatchObject({ dx: -NEIGHBOUR_RADIUS, dy: NEIGHBOUR_RADIUS })
    expect(n.cells[n.cells.length - 1]).toMatchObject({ dx: NEIGHBOUR_RADIUS, dy: -NEIGHBOUR_RADIUS })
    const mid = n.cells[NEIGHBOUR_RADIUS * side + NEIGHBOUR_RADIUS]!
    expect(mid).toMatchObject({ cell: centre, level: 3 })
  })

  it('gives each cell the grid level, and null for a cell that was not scored', () => {
    const n = neighbourhood(grid, centre)
    const at = (dx: number, dy: number) => n.cells.find((c) => c.dx === dx && c.dy === dy)!
    expect(at(1, 0).level).toBe(2)
    expect(at(0, -1).level).toBe(1)
    expect(at(1, 1).level).toBe(0)
    expect(at(2, 2).level).toBeNull()
    expect(at(2, 2).risk).toBeNull()
  })

  it('counts scored cells and alerts, leaving out cells beyond the radius', () => {
    const n = neighbourhood(grid, centre)
    expect(n.scored).toBe(4)
    expect(n.alerts).toBe(3)
  })

  it('finds the cell under a point of the canvas', () => {
    const n = neighbourhood(grid, centre)
    const size = 260
    const step = size / (2 * NEIGHBOUR_RADIUS + 1)
    expect(cellAtPoint(n, NEIGHBOUR_RADIUS * step + 1, NEIGHBOUR_RADIUS * step + 1, size)?.cell).toBe(centre)
    expect(cellAtPoint(n, (NEIGHBOUR_RADIUS + 1) * step + 1, NEIGHBOUR_RADIUS * step + 1, size)?.cell).toBe(centre + 1)
    expect(cellAtPoint(n, -1, 5, size)).toBeNull()
    expect(cellAtPoint(n, 5, size, size)).toBeNull()
  })
})
