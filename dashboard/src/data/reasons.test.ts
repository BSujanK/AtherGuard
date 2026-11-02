import { describe, expect, it } from 'vitest'
import {
  CONFIDENCE_CAUSES,
  confidenceCause,
  confidenceMeaning,
  FEATURE_LABELS,
  cappedExplanation,
  featureLabel,
  featureValueText,
  raisedReasons,
  reasonCode,
  REASON_CODES,
} from './reasons'
import { GRID_FLAG } from './types'

/** Every code the backend can write, from aetherguard.alerts.confidence / engine and aetherguard.live.run. */
const BACKEND_CAUSES = [
  'no_valid_source',
  'imd_missing',
  'chirps_missing',
  'sources_disagree',
  'stations_flagged_nearby',
  'station_out_of_distribution',
  'all_nearby_stations_untrusted',
  'model_input_missing',
  'nowcast_tail_persisted',
  'forecast_input_missing',
  'forecast_uncertainty_uncalibrated',
  'ensemble_disagrees',
  'forecast_day',
  'observed_through_d_high',
  'observed_through_d_degraded',
  'observed_through_d_insufficient',
  'forecast_widened',
]
const BACKEND_REASONS = [
  'risk_above_watch',
  'risk_above_warning',
  'risk_above_emergency',
  'uncertain_high',
  'sources_disagree_heavy_rain',
  'sensors_untrusted_heavy_rain',
  'hysteresis_hold',
  'model_input_missing',
  'no_recent_rain',
  'held_while_blind',
  'nowcast_tail_persisted_heavy_rain',
]
/** The 30 columns of the hazard model card. */
const MODEL_COLUMNS = [
  'rain_acc_1', 'rain_acc_3', 'rain_acc_5', 'rain_acc_7', 'rain_acc_14', 'rain_acc_30', 'rain_max1d_7', 'rain_max1d_30',
  'rain_wetdays_30', 'rain_days_since_10mm', 'rain_share1_3', 'rain_acc3_vs_clim', 'rain_acc7_vs_clim',
  'rain_acc30_vs_clim', 'wet_top', 'wet_root', 'wet_top_chg3', 'wet_top_chg7', 'wet_root_chg3', 'wet_root_chg7',
  'stat_elev_mean', 'stat_elev_std', 'stat_relief', 'stat_slope_mean', 'stat_slope_p90', 'stat_slope_max',
  'stat_curvature_mean', 'stat_aspect_sin', 'stat_aspect_cos', 'stat_twi_proxy',
]

describe('reason and cause labels', () => {
  it('labels every confidence cause the backend writes, with a readable sentence', () => {
    for (const code of BACKEND_CAUSES) {
      const { label, detail } = CONFIDENCE_CAUSES[code] ?? { label: '', detail: '' }
      expect(label, code).not.toBe('')
      expect(label, code).not.toContain('_')
      expect(detail.endsWith('.'), code).toBe(true)
    }
  })

  it('labels every reason code the backend writes', () => {
    for (const code of BACKEND_REASONS) {
      const { label, detail } = REASON_CODES[code] ?? { label: '', detail: '' }
      expect(label, code).not.toBe('')
      expect(label, code).not.toContain('_')
      expect(detail.endsWith('.'), code).toBe(true)
    }
  })

  it('has no label for a code the backend does not write', () => {
    expect(Object.keys(CONFIDENCE_CAUSES).sort()).toEqual([...BACKEND_CAUSES].sort())
    expect(Object.keys(REASON_CODES).sort()).toEqual([...BACKEND_REASONS].sort())
  })

  it('shows an unknown code in words rather than hiding it', () => {
    expect(confidenceCause('gauge_on_fire').label).toBe('Gauge on fire')
    expect(reasonCode('some_new_code').detail).toMatch(/no description/)
  })

  it('reads the right label for the codes used in the Wayanad replay', () => {
    expect(reasonCode('risk_above_emergency').label).toBe('Risk above the Emergency threshold')
    expect(reasonCode('hysteresis_hold').label).toBe('Held at a higher level')
    expect(confidenceCause('sources_disagree').label).toBe('Rain sources disagree')
  })
})

describe('confidence meaning', () => {
  it('never speaks of agreeing sources for a forecast day', () => {
    for (const state of ['High', 'Degraded', 'Insufficient']) expect(confidenceMeaning(state, true)).not.toMatch(/agree/)
    expect(confidenceMeaning('Degraded', true)).toMatch(/forecast/)
    expect(confidenceMeaning('High', false)).toMatch(/agree/)
  })
})

