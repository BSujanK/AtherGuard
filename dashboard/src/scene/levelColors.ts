import { hexToRgb, mixHex, PALETTE, type Rgb, rgbToHex } from '../charts/theme'

export { hexToRgb, mixHex, PALETTE, type Rgb, rgbToHex }

/** Royal blue dimmed toward ink: the calm Normal level (same as `--level-normal`). */
export const NORMAL_HEX = mixHex(PALETTE.ink, PALETTE.blue, 0.55)

/** Level colours indexed by the grid's level code 0..3, cool to hot: Normal, Watch, Warning, Emergency. */
export const LEVEL_HEX = [NORMAL_HEX, PALETTE.lime, PALETTE.flame, PALETTE.fire] as const

export const LEVEL_RGB: readonly Rgb[] = LEVEL_HEX.map(hexToRgb)

/** Opacity of each level's colour where it is draped on the terrain; calm cells stay subtle. */
export const LEVEL_ALPHA = [64, 190, 225, 240] as const
