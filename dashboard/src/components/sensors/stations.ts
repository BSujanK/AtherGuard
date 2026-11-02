import type { SensorStation } from '../../data/sources'

export const stationLabel = (s: SensorStation): string => s.name ?? s.station

/** A station belongs in the fault list when it carries a fault type or was flagged. */
export const isFault = (s: SensorStation): boolean => s.faultType !== '' || s.flagged

/**
 * True when most gauges have no value on the shown date and the table says when each last reported (a live table):
 * GHCN reports arrive days late, so the map then shows older state. A replay table has no last-reading dates and no
 * such delay.
 */
export function isMostlyMissing(stations: SensorStation[]): boolean {
  if (!stations.some((s) => s.lastReading !== null)) return false
  return stations.filter((s) => s.trust === null).length * 2 > stations.length
}

export const faultName = (s: SensorStation): string => s.faultType || 'flagged, type not given'
