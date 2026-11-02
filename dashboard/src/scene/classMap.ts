import { DataTexture, NearestFilter, RGBAFormat, UnsignedByteType } from 'three'
import type { Basemap } from '../data/types'

/** RGBA8 texels with the country class (`MASK` code) in the red channel, one per base map cell. */
export function buildClassTexels(mask: Uint8Array): Uint8Array {
  const data = new Uint8Array(mask.length * 4)
  for (let k = 0; k < mask.length; k++) {
    data[4 * k] = mask[k]!
    data[4 * k + 3] = 255
  }
  return data
}

/** The class texture the terrain shader samples to dim neighbouring countries; nearest filtered, so cells stay blocks. */
export function createClassTexture(map: Basemap): DataTexture {
  const texture = new DataTexture(buildClassTexels(map.mask), map.cols, map.rows, RGBAFormat, UnsignedByteType)
  texture.magFilter = NearestFilter
  texture.minFilter = NearestFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true
  return texture
}
