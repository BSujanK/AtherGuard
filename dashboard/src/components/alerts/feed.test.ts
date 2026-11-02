import { describe, expect, it } from 'vitest'
import { decodePlaces } from '../../data/api'
import { cellAt, makeGrid, syntheticGrid } from '../../test/alertFixtures'
import { bytesToBase64, u16ToBase64, u32ToBase64 } from '../../test/fixtures'
import {
  DEFAULT_LEVELS,
  DEFAULT_SORT,
  type FeedFilter,
  feedSource,
  matchesSearch,
  newAlertCells,
  rowAt,
  searchDigits,
  selectFeed,
  windowRange,
} from './feed'

const ghats = (n: number) => cellAt(11 + n * 0.05, 76)
const himalaya = (n: number) => cellAt(30 + n * 0.05, 80)

const grid = makeGrid([
  { cell: ghats(0), risk: 3e-5, level: 2, confidence: 1 },
  { cell: ghats(1), risk: 1e-5, level: 1, confidence: 0 },
  { cell: himalaya(0), risk: 9e-5, level: 3, confidence: 2 },
  { cell: himalaya(1), risk: 5e-6, level: 1, confidence: 1 },
  { cell: himalaya(2), risk: 1e-7, level: 0, confidence: 0 },
  { cell: cellAt(0.5, 10), risk: 2e-5, level: 2, confidence: 0 },
])
const source = feedSource(grid)
const filter = (over: Partial<FeedFilter> = {}): FeedFilter => ({ levels: DEFAULT_LEVELS, region: 'all', query: '', ...over })
const cells = (index: Uint32Array) => Array.from(index, (i) => grid.cells[i]!)

const outside = cellAt(0.5, 10)

describe('feed filtering', () => {
  it('lists Watch and above by default, most severe first, then by risk', () => {
    expect(cells(selectFeed(source, filter(), DEFAULT_SORT))).toEqual([himalaya(0), ghats(0), outside, ghats(1), himalaya(1)])
  })

  it('filters by level, with Normal available on request', () => {
    const warning = selectFeed(source, filter({ levels: [false, false, true, false] }), DEFAULT_SORT)
    expect(cells(warning)).toEqual([ghats(0), outside])
    expect(selectFeed(source, filter({ levels: [true, true, true, true] }), DEFAULT_SORT)).toHaveLength(6)
    expect(selectFeed(source, filter({ levels: [false, false, false, false] }), DEFAULT_SORT)).toHaveLength(0)
  })

  it('filters by region, and keeps the cells outside both regions out of either', () => {
    const all = { levels: [true, true, true, true] }
    expect(cells(selectFeed(source, filter({ ...all, region: 'himalaya' }), DEFAULT_SORT))).toEqual([
      himalaya(0),
      himalaya(1),
      himalaya(2),
    ])
    expect(cells(selectFeed(source, filter({ ...all, region: 'western_ghats' }), DEFAULT_SORT))).toEqual([ghats(0), ghats(1)])
  })

  it('searches by cell id, matching any part of it and ignoring non-digits', () => {
    const target = String(himalaya(0))
    expect(cells(selectFeed(source, filter({ query: target }), DEFAULT_SORT))).toEqual([himalaya(0)])
    expect(cells(selectFeed(source, filter({ query: ` #${target.slice(2, 8)} ` }), DEFAULT_SORT))).toContain(himalaya(0))
    expect(selectFeed(source, filter({ query: '999999999' }), DEFAULT_SORT)).toHaveLength(0)
    expect(selectFeed(source, filter({ query: 'abc' }), DEFAULT_SORT)).toHaveLength(0)
    expect(selectFeed(source, filter({ query: '  ' }), DEFAULT_SORT)).toHaveLength(5)
    expect(searchDigits('cell 12-3')).toBe('123')
  })

  describe('searching by place', () => {
    const ids = [ghats(0), ghats(1), himalaya(0), himalaya(1)].sort((a, b) => a - b)
    const names = ['Mananthavady', 'Kalpatta', 'Chamoli', 'Gopeshwar']
    const label = (cell: number) => ids.indexOf(cell)
    const places = decodePlaces({
      attribution: 'Place names: GeoNames (CC BY 4.0)',
      n: ids.length,
      places: names,
      districts: ['', 'Wayanad', 'Chamoli'],
      states: ['', 'Kerala', 'Uttarakhand'],
      countries: ['', 'India', 'Nepal'],
      cells: u32ToBase64(ids),
      place: u32ToBase64(ids.map((c) => [3, 0, 1, 2][label(c)]!)),
      district: u16ToBase64(ids.map((c) => (c === himalaya(0) || c === himalaya(1) ? 2 : 1))),
      state: u16ToBase64(ids.map((c) => (c === himalaya(0) || c === himalaya(1) ? 2 : 1))),
      country: bytesToBase64(new Uint8Array(ids.length).fill(1)),
      distance_km: u16ToBase64(ids.map(() => 5)),
    })
    const found = (query: string) => cells(selectFeed(source, filter({ query, places }), DEFAULT_SORT))

    it('matches the place, the district and the state, ignoring case', () => {
      const wayanad = new Set(found('wayanad'))
      expect([...wayanad].sort()).toEqual([ghats(0), ghats(1)].sort())
      expect(found('KERALA')).toHaveLength(2)
      expect(found('uttarakhand')).toEqual(found('chamoli'))
      expect(found('chamoli').sort()).toEqual([himalaya(0), himalaya(1)].sort())
    })

    it('matches a part of a name and trims the text', () => {
      expect(found('  gopesh ')).toHaveLength(1)
      expect(found('xyz')).toHaveLength(0)
    })

    it('still matches a cell id, and either one when the text holds both', () => {
      expect(found(String(himalaya(0)))).toEqual([himalaya(0)])
      expect(matchesSearch(himalaya(0), `${himalaya(0)}`, places)).toBe(true)
    })

    it('finds nothing by name when there is no place table', () => {
      expect(cells(selectFeed(source, filter({ query: 'wayanad', places: null }), DEFAULT_SORT))).toEqual([])
      expect(matchesSearch(ghats(0), 'wayanad', undefined)).toBe(false)
    })

    it('leaves a cell without a label out of a name search', () => {
      expect(matchesSearch(outside, 'wayanad', places)).toBe(false)
    })
  })

  it('combines level, region and search', () => {
    const out = selectFeed(
      source,
      filter({ region: 'himalaya', levels: [false, true, false, false], query: String(himalaya(1)) }),
      DEFAULT_SORT,
    )
    expect(cells(out)).toEqual([himalaya(1)])
  })
})

