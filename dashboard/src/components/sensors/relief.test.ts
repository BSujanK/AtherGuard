import { describe, expect, it } from 'vitest'
import { hexToRgb, mixHex, PALETTE } from '../../charts/theme'
import { type Basemap, MASK } from '../../data/types'
import { renderRelief } from './relief'

const basemap = (rows: number, cols: number, elev: number[], land: number = MASK.india): Basemap => ({
  rows,
  cols,
  lat0: 8,
  lon0: 72,
  step: 0.05,
  elev: Float32Array.from(elev),
  mask: Uint8Array.from(elev, (e) => (Number.isFinite(e) ? land : MASK.sea)),
  outline: [],
})

const pixel = (img: ReturnType<typeof renderRelief>, x: number, y: number) => {
  const i = (y * img.width + x) * 4
  return [...img.data.slice(i, i + 4)]
}

const opaque = (hex: string) => [...hexToRgb(hex), 255]

describe('renderRelief', () => {
  it('paints sea (no data) as bare paper and keeps every pixel opaque', () => {
    const img = renderRelief(basemap(2, 2, [Number.NaN, Number.NaN, Number.NaN, Number.NaN]))
    expect(pixel(img, 0, 0)).toEqual(opaque(PALETTE.paper))
    expect(pixel(img, 1, 1)).toEqual(opaque(PALETTE.paper))
  })

  it('puts the southern grid row at the bottom of the image', () => {
    // Row 0 (south) is a tall ridge, row 1 (north) is sea.
    const img = renderRelief(basemap(2, 2, [3000, 3000, Number.NaN, Number.NaN]))
    expect(pixel(img, 0, 1)[2]).toBeLessThan(hexToRgb(PALETTE.paper)[2])       // land is tinted, so darker than the paper
    expect(pixel(img, 0, 0)).toEqual(opaque(PALETTE.paper))
  })

  it('tints high ground toward slate and stays within the palette range', () => {
    const flatLow = renderRelief(basemap(3, 3, new Array<number>(9).fill(0)))
    const flatHigh = renderRelief(basemap(3, 3, new Array<number>(9).fill(3000)))
    expect(pixel(flatLow, 1, 1)).toEqual(opaque(mixHex(PALETTE.paper, PALETTE.slate, 0.08)))
    expect(pixel(flatHigh, 1, 1)).toEqual(opaque(mixHex(PALETTE.paper, PALETTE.slate, 0.42)))
  })

  it('draws the land of neighbouring countries much fainter than India', () => {
    const india = renderRelief(basemap(3, 3, new Array<number>(9).fill(3000)))
    const other = renderRelief(basemap(3, 3, new Array<number>(9).fill(3000), MASK.other))
    const paper = hexToRgb(PALETTE.paper)[0]
    expect(paper - pixel(other, 1, 1)[0]!).toBeLessThan((paper - pixel(india, 1, 1)[0]!) * 0.5)
  })
})
