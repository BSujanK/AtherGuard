/** Just enough CSS colour handling to evaluate the design tokens and measure WCAG contrast. No imports: Node can run it directly. */

export interface Rgba {
  r: number
  g: number
  b: number
  a: number
}

/** Custom properties declared in `:root` of a stylesheet: `--name: value;` (first declaration wins; later media overrides are ignored). */
export function parseTokens(css: string): Map<string, string> {
  const tokens = new Map<string, string>()
  const root = /:root\s*\{([^}]*)\}/.exec(css)
  for (const m of (root?.[1] ?? '').matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    if (!tokens.has(m[1]!)) tokens.set(m[1]!, m[2]!.trim())
  }
  return tokens
}

const hex = (value: string): Rgba | null => {
  const m = /^#([0-9a-f]{6})$/i.exec(value)
  if (!m) return null
  const n = parseInt(m[1]!, 16)
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: 1 }
}

/** Splits at top-level commas, so nested `color-mix(...)` arguments stay whole. */
function splitArgs(text: string): string[] {
  const out: string[] = []
  let depth = 0
  let start = 0
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '(') depth++
    else if (text[i] === ')') depth--
    else if (text[i] === ',' && depth === 0) {
      out.push(text.slice(start, i).trim())
      start = i + 1
    }
  }
  out.push(text.slice(start).trim())
  return out
}

/**
 * The colour of a token value: a #RRGGBB, `transparent`, `var(--x)` or `color-mix(in srgb, A p%, B [q%])`, with the
 * premultiplied interpolation CSS uses (so mixing with `transparent` gives the colour at the mixed alpha).
 */
export function resolve(value: string, tokens: Map<string, string>): Rgba {
  const v = value.trim()
  const direct = hex(v)
  if (direct) return direct
  if (v === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
  const variable = /^var\((--[\w-]+)\)$/.exec(v)
  if (variable) {
    const target = tokens.get(variable[1]!)
    if (target === undefined) throw new Error(`Unknown token ${variable[1]}`)
    return resolve(target, tokens)
  }
  const mix = /^color-mix\(in srgb,(.*)\)$/s.exec(v)
  if (mix) {
    const [first, second] = splitArgs(mix[1]!).map((part) => {
      const m = /^(.*?)\s+(\d+(?:\.\d+)?)%$/.exec(part)
      return { colour: resolve(m ? m[1]! : part, tokens), share: m ? Number(m[2]) / 100 : null }
    }) as [{ colour: Rgba; share: number | null }, { colour: Rgba; share: number | null }]
    const p1 = first.share ?? 1 - (second.share ?? 0.5)
    const p2 = second.share ?? 1 - p1
    const a = first.colour.a * p1 + second.colour.a * p2
    if (a === 0) return { r: 0, g: 0, b: 0, a: 0 }
    const channel = (k: 'r' | 'g' | 'b') => (first.colour[k] * first.colour.a * p1 + second.colour[k] * second.colour.a * p2) / a
    return { r: channel('r'), g: channel('g'), b: channel('b'), a }
  }
  throw new Error(`Cannot evaluate colour: ${value}`)
}

/** `top` composited over an opaque `under`. */
export function over(top: Rgba, under: Rgba): Rgba {
  const k = (c: 'r' | 'g' | 'b') => top[c] * top.a + under[c] * (1 - top.a)
  return { r: k('r'), g: k('g'), b: k('b'), a: 1 }
}

const linear = (c: number): number => {
  const s = c / 255
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

export const luminance = ({ r, g, b }: Rgba): number => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)

/** WCAG 2.x contrast ratio of `fg` on `bg` (a translucent `fg` is composited on `bg` first). */
export function contrast(fg: Rgba, bg: Rgba): number {
  const l1 = luminance(over(fg, bg))
  const l2 = luminance(bg)
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
}
