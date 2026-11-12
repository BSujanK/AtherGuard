/**
 * Review screenshots of the three views and the alert drawer, desktop and phone (headless Chromium, software GL).
 *
 *   node scripts/screenshots.ts [baseUrl] [prefix]
 *
 * baseUrl defaults to the API on 127.0.0.1:8790 (the built app); pass a Vite dev URL to shoot unbuilt sources.
 * Writes review/<prefix>-<view>-<width>.png (prefix defaults to "shot").
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const base = (process.argv[2] ?? 'http://127.0.0.1:8790').replace(/\/$/, '')
const prefix = process.argv[3] ?? 'shot'
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})

const VIEWS = [
  { name: 'map', path: '/map', ready: 'Map controls' },
  { name: 'alerts', path: '/alerts-why', ready: null },
  { name: 'sensors', path: '/sensors-sources', ready: null },
] as const

for (const width of [1440, 390]) {
  const context = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))
  // The story: one shot per chapter, each after the camera has caught up with the scroll.
  await page.goto(`${base}/`, { waitUntil: 'commit' })
  await page.getByRole('heading', { level: 1, name: 'AetherGuard' }).waitFor({ timeout: 90_000 })
  await page.waitForTimeout(9000)
  for (const chapter of ['chart', 'ground', 'rain', 'levels', 'today', 'limits']) {
    await page.evaluate((id) => document.getElementById(id)?.scrollIntoView({ block: 'start', behavior: 'instant' }), chapter)
    await page.waitForTimeout(chapter === 'chart' ? 500 : 4500)
    await page.screenshot({ path: file(`${prefix}-story-${chapter}-${width}.png`) })
    console.log(`story ${chapter} ${width}`)
  }
  for (const view of VIEWS) {
    await page.goto(`${base}${view.path}`, { waitUntil: 'commit' })
    await page.getByRole('heading', { level: 1 }).first().waitFor({ timeout: 90_000, state: 'attached' })
    if (view.ready) await page.getByRole('region', { name: view.ready }).waitFor({ timeout: 90_000 })
    await page.waitForTimeout(view.name === 'map' ? 9000 : 3500)
    await page.screenshot({ path: file(`${prefix}-${view.name}-${width}.png`) })
    console.log(`${view.name} ${width}`)
  }
  if (width > 600) {
    // The drawer of the first alert in the list.
    await page.goto(`${base}/alerts-why`, { waitUntil: 'commit' })
    const row = page.locator('[data-feed] button[data-index]').first()
    await row.click({ timeout: 30_000 }).catch(() => console.log('no alert row to open'))
    await page.getByTestId('alert-drawer').getByRole('heading', { name: 'Level' }).waitFor({ timeout: 30_000 }).catch(() => console.log('drawer did not finish loading'))
    await page.waitForTimeout(2500)
    await page.screenshot({ path: file(`${prefix}-drawer-${width}.png`) })
    console.log(`drawer ${width}`)
  }
  await context.close()
}

await browser.close()
