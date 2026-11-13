/**
 * Transition review: clicks through every view and the main controls with a real pointer and records frames during
 * each change, then lays them out as one contact sheet per width (headless Chromium, software GL).
 *
 *   node scripts/transitions.ts [baseUrl]
 *
 * Writes review/transitions-<width>.png (one row per step, frames left to right at the offsets below) and prints every
 * console error and page error seen. Software GL draws slowly, so the frames show where a change goes, not its speed.
 */
import { mkdirSync } from 'node:fs'
import { chromium, type Page } from 'playwright'

const base = (process.argv[2] ?? 'http://127.0.0.1:8790').replace(/\/$/, '')
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')
// CSS animations (view transitions, fades, presses) run at a tenth of their speed during the steps, so these
// offsets fall inside them; the canvas, driven by requestAnimationFrame, is not slowed.
const PLAYBACK = 0.1
const OFFSETS_MS = [0, 700, 1600, 2800, 4400, 7000]

const controls = (p: Page) => p.getByRole('region', { name: 'Map controls' })
type Step = { name: string; act: (page: Page) => Promise<void> }
const nav = (label: string): Step => ({ name: `nav: ${label}`, act: (p) => p.getByRole('navigation', { name: 'Views' }).getByRole('link', { name: label }).click() })
const STEPS: Step[] = [
  nav('Live map'),
  { name: 'map: D+1', act: (p) => controls(p).getByRole('radio', { name: 'D+1' }).click() },
  { name: 'map: Himalaya', act: (p) => controls(p).getByRole('radio', { name: 'Himalaya' }).click() },
  { name: 'map: Reset view', act: (p) => p.getByRole('button', { name: 'Reset view' }).click() },
  nav('Alerts'),
  nav('Sensors & sources'),
  { name: 'brand: story', act: (p) => p.getByRole('link', { name: 'AetherGuard, the story of the chart' }).click() },
  { name: 'story: Read the chart', act: (p) => p.getByRole('button', { name: 'Read the chart' }).click() },
  nav('Live map'),
  nav('Alerts'),
  { name: 'brand: story again', act: (p) => p.getByRole('link', { name: 'AetherGuard, the story of the chart' }).click() },
]

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
for (const width of [1440, 390]) {
  const context = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const problems: string[] = []
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  page.on('console', (m) => m.type() === 'error' && problems.push(`console: ${m.text()}`))
  await page.goto(`${base}/`, { waitUntil: 'commit' })
  await page.getByRole('heading', { level: 1, name: 'AetherGuard' }).waitFor({ timeout: 90_000 })
  await page.waitForTimeout(9000)                                      // the landing plays to its end
  const cdp = await context.newCDPSession(page)
  await cdp.send('Animation.enable')
  await cdp.send('Animation.setPlaybackRate', { playbackRate: PLAYBACK })
  const rows: { name: string; frames: string[] }[] = []
  for (const step of STEPS) {
    const shots: Buffer[] = []
    const started = Date.now()
    try {
      await step.act(page)
    } catch (error) {
      problems.push(`${step.name}: could not act (${String(error).split('\n')[0]})`)
      continue
    }
    for (const offset of OFFSETS_MS) {
      const wait = started + offset - Date.now()
      if (wait > 0) await page.waitForTimeout(wait)
      shots.push(await page.screenshot({ scale: 'css', timeout: 60_000 }))      // one at a time: the offsets are approximate
    }
    rows.push({ name: step.name, frames: shots.map((b) => b.toString('base64')) })
    await page.waitForTimeout(1500)
  }
  // One sheet: a row per step, frames at their offsets.
  const thumb = width > 600 ? 230 : 120
  const html = `<body style="margin:0;background:#222;font:12px system-ui;color:#eee">${rows
    .map((r) => `<div style="display:flex;gap:4px;align-items:center;padding:3px"><div style="width:120px">${r.name}</div>${r.frames
      .map((f) => `<img style="width:${thumb}px" src="data:image/png;base64,${f}">`)
      .join('')}</div>`)
    .join('')}<div style="padding:4px">frames at ${OFFSETS_MS.join(', ')} ms, CSS animations at ${PLAYBACK}x</div></body>`
  const sheet = await context.newPage()
  await sheet.setViewportSize({ width: 130 + OFFSETS_MS.length * (thumb + 4), height: 600 })
  await sheet.setContent(html)
  await sheet.screenshot({ path: file(`transitions-${width}.png`), fullPage: true })
  console.log(`width ${width}: ${rows.length}/${STEPS.length} steps; problems: ${problems.length ? '\n  ' + problems.join('\n  ') : 'none'}`)
  await context.close()
}
await browser.close()
