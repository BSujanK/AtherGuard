import { mixHex, PALETTE } from '../../charts/theme'
import { GRID_COLS } from '../../data/summary'
import type { Grid } from '../../data/types'
import { LEVEL_HEX } from '../../scene/levelColors'
import { findCell } from '../../scene/riskTexture'

/** Cells either side of the centre: a 13 x 13 square, about 0.65 degrees (70 km) across. */
export const NEIGHBOUR_RADIUS = 6

export interface NeighbourCell {
  cell: number
  /** Column offset from the centre, east positive. */
  dx: number
  /** Row offset from the centre, north positive. */
  dy: number
  /** Level 0..3, or null when the grid does not hold the cell (not scored that day). */
  level: number | null
  risk: number | null
}

export interface Neighbourhood {
  centre: number
  radius: number
  /** Row-major from the north-west corner, `(2 * radius + 1) ** 2` entries. */
  cells: NeighbourCell[]
  scored: number
  alerts: number
}

/** The square of cells around `centre` with the level the grid gives each; north is up. */
export function neighbourhood(grid: Grid, centre: number, radius = NEIGHBOUR_RADIUS): Neighbourhood {
  const cells: NeighbourCell[] = []
  let scored = 0
  let alerts = 0
  for (let dy = radius; dy >= -radius; dy--) {
    for (let dx = -radius; dx <= radius; dx++) {
      const cell = centre + dy * GRID_COLS + dx
      const index = cell >= 0 ? findCell(grid, cell) : -1
      const level = index < 0 ? null : grid.level[index]!
      if (level !== null) {
        scored++
        if (level >= 1) alerts++
      }
      cells.push({ cell, dx, dy, level, risk: index < 0 ? null : grid.risk[index]! })
    }
  }
  return { centre, radius, cells, scored, alerts }
}

/** The cell under a pointer at (x, y) in a square canvas of `size` CSS pixels, or null outside the square. */
export function cellAtPoint(n: Neighbourhood, x: number, y: number, size: number): NeighbourCell | null {
  const side = 2 * n.radius + 1
  const col = Math.floor((x / size) * side)
  const row = Math.floor((y / size) * side)
  if (col < 0 || col >= side || row < 0 || row >= side) return null
  return n.cells[row * side + col] ?? null
}

const UNSCORED_EDGE = mixHex(PALETTE.ink, PALETTE.blue, 0.4)

/** Draws the square, north up: level colours from the palette, unscored cells as empty outlines, the centre in neon cyan. */
export function drawNeighbourhood(ctx: CanvasRenderingContext2D, n: Neighbourhood, size: number): void {
  const side = 2 * n.radius + 1
  const step = size / side
  ctx.clearRect(0, 0, size, size)
  ctx.fillStyle = PALETTE.ink
  ctx.fillRect(0, 0, size, size)
  n.cells.forEach((c, i) => {
    const x = (i % side) * step
    const y = Math.floor(i / side) * step
    if (c.level === null) {
      ctx.strokeStyle = UNSCORED_EDGE
      ctx.lineWidth = 1
      ctx.strokeRect(x + 1.5, y + 1.5, step - 3, step - 3)
    } else {
      ctx.fillStyle = LEVEL_HEX[c.level]!
      ctx.fillRect(x + 1, y + 1, step - 2, step - 2)
    }
  })
  const mid = n.radius * step
  ctx.strokeStyle = PALETTE.cyan
  ctx.lineWidth = 3
  ctx.strokeRect(mid + 0.5, mid + 0.5, step - 1, step - 1)
}
