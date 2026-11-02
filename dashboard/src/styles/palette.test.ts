/// <reference types="node" />
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve as resolvePath } from 'node:path'
import { PALETTE } from '../charts/theme'
import { contrast, over, parseTokens, resolve } from '../test/color'

const ROOT = resolvePath(import.meta.dirname, '../..')
const read = (path: string): string => readFileSync(join(ROOT, path), 'utf8')

function walk(dir: string, accept: (path: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path, accept) : accept(path) ? [path] : []
  })
}

/** The user's palette (spec section 8). Every other colour is a mix of these, computed by `mixHex` or CSS `color-mix`. */
const ALLOWED_HEX = new Set(Object.values(PALETTE).map((h) => h.toLowerCase()))
/** Mixes written out as literals, each documented where it is used. None: mixes are always computed. */
const DOCUMENTED_MIXES: string[] = []

/** The old pinned palette and its mixes: smoke black, burnt brown, sand and the derived steps. */
const OLD_PALETTE = ['#15110F', '#4B1F17', '#F0C27B', '#5F3323']

const sources = [
  ...walk(join(ROOT, 'src'), (p) => /\.(ts|tsx|css)$/.test(p) && !p.endsWith('palette.test.ts')),
  join(ROOT, 'index.html'),
  join(ROOT, 'public/favicon.svg'),
]

const hexesIn = (text: string): string[] => [...text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toLowerCase())
const outsidePalette = (text: string): string[] =>
  hexesIn(text).filter((h) => !ALLOWED_HEX.has(h) && !DOCUMENTED_MIXES.includes(h))
/** The minifier writes `transparent` as #0000; that is no colour. */
const outsidePaletteBuilt = (text: string): string[] => outsidePalette(text).filter((h) => h !== '#0000')

describe('the palette', () => {
  it('uses no colour literal in the sources outside the palette and its documented mixes', () => {
    const offenders = sources.flatMap((file) =>
      outsidePalette(readFileSync(file, 'utf8')).map((h) => `${relative(ROOT, file)}: ${h}`),
    )
    expect(offenders).toEqual([])
  })

  it('has no old-palette colour anywhere in the sources', () => {
    const text = sources.map((file) => readFileSync(file, 'utf8').toLowerCase()).join('\n')
    for (const old of OLD_PALETTE) expect(text).not.toContain(old.toLowerCase())
  })

  it('writes colours only as hex or colour-mix, never rgb() or hsl()', () => {
    for (const file of sources.filter((f) => f.endsWith('.css'))) {
      expect(readFileSync(file, 'utf8'), relative(ROOT, file)).not.toMatch(/\b(?:rgba?|hsla?)\(/)
    }
  })

  it('declares the seven palette colours in the tokens, matching the TypeScript palette', () => {
    const tokens = parseTokens(read('src/styles/tokens.css'))
    const names = ['--ink-black', '--neon-cyan', '--royal-blue', '--neon-lime', '--flame-orange', '--fire-red', '--cloud']
    expect(names.map((name) => tokens.get(name)!.toLowerCase())).toEqual(
      [PALETTE.ink, PALETTE.cyan, PALETTE.blue, PALETTE.lime, PALETTE.flame, PALETTE.fire, PALETTE.cloud].map((h) => h.toLowerCase()),
    )
  })

  it('leaves the built stylesheets inside the palette too (when a build exists)', () => {
    let built: string[] = []
    try {
      built = walk(join(ROOT, 'dist/assets'), (p) => p.endsWith('.css'))
    } catch {
      return
    }
    for (const file of built) expect(outsidePaletteBuilt(readFileSync(file, 'utf8')), relative(ROOT, file)).toEqual([])
  })
})

describe('contrast', () => {
  const tokens = parseTokens(read('src/styles/tokens.css'))
  const colour = (name: string) => resolve(`var(${name})`, tokens)
  const SURFACES = ['--bg', '--surface-sunken', '--surface', '--surface-raised', '--surface-high']
  const onSurface = (surface: string) => over(colour(surface), colour('--bg'))

  it.each(['--text', '--text-2', '--text-3'].flatMap((text) => SURFACES.map((surface) => [text, surface] as const)))(
    'body text %s on %s is at least 4.5:1',
    (text, surface) => {
      expect(contrast(colour(text), onSurface(surface))).toBeGreaterThanOrEqual(4.5)
    },
  )

  it.each(['--bg', '--surface', '--surface-raised'])('neon cyan, the accent used for text, is at least 4.5:1 on %s', (surface) => {
    expect(contrast(colour('--neon-cyan'), onSurface(surface))).toBeGreaterThanOrEqual(4.5)
  })

  it.each(['--bg', '--surface'])('flame orange used as text (warnings) is at least 4.5:1 on %s', (surface) => {
    expect(contrast(colour('--flame-orange'), onSurface(surface))).toBeGreaterThanOrEqual(4.5)
  })

  it('text on the accent fill (selected chips, buttons) is at least 4.5:1', () => {
    expect(contrast(colour('--text-on-accent'), colour('--accent'))).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps fire red out of text: it is under 4.5:1 on ink, so it is only ever a fill, stroke or border', () => {
    expect(contrast(colour('--fire-red'), colour('--bg'))).toBeLessThan(4.5)
    const offenders = sources
      .filter((f) => f.endsWith('.css'))
      .flatMap((file) =>
        readFileSync(file, 'utf8')
          .split('\n')
          .filter((line) => /^\s*color\s*:/.test(line) && /--(?:fire-red|danger|level-emergency)/.test(line))
          .map((line) => `${relative(ROOT, file)}: ${line.trim()}`),
      )
    expect(offenders).toEqual([])
  })

  it('evaluates mixes like CSS: colour-mix with transparent keeps the colour at the mixed alpha', () => {
    const t = new Map([['--c', '#ffffff']])
    expect(resolve('color-mix(in srgb, var(--c) 40%, transparent)', t)).toEqual({ r: 255, g: 255, b: 255, a: 0.4 })
  })
})
