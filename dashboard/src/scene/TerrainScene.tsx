import { OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer } from '@react-three/postprocessing'
import { Component, type ReactNode, useEffect, useMemo, useRef } from 'react'
import { useMatch } from 'react-router-dom'
import { MathUtils, type PerspectiveCamera, Vector3 } from 'three'
import type { BloomEffect } from 'postprocessing'
import type { Basemap } from '../data/types'
import { usePrefersReducedMotion } from '../lib/motion'
import { useIntro } from '../state/intro'
import { useMapState } from '../state/map'
import { useStory } from '../state/story'
import AlertColumns from './AlertColumns'
import { Graticule, Rain } from './Atmosphere'
import CameraRig from './CameraRig'
import { buildColumns, columnMinLevel } from './columns'
import { createClassTexture } from './classMap'
import { frameNow, setLayersShown } from './frame'
import { MapInteraction, QualityWatchdog } from './MapInteraction'
import OutlineLayer from './OutlineLayer'
import { QUALITY_STEPS } from './perf'
import { PALETTE } from './levelColors'
import { MAP, OVERVIEW } from './poses'
import RainParticles from './RainParticles'
import { buildRainDrops } from './rainField'
import RiskLayer, { createRiskTexture } from './RiskLayer'
import styles from './TerrainScene.module.css'
import { lookTarget, poseAt, type Pose, storyPoses } from './storyCamera'
import { buildTerrainGeometry } from './terrainGeometry'
import { terrainField } from './terrainField'
import { createTerrainMaterial } from './terrainMaterial'
import { type MapModel, useMapModel } from './useMapModel'

interface WorldProps {
  terrain: Basemap
  model: MapModel
  /** The live map is the current view: interaction and the orbit controls exist only then. */
  onMap: boolean
  /** The story is the current view: it draws the map's layers too, as far as the scroll has brought them in. */
  onStory: boolean
  reducedMotion: boolean
}

