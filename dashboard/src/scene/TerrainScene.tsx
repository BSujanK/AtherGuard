import { OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer } from '@react-three/postprocessing'
import { Component, type ReactNode, useCallback, useEffect, useMemo, useRef } from 'react'
import { useMatch } from 'react-router-dom'
import { MathUtils, type PerspectiveCamera, Vector3 } from 'three'
import type { BloomEffect } from 'postprocessing'
import type { Basemap } from '../data/types'
import { usePrefersReducedMotion } from '../lib/motion'
import { useIntro } from '../state/intro'
import { useMapState } from '../state/map'
import AlertColumns from './AlertColumns'
import { Graticule, Rain } from './Atmosphere'
import CameraRig from './CameraRig'
import { buildColumns, columnMinLevel } from './columns'
import { createClassTexture } from './classMap'
import { frameNow } from './frame'
import { MapInteraction, QualityWatchdog } from './MapInteraction'
import OutlineLayer from './OutlineLayer'
import { QUALITY_STEPS } from './perf'
import { PALETTE } from './levelColors'
import { MAP, OVERVIEW } from './poses'
import RainParticles from './RainParticles'
import { buildRainDrops } from './rainField'
import RiskLayer, { createRiskTexture } from './RiskLayer'
import styles from './TerrainScene.module.css'
import { buildTerrainGeometry } from './terrainGeometry'
import { terrainField } from './terrainField'
import { createTerrainMaterial } from './terrainMaterial'
import { type MapModel, useMapModel } from './useMapModel'

interface WorldProps {
  terrain: Basemap
  model: MapModel
  /** The live map is the current view: risk, columns, rain and interaction show only then. */
  onMap: boolean
  reducedMotion: boolean
}

/** The terrain with everything the live map draws on it. */
function MapWorld({ terrain, model, onMap, reducedMotion }: WorldProps) {
  const invalidate = useThree((s) => s.invalidate)
  const introDone = useIntro((s) => s.status === 'done')
  const field = useMemo(() => terrainField(terrain), [terrain])

  const bundle = useMemo(() => {
    const built = buildTerrainGeometry(terrain, field)
    const riskMap = createRiskTexture(terrain)
    const classMap = createClassTexture(terrain)
    return {
      geometry: built.geometry,
      riskMap,
      classMap,
      material: createTerrainMaterial({ maxElevation: built.maxElevation, riskMap, classMap }),
    }
  }, [terrain, field])
  const { geometry, material, riskMap, classMap } = bundle

  useEffect(
    () => () => {
      geometry.dispose()
      material.dispose()
      riskMap.dispose()
      classMap.dispose()
    },
    [geometry, material, riskMap, classMap],
  )

  const { grid, visible, rain } = model
  const shownGrid = onMap ? grid : undefined
  const shownVisible = onMap ? visible : null
  const watchColumns = useMapState((s) => s.watchColumns)
  const columns = useMemo(
    () =>
      shownGrid && shownVisible
        ? buildColumns(shownGrid, terrain, field, shownVisible, columnMinLevel(watchColumns))
        : null,
    [shownGrid, shownVisible, terrain, field, watchColumns],
  )
  const drops = useMemo(() => (onMap && rain ? buildRainDrops(rain, terrain, field) : null), [onMap, rain, terrain, field])

  useFrame(() => {
    const f = frameNow()
    material.uniforms.uReveal!.value = f.reveal
    material.uniforms.uFill!.value = f.fill
    material.uniforms.uRisk!.value = onMap ? f.fill * f.fill : 0
  })

  useEffect(() => invalidate(), [onMap, invalidate])

  return (
    <>
      <mesh geometry={geometry} material={material} frustumCulled={false} />
      <OutlineLayer outline={terrain.outline} window={terrain} field={field} />
      <RiskLayer texture={riskMap} terrain={terrain} grid={shownGrid} visible={shownVisible} />
      {columns && columns.count > 0 && <AlertColumns columns={columns} reducedMotion={reducedMotion} />}
      {drops && drops.count > 0 && <RainParticles drops={drops} reducedMotion={reducedMotion} />}
      {onMap && introDone && (
        <>
          <MapInteraction window={terrain} field={field} grid={grid} visible={visible} />
          <QualityWatchdog />
        </>
      )}
      {introDone && (
        <OrbitControls
          makeDefault
          enabled={onMap}
          enableDamping={!reducedMotion}
          dampingFactor={0.12}
          minDistance={2.5}
          maxDistance={95}
          maxPolarAngle={1.35}
          screenSpacePanning={false}
          zoomToCursor
        />
      )}
      {introDone && <CameraRig window={terrain} field={field} />}
    </>
  )
}

