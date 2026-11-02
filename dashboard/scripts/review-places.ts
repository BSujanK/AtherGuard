/**
 * Review screenshots of the place names and the forecast-lead detail, taken against the live API.
 *
 *   node scripts/review-places.ts [baseUrl]        (default http://127.0.0.1:8790)
 *
 * Writes review/places-hover.png, places-alerts.png, places-drawer.png, lead3-map.png and lead3-drawer.png, and prints
 * the cell, target date, level and risk the lead-3 drawer shows (compare them with risk_D3.parquet of the run).
 */
import { mkdirSync } from 'node:fs'
import { chromium, type Page } from 'playwright'

const base = (process.argv[2] ?? 'http://127.0.0.1:8790').replace(/\/$/, '')
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})

async function newPage(width = 1440, height = 900) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))
  return page
}

async function openMap(page: Page, search = '') {
  await page.goto(`${base}/map?quality=full${search}`, { waitUntil: 'commit' })
  await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
  await page.getByRole('region', { name: 'Map controls' }).waitFor({ timeout: 90_000 })
  await page.locator('[data-terrain="loaded"]').waitFor({ timeout: 90_000 })
  await page.getByRole('radio', { name: 'Western Ghats' }).check()
  await page.waitForTimeout(5000)
}

/** Sweeps the pointer over the canvas until the hover card shows a cell with `pattern`; returns the card text. */
async function hoverCell(page: Page, pattern: RegExp): Promise<string> {
  for (let y = 180; y <= 820; y += 24) {
    for (let x = 300; x <= 1300; x += 24) {
      await page.mouse.move(x, y)
      await page.waitForTimeout(120)
      const text = (await page.getByTestId('hover-card').allTextContents())[0] ?? ''
      if (pattern.test(text)) return text
    }
  }
  throw new Error(`no hover card matching ${pattern}`)
}

// The newest date at lead 0: the map hover, the alert feed, one drawer.
{
  const page = await newPage()
  await openMap(page)
  const card = await hoverCell(page, /^(Warning|Emergency|Watch)[\s\S]*(from town centre|nearest town)/)
  console.log('places-hover card:', card.replace(/\s+/g, ' '))
  await page.screenshot({ path: file('places-hover.png') })
  await page.close()
}
{
  const page = await newPage()
  await page.goto(`${base}/alerts-why`, { waitUntil: 'commit' })
  await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
  await page.locator('[data-feed] button[data-index="0"]').waitFor({ timeout: 90_000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: file('places-alerts.png') })
  await page.locator('[data-feed] button[data-index="0"]').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('heading', { name: 'Last 30 days' }).waitFor({ timeout: 90_000 })
  await page.locator('[data-testid="alert-drawer"] canvas[role="img"]').first().waitFor({ timeout: 90_000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: file('places-drawer.png') })
  await page.close()
}

// The D+3 forecast: hover a cell on the map, then open the same cell's detail at D+3.
{
  const page = await newPage()
  await openMap(page, '&lead=3')
  const card = await hoverCell(page, /^(Watch|Warning|Emergency)[\s\S]*D\+3, forecast/)
  const cell = /Cell (\d+)/.exec(card)![1]!
  console.log('lead3-map card:', card.replace(/\s+/g, ' '))
  await page.screenshot({ path: file('lead3-map.png') })
  await page.close()

  const detail = await newPage()
  await detail.goto(`${base}/map?quality=full&lead=3`, { waitUntil: 'commit' })
  const date = await (await fetch(`${base}/api/mode`)).json().then((m: { latest_date: string }) => m.latest_date)
  await detail.goto(`${base}/alerts-why?cell=${cell}&date=${date}&lead=3`, { waitUntil: 'commit' })
  await detail.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
  const dialog = detail.getByRole('dialog')
  await dialog.getByRole('heading', { name: 'Last 30 days' }).waitFor({ timeout: 90_000 })
  await detail.locator('[data-testid="alert-drawer"] canvas[role="img"]').first().waitFor({ timeout: 90_000 })
  await detail.waitForTimeout(2500)
  await detail.screenshot({ path: file('lead3-drawer.png') })
  const level = await dialog.locator('section[aria-labelledby="drawer-level"]').innerText()
  const header = await dialog.locator('header').innerText()
  console.log(JSON.stringify({ cell, date, header: header.replace(/\s+/g, ' '), level: level.replace(/\s+/g, ' ') }))
  await detail.close()
}

await browser.close()
