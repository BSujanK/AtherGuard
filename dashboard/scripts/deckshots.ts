/**
 * Review screenshots of the presentation: every slide, desktop and phone, each after its entrance and the camera move.
 *
 *   node scripts/deckshots.ts [baseUrl]
 *
 * Writes review/deck-<n>-<width>.png.
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const base = (process.argv[2] ?? 'http://127.0.0.1:8790').replace(/\/$/, '')
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')
const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] })
for (const width of [1440, 390]) {
  const context = await browser.newContext({ viewport: { width, height: width > 600 ? 900 : 844 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))
  await page.goto(`${base}/deck`, { waitUntil: 'commit' })
  await page.getByRole('region', { name: /^1 of 8/ }).waitFor({ timeout: 90_000 })
  await page.waitForTimeout(9000)
  for (let n = 1; n <= 8; n++) {
    if (n > 1) await page.keyboard.press('ArrowRight')
    await page.waitForTimeout(5000)
    await page.screenshot({ path: file(`deck-${n}-${width}.png`) })
    console.log(`slide ${n} ${width}`)
  }
  await context.close()
}
await browser.close()
