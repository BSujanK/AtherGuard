import type { Terrain } from '../data/types'

/** Scene units are degrees; 1 degree of latitude is about this many metres. */
export const METRES_PER_DEGREE = 111_000
/** Vertical exaggeration applied on top of true scale. */
export const VERTICAL_EXAGGERATION = 14

/** The mesh fades out over this many cells inward from the grid border; the coast is a real edge and stays sharp. */
export const FEATHER_CELLS = 6
/** Height left at the very edge of the mesh, as a share of true height. */
const EDGE_HEIGHT = 0.12
/** Relief window radius in cells; relief (metres) below the first bound is plain, above the second mountain. */
const RELIEF_RADIUS = 5
const RELIEF_PLAIN = 70
const RELIEF_MOUNTAIN = 420

export interface TerrainField {
  rows: number
  cols: number
  step: number
  /** Scene-space height per vertex, faded toward the mesh edge; 0 where there is no data. */
  height: Float32Array
  /** True elevation in metres per vertex (-1 where there is no data), for contours and shading. */
  metres: Float32Array
  /** 0 at the grid border rising to 1 `FEATHER_CELLS` inside it. */
  edge: Float32Array
  /** 0 on low-relief plains rising to 1 in mountains, from the local elevation range. */
  prominence: Float32Array
  maxElevation: number
}

const smoothstep = (lo: number, hi: number, x: number): number => {
  const t = Math.min(1, Math.max(0, (x - lo) / (hi - lo)))
  return t * t * (3 - 2 * t)
}

/**
 * Distance in cells from every land sample to the nearest no-data sample or grid border, by a
 * two-pass chamfer transform (orthogonal step 1, diagonal step sqrt 2). Samples without data are 0.
 */
export function edgeDistance(land: Uint8Array, rows: number, cols: number): Float32Array {
  const d = new Float32Array(rows * cols)
  const DIAG = Math.SQRT2
  // Outside the grid counts as no data (distance 0), so a border sample is one step from an edge.
  const at = (i: number, j: number): number => (i < 0 || j < 0 || i >= rows || j >= cols ? 0 : d[i * cols + j]!)
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const k = i * cols + j
      if (!land[k]) continue
      d[k] = Math.min(at(i - 1, j) + 1, at(i, j - 1) + 1, at(i - 1, j - 1) + DIAG, at(i - 1, j + 1) + DIAG, 1e6)
    }
  }
  for (let i = rows - 1; i >= 0; i--) {
    for (let j = cols - 1; j >= 0; j--) {
      const k = i * cols + j
      if (!land[k]) continue
      d[k] = Math.min(d[k]!, at(i + 1, j) + 1, at(i, j + 1) + 1, at(i + 1, j + 1) + DIAG, at(i + 1, j - 1) + DIAG)
    }
  }
  return d
}

/** Max minus min elevation within `radius` cells (square window), ignoring no-data samples; separable. */
export function localRelief(metres: Float32Array, rows: number, cols: number, radius: number): Float32Array {
  const rowLo = new Float32Array(rows * cols)
  const rowHi = new Float32Array(rows * cols)
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      let mn = Infinity
      let mx = -Infinity
      for (let jj = Math.max(0, j - radius); jj <= Math.min(cols - 1, j + radius); jj++) {
        const e = metres[i * cols + jj]!
        if (e < 0) continue
        if (e < mn) mn = e
        if (e > mx) mx = e
      }
      rowLo[i * cols + j] = mn
      rowHi[i * cols + j] = mx
    }
  }
  const relief = new Float32Array(rows * cols)
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const k = i * cols + j
      if (metres[k]! < 0) continue
      let mn = Infinity
      let mx = -Infinity
      for (let ii = Math.max(0, i - radius); ii <= Math.min(rows - 1, i + radius); ii++) {
        const a = rowLo[ii * cols + j]!
        const b = rowHi[ii * cols + j]!
        if (a < mn) mn = a
        if (b > mx) mx = b
      }
      relief[k] = mx - mn
    }
  }
  return relief
}

/**
 * Everything the mesh and the picking need from the elevation grid, derived from the data alone:
 * faded heights, the border feather and how mountainous each place is. Sea (NaN) has no height and
 * does not feather its neighbours: the coast is drawn as the coast.
 */
export function buildTerrainField(terrain: Terrain, exaggeration = VERTICAL_EXAGGERATION): TerrainField {
  const { rows, cols, elev } = terrain
  const count = rows * cols
  const metres = new Float32Array(count)
  const land = new Uint8Array(count)
  let maxElevation = 0
  for (let k = 0; k < count; k++) {
    const e = elev[k]!
    if (Number.isFinite(e)) {
      metres[k] = Math.max(e, 0)
      land[k] = 1
      if (metres[k]! > maxElevation) maxElevation = metres[k]!
    } else {
      metres[k] = -1
    }
  }

  const dist = edgeDistance(new Uint8Array(count).fill(1), rows, cols)
  const relief = localRelief(metres, rows, cols, RELIEF_RADIUS)
  const yScale = exaggeration / METRES_PER_DEGREE
  const height = new Float32Array(count)
  const edge = new Float32Array(count)
  const prominence = new Float32Array(count)
  for (let k = 0; k < count; k++) {
    if (!land[k]) continue
    edge[k] = smoothstep(0, FEATHER_CELLS, dist[k]! - 1)
    prominence[k] = smoothstep(RELIEF_PLAIN, RELIEF_MOUNTAIN, relief[k]!)
    height[k] = metres[k]! * yScale * (EDGE_HEIGHT + (1 - EDGE_HEIGHT) * edge[k]!)
  }
  return { rows, cols, step: terrain.step, height, metres, edge, prominence, maxElevation }
}

const fields = new WeakMap<Terrain, TerrainField>()

/** The field of a terrain at the standard exaggeration, built once per terrain object. */
export function terrainField(terrain: Terrain): TerrainField {
  let field = fields.get(terrain)
  if (!field) {
    field = buildTerrainField(terrain)
    fields.set(terrain, field)
  }
  return field
}
