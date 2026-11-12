import { hexToRgb, mixHex, PALETTE, type Rgb, rgbToHex } from '../charts/theme'

export { hexToRgb, mixHex, PALETTE, type Rgb, rgbToHex }

/** A quiet slate tint of the paper: the calm Normal level (same as `--level-normal`). */
export const NORMAL_HEX = mixHex(PALETTE.paper, PALETTE.slate, 0.3)

/** The sea and everything beyond the sheet: the page background (same as `--bg`). */
export const SEA_HEX = mixHex(PALETTE.paper, PALETTE.slate, 0.14)

/** Level colours indexed by the grid's level code 0..3, cool to hot: Normal, Watch, Warning, Emergency. */
export const LEVEL_HEX = [NORMAL_HEX, PALETTE.yellow, PALETTE.orange, PALETTE.red] as const

export const LEVEL_RGB: readonly Rgb[] = LEVEL_HEX.map(hexToRgb)

/** Opacity of each level's colour where it is draped on the terrain; calm cells stay subtle. */
export const LEVEL_ALPHA = [110, 205, 230, 242] as const
