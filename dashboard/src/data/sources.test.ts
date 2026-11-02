import { describe, expect, it } from 'vitest'
import {
  buildSourceRows,
  classifySource,
  EXPECTED_LATENCY_H,
  formatIst,
  formatLatency,
  LATE_GRACE_H,
  parseSensors,
  parseSourcesStatus,
  type SourceRecord,
} from './sources'

const record = (over: Partial<SourceRecord> = {}): SourceRecord => ({
  name: 'imerg_late',
  ok: true,
  validThrough: '2026-10-13T00:00:00+00:00',
  issued: '2026-10-13T14:30:00+00:00',
  latencyH: 14.5,
  error: null,
  state: null,
  ...over,
})

const freshnessJson = {
  available: true,
  date: '2026-10-15',
  generated_utc: '2026-10-15T05:31:00+00:00',
  backtest: false,
  imd_day_inputs: {
    D: { 'utc_day_0.875': 'early_mapped', 'utc_day_0.125': 'gfs_0_3h', product: 'early_mapped+gfs_0_3h' },
    'D-1': { 'utc_day_0.875': 'late', 'utc_day_0.125': 'early_mapped', product: 'late+early_mapped' },
  },
  sources: {
    imerg_late: { name: 'imerg_late', ok: true, valid_through: '2026-10-13T00:00:00+00:00', issued: '2026-10-13T14:30:00+00:00', latency_h: 14.5, error: null, state: 'ok', expected_valid_through: 'x' },
    imerg_early: { name: 'imerg_early', ok: true, valid_through: '2026-10-14T00:00:00+00:00', issued: '2026-10-14T04:30:00+00:00', latency_h: 4.5, error: null, state: 'ok' },
    gfs: { name: 'gfs', ok: true, valid_through: '2026-10-18T03:00:00+00:00', issued: '2026-10-15T00:00:00+00:00', latency_h: 99, error: null },
    imd_rt: { name: 'imd_rt', ok: false, valid_through: null, issued: null, latency_h: null, error: 'HTTPError: 503' },
    ghcn: { name: 'ghcn', ok: true, valid_through: '2026-10-08T00:00:00+00:00', issued: '2026-10-15T01:00:00+00:00', latency_h: 150, error: null },
  },
}

describe('expected latencies', () => {
  it('holds the measured medians of the phase 6 probe', () => {
    expect(EXPECTED_LATENCY_H).toEqual({ imerg_late: 14.5, imerg_early: 4.5, gfs: 5, imd_rt: 24, ghcn: 168 })
  })
})

describe('classifySource', () => {
  it('uses the state the runner wrote, whatever the latency says', () => {
    expect(classifySource(record({ state: 'late', latencyH: 1 }), 14.5)).toBe('late')
    expect(classifySource(record({ state: 'ok', latencyH: 90 }), 14.5)).toBe('ok')
    expect(classifySource(record({ state: 'failed', ok: true }), 14.5)).toBe('failed')
  })

  it('is failed whenever ok is false and no state was written, even with partial data', () => {
    expect(classifySource(record({ ok: false }), 14.5)).toBe('failed')
    expect(classifySource(record({ ok: false, latencyH: 1 }), 14.5)).toBe('failed')
  })

  it('is ok at or within the expected latency plus the grace', () => {
    expect(classifySource(record({ latencyH: 14.5 }), 14.5)).toBe('ok')
    expect(classifySource(record({ latencyH: 14.5 + LATE_GRACE_H }), 14.5)).toBe('ok')
    expect(classifySource(record({ latencyH: 0.2 }), 14.5)).toBe('ok')
  })

  it('is late beyond the expected latency plus the grace', () => {
    expect(classifySource(record({ latencyH: 14.5 + LATE_GRACE_H + 0.01 }), 14.5)).toBe('late')
    expect(classifySource(record({ latencyH: 200 }), 168)).toBe('late')
  })

  it('is unknown when the source is ok but reports no usable latency', () => {
    expect(classifySource(record({ latencyH: null }), 14.5)).toBe('unknown')
    expect(classifySource(record({ latencyH: Number.NaN }), 14.5)).toBe('unknown')
  })

  it('is unknown when the run has no record of the source', () => {
    expect(classifySource(null, 14.5)).toBe('unknown')
  })
})

describe('parseSourcesStatus', () => {
  it('reads the freshness.json the live runner writes', () => {
    const result = parseSourcesStatus(freshnessJson)
    if (!result.available) throw new Error('expected an available status')
    expect(result.run).toEqual({
      date: '2026-10-15',
      generatedUtc: '2026-10-15T05:31:00+00:00',
      backtest: false,
      rainProvenance: [
        { day: 'D', product: 'early_mapped+gfs_0_3h' },
        { day: 'D-1', product: 'late+early_mapped' },
      ],
    })
    expect(result.sources).toHaveLength(5)
    expect(result.sources[3]).toEqual({
      name: 'imd_rt',
      ok: false,
      validThrough: null,
      issued: null,
      latencyH: null,
      error: 'HTTPError: 503',
      state: null,
    })
  })

  it('ignores extra fields and accepts a list of records', () => {
    const list = { ...freshnessJson, future_field: 1, sources: Object.values(freshnessJson.sources).map((s) => ({ ...s, extra: true })) }
    const result = parseSourcesStatus(list)
    expect(result.available && result.sources.map((s) => s.name)).toEqual(['imerg_late', 'imerg_early', 'gfs', 'imd_rt', 'ghcn'])
  })

  it('takes the name from the key when a record omits it, and skips entries that are not records', () => {
    const result = parseSourcesStatus({ available: true, sources: { gfs: { ok: true, latency_h: '4.2' }, junk: 7, imd_rt: null } })
    expect(result.available && result.sources).toEqual([
      { name: 'gfs', ok: true, validThrough: null, issued: null, latencyH: 4.2, error: null, state: null },
    ])
  })

  it('treats non-numeric latency as missing', () => {
    const result = parseSourcesStatus({ available: true, sources: { gfs: { ok: true, latency_h: 'soon' } } })
    expect(result.available && result.sources[0]!.latencyH).toBeNull()
  })

  it('passes the reason through when no live run exists', () => {
    expect(parseSourcesStatus({ available: false, reason: 'no live run yet (no freshness.json under /data/live)' })).toEqual({
      available: false,
      reason: 'no live run yet (no freshness.json under /data/live)',
    })
  })

  it('never invents sources for an unavailable or unreadable payload', () => {
    expect(parseSourcesStatus({ available: false })).toEqual({ available: false, reason: 'The API reports no source status.' })
    expect(parseSourcesStatus('nope')).toEqual({ available: false, reason: 'The API returned source status in an unknown format.' })
    expect(parseSourcesStatus(null).available).toBe(false)
  })
})

