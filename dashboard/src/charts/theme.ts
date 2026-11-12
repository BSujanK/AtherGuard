/**
 * The pinned palette (spec section 8) and ECharts theme. Pure data: nothing here imports echarts, so tests and
 * non-chart code can share the palette helpers. `EChart` registers the theme under `THEME_NAME`.
 * Every other colour in the app is a mix of these seven (see `mixHex`); `palette.test.ts` enforces that.
 */

export const PALETTE = {
  paper: '#EEF2EC',
  signal: '#1746C7',
  slate: '#2F6F8F',
  yellow: '#F0B400',
  orange: '#E8700C',
  red: '#C8201C',
  ink: '#17233D',
} as const

export const THEME_NAME = 'aetherguard'
export const FONT_UI = "'Atkinson Hyperlegible Next', system-ui, -apple-system, 'Segoe UI', sans-serif"
export const FONT_DATA = "'Atkinson Hyperlegible Mono', ui-monospace, Consolas, monospace"
export const FONT_DISPLAY = "'National Park', system-ui, -apple-system, 'Segoe UI', sans-serif"

export type Rgb = readonly [number, number, number]

export function hexToRgb(hex: string): Rgb {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!m) throw new RangeError(`Not a #RRGGBB colour: ${hex}`)
  const n = parseInt(m[1]!, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export const rgbToHex = (rgb: Rgb): string =>
  `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`.toUpperCase()

/** Linear mix in sRGB: `t` = 0 gives `a`, 1 gives `b`. Mixing palette colours is the only way to derive new ones. */
export function mixHex(a: string, b: string, t: number): string {
  const k = Math.min(1, Math.max(0, t))
  const [ar, ag, ab] = hexToRgb(a)
  const [br, bg, bb] = hexToRgb(b)
  return rgbToHex([ar + (br - ar) * k, ag + (bg - ag) * k, ab + (bb - ab) * k])
}

/** `color` over ink at `alpha`, as an opaque hex (for places that cannot take CSS colour-mix). */
export const tint = (color: string, alpha: number): string => mixHex(PALETTE.paper, color, alpha)

export const TEXT = PALETTE.ink
export const TEXT_2 = tint(PALETTE.ink, 0.86)
export const TEXT_3 = tint(PALETTE.ink, 0.74)
export const GRID_LINE = mixHex(PALETTE.paper, PALETTE.ink, 0.13)
export const AXIS_LINE = mixHex(PALETTE.paper, PALETTE.ink, 0.44)
export const SURFACE = PALETTE.paper
export const SURFACE_RAISED = mixHex(PALETTE.paper, PALETTE.slate, 0.07)

/**
 * Series colours when several series share a chart: cyan, royal blue and lime and their mixes, ordered so
 * neighbours differ in lightness. Pair with distinct symbols or direct labels; colour alone never carries meaning.
 */
export const SERIES_COLORS = [
  PALETTE.signal,
  PALETTE.slate,
  PALETTE.yellow,
  mixHex(PALETTE.slate, PALETTE.signal, 0.5),
  mixHex(PALETTE.signal, PALETTE.yellow, 0.5),
] as const

const axisCommon = {
  axisLine: { lineStyle: { color: AXIS_LINE } },
  axisTick: { lineStyle: { color: AXIS_LINE } },
  axisLabel: { color: TEXT_2, fontFamily: FONT_UI, fontSize: 12 },
  nameTextStyle: { color: TEXT_2, fontFamily: FONT_UI, fontSize: 12 },
  splitLine: { lineStyle: { color: GRID_LINE } },
}

/** Value, log and time axes carry numbers, so their labels are set in the data face. */
const numericAxis = { ...axisCommon, axisLabel: { ...axisCommon.axisLabel, fontFamily: FONT_DATA, fontSize: 11 } }

export const aetherguardTheme = {
  color: [...SERIES_COLORS],
  backgroundColor: 'transparent',
  textStyle: { color: TEXT, fontFamily: FONT_UI },
  title: { textStyle: { color: TEXT, fontFamily: FONT_DISPLAY } },
  legend: { textStyle: { color: TEXT_2, fontFamily: FONT_UI, fontSize: 12 } },
  categoryAxis: { ...axisCommon, splitLine: { show: false } },
  valueAxis: numericAxis,
  logAxis: numericAxis,
  timeAxis: numericAxis,
  line: { lineStyle: { width: 2 }, symbolSize: 7 },
  bar: { barMaxWidth: 18 },
  tooltip: {
    backgroundColor: SURFACE_RAISED,
    borderColor: AXIS_LINE,
    borderWidth: 1,
    padding: [8, 12],
    extraCssText: 'border-radius: 10px;',
    textStyle: { color: TEXT, fontFamily: FONT_UI, fontSize: 13 },
    axisPointer: { lineStyle: { color: AXIS_LINE }, crossStyle: { color: AXIS_LINE } },
  },
} as const
