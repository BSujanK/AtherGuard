/// <reference types="node" />
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cellCenter } from '../data/summary'
import type { Rain } from '../data/types'
import { buildColumns, COLUMN_MAX_HEIGHT, COLUMN_MIN_HEIGHT, columnHeight, columnMinLevel } from './columns'
import { cubicBezier, easeOutMotion } from './cameraEase'
import {
  cellToTexel,
  latLonToTexel,
  REGION_BOXES,
  regionOf,
  texelToCell,
  texelWorld,
  worldToTexel,
} from './geo'
import { hexToRgb, LEVEL_HEX, LEVEL_RGB, mixHex, NORMAL_HEX, PALETTE } from './levelColors'
import { FrameWatchdog, type QualityStep } from './perf'
import { pickTerrain } from './pick'
import { buildRainDrops, MAX_DROPS } from './rainField'
import { ALL_LEVELS, buildRiskTexels, findCell, visibleCells } from './riskTexture'
import { buildTerrainField, edgeDistance, FEATHER_CELLS, localRelief } from './terrainField'
import { flatTerrain, makeGrid, REAL_WINDOW } from './testData'

/** Ids and centres produced by aetherguard.grid.cell_center (the Python formula) for three real cells. */
const PYTHON_CELLS = [
  { id: 20285116, lat: 11.425, lon: 75.825, texel: 108 * 600 + 156 },
  { id: 20335116, lat: 11.675, lon: 75.825, texel: 113 * 600 + 156 },
  { id: 20375129, lat: 11.875, lon: 76.475, texel: 117 * 600 + 169 },
  // The base map's own corners and a Himalayan cell, so a shifted window cannot pass.
  { id: 19204960, lat: 6.025, lon: 68.025, texel: 0 },
  { id: 25495559, lat: 37.475, lon: 97.975, texel: 629 * 600 + 599 },
  { id: 24805150, lat: 34.025, lon: 77.525, texel: 560 * 600 + 190 },
]

describe('cell to texel mapping', () => {
  it.each(PYTHON_CELLS)('places cell $id at texel $texel and back', ({ id, lat, lon, texel }) => {
    expect(cellToTexel(id, REAL_WINDOW)).toBe(texel)
    expect(texelToCell(texel, REAL_WINDOW)).toBe(id)
    const c = cellCenter(id)
    expect(c.lat).toBeCloseTo(lat, 9)
    expect(c.lon).toBeCloseTo(lon, 9)
    expect(latLonToTexel(lat, lon, REAL_WINDOW)).toBe(texel)
  })

  it('is -1 for cells outside the window', () => {
    expect(cellToTexel(1919 * 10_000 + 4960, REAL_WINDOW)).toBe(-1)
    expect(cellToTexel(1920 * 10_000 + 4959, REAL_WINDOW)).toBe(-1)
    expect(cellToTexel(2550 * 10_000 + 4960, REAL_WINDOW)).toBe(-1)
    expect(cellToTexel(1920 * 10_000 + 5560, REAL_WINDOW)).toBe(-1)
    expect(latLonToTexel(5.99, 80, REAL_WINDOW)).toBeNull()
  })

  it('covers the window corners exactly', () => {
    expect(cellToTexel(1920 * 10_000 + 4960, REAL_WINDOW)).toBe(0)
    expect(cellToTexel(2549 * 10_000 + 5559, REAL_WINDOW)).toBe(630 * 600 - 1)
  })

  it('round-trips every texel of a window through the cell id', () => {
    const w = { rows: 7, cols: 5, lat0: 6, lon0: 68, step: 0.05 }
    for (let k = 0; k < 35; k++) expect(cellToTexel(texelToCell(k, w), w)).toBe(k)
  })

  it('maps scene space to the nearest texel and back', () => {
    for (const k of [0, 76, 35436, 560 * 520 - 1]) {
      const { x, z } = texelWorld(k, REAL_WINDOW)
      expect(worldToTexel(x, z, REAL_WINDOW)).toBe(k)
    }
    expect(worldToTexel(100, 0, REAL_WINDOW)).toBe(-1)
  })
})

