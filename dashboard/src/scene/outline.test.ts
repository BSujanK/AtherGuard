import { describe, expect, it } from 'vitest'
import { cellCenter } from '../data/summary'
import { buildClassTexels } from './classMap'
import { buildColumns } from './columns'
import { cellToTexel, lonLatToWorld, texelWorld } from './geo'
import { OUTLINE_LIFT, outlineSegments } from './outline'
import { buildRiskTexels, visibleCells, ALL_LEVELS } from './riskTexture'
import { buildTerrainField } from './terrainField'
import { flatTerrain, makeGrid, REAL_WINDOW } from './testData'

describe('lonLatToWorld', () => {
  it('puts a cell centre exactly where the cell sits in the mesh and the risk layer', () => {
    // A Western Ghats cell, a Himalayan one and both corners of the real window, by their global-grid ids.
    for (const id of [20285116, 24805150, 19204960, 25495559]) {
      const { lat, lon } = cellCenter(id)
      const here = lonLatToWorld(lon, lat, REAL_WINDOW)
      const mesh = texelWorld(cellToTexel(id, REAL_WINDOW), REAL_WINDOW)
      expect(here.x).toBeCloseTo(mesh.x, 9)
      expect(here.z).toBeCloseTo(mesh.z, 9)
    }
  })

  it('has north pointing away from the viewer and east to the right', () => {
    const a = lonLatToWorld(80, 10, REAL_WINDOW)
    const b = lonLatToWorld(81, 11, REAL_WINDOW)
    expect(b.x - a.x).toBeCloseTo(1, 9)
    expect(b.z - a.z).toBeCloseTo(-1, 9)
  })
})

describe('risk texture and columns share one cell addressing', () => {
  it('draws a cell on the same texel and the same scene position whichever layer draws it', () => {
    const terrain = flatTerrain(REAL_WINDOW.rows, REAL_WINDOW.cols, 500)
    const field = buildTerrainField(terrain)
    const grid = makeGrid([{ row: 450, col: 190 }, { row: 108, col: 156 }], () => 3)
    const visible = visibleCells(grid, { levels: ALL_LEVELS, region: 'all' })
    const texels = buildRiskTexels(grid, terrain, visible)
    const columns = buildColumns(grid, terrain, field, visible)
    for (let n = 0; n < grid.n; n++) {
      const texel = cellToTexel(grid.cells[n]!, terrain)
      expect(texels[4 * texel + 3]).toBeGreaterThan(0)
      const { lat, lon } = cellCenter(grid.cells[n]!)
      const world = lonLatToWorld(lon, lat, terrain)
      expect(columns.matrices[16 * n + 12]).toBeCloseTo(world.x, 5)
      expect(columns.matrices[16 * n + 14]).toBeCloseTo(world.z, 5)
    }
    expect(texels.filter((_, k) => k % 4 === 3 && texels[k]! > 0)).toHaveLength(2)
  })
})

describe('outlineSegments', () => {
  const terrain = flatTerrain(100, 100, 1000)
  const field = buildTerrainField(terrain)
  const lon = (c: number) => terrain.lon0 + c * terrain.step
  const lat = (r: number) => terrain.lat0 + r * terrain.step
  const triangle = { name: 'Test', rings: [[[lon(30), lat(30)], [lon(60), lat(30)], [lon(60), lat(60)], [lon(30), lat(30)]]] as [number, number][][] }

  it('makes one segment per ring edge, six floats each, floating above the surface', () => {
    const seg = outlineSegments(triangle, terrain, field)
    expect(seg).toHaveLength(3 * 6)
    for (let i = 1; i < seg.length; i += 3) expect(seg[i]).toBeGreaterThanOrEqual(field.height[30 * 100 + 30]! + OUTLINE_LIFT - 1e-6)
  })

  it('closes a ring that was left open', () => {
    const open = { name: 'Open', rings: [triangle.rings[0]!.slice(0, 3)] }
    expect(outlineSegments(open, terrain, field)).toHaveLength(3 * 6)
  })

  it('sits on the same scene plane as the cells', () => {
    const seg = outlineSegments(triangle, terrain, field)
    const cell = texelWorld(30 * 100 + 30, terrain)
    // The first point is the south-west corner of the cell at row 30, column 30: half a cell from its centre.
    expect(seg[0]).toBeCloseTo(cell.x - terrain.step / 2, 6)
    expect(seg[2]).toBeCloseTo(cell.z + terrain.step / 2, 6)
  })

  it('stops at the window edge instead of drawing off the map', () => {
    const outside = { name: 'Out', rings: [[[lon(-5), lat(10)], [lon(10), lat(10)], [lon(10), lat(20)], [lon(-5), lat(10)]]] as [number, number][][] }
    expect(outlineSegments(outside, terrain, field)).toHaveLength(1 * 6)
  })

  it('draws nothing for a country without rings', () => {
    expect(outlineSegments({ name: 'Empty', rings: [] }, terrain, field)).toHaveLength(0)
  })
})

describe('buildClassTexels', () => {
  it('writes the country class in the red channel of opaque texels', () => {
    expect(Array.from(buildClassTexels(Uint8Array.from([0, 1, 4])))).toEqual([0, 0, 0, 255, 1, 0, 0, 255, 4, 0, 0, 255])
  })
})
