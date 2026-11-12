import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import {
  BoxGeometry,
  Color,
  InstancedBufferAttribute,
  InstancedMesh,
  ShaderMaterial,
} from 'three'
import type { ColumnInstances } from './columns'
import { frameNow } from './frame'
import { PALETTE } from './levelColors'

/** Seconds per Emergency pulse (spec section 2). */
export const PULSE_SECONDS = 2.4

const vertexShader = /* glsl */ `
  attribute float aLevel;
  uniform float uTime;
  uniform float uPulse;
  uniform float uIntensity;
  varying float vHeight;
  varying float vLevel;
  varying float vGlow;

  void main() {
    vHeight = position.y;
    vLevel = aLevel;
    float beat = 0.62 + 0.38 * sin(uTime * 6.2831853 / ${PULSE_SECONDS.toFixed(1)});
    vGlow = aLevel > 2.5 ? mix(1.0, beat, uPulse) : 1.0;
    // The columns rise out of the ground as the levels arrive, instead of fading in.
    gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position.x, position.y * uIntensity, position.z, 1.0);
  }
`

const fragmentShader = /* glsl */ `
  uniform vec3 uLime;
  uniform vec3 uFlame;
  uniform vec3 uFire;
  varying float vHeight;
  varying float vLevel;
  varying float vGlow;

  void main() {
    vec3 base = vLevel < 1.5 ? uLime : (vLevel < 2.5 ? uFlame : uFire);
    // Opaque and never brighter than the level colour, so a dense field stays the colour of its level. The foot is
    // a little darker than the tip so a column reads as standing on the ground; the Emergency pulse is a shallow dip.
    float lit = mix(0.74, 1.0, vHeight) * mix(1.0, vGlow, 0.45);
    gl_FragColor = vec4(base * min(lit, 1.0), 1.0);
    #include <colorspace_fragment>
  }
`

interface AlertColumnsProps {
  columns: ColumnInstances
  reducedMotion: boolean
}

const nextPowerOfTwo = (n: number): number => 2 ** Math.ceil(Math.log2(Math.max(n, 256)))

/**
 * Columns for Warning and Emergency (and Watch when asked for), height encoding risk. Every column is
 * one instance of a single mesh, so thousands of alerts are one draw call. Emergency columns pulse every
 * 2.4 s; with reduced motion they hold steady.
 */
export default function AlertColumns({ columns, reducedMotion }: AlertColumnsProps) {
  const invalidate = useThree((s) => s.invalidate)
  const capacity = nextPowerOfTwo(columns.count)

  const { mesh, material, geometry } = useMemo(() => {
    const g = new BoxGeometry(1, 1, 1).translate(0, 0.5, 0)
    g.setAttribute('aLevel', new InstancedBufferAttribute(new Float32Array(capacity), 1))
    const m = new ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uPulse: { value: 1 },
        uIntensity: { value: 1 },
        uLime: { value: new Color(PALETTE.yellow) },
        uFlame: { value: new Color(PALETTE.orange) },
        uFire: { value: new Color(PALETTE.red) },
      },
      vertexShader,
      fragmentShader,
    })
    const im = new InstancedMesh(g, m, capacity)
    im.frustumCulled = false
    return { mesh: im, material: m, geometry: g }
  }, [capacity])

  useEffect(
    () => () => {
      mesh.dispose()
      geometry.dispose()
      material.dispose()
    },
    [mesh, geometry, material],
  )

  useEffect(() => {
    mesh.instanceMatrix.array.set(columns.matrices)
    mesh.instanceMatrix.needsUpdate = true
    const level = geometry.getAttribute('aLevel') as InstancedBufferAttribute
    level.array.set(columns.levels)
    level.needsUpdate = true
    mesh.count = columns.count
    invalidate()
  }, [mesh, geometry, columns, invalidate])

  useEffect(() => {
    material.uniforms.uPulse!.value = reducedMotion ? 0 : 1
    invalidate()
  }, [material, reducedMotion, invalidate])

  useFrame((state) => {
    material.uniforms.uTime!.value = state.clock.elapsedTime
    const f = frameNow().risk
    material.uniforms.uIntensity!.value = f * f
  })

  return <primitive object={mesh} />
}
