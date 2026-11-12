import { useEffect, useMemo } from 'react'
import { BufferAttribute, BufferGeometry, LineBasicMaterial } from 'three'
import type { Outline } from '../data/types'
import { PALETTE } from './levelColors'
import { outlineSegments } from './outline'
import type { TerrainField } from './terrainField'
import type { Window } from './geo'

/** India's outline is the subject; Nepal and Bhutan are drawn as its neighbours. */
const OPACITY: Record<string, number> = { India: 0.82 }
const NEIGHBOUR_OPACITY = 0.5

interface OutlineLayerProps {
  outline: Outline[]
  window: Window
  field: TerrainField
}

/** The India, Nepal and Bhutan outlines as crisp cyan lines floating just above the terrain. */
export default function OutlineLayer({ outline, window, field }: OutlineLayerProps) {
  const layers = useMemo(
    () =>
      outline.map((country) => {
        const geometry = new BufferGeometry()
        geometry.setAttribute('position', new BufferAttribute(outlineSegments(country, window, field), 3))
        const material = new LineBasicMaterial({
          color: PALETTE.cyan,
          transparent: true,
          opacity: OPACITY[country.name] ?? NEIGHBOUR_OPACITY,
        })
        return { name: country.name, geometry, material }
      }),
    [outline, window, field],
  )

  useEffect(
    () => () => {
      for (const { geometry, material } of layers) {
        geometry.dispose()
        material.dispose()
      }
    },
    [layers],
  )

  return (
    <>
      {layers.map(({ name, geometry, material }) => (
        <lineSegments key={name} geometry={geometry} material={material} frustumCulled={false} renderOrder={2} />
      ))}
    </>
  )
}
