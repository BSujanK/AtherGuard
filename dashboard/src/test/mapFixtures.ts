import { http, HttpResponse } from 'msw'
import { f32ToBase64 } from './fixtures'

/** A 2 x 2 coarse rain field: 5 mm, no data, 60 mm, no data. */
export const rainPayload = {
  date: '2024-08-05',
  set: 'case_test_set',
  column: 'rain_acc_1',
  unit: 'mm/day',
  n_cells: 10,
  rows: 2,
  cols: 2,
  lat0: 8,
  lon0: 72,
  step: 0.25,
  rain: f32ToBase64([5, NaN, 60, NaN]),
}

export const LEAD_MISSING = "replay set 'case_test_set' holds lead 0 only (requested lead 1)"

/**
 * Map-specific API handlers, to be listed before the shared ones: the rain field, and a 404 for every
 * forecast lead (as a replay set answers). Lead 0 falls through to the shared grid handler.
 */
export function mapHandlers() {
  return [
    http.get('*/api/rain', () => HttpResponse.json(rainPayload)),
    http.get('*/api/grid', ({ request }) => {
      const lead = new URL(request.url).searchParams.get('lead')
      if (lead && lead !== '0') {
        return HttpResponse.json({ detail: LEAD_MISSING.replace('lead 1', `lead ${lead}`) }, { status: 404 })
      }
      return undefined
    }),
  ]
}
