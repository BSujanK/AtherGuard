import { mixHex, PALETTE } from '../../charts/theme'
import { type Basemap, MASK } from '../../data/types'

export interface ReliefImage {
  width: number
  height: number
  /** RGBA, row 0 at the top (north). */
  data: Uint8ClampedArray<ArrayBuffer>
}

/** Elevation at which the land reaches its brightest royal blue. */
const FULL_RELIEF_M = 3000
/** Royal blue share of the lowland and of the highest ground (the rest is ink). */
const LOW_BLUE = 0.16
const HIGH_BLUE = 0.62
/** Land of neighbouring countries is drawn this far toward ink: context, not subject. */
const OTHER_LAND_DIM = 0.72
/** Metres per cell at the domain's mid latitude, to turn elevation steps into slopes. */
const CELL_M = 5000
const EXAGGERATION = 5
/** Light from the north-west, 45 degrees up, as a unit vector (x east, y north, z up). */
const LIGHT = [-0.5, 0.5, 0.7071].map((v, _, a) => v / Math.hypot(a[0]!, a[1]!, a[2]!)) as [number, number, number]

const rgbOf = (hex: string): [number, number, number] => {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/**
 * A faint hillshaded relief of the base map for the gauge map backdrop: ink for sea, royal blue lifted with
 * elevation over India, Nepal and Bhutan, with a light-and-shadow pass from the north-west (cyan on the lit side).
 * Land of other countries is drawn very dim. Only palette mixes.
 */
export function renderRelief(map: Basemap): ReliefImage {
  const { rows, cols, elev, mask } = map
  const data = new Uint8ClampedArray(rows * cols * 4)
  const at = (r: number, c: number): number =>
    elev[Math.min(rows - 1, Math.max(0, r)) * cols + Math.min(cols - 1, Math.max(0, c))]!
  const flat = LIGHT[2]
  for (let r = 0; r < rows; r++) {
    const y = rows - 1 - r // grid row 0 is the southern edge; the image's row 0 is the northern one
    for (let c = 0; c < cols; c++) {
      const e = elev[r * cols + c]!
      let hex: string = PALETTE.ink
      if (Number.isFinite(e)) {
        const here = Math.max(0, e)
        const side = (rr: number, cc: number) => (Number.isFinite(at(rr, cc)) ? Math.max(0, at(rr, cc)) : here)
        const dzdx = (side(r, c + 1) - side(r, c - 1)) / (2 * CELL_M)
        const dzdy = (side(r + 1, c) - side(r - 1, c)) / (2 * CELL_M)
        const nx = -dzdx * EXAGGERATION
        const ny = -dzdy * EXAGGERATION
        const shade = (nx * LIGHT[0] + ny * LIGHT[1] + LIGHT[2]) / Math.hypot(nx, ny, 1) / flat
        const share = LOW_BLUE + (HIGH_BLUE - LOW_BLUE) * Math.min(1, here / FULL_RELIEF_M)
        const base = mixHex(PALETTE.ink, PALETTE.blue, share)
        hex =
          shade >= 1
            ? mixHex(base, PALETTE.cyan, Math.min(1, (shade - 1) * 0.5) * 0.3)
            : mixHex(base, PALETTE.ink, Math.min(1, (1 - shade) * 0.8) * 0.6)
        if (mask[r * cols + c] === MASK.other) hex = mixHex(hex, PALETTE.ink, OTHER_LAND_DIM)
      }
      const [red, green, blue] = rgbOf(hex)
      const i = (y * cols + c) * 4
      data[i] = red
      data[i + 1] = green
      data[i + 2] = blue
      data[i + 3] = 255
    }
  }
  return { width: cols, height: rows, data }
}