describe('buildSourceRows', () => {
  it('returns the five sources in display order with status and latency', () => {
    const result = parseSourcesStatus(freshnessJson)
    if (!result.available) throw new Error('expected an available status')
    const rows = buildSourceRows(result.sources)
    expect(rows.map((r) => [r.label, r.status])).toEqual([
      ['IMERG Late', 'ok'],
      ['IMERG Early', 'ok'],
      ['GFS', 'late'],
      ['IMD real-time', 'failed'],
      ['GHCN gauges', 'ok'],
    ])
    expect(rows[2]!.expectedLatencyH).toBe(5)
  })

  it('marks a source the run did not report as unknown rather than dropping or faking it', () => {
    const rows = buildSourceRows([record({ name: 'gfs', latencyH: 4 })])
    expect(rows).toHaveLength(5)
    expect(rows.find((r) => r.key === 'imerg_late')).toMatchObject({ status: 'unknown', record: null })
    expect(rows.find((r) => r.key === 'gfs')!.status).toBe('ok')
  })

  it('appends sources it has no label for', () => {
    const rows = buildSourceRows([record({ name: 'radar', latencyH: 1 })])
    expect(rows.at(-1)).toMatchObject({ key: 'radar', label: 'radar', expectedLatencyH: null, status: 'ok' })
  })
})

describe('formatters', () => {
  it('formats latency to one decimal and shows an em dash when unknown', () => {
    expect(formatLatency(14.46)).toBe('14.5')
    expect(formatLatency(null)).toBe('—')
    expect(formatLatency(Number.NaN)).toBe('—')
  })

  it('formats instants in IST', () => {
    expect(formatIst('2026-10-15T05:31:00+00:00')).toBe('15 Oct, 11:01')
    expect(formatIst(null)).toBe('—')
    expect(formatIst('garbage')).toBe('—')
  })
})

describe('parseSensors', () => {
  it('keeps the station rows and normalises missing trust to null', () => {
    const parsed = parseSensors({
      date: '2024-08-05',
      set: 's',
      n_stations: 2,
      state_counts: { trusted: 1, missing: 1 },
      stations: [
        { station: 'A', name: 'Alpha', lat: 10, lon: 75, trust: 0.9, fault_type: '', flagged: false, genuine_extreme: false, reasons: '', state: 'trusted', flag_rate_window: 0, ood: false },
        { station: 'B', name: null, lat: 11, lon: 76, trust: null, fault_type: 'dropout', flagged: true, genuine_extreme: false, reasons: 'model', state: 'missing', flag_rate_window: null, ood: true },
      ],
    })
    expect(parsed.stations.map((s) => [s.station, s.trust, s.name])).toEqual([
      ['A', 0.9, 'Alpha'],
      ['B', null, null],
    ])
    expect(parsed.stateCounts).toEqual({ trusted: 1, missing: 1 })
  })

  it('reads the last reading date and the reason an empty list comes with', () => {
    const parsed = parseSensors({
      date: '2026-10-16',
      set: 'live',
      n_stations: 2,
      state_counts: { missing: 2 },
      stations: [
        { station: 'A', name: 'Alpha', lat: 10, lon: 75, trust: null, fault_type: '', flagged: false, genuine_extreme: false, reasons: '', state: 'missing', flag_rate_window: 0, ood: false, last_reading: '2026-10-12' },
        { station: 'B', name: 'Beta', lat: 11, lon: 76, trust: null, fault_type: '', flagged: false, genuine_extreme: false, reasons: '', state: 'missing', flag_rate_window: 0, ood: false, last_reading: null },
      ],
    })
    expect(parsed.stations.map((s) => s.lastReading)).toEqual(['2026-10-12', null])
    expect(parsed.reason).toBeNull()
    const empty = parseSensors({ date: '2026-10-16', set: 'live', n_stations: 0, state_counts: {}, stations: [], reason: 'No gauge table for 2026-10-16: GHCN-Daily gauges unavailable.' })
    expect(empty.stations).toEqual([])
    expect(empty.reason).toBe('No gauge table for 2026-10-16: GHCN-Daily gauges unavailable.')
  })

  it('rejects a payload without stations', () => {
    expect(() => parseSensors({ date: 'x' })).toThrow(/stations/)
  })
})

describe('an optional source', () => {
  it('shows ECMWF IFS with its measured latency when the run reports it, and not otherwise', () => {
    const rows = buildSourceRows([record({ name: 'ecmwf', latencyH: 8.2 })])
    expect(rows.find((r) => r.key === 'ecmwf')).toMatchObject({ label: 'ECMWF IFS', expectedLatencyH: 8.2, status: 'ok' })
    expect(buildSourceRows([]).map((r) => r.key)).not.toContain('ecmwf')
  })
})
