import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import { AdditiveBlending, BufferAttribute, BufferGeometry, Color, ShaderMaterial } from 'three'
import { frameNow } from './frame'
import { PALETTE } from './levelColors'
import { QUALITY_STEPS } from './perf'
import type { RainDrops } from './rainField'
import { useMapState } from '../state/map'

/** How far above the ground a drop starts and how long its streak is, in scene units. */
const FALL_HEIGHT = 1.8
const STREAK = 0.2

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uIntensity;
  attribute vec4 aDrop;
  attribute float aEnd;
  varying float vAlpha;

  void main() {
    float speed = 0.4 + fract(aDrop.z * 7.0) * 0.3;
    float fall = fract(aDrop.z + uTime * speed);
    float y = aDrop.w + (1.0 - fall) * ${FALL_HEIGHT.toFixed(1)} + aEnd * ${STREAK.toFixed(2)};
    vAlpha = (1.0 - aEnd * 0.85) * uIntensity * smoothstep(0.0, 0.08, fall) * (1.0 - smoothstep(0.92, 1.0, fall));
    gl_Position = projectionMatrix * modelViewMatrix * vec4(aDrop.x, y, aDrop.y, 1.0);
  }
`

const fragmentShader = /* glsl */ `
  uniform vec3 uCyan;
  varying float vAlpha;

  void main() {
    gl_FragColor = vec4(uCyan * vAlpha * 0.7, 1.0);
    #include <colorspace_fragment>
  }
`

interface RainParticlesProps {
  drops: RainDrops
  reducedMotion: boolean
}

/**
 * Rain streaks falling onto the terrain wherever the day's rain field says it rained, denser for
 * heavier rain. The quality step from the frame-time watchdog draws only a prefix of the drops
 * (which are shuffled, so any prefix is an even sample) or none. With reduced motion the streaks
 * are frozen in place.
 */
export default function RainParticles({ drops, reducedMotion }: RainParticlesProps) {
  const invalidate = useThree((s) => s.invalidate)
  const quality = useMapState((s) => s.quality)

  const { geometry, material } = useMemo(() => {
    const g = new BufferGeometry()
    const drop = new Float32Array(drops.count * 8)
    const end = new Float32Array(drops.count * 2)
    for (let n = 0; n < drops.count; n++) {
      for (let v = 0; v < 2; v++) {
        drop.set(drops.data.subarray(4 * n, 4 * n + 4), (2 * n + v) * 4)
        end[2 * n + v] = v
      }
    }
    g.setAttribute('position', new BufferAttribute(new Float32Array(drops.count * 6), 3))
    g.setAttribute('aDrop', new BufferAttribute(drop, 4))
    g.setAttribute('aEnd', new BufferAttribute(end, 1))
    const m = new ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uIntensity: { value: 1 },
        uCyan: { value: new Color(PALETTE.cyan) },
      },
      vertexShader,
      fragmentShader,
      blending: AdditiveBlending,
      transparent: true,
      depthWrite: false,
    })
    return { geometry: g, material: m }
  }, [drops])

  useEffect(
    () => () => {
      geometry.dispose()
      material.dispose()
    },
    [geometry, material],
  )

  const share = QUALITY_STEPS[quality].particles
  useEffect(() => {
    geometry.setDrawRange(0, Math.floor(drops.count * share) * 2)
    invalidate()
  }, [geometry, drops.count, share, invalidate])

  useFrame((state) => {
    material.uniforms.uTime!.value = reducedMotion ? 0 : state.clock.elapsedTime
    const f = frameNow().rain
    material.uniforms.uIntensity!.value = f
  })

  return share > 0 ? <lineSegments geometry={geometry} material={material} frustumCulled={false} /> : null
}
