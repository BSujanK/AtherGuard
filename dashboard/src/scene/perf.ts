/**
 * Frame-time watchdog. Sustained slow frames step the visual quality down one notch at a time;
 * a long recovery period of fast frames steps it back up one notch. Both directions need a hold
 * time and the watchdog waits after every change, so quality never flaps.
 */

/** Quality steps, best first: full, half the rain particles, pixel ratio 1.0, no rain particles. */
export const QUALITY_STEPS = [
  { particles: 1, dprMax: 1.5 },
  { particles: 0.5, dprMax: 1.5 },
  { particles: 0.5, dprMax: 1 },
  { particles: 0, dprMax: 1 },
] as const

export type QualityStep = 0 | 1 | 2 | 3
export const LOWEST_QUALITY: QualityStep = 3

export interface WatchdogOptions {
  /** Smoothed frame time above this is slow, in ms. */
  slowMs?: number
  /** ... and must stay above it this long before quality drops, in ms. */
  slowHoldMs?: number
  /** Smoothed frame time below this is fast. */
  fastMs?: number
  /** ... for this long before quality may rise again. */
  fastHoldMs?: number
  /** No change of any kind for this long after a change. */
  cooldownMs?: number
  /** Weight of the newest frame in the moving average. */
  smoothing?: number
  /** A frame longer than this is a paused tab or a debugger stop, not a slow GPU, and is ignored. */
  pauseMs?: number
}

const DEFAULTS: Required<WatchdogOptions> = {
  slowMs: 28,
  slowHoldMs: 2000,
  fastMs: 20,
  fastHoldMs: 20_000,
  cooldownMs: 4000,
  smoothing: 0.1,
  pauseMs: 1000,
}

export class FrameWatchdog {
  private readonly o: Required<WatchdogOptions>
  private ema: number | null = null
  private slowSince: number | null = null
  private fastSince: number | null = null
  private changedAt = Number.NEGATIVE_INFINITY
  private step: QualityStep
  private readonly onChange: (step: QualityStep) => void

  constructor(onChange: (step: QualityStep) => void, options: WatchdogOptions = {}, start: QualityStep = 0) {
    this.onChange = onChange
    this.o = { ...DEFAULTS, ...options }
    this.step = start
  }

  get quality(): QualityStep {
    return this.step
  }

  /** The smoothed frame time in ms, null before the first frame. */
  get frameMs(): number | null {
    return this.ema
  }

  /** Feed one frame: its duration and the current time, both in ms. */
  sample(frameMs: number, nowMs: number): void {
    if (frameMs > this.o.pauseMs) {
      this.slowSince = null
      this.fastSince = null
      return
    }
    this.ema = this.ema === null ? frameMs : this.ema + (frameMs - this.ema) * this.o.smoothing
    if (nowMs - this.changedAt < this.o.cooldownMs) {
      this.slowSince = null
      this.fastSince = null
      return
    }

    if (this.ema > this.o.slowMs) {
      this.fastSince = null
      this.slowSince ??= nowMs
      if (nowMs - this.slowSince >= this.o.slowHoldMs && this.step < LOWEST_QUALITY) {
        this.move((this.step + 1) as QualityStep, nowMs)
      }
    } else if (this.ema < this.o.fastMs) {
      this.slowSince = null
      this.fastSince ??= nowMs
      if (nowMs - this.fastSince >= this.o.fastHoldMs && this.step > 0) {
        this.move((this.step - 1) as QualityStep, nowMs)
      }
    } else {
      this.slowSince = null
      this.fastSince = null
    }
  }

  private move(step: QualityStep, nowMs: number): void {
    this.step = step
    this.changedAt = nowMs
    this.slowSince = null
    this.fastSince = null
    this.ema = null
    this.onChange(step)
  }
}