/** Puts the orbit target on the map pose the camera rests at once the landing has handed over. */
function OrbitStart() {
  const controls = useThree((s) => s.controls) as { target: Vector3; update: () => unknown } | null
  useEffect(() => {
    controls?.target.copy(MAP.target)
    controls?.update()
  }, [controls])
  return null
}

/** Width in px the map is nudged right by (twice the shift), so it sits clear of the controls dock on the left. */
function dockAllowance(): number {
  if (window.innerWidth <= 900) return 0
  return parseFloat(getComputedStyle(document.documentElement).fontSize) * 13.5
}

/** Below this width the map controls wrap to three rows and cover the top of the map. */
const NARROW_PX = 1100
/** On a narrow screen the map is drawn this much smaller and shifted down, so the Himalaya clears the controls. */
const NARROW_ZOOM = 0.88
const NARROW_SHIFT_PX = 95

/**
 * Drives the camera along the landing dive and hands over to the map pose once the sequence ends.
 * The projection is shifted right so the map is centred in the area the controls dock leaves free.
 */
function CameraDirector() {
  const camera = useThree((s) => s.camera) as PerspectiveCamera
  const size = useThree((s) => s.size)
  const target = useMemo(() => new Vector3(), [])
  const settled = useRef(false)

  const applyOffset = useCallback(
    (dive: number) => {
      const narrow = window.innerWidth <= NARROW_PX
      camera.zoom = narrow ? NARROW_ZOOM : 1
      camera.setViewOffset(size.width, size.height, (-dockAllowance() / 2) * dive, narrow ? -NARROW_SHIFT_PX * dive : 0, size.width, size.height)
    },
    [camera, size],
  )

  useEffect(() => {
    if (settled.current) applyOffset(1)
  }, [applyOffset])

  useFrame(() => {
    if (settled.current) return
    const { dive } = frameNow()
    camera.position.lerpVectors(OVERVIEW.position, MAP.position, dive)
    target.lerpVectors(OVERVIEW.target, MAP.target, dive)
    camera.lookAt(target)
    applyOffset(dive)
    if (useIntro.getState().status === 'done') settled.current = true
  })
  return null
}

/**
 * Bloom is tuned so colour survives it: the threshold sits above the luminance of fire red and flame orange
 * (about 0.15 and 0.25 in linear light), so a dense field of Warning and Emergency columns stays red and
 * orange instead of washing to white; only the neon lime, cyan and cloud parts of the scene glow.
 */
const BLOOM_REST = 0.45
const BLOOM_LANDING = 0.9
const BLOOM_THRESHOLD = 0.5

function Effects() {
  const bloom = useRef<BloomEffect>(null)
  useFrame(() => {
    const f = frameNow()
    if (bloom.current) bloom.current.intensity = MathUtils.lerp(BLOOM_REST, BLOOM_LANDING, f.atmosphere)
  })
  return (
    <EffectComposer multisampling={0}>
      <Bloom
        ref={bloom}
        mipmapBlur
        intensity={BLOOM_REST}
        luminanceThreshold={BLOOM_THRESHOLD}
        luminanceSmoothing={0.25}
        radius={0.7}
      />
    </EffectComposer>
  )
}

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('3D scene failed; continuing without it.', error)
    useIntro.getState().finish()
  }

  render() {
    return this.state.failed ? null : this.props.children
  }
}

/**
 * The one persistent canvas behind the whole app: the landing plays in it and the live map views
 * draw into it. Decorative to assistive tech; views expose their data as text.
 */
export default function TerrainScene() {
  const model = useMapModel()
  const terrain = model.terrain
  const reducedMotion = usePrefersReducedMotion()
  const onMap = useMatch('/map') !== null
  const quality = useMapState((s) => s.quality)
  const introPlaying = useIntro((s) => s.status === 'playing')

  return (
    <div className={styles.stage} aria-hidden="true" data-testid="terrain-scene" data-terrain={terrain ? 'loaded' : 'pending'}>
      <SceneBoundary>
        <Canvas
          dpr={[1, QUALITY_STEPS[quality].dprMax]}
          frameloop={reducedMotion ? 'demand' : 'always'}
          gl={{ antialias: false, powerPreference: 'high-performance' }}
          camera={{ fov: 38, near: 0.1, far: 220, position: MAP.position.toArray() }}
          onCreated={({ camera }) => camera.lookAt(MAP.target)}
        >
          <color attach="background" args={[PALETTE.ink]} />
          <CameraDirector />
          {terrain && <MapWorld terrain={terrain} model={model} onMap={onMap} reducedMotion={reducedMotion} />}
          {terrain && <OrbitStart />}
          {terrain && <Graticule window={terrain} />}
          {!reducedMotion && introPlaying && <Rain />}
          <Effects />
        </Canvas>
      </SceneBoundary>
    </div>
  )
}
