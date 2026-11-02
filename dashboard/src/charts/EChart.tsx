import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import { usePrefersReducedMotion } from '../lib/motion'
import { aetherguardTheme, THEME_NAME } from './theme'

echarts.use([
  BarChart,
  LineChart,
  ScatterChart,
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
])
echarts.registerTheme(THEME_NAME, aetherguardTheme)

export type ChartOption = echarts.EChartsCoreOption

interface EChartProps {
  option: ChartOption
  /** Pixel height; the chart fills the width of its container. */
  height: number
  /** Text alternative: a canvas chart is invisible to assistive technology. */
  label: string
}

/** An ECharts canvas in the AetherGuard theme that follows its container's width and honours reduced motion. */
export default function EChart({ option, height, label }: EChartProps) {
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const reduced = usePrefersReducedMotion()

  useEffect(() => {
    const el = host.current
    if (!el) return
    const instance = echarts.init(el, THEME_NAME, { renderer: 'canvas' })
    chart.current = instance
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(el)
    return () => {
      observer.disconnect()
      instance.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption({ ...option, animation: !reduced }, { notMerge: true })
  }, [option, reduced])

  return <div ref={host} role="img" aria-label={label} style={{ width: '100%', height }} />
}
