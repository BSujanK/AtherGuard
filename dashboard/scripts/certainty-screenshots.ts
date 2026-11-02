/**
 * Review screenshots of the forecast certainty, the plain-language probability line and the capped-level reason (spec section 12),
 * as the API on 127.0.0.1:8790 serves the built app (headless Chromium, software GL).
 *
 *   node scripts/certainty-screenshots.ts [baseUrl]
 *
 * Environment: DATE (run date), FIRM_CELL and DEPENDS_CELL (cells of the lead-LEAD forecast whose certainty is firm / depends),
 * CAPPED_CELL (a lead-0 cell whose level is capped by `no_recent_rain`), LEAD (default 1). Writes to dashboard/review/:
 *   forecast-firm-hover.png, forecast-depends-drawer.png, drawer-plain-probability.png, drawer-capped-reason.png
 */
import { mkdirSync } from 'node:fs'
import { chromium, type Page } from 'playwright'

const base = (process.argv[2] ?? 'http://127.0.0.1:8790').replace(/\/$/, '')
const need = (name: string): string => {
  const value = process.env[name]
  if (!value) throw new Error(`set ${name}`)
  return value
}
const date = need('DATE')
const lead = process.env.LEAD ?? '1'
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})

async function newPage(): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))
  return page
}

async function openDrawer(page: Page, cell: string, forLead: string) {
  const query = forLead === '0' ? '' : `&lead=${forLead}`
  await page.goto(`${base}/alerts-why?cell=${cell}&date=${date}${query}`, { waitUntil: 'commit' })
  await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('heading', { name: 'Level', exact: true }).waitFor({ timeout: 90_000 })
  await page.waitForTimeout(2500)
  return dialog
}

// Hover over a firm forecast cell on the map: the card names Firm, why, the rain source and the probability in words.
{
  const page = await newPage()
  await page.goto(`${base}/map?quality=full&lead=${lead}&date=${date}`, { waitUntil: 'commit' })
  await page.getByRole('region', { name: 'Map controls' }).waitFor({ timeout: 90_000 })
  await page.locator('[data-terrain="loaded"]').waitFor({ timeout: 90_000 })
  await page.waitForTimeout(5000)
  // The map is a canvas: scan a coarse grid of points until a hover card with "Firm" appears.
  const box = (process.env.HOVER_BOX ?? '300,250,1100,800').split(',').map(Number) as [number, number, number, number]
  let found = false
  for (let y = box[1]; y <= box[3] && !found; y += 14) {
    for (let x = box[0]; x <= box[2] && !found; x += 14) {
      await page.mouse.move(x, y)
      await page.waitForTimeout(120)
      const text = (await page.getByTestId('hover-card').allTextContents())[0] ?? ''
      found = /Firm/.test(text) && /1 in/.test(text)
    }
  }
  console.log(found ? 'forecast-firm-hover: card with Firm found' : 'forecast-firm-hover: NO FIRM CARD FOUND')
  await page.screenshot({ path: file('forecast-firm-hover.png') })
  await page.close()
}

// Drawer of a forecast cell whose level depends on the rain forecast.
{
  const page = await newPage()
  const dialog = await openDrawer(page, need('DEPENDS_CELL'), lead)
  console.log('depends drawer:', (await dialog.getByTestId('certainty').textContent()) ?? 'NO CERTAINTY LINE')
  await page.screenshot({ path: file('forecast-depends-drawer.png') })
  await page.close()
}

// Drawer with the probability in words (the firm forecast cell, so the picture also shows Firm).
{
  const page = await newPage()
  const dialog = await openDrawer(page, need('FIRM_CELL'), lead)
  console.log('odds:', (await dialog.getByTestId('odds').textContent()) ?? 'NO ODDS LINE')
  await page.screenshot({ path: file('drawer-plain-probability.png') })
  await page.close()
}

// Drawer of a capped cell at lead 0.
{
  const page = await newPage()
  const dialog = await openDrawer(page, need('CAPPED_CELL'), '0')
  console.log('capped:', (await dialog.getByTestId('capped-reason').textContent()) ?? 'NO CAPPED LINE')
  await page.screenshot({ path: file('drawer-capped-reason.png') })
  await page.close()
}

await browser.close()
