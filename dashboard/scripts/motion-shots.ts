/**
 * Review shots for the type-size pass and the motion pass: story chapters at the new sizes, the press glint caught
 * mid-sweep, and the Sensors view caught while its panels and gauges arrive and once they have settled.
 *
 *   npx vite preview --port 4176 --strictPort &   (API on 127.0.0.1:8790 behind the proxy)
 *   node scripts/motion-shots.ts [baseUrl]
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const base = process.argv[2] ?? 'http://127.0.0.1:4176'
const out = new URL('../review/', import.meta.url)
mkdirSync(out, { recursive: true })
const file = (name: string) => decodeURIComponent(new URL(name, out).pathname).replace(/^\//, '')

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
const page = await context.newPage()
page.on('pageerror', (e) => console.log('[pageerror]', e.message))

await page.goto(`${base}/`, { waitUntil: 'commit' })
await page.getByRole('button', { name: 'Skip intro' }).click({ timeout: 15_000 }).catch(() => {})
await page.waitForTimeout(2500)
await page.screenshot({ path: file('m-story-chart-1440.png') })

for (const id of ['ground', 'rain', 'levels', 'today']) {
  await page.evaluate((s) => document.getElementById(s)?.scrollIntoView({ behavior: 'instant' }), id)
  await page.waitForTimeout(1800)
  await page.screenshot({ path: file(`m-story-${id}-1440.png`) })
}

// The glint, frozen at three points of its sweep on the press of a primary action. A screenshot can take longer than the
// glint itself, and the shell's clean-up timer would drop the attribute (and the pseudo-element) mid-shot, so that one
// timer is held back here; the page is otherwise untouched.
await page.evaluate(() => {
  const real = window.setTimeout.bind(window)
  window.setTimeout = ((fn: TimerHandler, ms?: number, ...rest: unknown[]) =>
    ms === 650 ? 0 : real(fn, ms, ...rest)) as typeof window.setTimeout
})
const action = page.getByRole('link', { name: 'Open the live map' })
const box = await action.boundingBox()
if (box) {
  await page.evaluate((s) => document.getElementById(s)?.scrollIntoView({ behavior: 'instant' }), 'today')
  await page.waitForTimeout(800)
  const b = (await action.boundingBox())!
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2)
  await page.mouse.down()
  // Freeze the sweep at three points so the shot does not depend on screenshot latency.
  for (const ms of [180, 325, 470]) {
    await page.evaluate((at) => {
      for (const anim of document.getAnimations()) {
        if ((anim as CSSAnimation).animationName === 'glint') {
          anim.pause()
          anim.currentTime = at
        }
      }
    }, ms)
    await page.screenshot({ path: file(`m-glint-${ms}.png`), clip: { x: b.x - 40, y: b.y - 30, width: b.width + 80, height: b.height + 60 } })
  }
  await page.mouse.up()
}

// The same sweep on a quiet control: a nav link on the dark bar.
{
  await page.evaluate(() => document.getElementById('chart')?.scrollIntoView({ behavior: 'instant' }))
  const nav = page.getByRole('link', { name: 'Alerts' }).first()
  const n = (await nav.boundingBox())!
  await nav.dispatchEvent('pointerdown')
  await page.evaluate(() => {
    for (const anim of document.getAnimations()) {
      if ((anim as CSSAnimation).animationName === 'glint') {
        anim.pause()
        anim.currentTime = 325
      }
    }
  })
  await page.screenshot({ path: file('m-glint-nav.png'), clip: { x: n.x - 30, y: n.y - 12, width: n.width + 60, height: n.height + 24 } })
}

await page.goto(`${base}/sensors-sources`, { waitUntil: 'commit' })
await page.getByRole('group', { name: /rain gauges coloured by trust/ }).waitFor({ timeout: 60_000 })
// Freeze every entrance animation part-way, then let them run out.
const names = await page.evaluate(() => {
  const found: Record<string, number> = {}
  for (const anim of document.getAnimations()) {
    const name = (anim as CSSAnimation).animationName
    if (!name) continue
    found[name] = (found[name] ?? 0) + 1
    anim.pause()
    anim.currentTime = 420
  }
  return found
})
console.log('sensors animations', JSON.stringify(names))
await page.screenshot({ path: file('m-sensors-arriving.png') })
await page.evaluate(() => document.getAnimations().forEach((a) => a.play()))
await page.waitForTimeout(2200)
await page.screenshot({ path: file('m-sensors-settled.png') })

await browser.close()
console.log('done')
