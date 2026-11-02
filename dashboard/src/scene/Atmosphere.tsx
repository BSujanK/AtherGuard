import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  type LineSegments,
  type Points,
  ShaderMaterial,
} from 'three'
import { frameNow } from './frame'
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

const sparkVertex = /* glsl */ `
  uniform float uTime;
  uniform float uSize;
  uniform float uIntensity;
  uniform float uPixelRatio;
  attribute vec4 aSeed;
  varying float vAlpha;
  varying float vHeat;
  varying float vSpark;

  void main() {
    float life = fract(aSeed.w + uTime * (0.035 + aSeed.z * 0.05));
    vec3 p;
    p.x = (aSeed.x - 0.5) * 38.0 + sin(life * 12.0 + aSeed.y * 40.0) * 0.55;
    p.z = (aSeed.y - 0.5) * 40.0 + cos(life * 9.0 + aSeed.x * 30.0) * 0.4;
    p.y = -0.4 + life * 11.0;
    vAlpha = smoothstep(0.0, 0.08, life) * (1.0 - smoothstep(0.55, 1.0, life)) * uIntensity;
    vHeat = aSeed.z * aSeed.z;
    vSpark = step(0.94, fract(aSeed.x * 7.31 + aSeed.y * 3.17));
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = uSize * uPixelRatio * (0.5 + aSeed.z) * (26.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`

const sparkFragment = /* glsl */ `
  uniform vec3 uCyan;
  uniform vec3 uLime;
  uniform vec3 uFlame;
  varying float vAlpha;
  varying float vHeat;
  varying float vSpark;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    float core = smoothstep(0.5, 0.08, d);
    // Mostly cyan sparks, some lime, and an occasional flame orange one.
    vec3 spark = mix(mix(uCyan, uLime, vHeat), uFlame, vSpark);
    vec3 col = spark * (0.9 + 1.4 * core * core);
    gl_FragColor = vec4(col * core * vAlpha, 1.0);
    #include <colorspace_fragment>
  }
`

export function Sparks({ count = 650 }: { count?: number }) {
  const ref = useRef<Points>(null)
  const { geometry, material } = useMemo(() => {
    const rand = seeded(7)
    const seeds = new Float32Array(count * 4)
    for (let i = 0; i < seeds.length; i++) seeds[i] = rand()
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(count * 3), 3))
    g.setAttribute('aSeed', new BufferAttribute(seeds, 4))
    const m = new ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uSize: { value: 5.5 },
        uIntensity: { value: 1 },
        uPixelRatio: { value: 1 },
        uCyan: { value: new Color(PALETTE.cyan) },
        uLime: { value: new Color(PALETTE.lime) },
        uFlame: { value: new Color(PALETTE.flame) },
      },
      vertexShader: sparkVertex,
      fragmentShader: sparkFragment,
      blending: AdditiveBlending,
      transparent: true,
      depthWrite: false,
    })
    return { geometry: g, material: m }
  }, [count])

  useFrame((state) => {
    const u = material.uniforms
    u.uTime!.value = state.clock.elapsedTime
    u.uPixelRatio!.value = state.gl.getPixelRatio()
    u.uIntensity!.value = frameNow().atmosphere
  })

  return <points ref={ref} geometry={geometry} material={material} frustumCulled={false} />
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
