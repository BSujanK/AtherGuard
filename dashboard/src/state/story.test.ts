import { Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { MAP } from '../scene/poses'
import { poseAt, storyPoses } from '../scene/storyCamera'
import { CHAPTERS, LAST_CHAPTER, PLOT_SECONDS, REST_FRAME, storyFrame, useStory } from './story'

const WINDOW = { lat0: 6, lon0: 67, rows: 631, cols: 601, step: 0.05 }
const blank = () => ({ position: new Vector3(), target: new Vector3() })

describe('storyFrame', () => {
  it('plots the lines on arrival and leaves every other layer for the scroll', () => {
    expect(storyFrame(0, 0)).toEqual({ reveal: 0, fill: 0, rain: 0, risk: 0 })
    expect(storyFrame(0, PLOT_SECONDS)).toEqual({ reveal: 1, fill: 0, rain: 0, risk: 0 })
  })

  it('adds one layer per chapter, in order, and keeps each once it is on', () => {
    expect(storyFrame(1, 99)).toEqual({ reveal: 1, fill: 1, rain: 0, risk: 0 })
    expect(storyFrame(2, 99)).toEqual({ reveal: 1, fill: 1, rain: 1, risk: 0 })
    expect(storyFrame(3, 99)).toEqual(REST_FRAME)
    expect(storyFrame(LAST_CHAPTER, 99)).toEqual(REST_FRAME)
  })

  it('never hides the lines from a reader who scrolls before the plot has finished', () => {
    expect(storyFrame(1, 0).reveal).toBe(1)
  })

  it('moves every layer monotonically with the scroll', () => {
    let last = storyFrame(0, 99)
    for (let p = 0.05; p <= LAST_CHAPTER; p += 0.05) {
      const now = storyFrame(p, 99)
      for (const key of ['fill', 'rain', 'risk'] as const) expect(now[key]).toBeGreaterThanOrEqual(last[key])
      last = now
    }
  })
})

describe('the story camera', () => {
  const poses = storyPoses(WINDOW)

  it('has one pose per chapter, opening where the landing dive ends and ending on the live map view', () => {
    expect(poses).toHaveLength(CHAPTERS.length)
    expect(poses[0]!.position.equals(MAP.position)).toBe(true)
    for (const pose of poses.slice(-2)) {
      expect(pose.position.equals(MAP.position)).toBe(true)
      expect(pose.target.equals(MAP.target)).toBe(true)
    }
  })

  it('rests exactly on a chapter pose and eases between two', () => {
    expect(poseAt(poses, 2, blank()).position.equals(poses[2]!.position)).toBe(true)
    const mid = poseAt(poses, 0.5, blank()).position
    expect(mid.distanceTo(poses[0]!.position.clone().lerp(poses[1]!.position, 0.5))).toBeLessThan(1e-9)
    const early = poseAt(poses, 0.1, blank()).position
    expect(early.distanceTo(poses[0]!.position)).toBeLessThan(0.1 * poses[0]!.position.distanceTo(poses[1]!.position))
  })

  it('stays within the chapters whatever position it is given', () => {
    expect(poseAt(poses, -3, blank()).position.equals(poses[0]!.position)).toBe(true)
    expect(poseAt(poses, 99, blank()).position.equals(MAP.position)).toBe(true)
  })
})

describe('the story store', () => {
  it('clamps the position to the chapters and restarts the plot on entry', () => {
    useStory.getState().setPosition(42)
    expect(useStory.getState().position).toBe(LAST_CHAPTER)
    useStory.getState().enter()
    expect(useStory.getState()).toMatchObject({ active: true, position: 0 })
    useStory.getState().leave()
    expect(useStory.getState().active).toBe(false)
  })
})
