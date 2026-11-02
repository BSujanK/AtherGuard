import type { QueryClient } from '@tanstack/react-query'
import { create } from 'zustand'

export type StreamState = 'connecting' | 'open' | 'reconnecting'
export type StreamEventName = 'run' | 'sources' | 'heartbeat'

/** The slice of EventSource this module uses, so tests can supply a fake. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void
  close(): void
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
}

export type EventSourceFactory = (url: string) => EventSourceLike

export interface StreamOptions {
  url?: string
  factory?: EventSourceFactory
  onState?: (state: StreamState) => void
  onEvent?: (name: StreamEventName, data: unknown) => void
  /** Called when a connection opens after at least one drop. */
  onReconnect?: () => void
  baseDelayMs?: number
  maxDelayMs?: number
  /** A silent connection older than this is treated as dropped (server sends a heartbeat every 15 s). */
  staleAfterMs?: number
}

const EVENTS: StreamEventName[] = ['run', 'sources', 'heartbeat']

export const useStreamStatus = create<{ state: StreamState; set: (s: StreamState) => void }>(
  (set) => ({ state: 'connecting', set: (state) => set({ state }) }),
)

/** Exponential backoff: base * 2^attempt, capped. */
export function backoffDelay(attempt: number, baseMs: number, maxMs: number): number {
  return Math.min(maxMs, baseMs * 2 ** attempt)
}

export function openStream(options: StreamOptions = {}): { close: () => void } {
  const {
    url = '/api/stream',
    factory = (u) => new EventSource(u) as unknown as EventSourceLike,
    onState,
    onEvent,
    onReconnect,
    baseDelayMs = 1000,
    maxDelayMs = 30_000,
    staleAfterMs = 45_000,
  } = options

  let source: EventSourceLike | null = null
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let staleTimer: ReturnType<typeof setTimeout> | undefined
  let attempt = 0
  let dropped = false
  let closed = false

  const armStale = () => {
    clearTimeout(staleTimer)
    staleTimer = setTimeout(drop, staleAfterMs)
  }

  function drop() {
    if (closed) return
    clearTimeout(staleTimer)
    source?.close()
    source = null
    dropped = true
    onState?.('reconnecting')
    retryTimer = setTimeout(connect, backoffDelay(attempt, baseDelayMs, maxDelayMs))
    attempt += 1
  }

  function connect() {
    if (closed) return
    const es = factory(url)
    source = es
    es.onopen = () => {
      if (es !== source) return
      attempt = 0
      armStale()
      onState?.('open')
      if (dropped) {
        dropped = false
        onReconnect?.()
      }
    }
    es.onerror = () => {
      if (es === source) drop()
    }
    for (const name of EVENTS) {
      es.addEventListener(name, (event) => {
        if (es !== source) return
        armStale()
        let data: unknown = null
        try {
          data = JSON.parse(event.data)
        } catch {
          /* a malformed payload is still a sign of life; deliver null */
        }
        onEvent?.(name, data)
      })
    }
  }

  onState?.('connecting')
  connect()

  return {
    close() {
      closed = true
      clearTimeout(retryTimer)
      clearTimeout(staleTimer)
      source?.close()
      source = null
    },
  }
}

/**
 * Connect the app to the server stream: publish connection state, refresh data when a run lands
 * or source freshness changes, and refresh everything after a reconnect.
 */
export function connectStream(queryClient: QueryClient, options: StreamOptions = {}) {
  return openStream({
    ...options,
    onState: (state) => {
      useStreamStatus.getState().set(state)
      options.onState?.(state)
    },
    onEvent: (name, data) => {
      if (name === 'run') {
        void queryClient.invalidateQueries({ queryKey: ['mode'] })
        void queryClient.invalidateQueries({ queryKey: ['grid'] })
        void queryClient.invalidateQueries({ queryKey: ['rain'] })
        void queryClient.invalidateQueries({ queryKey: ['cell'] })
        void queryClient.invalidateQueries({ queryKey: ['history'] })
      } else if (name === 'sources') {
        void queryClient.invalidateQueries({ queryKey: ['sources'] })
      }
      options.onEvent?.(name, data)
    },
    onReconnect: () => {
      // The base map is static for the life of a build; everything else may have changed while offline.
      void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'basemap' })
      options.onReconnect?.()
    },
  })
}