describe('feed sorting', () => {
  const all = filter({ levels: [true, true, true, true] })
  const by = (key: 'level' | 'risk' | 'confidence' | 'region', dir: 'asc' | 'desc') =>
    cells(selectFeed(source, all, { key, dir }))

  it('sorts by level and breaks ties by higher risk', () => {
    expect(by('level', 'desc')).toEqual([himalaya(0), ghats(0), outside, ghats(1), himalaya(1), himalaya(2)])
    expect(by('level', 'asc')).toEqual([himalaya(2), ghats(1), himalaya(1), ghats(0), outside, himalaya(0)])
  })

  it('sorts by risk in both directions', () => {
    expect(by('risk', 'desc')).toEqual([himalaya(0), ghats(0), outside, ghats(1), himalaya(1), himalaya(2)])
    expect(by('risk', 'asc')).toEqual([himalaya(2), himalaya(1), ghats(1), outside, ghats(0), himalaya(0)])
  })

  it('sorts by confidence, best first when ascending, then by risk', () => {
    expect(by('confidence', 'asc')).toEqual([outside, ghats(1), himalaya(2), ghats(0), himalaya(1), himalaya(0)])
    expect(by('confidence', 'desc')[0]).toBe(himalaya(0))
  })

  it('sorts by region name, A to Z, with cells outside both regions between the two', () => {
    expect(by('region', 'asc')).toEqual([himalaya(0), himalaya(1), himalaya(2), outside, ghats(0), ghats(1)])
    expect(by('region', 'desc')[0]).toBe(ghats(0))
  })

  it('puts a missing risk last whichever way the sort runs', () => {
    const withGap = feedSource(
      makeGrid([
        { cell: 1, risk: NaN, level: 1 },
        { cell: 2, risk: 1e-6, level: 1 },
        { cell: 3, risk: 5e-6, level: 1 },
      ]),
    )
    const run = (key: 'risk' | 'level', dir: 'asc' | 'desc') =>
      Array.from(selectFeed(withGap, filter({ levels: [true, true, true, true] }), { key, dir }), (i) => withGap.grid.cells[i])
    expect(run('risk', 'desc')).toEqual([3, 2, 1])
    expect(run('risk', 'asc')).toEqual([2, 3, 1])
    expect(run('level', 'desc')).toEqual([3, 2, 1])
  })
})

describe('feed rows', () => {
  it('describes a row with place, region and confidence name', () => {
    const row = rowAt(source, grid.cells.indexOf(himalaya(0)))
    expect(row).toMatchObject({ cell: himalaya(0), level: 3, region: 'Himalaya', confidenceName: 'Insufficient' })
    expect(row.lat).toBeCloseTo(30.025, 2)
    expect(row.lon).toBeCloseTo(80.025, 2)
  })
})

