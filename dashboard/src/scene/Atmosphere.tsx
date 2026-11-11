import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  type LineSegments,
  ShaderMaterial,
} from 'three'
import { frameNow } from './frame'
import { lonLatToWorld, type Window } from './geo'
import { PALETTE } from './levelColors'

/** Deterministic pseudo-random sequence so the scene looks the same on every load. */
function seeded(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

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

const rainVertex = /* glsl */ `
  uniform float uTime;
  uniform float uIntensity;
  attribute vec3 aSeed;
  attribute float aEnd;
  varying float vAlpha;

  void main() {
    float fall = fract(aSeed.z + uTime * (0.55 + aSeed.x * 0.35));
    float y = 9.0 - fall * 10.0;
    vec3 p = vec3((aSeed.x - 0.5) * 40.0, y, (aSeed.y - 0.5) * 42.0);
    p += aEnd * vec3(0.12, 0.7, 0.0);
    vAlpha = (1.0 - aEnd * 0.9) * uIntensity * smoothstep(0.0, 0.1, fall) * (1.0 - smoothstep(0.9, 1.0, fall));
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`

const rainFragment = /* glsl */ `
  uniform vec3 uCyan;
  varying float vAlpha;

  void main() {
    gl_FragColor = vec4(uCyan * vAlpha * 0.22, 1.0);
    #include <colorspace_fragment>
  }
`

export function Rain({ count = 420 }: { count?: number }) {
  const ref = useRef<LineSegments>(null)
  const { geometry, material } = useMemo(() => {
    const rand = seeded(11)
    const seeds = new Float32Array(count * 2 * 3)
    const ends = new Float32Array(count * 2)
    for (let i = 0; i < count; i++) {
      const sx = rand()
      const sy = rand()
      const sz = rand()
      for (let v = 0; v < 2; v++) {
        seeds.set([sx, sy, sz], (i * 2 + v) * 3)
        ends[i * 2 + v] = v
      }
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(count * 2 * 3), 3))
    g.setAttribute('aSeed', new BufferAttribute(seeds, 3))
    g.setAttribute('aEnd', new BufferAttribute(ends, 1))
    const m = new ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uIntensity: { value: 1 },
        uCyan: { value: new Color(PALETTE.cyan) },
      },
      vertexShader: rainVertex,
      fragmentShader: rainFragment,
      blending: AdditiveBlending,
      transparent: true,
      depthWrite: false,
    })
    return { geometry: g, material: m }
  }, [count])

  useFrame((state) => {
    material.uniforms.uTime!.value = state.clock.elapsedTime
    material.uniforms.uIntensity!.value = frameNow().atmosphere
  })

  return <lineSegments ref={ref} geometry={geometry} material={material} frustumCulled={false} />
}
