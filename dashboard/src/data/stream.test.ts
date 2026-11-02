import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  backoffDelay,
  connectStream,
  type EventSourceLike,
  openStream,
  type StreamState,
  useStreamStatus,
} from './stream'

class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = []
  onopen: ((e: Event) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  closed = false
  private listeners = new Map<string, Array<(e: MessageEvent<string>) => void>>()

  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (e: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close() {
    this.closed = true
  }

  open() {
    this.onopen?.(new Event('open'))
  }

  fail() {
    this.onerror?.(new Event('error'))
  }

  emit(type: string, data: string) {
    for (const l of this.listeners.get(type) ?? []) l(new MessageEvent(type, { data }))
  }
}

const factory = (url: string) => new FakeEventSource(url)
const last = () => FakeEventSource.instances.at(-1)!

beforeEach(() => {
  FakeEventSource.instances = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('backoffDelay', () => {
  it('doubles from the base and caps at the maximum', () => {
    expect([0, 1, 2, 3, 4, 5, 6].map((n) => backoffDelay(n, 1000, 30_000))).toEqual([
      1000, 2000, 4000, 8000, 16_000, 30_000, 30_000,
    ])
  })
})

describe('openStream', () => {
  it('reports connecting then open, and delivers parsed events', () => {
    const states: StreamState[] = []
    const events: Array<[string, unknown]> = []
    openStream({
      factory,
      onState: (s) => states.push(s),
      onEvent: (n, d) => events.push([n, d]),
    })
    expect(last().url).toBe('/api/stream')
    last().open()
    last().emit('run', '{"date":"2024-08-05"}')
    last().emit('heartbeat', 'not json')
    expect(states).toEqual(['connecting', 'open'])
    expect(events).toEqual([
      ['run', { date: '2024-08-05' }],
      ['heartbeat', null],
    ])
  })

  it('reconnects with exponential backoff and resets after a successful open', () => {
    const states: StreamState[] = []
    const onReconnect = vi.fn()
    openStream({ factory, onState: (s) => states.push(s), onReconnect, baseDelayMs: 1000, maxDelayMs: 4000 })
    last().open()

    last().fail()
    expect(states.at(-1)).toBe('reconnecting')
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0]!.closed).toBe(true)

    vi.advanceTimersByTime(999)
    expect(FakeEventSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeEventSource.instances).toHaveLength(2)

    last().fail() // second failure waits 2 s
    vi.advanceTimersByTime(1999)
    expect(FakeEventSource.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeEventSource.instances).toHaveLength(3)

    last().fail() // third waits 4 s (cap)
    vi.advanceTimersByTime(4000)
    expect(FakeEventSource.instances).toHaveLength(4)
    expect(onReconnect).not.toHaveBeenCalled()

    last().open()
    expect(states.at(-1)).toBe('open')
    expect(onReconnect).toHaveBeenCalledTimes(1)

    last().fail() // delay restarts from the base
    vi.advanceTimersByTime(1000)
    expect(FakeEventSource.instances).toHaveLength(5)
  })

  it('treats a silent connection as dropped', () => {
    const states: StreamState[] = []
    openStream({ factory, onState: (s) => states.push(s), staleAfterMs: 45_000, baseDelayMs: 1000 })
    last().open()
    vi.advanceTimersByTime(44_000)
    last().emit('heartbeat', '{}')
    vi.advanceTimersByTime(44_000)
    expect(states.at(-1)).toBe('open')
    vi.advanceTimersByTime(1000)
    expect(states.at(-1)).toBe('reconnecting')
    vi.advanceTimersByTime(1000)
    expect(FakeEventSource.instances).toHaveLength(2)
  })

  it('ignores events from a superseded connection and stops after close()', () => {
    const onEvent = vi.fn()
    const stream = openStream({ factory, onEvent, baseDelayMs: 10 })
    const first = last()
    first.open()
    first.fail()
    vi.advanceTimersByTime(10)
    first.emit('run', '{}')
    expect(onEvent).not.toHaveBeenCalled()

    stream.close()
    last().fail()
    vi.advanceTimersByTime(60_000)
    expect(FakeEventSource.instances).toHaveLength(2)
    expect(last().closed).toBe(true)
  })
})

describe('connectStream', () => {
  it('invalidates queries on run and sources events, and everything but the base map after a reconnect', () => {
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()
    connectStream(queryClient, { factory, baseDelayMs: 10 })
    expect(useStreamStatus.getState().state).toBe('connecting')
    last().open()
    expect(useStreamStatus.getState().state).toBe('open')

    last().emit('run', '{}')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['mode'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['grid'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['cell'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['history'] })

    invalidate.mockClear()
    last().emit('sources', '{}')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sources'] })

    invalidate.mockClear()
    last().emit('heartbeat', '{}')
    expect(invalidate).not.toHaveBeenCalled()

    last().fail()
    expect(useStreamStatus.getState().state).toBe('reconnecting')
    vi.advanceTimersByTime(10)
    last().open()
    expect(useStreamStatus.getState().state).toBe('open')
    const call = invalidate.mock.calls.at(-1)![0]!
    expect(call.predicate?.({ queryKey: ['basemap'] } as never)).toBe(false)
    expect(call.predicate?.({ queryKey: ['grid', 'd', 0] } as never)).toBe(true)
  })
})