describe('thousands of rows', () => {
  const big = syntheticGrid(5000)
  const bigSource = feedSource(big)

  it('filters and sorts 5k rows quickly', () => {
    const started = performance.now()
    const all = selectFeed(bigSource, filter({ levels: [true, true, true, true] }), { key: 'risk', dir: 'desc' })
    const alerts = selectFeed(bigSource, filter(), DEFAULT_SORT)
    expect(all).toHaveLength(5000)
    expect(alerts.length).toBeGreaterThan(2000)
    for (let i = 1; i < all.length; i++) expect(big.risk[all[i - 1]!]!).toBeGreaterThanOrEqual(big.risk[all[i]!]!)
    expect(performance.now() - started).toBeLessThan(1500)
  })

  it('renders only the window of rows around the scroll position', () => {
    expect(windowRange(0, 600, 56, 5000, 6)).toEqual({ start: 0, end: 17 })
    const mid = windowRange(56 * 2000, 600, 56, 5000, 6)
    expect(mid.start).toBe(1994)
    expect(mid.end - mid.start).toBeLessThan(30)
    expect(windowRange(56 * 4990, 600, 56, 5000, 6).end).toBe(5000)
    expect(windowRange(0, 600, 56, 0)).toEqual({ start: 0, end: 0 })
  })
})

describe('new alerts after a refresh', () => {
  const day1 = makeGrid([
    { cell: 1, risk: 1e-5, level: 1 },
    { cell: 2, risk: 1e-7, level: 0 },
  ], '2024-08-05')
  const refreshed = makeGrid([
    { cell: 1, risk: 1e-5, level: 1 },
    { cell: 2, risk: 3e-5, level: 2 },
    { cell: 3, risk: 9e-5, level: 3 },
  ], '2024-08-05')

  it('flags cells that reached Watch since the previous grid of the same day', () => {
    expect([...newAlertCells(day1, refreshed, false)].sort()).toEqual([2, 3])
  })

  it('flags nothing on the first load', () => {
    expect(newAlertCells(null, refreshed, true).size).toBe(0)
  })

  it('flags a newer day only while following the latest date', () => {
    const next = makeGrid([{ cell: 1, risk: 1e-5, level: 1 }, { cell: 9, risk: 2e-5, level: 2 }], '2024-08-06')
    expect([...newAlertCells(day1, next, true)]).toEqual([9])
    expect(newAlertCells(day1, next, false).size).toBe(0)
    expect(newAlertCells(next, day1, true).size).toBe(0)
  })

  it('flags nothing when the lead changed, since the forecast grid is a different assessment of the day', () => {
    expect(newAlertCells(day1, { ...refreshed, lead: 3 }, false).size).toBe(0)
  })
})

describe('the firm-only filter and the certainty of a row', () => {
  // certainty per cell: 0 none, 1 firm, 2 depends; the level range over the rain scenarios
  const byCell = new Map<number, [number, number, number]>([
    [ghats(0), [2, 1, 3]],
    [ghats(1), [1, 1, 1]],
    [himalaya(0), [1, 3, 3]],
    [himalaya(1), [2, 0, 2]],
    [himalaya(2), [1, 0, 0]],
    [outside, [0, 2, 2]],
  ])
  const pick = (k: 0 | 1 | 2) => Uint8Array.from(Array.from(grid.cells, (c) => byCell.get(c)![k]))
  const forecast = { ...grid, lead: 2, certainty: pick(0), levelMin: pick(1), levelMax: pick(2) }
  const withCertainty = feedSource(forecast)
  const all = { levels: [true, true, true, true] as const }
  const listed = (index: Uint32Array) => Array.from(index, (i) => forecast.cells[i]!)

  it('lists only the cells whose level is firm when asked', () => {
    const firm = selectFeed(withCertainty, filter({ ...all, firmOnly: true }), DEFAULT_SORT)
    expect(listed(firm).sort()).toEqual([ghats(1), himalaya(0), himalaya(2)].sort())
    expect(selectFeed(withCertainty, filter({ ...all }), DEFAULT_SORT)).toHaveLength(6)
  })

  it('combines with the other filters', () => {
    const firm = selectFeed(withCertainty, filter({ firmOnly: true }), DEFAULT_SORT)
    expect(listed(firm)).toEqual([himalaya(0), ghats(1)]) // Watch and above only, most severe first
  })

  it('lists nothing as firm in a grid that has no certainty', () => {
    expect(selectFeed(source, filter({ ...all, firmOnly: true }), DEFAULT_SORT)).toHaveLength(0)
  })

  it('puts the certainty words on the row of a forecast cell', () => {
    const row = (cell: number) => rowAt(withCertainty, Array.from(forecast.cells).indexOf(cell))
    expect(row(ghats(0))).toMatchObject({ certaintyShort: 'Depends (Watch–Emergency)' })
    expect(row(ghats(1))).toMatchObject({ certaintyShort: 'Firm' })
    expect(row(outside).certainty).toBeNull()
    expect(rowAt(source, 0).certaintyShort).toBeNull()
  })
})
