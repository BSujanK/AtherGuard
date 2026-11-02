/**
 * Captures review screenshots of the built app at 1440x900 with headless Chromium (software GL).
 *
 *   npm run build && npx vite preview --port 4173 &   (API on 127.0.0.1:8790 behind the proxy)
 *   node scripts/screenshots.ts [baseUrl] [section,...]   (sections: landing, shell, map, empty, alerts, final, theme; default all except theme)
 *
 * The map shots pin `?quality=full` so the frame-time watchdog does not strip effects on software GL.
 */
import { mkdirSync } from 'node:fs'
import { chromium, type Page } from 'playwright'

const base = process.argv[2] ?? 'http://127.0.0.1:4173'
const only = process.argv[3]?.split(',')
const want = (section: string) => (only === undefined ? section !== 'theme' : only.includes(section))
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')

const fakeNow = (page: Page) => page.evaluate(() => performance.now())

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})

async function newPage(width = 1440, height = 900) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') console.log(`[browser ${m.type()}]`, m.text())
  })
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))
  return page
}

// Landing: three moments of the intro. Software GL renders a frame in hundreds of ms, so the page
// runs on a fake clock that is advanced explicitly; the sequence then lands on exact timestamps.
if (want('landing')) {
  const page = await newPage()
  page.setDefaultTimeout(240_000)
  await page.clock.install({ time: 0 })
  await page.clock.pauseAt(1000)
  await page.goto(base + '/', { waitUntil: 'commit' })
  // Timers are stalled while paused; nudge by 1 ms so queued zero-delay work (data fetching) runs.
  let t0 = -1
  for (;;) {
    const state = await page.evaluate(() => ({
      landing: document.querySelector('[data-testid="landing"]') !== null,
      terrain: document.querySelector('[data-terrain="loaded"]') !== null,
    }))
    if (state.landing && t0 < 0) t0 = await fakeNow(page)
    if (state.landing && state.terrain) break
    await page.clock.runFor(1)
    await page.waitForTimeout(150)
  }
  const introTime = async () => ((await fakeNow(page)) - t0) / 1000
  const taken: string[] = []
  for (const [target, name] of [
    [0.8, 'landing-0.8s.png'],
    [2.5, 'landing-2.5s.png'],
    [4.0, 'landing-4.0s.png'],
  ] as const) {
    const now = await introTime()
    await page.clock.runFor(Math.max(1, Math.round((target - now) * 1000)))
    await page.screenshot({ path: file(name) })
    taken.push(`${name} (intro t = ${(await introTime()).toFixed(2)} s)`)
  }
  console.log(taken.join('\n'))
  await page.close()
}

// Shell after the intro has been skipped, map view and the other two views.
if (want('shell')) {
  const page = await newPage()
  await page.goto(base + '/', { waitUntil: 'commit' })
  await page.getByRole('button', { name: 'Skip intro' }).click()
  await page.getByRole('list', { name: 'Cells by risk level' }).waitFor({ timeout: 30_000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: file('shell-map.png') })
  await page.getByRole('link', { name: 'Alerts' }).click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: file('shell-alerts.png') })
  await page.getByRole('link', { name: 'Sensors & sources' }).click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: file('shell-sensors.png') })
  await page.close()
}

// Narrow desktop.
if (want('shell')) {
  const page = await newPage(1024, 768)
  await page.goto(base + '/map', { waitUntil: 'commit' })
  await page.getByRole('list', { name: 'Cells by risk level' }).waitFor({ timeout: 30_000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: file('shell-map-1024.png') })
  await page.close()
}

// Fresh install: the API reports no data.
if (want('empty')) {
  const page = await newPage()
  await page.route('**/api/mode', (route) =>
    route.fulfill({ json: { mode: 'none', set: null, latest_date: null, dates: [] } }),
  )
  await page.goto(base + '/map', { waitUntil: 'commit' })
  await page.getByText('No data yet').waitFor({ timeout: 30_000 })
  await page.waitForTimeout(2000)
  await page.screenshot({ path: file('shell-empty.png') })
  await page.close()
}