describe('regions', () => {
  it('mirrors the boxes in configs/domain.yaml', () => {
    const yaml = readFileSync(resolve(process.cwd(), '../configs/domain.yaml'), 'utf8')
    for (const [name, box] of Object.entries(REGION_BOXES)) {
      const block = yaml.split(`  ${name}:`)[1]!.split(/\n\S/)[0]!
      const read = (key: string) => Number(new RegExp(`${key}:\\s*([\\d.]+)`).exec(block)![1])
      expect([read('lat_min'), read('lat_max'), read('lon_min'), read('lon_max')]).toEqual([
        box.latMin,
        box.latMax,
        box.lonMin,
        box.lonMax,
      ])
    }
  })

  it('classifies points like the backend: lower bound inclusive, upper exclusive, else none', () => {
    expect(regionOf(11.4, 75.8)).toBe('western_ghats')
    expect(regionOf(30, 85)).toBe('himalaya')
    expect(regionOf(22, 72)).toBe('himalaya')
    expect(regionOf(36, 85)).toBeNull()
    expect(regionOf(21.5, 75)).toBeNull()
    expect(regionOf(15, 80)).toBeNull()
  })
})

describe('level colours', () => {
  it('are exactly the palette, cool to hot, with Normal a quiet slate tint of the paper', () => {
    expect(LEVEL_HEX[1]).toBe(PALETTE.yellow)
    expect(LEVEL_HEX[2]).toBe(PALETTE.orange)
    expect(LEVEL_HEX[3]).toBe(PALETTE.red)
    expect(NORMAL_HEX).toBe(mixHex(PALETTE.paper, PALETTE.slate, 0.3))
    expect(LEVEL_RGB[1]).toEqual(hexToRgb(PALETTE.yellow))
  })

  it('end up byte for byte in the texture', () => {
    const grid = makeGrid(
      [0, 1, 2, 3].map((col) => ({ row: 0, col })),
      (i) => i,
    )
    const texels = buildRiskTexels(grid, REAL_WINDOW, visibleCells(grid, { levels: ALL_LEVELS, region: 'all' }))
    for (let level = 0; level < 4; level++) {
      expect(Array.from(texels.slice(4 * level, 4 * level + 3))).toEqual(Array.from(LEVEL_RGB[level]!))
      expect(texels[4 * level + 3]).toBeGreaterThan(0)
    }
    expect(texels[16 + 3]).toBe(0)
  })
})

describe('risk texture filters', () => {
  const grid = makeGrid(
    // Rows 0-2 are lat 8.0-8.15 (no region); a Himalaya cell and a Ghats cell are added below.
    [
      { row: 100, col: 100 }, // lat 13.0, Ghats box needs lon 72.5-78.5: lon 77.0 -> Western Ghats
      { row: 100, col: 400 }, // lon 92.0 at lat 13: no region
      { row: 450, col: 100 }, // lat 30.5, lon 77.0: Himalaya
      { row: 450, col: 101 },
    ],
    (i) => i,
  )

  it('hides levels that are switched off', () => {
    const levels = [true, false, true, false]
    const visible = visibleCells(grid, { levels, region: 'all' })
    expect(Array.from(visible)).toEqual(Array.from(grid.level, (l) => (levels[l] ? 1 : 0)))
  })

  it('keeps only the chosen region, decided from the cell centre', () => {
    const ghats = visibleCells(grid, { levels: ALL_LEVELS, region: 'western_ghats' })
    const himalaya = visibleCells(grid, { levels: ALL_LEVELS, region: 'himalaya' })
    expect(Array.from(ghats)).toEqual([1, 0, 0, 0])
    expect(Array.from(himalaya)).toEqual([0, 0, 1, 1])
  })

  it('finds a cell by id in the sorted grid', () => {
    expect(findCell(grid, grid.cells[2]!)).toBe(2)
    expect(findCell(grid, 5)).toBe(-1)
  })
})

