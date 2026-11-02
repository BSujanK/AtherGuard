import { useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(QUERY).matches
    : false
}

function subscribe(onChange: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
  const mql = window.matchMedia(QUERY)
  mql.addEventListener('change', onChange)
  return () => mql.removeEventListener('change', onChange)
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false)
}

let webgl: boolean | undefined

/** True when a WebGL2 context can be created. Cached; false in non-browser environments. */
export function webglAvailable(): boolean {
  if (webgl !== undefined) return webgl
  if (typeof window === 'undefined' || typeof WebGL2RenderingContext === 'undefined') {
    webgl = false
    return webgl
  }
  try {
    const canvas = document.createElement('canvas')
    webgl = Boolean(canvas.getContext('webgl2'))
  } catch {
    webgl = false
  }
  return webgl
}