describe('raised reasons', () => {
  it('says nothing for an unflagged cell', () => {
    expect(raisedReasons(0)).toEqual([])
    expect(raisedReasons(GRID_FLAG.gaugesUntrusted)).toEqual([])
  })

  it('names the blind raise by the reason that caused it, in the labels of the code tables', () => {
    expect(raisedReasons(GRID_FLAG.blindRaised)).toEqual(['Raised: heavy rain while sources disagree'])
    expect(raisedReasons(GRID_FLAG.blindRaised | GRID_FLAG.gaugesUntrusted)).toEqual([
      'Raised: heavy rain while gauges are untrusted',
    ])
  })

  it('names a hysteresis hold, alone or after a raise', () => {
    expect(raisedReasons(GRID_FLAG.held)).toEqual(['Held at a higher level from yesterday'])
    expect(raisedReasons(GRID_FLAG.held | GRID_FLAG.blindRaised)).toHaveLength(2)
  })
})

describe('input names', () => {
  it('names every column of the hazard model', () => {
    for (const column of MODEL_COLUMNS) expect(FEATURE_LABELS[column], column).toBeTruthy()
    expect(Object.keys(FEATURE_LABELS)).toHaveLength(MODEL_COLUMNS.length)
  })

  it('falls back to the column name in words', () => {
    expect(featureLabel('rain_acc_1')).toBe('Rain, today')
    expect(featureLabel('new_feature_x')).toBe('New feature x')
  })

  it('gives rain in millimetres, elevation in metres and no unit otherwise', () => {
    expect(featureValueText('rain_acc_1', 179.2358)).toBe('179 mm')
    expect(featureValueText('rain_acc_30', 1131.4)).toBe('1,131 mm')
    expect(featureValueText('stat_elev_mean', 1619.1)).toBe('1,619 m')
    expect(featureValueText('rain_share1_3', 0.93936)).toBe('0.939')
    expect(featureValueText('rain_acc_1', null)).toBe('n/a')
  })
})

describe('cappedExplanation', () => {
  const rule = { passed: false, exempt: false, capped: true, windowDays: 7, rainMm: 0, minimumMm: 11.5, cappedTo: 'Watch' }

  it('explains an Emergency capped to Watch with the rain and the trigger', () => {
    expect(cappedExplanation(['risk_above_emergency', 'no_recent_rain'], rule)).toBe(
      'Model risk is in the Emergency range, but there was no rain in the last 7 days (rain trigger: 11.5 mm), so the level is capped at Watch.',
    )
    expect(cappedExplanation(['risk_above_warning', 'no_recent_rain'], { ...rule, rainMm: 4.25 })).toBe(
      'Model risk is in the Warning range, but there was only 4.3 mm of rain in the last 7 days (rain trigger: 11.5 mm), so the level is capped at Watch.',
    )
  })

  it('names the highest tier the cell has, and Watch for an upper estimate that reached it', () => {
    expect(cappedExplanation(['risk_above_watch', 'risk_above_warning', 'no_recent_rain'], { ...rule, rainMm: 2 })).toContain('Warning range')
    expect(cappedExplanation(['uncertain_high', 'no_recent_rain'], { ...rule, cappedTo: 'Normal', rainMm: 2 })).toBe(
      'The upper end of the risk range reaches Watch, but there was only 2 mm of rain in the last 7 days (rain trigger: 11.5 mm), so the level is capped at Normal.',
    )
  })

  it('still reads clearly when the run kept no numbers', () => {
    expect(cappedExplanation(['risk_above_emergency', 'no_recent_rain'], null)).toBe(
      'Model risk is in the Emergency range, but there was too little rain in the last 7 days, so the level is capped at Watch.',
    )
    expect(cappedExplanation(['no_recent_rain'], null)).toBe(
      'The model risk would give a higher level, but there was too little rain in the last 7 days, so the level is capped.',
    )
  })

  it('is null for a cell that was not capped', () => {
    expect(cappedExplanation(['risk_above_warning'], { ...rule, capped: false })).toBeNull()
    expect(cappedExplanation([], null)).toBeNull()
  })
})

describe('heavy-rain codes named after a cause', () => {
  it('spells out a <cause>_heavy_rain code from its cause', () => {
    const text = reasonCode('imd_missing_heavy_rain')
    expect(text.label).toBe('Heavy rain while: IMD rain missing')
    expect(text.detail).toMatch(/raised to at least Watch/)
  })

  it('keeps the listed codes and falls back to words for the rest', () => {
    expect(reasonCode('nowcast_tail_persisted_heavy_rain').label).toBe('Heavy rain while the newest rain hours are missing')
    expect(reasonCode('gauge_on_fire_heavy_rain').detail).toMatch(/no description/)
  })
})