// Live map (D3). The first load of the terrain and the grid is slow on software GL, hence the long waits.
async function openMap(page: Page, search = '') {
  await page.goto(`${base}/map?quality=full${search}`, { waitUntil: 'commit' })
  await page.getByRole('region', { name: 'Map controls' }).waitFor({ timeout: 60_000 })
  await page.locator('[data-terrain="loaded"]').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(4000)
}

if (want('map')) {
  for (const [width, height, name] of [
    [1440, 900, 'map-1440.png'],
    [1024, 768, 'map-1024.png'],
  ] as const) {
    const page = await newPage(width, height)
    await openMap(page)
    await page.screenshot({ path: file(name) })
    await page.close()
  }

  // Hover: sweep the pointer over the area where the replay cells sit until the card appears.
  {
    const page = await newPage()
    await openMap(page)
    const [x0, y0, x1, y1] = (process.env.HOVER_BOX ?? '462,712,505,758').split(',').map(Number) as [number, number, number, number]
    let found = false
    for (let y = y0; y <= y1 && !found; y += 6) {
      for (let x = x0; x <= x1 && !found; x += 6) {
        await page.mouse.move(x, y)
        await page.waitForTimeout(350)
        found = (await page.getByTestId('hover-card').count()) > 0
      }
    }
    console.log(found ? 'map-hover: card found' : 'map-hover: NO CARD FOUND')
    await page.screenshot({ path: file('map-hover.png') })
    await page.close()
  }

  // Forecast lead: the replay store holds lead 0 only, so D+1 is deep-linked and must fall back with the reason shown.
  {
    const page = await newPage()
    await openMap(page, '&lead=1')
    await page.getByText(/Showing D0/).waitFor({ timeout: 30_000 })
    await page.screenshot({ path: file('map-lead1.png') })
    await page.close()
  }

  // No WebGL: the 2D canvas map with the same controls and data.
  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
    await context.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        return /webgl/i.test(type) ? null : (original as (...a: unknown[]) => unknown).call(this, type, ...rest)
      } as typeof original
      Reflect.deleteProperty(window, 'WebGL2RenderingContext')
      Reflect.deleteProperty(window, 'WebGLRenderingContext')
    })
    const page = await context.newPage()
    page.on('pageerror', (e) => console.log('[pageerror]', e.message))
    await page.goto(`${base}/map`, { waitUntil: 'commit' })
    await page.getByTestId('map-2d').waitFor({ timeout: 60_000 })
    await page.getByRole('list', { name: 'Cells by risk level' }).waitFor({ timeout: 60_000 })
    await page.waitForTimeout(3000)
    await page.screenshot({ path: file('map-2d.png') })
    await context.close()
  }
}

// Alerts and why (D4): the feed at two widths, and the drawer of a Warning/Emergency cell of the Wayanad replay.
async function openAlerts(page: Page, search = '') {
  await page.goto(`${base}/alerts-why${search}`, { waitUntil: 'commit' })
  await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
  await page.getByRole('region', { name: 'Alert feed' }).waitFor({ timeout: 60_000 })
  await page.locator('[data-feed] button[data-index="0"]').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(1500)
}