describe('alert columns', () => {
  const terrain = flatTerrain(300, 300)
  const field = buildTerrainField(terrain)

  const crowd = () => {
    const cells = Array.from({ length: 20_000 }, (_, i) => ({ row: Math.floor(i / 200), col: i % 200 }))
    const grid = makeGrid(cells, (i) => i % 4)
    return { grid, visible: visibleCells(grid, { levels: ALL_LEVELS, region: 'all' }) }
  }

  it('builds one instance per visible Warning-and-above cell by default, 20k cells at once', () => {
    const { grid, visible } = crowd()
    const started = performance.now()
    const built = buildColumns(grid, terrain, field, visible)
    const elapsed = performance.now() - started
    expect(built.count).toBe(10_000)
    expect(built.matrices).toHaveLength(10_000 * 16)
    expect(Math.min(...built.levels)).toBe(2)
    expect(elapsed).toBeLessThan(1000)
  })

  it('adds a column for every Watch cell when Watch columns are switched on', () => {
    const { grid, visible } = crowd()
    expect(columnMinLevel(false)).toBe(2)
    expect(columnMinLevel(true)).toBe(1)
    const built = buildColumns(grid, terrain, field, visible, columnMinLevel(true))
    expect(built.count).toBe(15_000)
    expect(Math.min(...built.levels)).toBe(1)
  })

  it('stands each column on the terrain with height growing with risk', () => {
    const grid = makeGrid(
      [
        { row: 150, col: 150 },
        { row: 150, col: 151 },
        { row: 150, col: 152 },
      ],
      () => 2,
      (i) => [0.1, 0.5, 1][i]!,
    )
    const built = buildColumns(grid, terrain, field, new Uint8Array([1, 1, 1]))
    const heights = [0, 1, 2].map((n) => built.matrices[16 * n + 5]!)
    expect(heights[0]).toBeLessThan(heights[1]!)
    expect(heights[1]).toBeLessThan(heights[2]!)
    expect(heights[2]).toBeCloseTo(COLUMN_MAX_HEIGHT, 6)
    const texel = 150 * 300 + 150
    expect(built.matrices[13]).toBeCloseTo(field.height[texel]!, 6)
    expect(built.maxRisk).toBe(1)
  })

  it('skips Normal cells, hidden cells and cells outside the terrain', () => {
    const grid = makeGrid(
      [
        { row: 10, col: 10 },
        { row: 10, col: 11 },
        { row: 10, col: 12 },
        { row: 400, col: 10 },
      ],
      () => 2,
    )
    grid.level[0] = 0
    const built = buildColumns(grid, terrain, field, new Uint8Array([1, 0, 1, 1]))
    expect(built.count).toBe(1)
    expect(Array.from(built.source)).toEqual([2])
  })

  it('never makes a column shorter than the minimum', () => {
    expect(columnHeight(0, 1)).toBe(COLUMN_MIN_HEIGHT)
    expect(columnHeight(1, 0)).toBe(COLUMN_MIN_HEIGHT)
  })
})

