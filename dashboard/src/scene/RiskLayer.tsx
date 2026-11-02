import { useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import { DataTexture, NearestFilter, RGBAFormat, SRGBColorSpace, UnsignedByteType } from 'three'
import type { Grid, Terrain } from '../data/types'
import { buildRiskTexels } from './riskTexture'

/** An empty risk texture: one texel per terrain sample, nearest filtered so every cell reads as a block. */
export function createRiskTexture(terrain: Terrain): DataTexture {
  const texture = new DataTexture(
    new Uint8Array(terrain.rows * terrain.cols * 4),
    terrain.cols,
    terrain.rows,
    RGBAFormat,
    UnsignedByteType,
  )
  texture.colorSpace = SRGBColorSpace
  texture.magFilter = NearestFilter
  texture.minFilter = NearestFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true
  return texture
}

interface RiskLayerProps {
  texture: DataTexture
  terrain: Terrain
  grid: Grid | undefined
  visible: Uint8Array | null
}

/**
 * Drapes the risk grid on the terrain by writing the cells into the texture the terrain shader
 * samples. Re-runs when the grid or the filters change; renders nothing itself.
 */
export default function RiskLayer({ texture, terrain, grid, visible }: RiskLayerProps) {
  const invalidate = useThree((s) => s.invalidate)
  const texels = useMemo(
    () => (grid && visible ? buildRiskTexels(grid, terrain, visible) : new Uint8Array(terrain.rows * terrain.cols * 4)),
    [grid, visible, terrain],
  )

  useEffect(() => {
    texture.image.data!.set(texels)
    texture.needsUpdate = true
    invalidate()
  }, [texture, texels, invalidate])

  return null
}