if (want('alerts')) {
  for (const [width, height, name] of [
    [1440, 900, 'alerts-1440.png'],
    [1024, 768, 'alerts-1024.png'],
  ] as const) {
    const page = await newPage(width, height)
    await openAlerts(page)
    await page.screenshot({ path: file(name) })
    await page.close()
  }

  // Cell 20285122 is the highest-risk Emergency cell of the Wayanad replay on 30 Jul 2024.
  {
    const page = await newPage(1440, 900)
    await openAlerts(page, '?cell=20285122&date=2024-07-30')
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('heading', { name: 'Last 30 days' }).waitFor({ timeout: 60_000 })
    await page.locator('[data-testid="alert-drawer"] canvas[role="img"]').first().waitFor({ timeout: 60_000 })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: file('alerts-drawer.png') })
    // The drawer body scrolls: one more shot at the rain sources, one at the bottom (history, neighbourhood).
    const body = dialog.locator('div').filter({ has: page.locator('section') }).last()
    await dialog.getByRole('heading', { name: 'Rain today, by source' }).scrollIntoViewIfNeeded()
    await page.waitForTimeout(1500)
    await page.screenshot({ path: file('alerts-drawer-sources.png') })
    await body.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    await page.waitForTimeout(1500)
    await page.screenshot({ path: file('alerts-drawer-lower.png') })
    await page.close()
  }
}

// Final review set (D6), as the API serves the built app: map at two widths, alerts and sensors.
if (want('final')) {
  for (const [width, height, name] of [
    [1440, 900, 'final-map-1440.png'],
    [1024, 768, 'final-map-1024.png'],
  ] as const) {
    const page = await newPage(width, height)
    await openMap(page)
    await page.screenshot({ path: file(name) })
    await page.close()
  }
  {
    // Hover over cells held by hysteresis (the Wayanad replay has many): the card must say why the level is above its band.
    const page = await newPage()
    await openMap(page)
    const [x0, y0, x1, y1] = (process.env.HOVER_BOX ?? '462,712,505,758').split(',').map(Number) as [number, number, number, number]
    let reason = ''
    for (let y = y0; y <= y1 && !reason; y += 6) {
      for (let x = x0; x <= x1 && !reason; x += 6) {
        await page.mouse.move(x, y)
        await page.waitForTimeout(350)
        const text = (await page.getByTestId('hover-card').allTextContents())[0] ?? ''
        reason = /Held|Raised/.exec(text)?.[0] ?? ''
      }
    }
    console.log(reason ? `final-map-hover: card with reason (${reason})` : 'final-map-hover: NO REASON LINE FOUND')
    await page.screenshot({ path: file('final-map-hover.png') })
    await page.close()
  }
  {
    const page = await newPage()
    await openAlerts(page)
    await page.screenshot({ path: file('final-alerts-1440.png') })
    await page.close()
  }
  {
    const page = await newPage()
    await page.goto(`${base}/sensors-sources`, { waitUntil: 'commit' })
    await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
    await page.locator('g[data-station]').first().waitFor({ timeout: 60_000 })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: file('final-sensors-1440.png') })
    await page.close()
  }
}