describe('terrain field', () => {
  it('measures the distance to the nearest no-data sample or border', () => {
    const land = new Uint8Array(5 * 5).fill(1)
    land[2 * 5 + 4] = 0
    const d = edgeDistance(land, 5, 5)
    expect(d[2 * 5 + 3]).toBe(1)
    expect(d[2 * 5 + 2]).toBe(2)
    expect(d[0]).toBe(1)
    expect(d[2 * 5 + 0]).toBe(1)
    expect(d[1 * 5 + 3]).toBeCloseTo(1.41, 1)
  })

  it('feathers the window border: edge and height rise from the border inward', () => {
    const terrain = flatTerrain(40, 40, 1000)
    const field = buildTerrainField(terrain)
    const row = 20 * 40
    expect(field.edge[row + 39]).toBeLessThan(0.05)
    expect(field.edge[row + 39 - FEATHER_CELLS]).toBeGreaterThan(0.95)
    expect(field.height[row + 39]).toBeLessThan(field.height[row + 20]! * 0.2)
    for (let j = 20; j < 39; j++) expect(field.edge[row + j]).toBeLessThanOrEqual(field.edge[row + j - 1]!)
  })

  it('leaves the coast sharp: sea has no height and does not feather the land beside it', () => {
    const terrain = flatTerrain(40, 40, 1000)
    for (let i = 0; i < 40; i++) terrain.elev[i * 40 + 30] = NaN
    const field = buildTerrainField(terrain)
    const row = 20 * 40
    expect(field.height[row + 30]).toBe(0)
    expect(field.metres[row + 30]).toBe(-1)
    expect(field.edge[row + 29]).toBe(1)
    expect(field.height[row + 29]).toBe(field.height[row + 20])
  })

  it('lets low-relief plains recede and mountains stand out, from the elevation alone', () => {
    const rows = 60
    const cols = 60
    const terrain = flatTerrain(rows, cols, 80)
    for (let i = 0; i < rows; i++) {
      for (let j = 30; j < cols; j++) terrain.elev[i * cols + j] = 80 + (j - 30) * 150
    }
    const field = buildTerrainField(terrain)
    expect(field.prominence[30 * cols + 8]).toBe(0)
    expect(field.prominence[30 * cols + 50]).toBeGreaterThan(0.95)
  })

  it('computes relief as the local elevation range', () => {
    const metres = new Float32Array([0, 0, 0, 0, 500, 0, 0, 0, 0])
    const relief = localRelief(metres, 3, 3, 1)
    expect(Array.from(relief)).toEqual(new Array(9).fill(500))
  })
})

describe('terrain picking', () => {
  const terrain = flatTerrain(200, 200, 2000)
  const field = buildTerrainField(terrain)

  it('lands a ray cast straight down on the cell below it', () => {
    const { x, z } = texelWorld(100 * 200 + 120, terrain)
    const hit = pickTerrain({ origin: [x, 10, z], direction: [0, -1, 0] }, terrain, field)
    expect(hit?.texel).toBe(100 * 200 + 120)
    expect(hit?.cell).toBe(texelToCell(100 * 200 + 120, terrain))
  })

  it('finds the surface along an oblique ray', () => {
    const { x, z } = texelWorld(100 * 200 + 100, terrain)
    const dir = [0, -0.6, -0.8] as const
    const hit = pickTerrain({ origin: [x, 6, z + 8], direction: dir }, terrain, field)
    expect(hit).not.toBeNull()
    expect(hit!.point[1]).toBeCloseTo(field.height[hit!.texel]!, 1)
  })

  it('misses when the ray passes over the land or the cell has no data', () => {
    expect(pickTerrain({ origin: [0, 10, 0], direction: [1, 0, 0] }, terrain, field)).toBeNull()
    expect(pickTerrain({ origin: [100, 10, 0], direction: [0, -1, 0] }, terrain, field)).toBeNull()
    const holed = flatTerrain(200, 200, 2000)
    holed.elev[100 * 200 + 120] = NaN
    const { x, z } = texelWorld(100 * 200 + 120, holed)
    expect(pickTerrain({ origin: [x, 10, z], direction: [0, -1, 0] }, holed, buildTerrainField(holed))).toBeNull()
  })
})

