/**
 * Review screenshots of the Sensors & sources view (Task D5), kept apart from screenshots.ts so the two scripts merge cleanly.
 *
 *   npx vite preview --port 4174 &   (API on 127.0.0.1:8790 behind the proxy)
 *   node scripts/sensors-screenshots.ts [baseUrl]
 *
 * Writes review/sensors-1440.png, sensors-1024.png and sensors-hover.png from whatever the API holds: with no live run
 * yet the source panel shows its empty state, which is what these shots record.
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const base = process.argv[2] ?? 'http://127.0.0.1:4174'
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')

const browser = await chromium.launch({ headless: true })

async function open(width: number, height: number) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') console.log(`[browser ${m.type()}]`, m.text())
  })
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))
  await page.goto(`${base}/sensors-sources`, { waitUntil: 'commit' })
  await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
  await page.getByRole('group', { name: /rain gauges coloured by trust/ }).waitFor({ timeout: 60_000 })
  await page.getByTestId('relief').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(1500)
  return page
}

{
  const page = await open(1440, 900)
  await page.screenshot({ path: file('sensors-1440.png') })
  const flagged = page.locator('[data-flagged="true"] circle[role="img"]').first()
  await flagged.hover({ force: true })
  await page.getByRole('tooltip').waitFor()
  await page.waitForTimeout(600)
  await page.screenshot({ path: file('sensors-hover.png') })
  await page.close()
}

{
  const page = await open(1024, 768)
  await page.screenshot({ path: file('sensors-1024.png') })
  await page.close()
}

await browser.close()
