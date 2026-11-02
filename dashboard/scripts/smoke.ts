/**
 * Browser smoke test of the built dashboard, as the API serves it (headless Chromium, software GL).
 *
 *   npm run smoke -- http://127.0.0.1:8791
 *
 * Loads `/`, skips the intro, and checks that each view shows real data: the map (3D canvas or the 2D fallback) with its
 * status strip and no error state, the alert feed with rows, the sensors map with gauges (or the reason the API gives for having none). Opens one alert drawer.
 * Fails (exit code 1) on any console error, uncaught page error, failed request or 5xx response.
 */
import { chromium, type Page } from 'playwright'

const base = (process.argv[2] ?? 'http://127.0.0.1:8790').replace(/\/$/, '')
const SLOW = 90_000 // software GL draws the first frame slowly

const problems: string[] = []
const checks: string[] = []

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

page.on('console', (message) => {
  if (message.type() === 'error') problems.push(`console error: ${message.text()}`)
})
page.on('pageerror', (error) => problems.push(`uncaught error: ${error.message}`))
page.on('requestfailed', (request) => {
  // The live-update stream is closed by navigation; that is not a failure.
  if (!request.url().includes('/api/stream')) problems.push(`request failed: ${request.url()} (${request.failure()?.errorText})`)
})
page.on('response', (response) => {
  if (response.status() >= 500) problems.push(`HTTP ${response.status()}: ${response.url()}`)
})

async function check(name: string, run: () => Promise<void>) {
  try {
    await run()
    checks.push(`ok    ${name}`)
  } catch (error) {
    const reason = error instanceof Error ? error.message.split('\n')[0] : String(error)
    checks.push(`FAIL  ${name}: ${reason}`)
    problems.push(`${name}: ${reason}`)
  }
}

/** Fails when the view is showing one of the frame's states instead of data (`allowed`: titles that are a true answer). */
async function noErrorState(view: Page, allowed: string[] = []) {
  const titles = (await view.locator('section[role="status"] h2').allTextContents()).filter((t) => !allowed.includes(t))
  if (titles.length > 0) throw new Error(`the view shows "${titles[0]}"`)
}

await check('the app loads at /', async () => {
  const response = await page.goto(`${base}/`, { waitUntil: 'domcontentloaded' })
  if (!response || !response.ok()) throw new Error(`GET / answered ${response?.status()}`)
  if ((await page.title()).trim() === '') throw new Error('the page has no title')
})

await check('the intro can be skipped', async () => {
  const skip = page.getByRole('button', { name: 'Skip intro' })
  if (await skip.isVisible({ timeout: 10_000 }).catch(() => false)) await skip.click()
  await page.getByRole('navigation').first().waitFor({ timeout: SLOW })
})

await check('the status strip says what data is shown', async () => {
  await page.getByRole('list', { name: 'Cells by risk level' }).waitFor({ timeout: SLOW })
  const mode = await page.locator('[data-mode]').first().getAttribute('data-mode')
  if (mode === null || mode === 'none') throw new Error(`data mode is ${mode}`)
})

await check('map: the terrain is drawn (3D canvas or 2D fallback) with data and no error state', async () => {
  await page.getByRole('region', { name: 'Map controls' }).waitFor({ timeout: SLOW })
  await page.locator('[data-terrain="loaded"], [data-testid="map-2d"]').first().waitFor({ timeout: SLOW })
  if ((await page.locator('canvas').count()) === 0) throw new Error('no canvas on the map view')
  await page.getByRole('list', { name: 'Top alerts', includeHidden: true }).waitFor({ state: 'attached', timeout: SLOW })
  await noErrorState(page)
})

await check('alerts: the feed has rows', async () => {
  await page.getByRole('link', { name: 'Alerts' }).click()
  await page.getByRole('region', { name: 'Alert feed' }).waitFor({ timeout: SLOW })
  await page.locator('[data-feed] button[data-index="0"]').waitFor({ timeout: SLOW })
  if ((await page.locator('[data-feed] button[data-index]').count()) === 0) throw new Error('the feed has no rows')
  await noErrorState(page)
})

await check('alerts: an alert opens its drawer with the reasons', async () => {
  await page.locator('[data-feed] button[data-index="0"]').click()
  const drawer = page.getByRole('dialog')
  await drawer.waitFor({ timeout: SLOW })
  if ((await drawer.locator('#drawer-title').textContent())?.trim() === '') throw new Error('the drawer has no title')
  await drawer.getByRole('list', { name: 'Why this level' }).waitFor({ timeout: SLOW })
  await page.getByRole('button', { name: 'Close alert details' }).click()
  await drawer.waitFor({ state: 'hidden', timeout: 10_000 })
})

await check('sensors: the gauge map has gauges (or the API gives a reason) and the source panel answers', async () => {
  await page.getByRole('link', { name: 'Sensors & sources' }).click()
  // Gauges, or the explicit reason the API gives when the date has no gauge table; an empty map or an error state is a failure.
  const gauges = page.locator('g[data-station]').first()
  const reason = page.locator('[data-sensors-reason]')
  await gauges.or(reason).first().waitFor({ timeout: SLOW })
  const explained = (await reason.count()) > 0
  if (!explained && (await page.locator('g[data-station]').count()) === 0) throw new Error('no gauges drawn')
  // A replay set has no live run, so the source panel then says "No live run yet" instead of listing sources.
  const replay = (await page.locator('[data-mode]').first().getAttribute('data-mode')) === 'replay'
  await page.locator(replay ? 'section[role="status"] h2:text("No live run yet")' : 'tr[data-source]').first().waitFor({ timeout: SLOW })
  const allowed = [...(replay ? ['No live run yet'] : []), ...(explained ? ['No gauge readings to show'] : [])]
  await noErrorState(page, allowed)
})

await check('a client route loads directly', async () => {
  const response = await page.goto(`${base}/alerts-why`, { waitUntil: 'domcontentloaded' })
  if (!response || !response.ok()) throw new Error(`GET /alerts-why answered ${response?.status()}`)
  await page.getByRole('region', { name: 'Alert feed' }).waitFor({ timeout: SLOW })
})

await browser.close()

console.log(checks.join('\n'))
if (problems.length > 0) {
  console.log(`\n${problems.length} problem(s):\n${[...new Set(problems)].map((p) => `  ${p}`).join('\n')}`)
  process.exit(1)
}
console.log('\nsmoke test passed')