describe('frame-time watchdog', () => {
  function run(frames: number, ms: number, from: { t: number }, w: FrameWatchdog) {
    for (let i = 0; i < frames; i++) {
      from.t += ms
      w.sample(ms, from.t)
    }
  }

  it('steps quality down one notch after sustained slow frames', () => {
    const steps: QualityStep[] = []
    const w = new FrameWatchdog((s) => steps.push(s))
    const clock = { t: 0 }
    run(60, 16, clock, w)
    expect(steps).toEqual([])
    run(150, 50, clock, w)
    expect(steps[0]).toBe(1)
    expect(w.quality).toBe(steps.at(-1))
  })

  it('does not react to a single spike or a short stutter', () => {
    const steps: QualityStep[] = []
    const w = new FrameWatchdog((s) => steps.push(s))
    const clock = { t: 0 }
    run(60, 16, clock, w)
    run(1, 400, clock, w)
    run(60, 16, clock, w)
    run(20, 60, clock, w)
    run(100, 16, clock, w)
    expect(steps).toEqual([])
  })

  it('ignores frames from a paused tab', () => {
    const w = new FrameWatchdog(() => expect.unreachable())
    const clock = { t: 0 }
    run(30, 16, clock, w)
    for (let i = 0; i < 10; i++) {
      clock.t += 5000
      w.sample(5000, clock.t)
    }
  })

  it('goes through particles, pixel ratio, then particles off, and stops at the bottom', () => {
    const steps: QualityStep[] = []
    const w = new FrameWatchdog((s) => steps.push(s))
    const clock = { t: 0 }
    run(2000, 60, clock, w)
    expect(steps).toEqual([1, 2, 3])
  })

  it('waits between steps instead of dropping several at once', () => {
    const times: number[] = []
    const w = new FrameWatchdog(() => times.push(clock.t))
    const clock = { t: 0 }
    run(2000, 60, clock, w)
    expect(times[1]! - times[0]!).toBeGreaterThanOrEqual(4000)
  })

  it('recovers one notch only after a long fast stretch', () => {
    const steps: QualityStep[] = []
    const w = new FrameWatchdog((s) => steps.push(s))
    const clock = { t: 0 }
    run(100, 60, clock, w)
    expect(steps).toEqual([1])
    run(600, 10, clock, w)
    expect(steps).toEqual([1])
    run(1500, 10, clock, w)
    expect(steps).toEqual([1, 0])
  })
})

describe('camera easing', () => {
  it('starts at 0, ends at 1 and never undershoots', () => {
    expect(easeOutMotion(0)).toBe(0)
    expect(easeOutMotion(1)).toBe(1)
    let last = 0
    for (let i = 1; i <= 100; i++) {
      const y = easeOutMotion(i / 100)
      expect(y).toBeGreaterThanOrEqual(last - 1e-9)
      last = y
    }
  })

  it('is front loaded like cubic-bezier(.16, 1, .3, 1)', () => {
    expect(easeOutMotion(0.2)).toBeGreaterThan(0.6)
    expect(easeOutMotion(0.5)).toBeGreaterThan(0.95)
  })

  it('reduces to the identity for a straight-line curve', () => {
    const linear = cubicBezier(0.25, 0.25, 0.75, 0.75)
    for (const x of [0.1, 0.5, 0.9]) expect(linear(x)).toBeCloseTo(x, 4)
  })
})

describe('rain drops', () => {
  const terrain = flatTerrain(200, 200, 500)
  const field = buildTerrainField(terrain)
  function rainOf(values: number[], rows: number, cols: number): Rain {
    return { date: 'd', set: 's', column: 'rain_acc_1', unit: 'mm/day', sources: [], rows, cols, lat0: 8, lon0: 72, step: 0.25, rain: Float32Array.from(values) }
  }

  it('has no drops on a dry day or where there is no data', () => {
    expect(buildRainDrops(rainOf([0, 0.2, NaN, NaN], 2, 2), terrain, field).count).toBe(0)
  })

  it('puts drops where it rained, more where it rained more', () => {
    const drops = buildRainDrops(rainOf([5, NaN, 60, NaN], 2, 2), terrain, field)
    expect(drops.count).toBeGreaterThan(0)
    let light = 0
    let heavy = 0
    for (let n = 0; n < drops.count; n++) {
      const z = drops.data[4 * n + 1]!
      // Row 0 spans lat 8-8.25 (z near +4.95 .. +4.7 on this 200-row window); row 1 is further north.
      if (z > 4.7) light++
      else heavy++
    }
    expect(heavy).toBeGreaterThan(light)
  })

  it('caps the total and orders drops so that any prefix is an even sample', () => {
    const wet = rainOf(new Array(36).fill(200), 6, 6)
    const drops = buildRainDrops(wet, terrain, field)
    expect(drops.count).toBeLessThanOrEqual(MAX_DROPS)
    const half = drops.count >> 1
    const mean = (from: number, to: number) => {
      let s = 0
      for (let n = from; n < to; n++) s += drops.data[4 * n]!
      return s / (to - from)
    }
    expect(Math.abs(mean(0, half) - mean(half, drops.count))).toBeLessThan(0.15)
  })
})
