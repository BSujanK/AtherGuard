import { describe, expect, it } from 'vitest'
import { makeGrid } from '../../scene/testData'
import { alertCount, topAlerts } from './topAlerts'

describe('topAlerts', () => {
  const cells = Array.from({ length: 2000 }, (_, i) => ({ row: Math.floor(i / 100), col: i % 100 }))
  const grid = makeGrid(cells, (i) => i % 4, (i) => ((i * 7919) % 1000) / 1000)
  const all = new Uint8Array(grid.n).fill(1)

  it('ranks by level then risk and leaves out Normal cells', () => {
    const top = topAlerts(grid, all, 10)
    expect(top).toHaveLength(10)
    expect(top.every((a) => a.level === 3)).toBe(true)
    for (let i = 1; i < top.length; i++) expect(top[i - 1]!.risk).toBeGreaterThanOrEqual(top[i]!.risk)
  })

  it('respects the visibility mask and counts Watch and above', () => {
    const none = new Uint8Array(grid.n)
    expect(topAlerts(grid, none, 5)).toEqual([])
    expect(alertCount(grid, none)).toBe(0)
    expect(alertCount(grid, all)).toBe(1500)
  })
})