/** The terrain with everything the live map draws on it. */
function MapWorld({ terrain, model, onMap, onStory, reducedMotion }: WorldProps) {
  const invalidate = useThree((s) => s.invalidate)
  const layers = onMap || onStory
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
  const shownGrid = grid
  const shownVisible = visible
  const watchColumns = useMapState((s) => s.watchColumns)
  const columns = useMemo(
    () =>
      shownGrid && shownVisible
        ? buildColumns(shownGrid, terrain, field, shownVisible, columnMinLevel(watchColumns))
        : null,
    [shownGrid, shownVisible, terrain, field, watchColumns],
  )
  const drops = useMemo(() => (rain ? buildRainDrops(rain, terrain, field) : null), [rain, terrain, field])

  useFrame(() => {
    const f = frameNow()
    material.uniforms.uReveal!.value = f.reveal
    material.uniforms.uFill!.value = f.fill
    material.uniforms.uRisk!.value = f.risk * f.risk
  })

  useEffect(() => {
    setLayersShown(layers)
    invalidate()
  }, [layers, invalidate])
  // The landing waits for this: one frame after the terrain exists, the canvas has it on screen.
  useEffect(() => {
    const id = requestAnimationFrame(() => useIntro.getState().setReady())
    return () => cancelAnimationFrame(id)
  }, [geometry])
  // With reduced motion the canvas draws on demand, so the story's scroll has to ask for each frame.
  useEffect(() => useStory.subscribe(() => invalidate()), [invalidate])

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
      {introDone && !onStory && (
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
      {introDone && !onStory && <CameraRig window={terrain} field={field} />}
    </>
  )
}

/**
 * Hands the camera to the orbit controls where it was last looking (the map pose after the landing, a chapter's view
 * after the story), then flies it to the map's resting pose, so leaving the story is a camera move and never a cut.
 */
function OrbitStart() {
  const controls = useThree((s) => s.controls) as { target: Vector3; update: () => unknown } | null
  const camera = useThree((s) => s.camera)
  useEffect(() => {
    if (!controls) return
    controls.target.copy(lookTarget)
    controls.update()
    if (camera.position.distanceTo(MAP.position) > 0.01) useMapState.getState().resetView()
  }, [controls, camera])
  return null
}

/**
 * Width in px the map is nudged right by (twice the shift), so it sits clear of what is on the left: the controls
 * dock on the map, the wider column of copy in the story.
 */
function leftAllowance(onStory: boolean): number {
  if (window.innerWidth <= 900) return 0
  return parseFloat(getComputedStyle(document.documentElement).fontSize) * (onStory ? 27 : 13.5)
}

/** Below this width the map controls wrap to three rows and cover the top of the map. */
const NARROW_PX = 1100
/** On a narrow screen the map is drawn this much smaller and shifted down, so the Himalaya clears the controls. */
const NARROW_ZOOM = 0.88
const NARROW_SHIFT_PX = 95

/**
 * Owns the projection and, outside the live map, the camera. During the landing it flies the dive from the overview
 * to the map pose; in the story it follows the scroll along the chapter poses with a little lag, which is what makes
 * the flight read as one continuous move. The projection is shifted right so the map is centred in the area the left
 * column leaves free; between views the shift eases instead of jumping.
 */
function CameraDirector({ onStory, poses, reducedMotion }: { onStory: boolean; poses: Pose[] | null; reducedMotion: boolean }) {
  const camera = useThree((s) => s.camera) as PerspectiveCamera
  const size = useThree((s) => s.size)
  const controls = useThree((s) => s.controls) as { target: Vector3 } | null
  const shift = useRef<number | null>(null)
  const want = useMemo<Pose>(() => ({ position: new Vector3(), target: new Vector3() }), [])

  useFrame((_, delta) => {
    const landing = useIntro.getState().status === 'playing'
    const dive = landing ? frameNow().dive : 1
    const narrow = !onStory && window.innerWidth <= NARROW_PX
    const ease = reducedMotion ? 1 : 1 - Math.exp(-delta * 5)
    const allowance = leftAllowance(onStory) * dive
    shift.current = shift.current === null || landing ? allowance : MathUtils.lerp(shift.current, allowance, ease)
    camera.zoom = narrow ? NARROW_ZOOM : 1
    camera.setViewOffset(size.width, size.height, -shift.current / 2, narrow ? -NARROW_SHIFT_PX * dive : 0, size.width, size.height)
    if (landing) {
      // The dive ends where the view under it begins: the story's first chapter on the home page, else the map.
      const end = onStory && poses ? poses[0]! : MAP
      camera.position.lerpVectors(OVERVIEW.position, end.position, dive)
      lookTarget.lerpVectors(OVERVIEW.target, end.target, dive)
      camera.lookAt(lookTarget)
      return
    }
    if (!onStory || !poses) {
      // On the map the orbit controls own the view; remember where they look, so the story flies on from there.
      if (controls) lookTarget.copy(controls.target)
      return
    }
    poseAt(poses, useStory.getState().position, want)
    const follow = reducedMotion ? 1 : 1 - Math.exp(-delta * 3.2)
    camera.position.lerp(want.position, follow)
    lookTarget.lerp(want.target, follow)
    camera.lookAt(lookTarget)
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
  // The story and the presentation both drive the camera along the chapter poses.
  // Both hooks run on every render (never behind ||): a hook called only sometimes breaks React's hook order.
  const onHome = useMatch('/') !== null
  const onDeck = useMatch('/deck') !== null
  const onStory = onHome || onDeck
  const quality = useMapState((s) => s.quality)
  const poses = useMemo(() => (terrain ? storyPoses(terrain) : null), [terrain])
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
          <CameraDirector onStory={onStory} poses={poses} reducedMotion={reducedMotion} />
          {terrain && <MapWorld terrain={terrain} model={model} onMap={onMap} onStory={onStory} reducedMotion={reducedMotion} />}
          {terrain && !onStory && <OrbitStart />}
          {terrain && <Graticule window={terrain} />}
          {!reducedMotion && introPlaying && <Rain />}
          <Effects />
        </Canvas>
      </SceneBoundary>
    </div>
  )
}
