import { create } from 'zustand'
import type { RegionFilter } from '../scene/geo'
import { ALL_LEVELS } from '../scene/riskTexture'
import type { QualityStep } from '../scene/perf'

export type Lead = 0 | 1 | 2 | 3
export const LEADS: readonly Lead[] = [0, 1, 2, 3]

/** A request to the camera rig; `nonce` makes a repeat of the same request a new one. */
export type CameraCommand =
  | { kind: 'reset'; nonce: number }
  | { kind: 'region'; region: RegionFilter; nonce: number }
  | { kind: 'cell'; cell: number; nonce: number }

export interface Hover {
  cell: number
  /** Pointer position in viewport pixels, for placing the hover card. */
  x: number
  y: number
}

interface MapState {
  /** Chosen date; null follows the latest date the API reports. */
  date: string | null
  lead: Lead
  levels: readonly boolean[]
  region: RegionFilter
  /** Also draw columns for Watch cells; off by default, where Watch is the lime tint on the terrain. */
  watchColumns: boolean
  hover: Hover | null
  /** The cell the user last opened; the view navigates to its alert detail. */
  opened: { cell: number; nonce: number } | null
  camera: CameraCommand | null
  /** Quality step chosen by the frame-time watchdog (see perf.ts). */
  quality: QualityStep

  setDate: (date: string | null) => void
  setLead: (lead: Lead) => void
  toggleLevel: (level: number) => void
  setRegion: (region: RegionFilter) => void
  setWatchColumns: (on: boolean) => void
  setHover: (hover: Hover | null) => void
  /** Fly to a cell and ask the view to open its detail. */
  openCell: (cell: number) => void
  resetView: () => void
  setQuality: (quality: QualityStep) => void
}

let nonce = 0

export const useMapState = create<MapState>((set) => ({
  date: null,
  lead: 0,
  levels: ALL_LEVELS,
  region: 'all',
  watchColumns: false,
  hover: null,
  opened: null,
  camera: null,
  quality: 0,

  setDate: (date) => set({ date }),
  setLead: (lead) => set({ lead }),
  toggleLevel: (level) =>
    set((s) => ({ levels: s.levels.map((on, i) => (i === level ? !on : on)) })),
  setRegion: (region) => set({ region, camera: { kind: 'region', region, nonce: ++nonce } }),
  setWatchColumns: (watchColumns) => set({ watchColumns }),
  setHover: (hover) => set({ hover }),
  openCell: (cell) =>
    set({ opened: { cell, nonce: ++nonce }, camera: { kind: 'cell', cell, nonce: nonce } }),
  resetView: () => set({ camera: { kind: 'reset', nonce: ++nonce } }),
  setQuality: (quality) => set({ quality }),
}))

/** Back to the opening state; used by tests and when the data set changes under the view. */
export function resetMapState(): void {
  useMapState.setState({
    date: null,
    lead: 0,
    levels: ALL_LEVELS,
    region: 'all',
    watchColumns: false,
    hover: null,
    opened: null,
    camera: null,
    quality: 0,
  })
}