// Theme set (whole-India map and the ink/cyan/royal-blue/lime theme), against the real live data. Needs the live run
// of THEME_DATE (1,818 Warning and 1,446 Emergency cells), which the map shots pin so they stay comparable.
const THEME_DATE = '2026-10-16'
if (want('theme')) {
  // The strongest Emergency cell of the latest live run, from the grid the API serves.
  const topEmergency = async (page: Page): Promise<number> =>
    page.evaluate(async (date) => {
      const g = await (await fetch(`/api/grid?date=${date}&lead=0`)).json()
      const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
      const cells = new Uint32Array(bytes(g.cells).buffer)
      const risk = new Float32Array(bytes(g.risk).buffer)
      const level = bytes(g.level)
      let best = -1
      for (let i = 0; i < g.n; i++) if (level[i] === 3 && (best < 0 || risk[i]! > risk[best]!)) best = i
      return cells[best]!
    }, THEME_DATE)

  {
    const page = await newPage()
    page.setDefaultTimeout(240_000)
    await page.clock.install({ time: 0 })
    await page.clock.pauseAt(1000)
    await page.goto(base + '/', { waitUntil: 'commit' })
    let t0 = -1
    for (;;) {
      const state = await page.evaluate(() => ({
        landing: document.querySelector('[data-testid="landing"]') !== null,
        terrain: document.querySelector('[data-terrain="loaded"]') !== null,
      }))
      if (state.landing && t0 < 0) t0 = await fakeNow(page)
      if (state.landing && state.terrain) break
      await page.clock.runFor(1)
      await page.waitForTimeout(150)
    }
    const now = ((await fakeNow(page)) - t0) / 1000
    await page.clock.runFor(Math.max(1, Math.round((2.5 - now) * 1000)))
    await page.screenshot({ path: file('theme-landing-2.5s.png') })
    await page.close()
  }

  for (const [width, height, name] of [
    [1440, 900, 'theme-map-1440.png'],
    [1024, 768, 'theme-map-1024.png'],
  ] as const) {
    const page = await newPage(width, height)
    await openMap(page, `&date=${THEME_DATE}`)
    await page.screenshot({ path: file(name) })
    await page.close()
  }

  {
    // Zoomed on the Western Ghats Emergency cluster: frame the region, then wheel-zoom toward the point under the cursor.
    const page = await newPage()
    await openMap(page, `&date=${THEME_DATE}`)
    await page.getByLabel('Western Ghats').check()
    await page.waitForTimeout(1500)
    // The Emergency cluster sits low on the framed region: right-drag pans it up to the middle before zooming in.
    const [fromX, fromY, x, y, ticks] = (process.env.GHATS_ZOOM ?? '950,640,640,470,4').split(',').map(Number) as [number, number, number, number, number]
    await page.mouse.move(fromX, fromY)
    await page.mouse.down({ button: 'right' })
    await page.mouse.move((fromX + x) / 2, (fromY + y) / 2, { steps: 5 })
    await page.mouse.move(x, y, { steps: 5 })
    await page.mouse.up({ button: 'right' })
    await page.waitForTimeout(800)
    for (let i = 0; i < ticks; i++) {
      await page.mouse.wheel(0, -240)
      await page.waitForTimeout(400)
    }
    await page.waitForTimeout(2500)
    await page.screenshot({ path: file('theme-map-zoom-ghats.png') })
    await page.close()
  }

  {
    const page = await newPage()
    await openMap(page, `&date=${THEME_DATE}`)
    await page.getByLabel('Watch columns').check()
    await page.waitForTimeout(3000)
    await page.screenshot({ path: file('theme-map-watch-columns.png') })
    await page.close()
  }

  {
    const page = await newPage()
    await openAlerts(page)
    await page.screenshot({ path: file('theme-alerts-1440.png') })
    const cell = await topEmergency(page)
    await openAlerts(page, `?cell=${cell}&date=${THEME_DATE}`)
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('heading', { name: 'Last 30 days' }).waitFor({ timeout: 60_000 })
    await page.locator('[data-testid="alert-drawer"] canvas[role="img"]').first().waitFor({ timeout: 60_000 })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: file('theme-alerts-drawer.png') })
    await page.close()
  }

  {
    const page = await newPage()
    await page.goto(`${base}/sensors-sources`, { waitUntil: 'commit' })
    await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
    await page.locator('g[data-station]').first().waitFor({ timeout: 60_000 })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: file('theme-sensors-1440.png') })
    await page.close()
  }

  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
    await context.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        return /webgl/i.test(type) ? null : (original as (...a: unknown[]) => unknown).call(this, type, ...rest)
      } as typeof original
      Reflect.deleteProperty(window, 'WebGL2RenderingContext')
      Reflect.deleteProperty(window, 'WebGLRenderingContext')
    })
    const page = await context.newPage()
    page.on('pageerror', (e) => console.log('[pageerror]', e.message))
    await page.goto(`${base}/map`, { waitUntil: 'commit' })
    await page.getByTestId('map-2d').waitFor({ timeout: 60_000 })
    await page.getByRole('list', { name: 'Cells by risk level' }).waitFor({ timeout: 60_000 })
    await page.waitForTimeout(3000)
    await page.screenshot({ path: file('theme-map-2d.png') })
    await context.close()
  }
}

await browser.close()
