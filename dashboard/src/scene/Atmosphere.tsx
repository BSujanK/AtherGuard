import { useEffect, useMemo } from 'react'
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  ShaderMaterial,
} from 'three'
import { lonLatToWorld, type Window } from './geo'
import { PALETTE } from './levelColors'

const graticuleVertex = /* glsl */ `
  varying vec2 vPlace;

  void main() {
    vPlace = position.xz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const graticuleFragment = /* glsl */ `
  uniform vec3 uColor;
  varying vec2 vPlace;

  void main() {
    // Strongest around the map, gone well before the lines would reach the horizon. Per fragment: a line's
    // ends both lie beyond the fade, so a per-vertex value would blank the whole line.
    float fade = 1.0 - smoothstep(16.0, 58.0, length(vPlace));
    gl_FragColor = vec4(uColor * fade, 1.0);
    #include <colorspace_fragment>
  }
`

/** Half-extent of the graticule in degrees; the shader fades it out long before this. */
const GRATICULE_REACH = 70
/** Meridians stop here on the viewer's side: a line running behind the camera is dropped by some GL drivers. */
const GRATICULE_NEAR = 30
const GRATICULE_DEGREES = 5

/**
 * The chart the map lies on: every fifth parallel and meridian as a faint line at sea level. Scene space is
 * degrees, so these are the real lines, laid faintly over land and sea like the graticule of a printed chart.
 * `window` gives the latitude and longitude of the scene's origin.
 */
export function Graticule({ window: w }: { window: Window }) {
  const { geometry, material } = useMemo(() => {
    const centre = { lon: w.lon0 + (w.cols * w.step) / 2, lat: w.lat0 + (w.rows * w.step) / 2 }
    const first = (from: number) => Math.ceil(from / GRATICULE_DEGREES) * GRATICULE_DEGREES
    const positions: number[] = []
    for (let lon = first(centre.lon - GRATICULE_REACH); lon <= centre.lon + GRATICULE_REACH; lon += GRATICULE_DEGREES) {
      const { x } = lonLatToWorld(lon, centre.lat, w)
      positions.push(x, -0.02, -GRATICULE_REACH, x, -0.02, GRATICULE_NEAR)
    }
    for (let lat = first(centre.lat - GRATICULE_NEAR); lat <= centre.lat + GRATICULE_REACH; lat += GRATICULE_DEGREES) {
      const { z } = lonLatToWorld(centre.lon, lat, w)
      positions.push(-GRATICULE_REACH, -0.02, z, GRATICULE_REACH, -0.02, z)
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(positions), 3))
    const m = new ShaderMaterial({
      uniforms: { uColor: { value: new Color(PALETTE.blue).lerp(new Color(PALETTE.cyan), 0.3).multiplyScalar(0.2) } },
      vertexShader: graticuleVertex,
      fragmentShader: graticuleFragment,
      blending: AdditiveBlending,
      transparent: true,
      depthWrite: false,
      // Drawn over land and sea alike: stopping at the terrain would cut a rectangle (the data window) out of the grid.
      depthTest: false,
    })
    return { geometry: g, material: m }
  }, [w])

  useEffect(
    () => () => {
      geometry.dispose()
      material.dispose()
    },
    [geometry, material],
  )

  return <lineSegments geometry={geometry} material={material} frustumCulled={false} />
}
