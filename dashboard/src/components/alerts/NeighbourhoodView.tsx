import { useEffect, useMemo, useRef } from 'react'
import { cellCenter, formatLatLon } from '../../data/summary'
import { type Grid, LEVELS } from '../../data/types'
import { LEVEL_HEX } from '../../scene/levelColors'
import { cellAtPoint, drawNeighbourhood, neighbourhood } from './neighbourhood'
import styles from './NeighbourhoodView.module.css'

/** Canvas side in CSS pixels. */
const SIZE = 260

interface NeighbourhoodViewProps {
  grid: Grid
  centre: number
  onSelect: (cell: number) => void
}

/**
 * The cells around the selected one, coloured by level, on a plain 2D canvas (the map behind the app owns the only
 * WebGL context). Clicking a scored cell opens it; the buttons under the canvas are the keyboard route to the same.
 */
export default function NeighbourhoodView({ grid, centre, onSelect }: NeighbourhoodViewProps) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const model = useMemo(() => neighbourhood(grid, centre), [grid, centre])
  const side = 2 * model.radius + 1

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    const ratio = window.devicePixelRatio || 1
    el.width = SIZE * ratio
    el.height = SIZE * ratio
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    drawNeighbourhood(ctx, model, SIZE)
  }, [model])

  const alerts = model.cells
    .filter((c) => c.level !== null && c.level >= 1 && c.cell !== centre)
    .sort((a, b) => b.level! - a.level! || (b.risk ?? 0) - (a.risk ?? 0))
    .slice(0, 6)

  const onClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const hit = cellAtPoint(model, ((event.clientX - rect.left) / rect.width) * SIZE, ((event.clientY - rect.top) / rect.height) * SIZE, SIZE)
    if (hit && hit.level !== null && hit.cell !== centre) onSelect(hit.cell)
  }

  const counts = [0, 1, 2, 3].map((level) => ({ level, n: model.cells.filter((c) => c.level === level).length }))
  return (
    <div className={styles.view}>
      <canvas
        ref={canvas}
        className={styles.canvas}
        width={SIZE}
        height={SIZE}
        role="img"
        aria-label={`Map of the ${side} by ${side} cells around cell ${centre}, north up: ${model.scored} scored that day, ${model.alerts} at Watch or above. The selected cell is outlined in orange.`}
        onClick={onClick}
      />
      <div className={styles.side}>
        <ul className={styles.legend} aria-label="Level colours">
          {counts.map(({ level, n }) => (
            <li key={level}>
              <i style={{ background: LEVEL_HEX[level] }} aria-hidden="true" />
              {LEVELS[level as 0 | 1 | 2 | 3]} <span className="num">{n}</span>
            </li>
          ))}
          <li>
            <i className={styles.unscored} aria-hidden="true" />
            Not scored <span className="num">{model.cells.length - model.scored}</span>
          </li>
        </ul>
        {alerts.length > 0 ? (
          <>
            <p className={styles.note}>Nearby cells at Watch or above</p>
            <ul className={styles.nearby}>
              {alerts.map((c) => {
                const { lat, lon } = cellCenter(c.cell)
                return (
                  <li key={c.cell}>
                    <button type="button" onClick={() => onSelect(c.cell)}>
                      <i style={{ background: LEVEL_HEX[c.level!] }} aria-hidden="true" />
                      <span>
                        {LEVELS[c.level! as 0 | 1 | 2 | 3]} <span className="num">{formatLatLon(lat, lon)}</span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </>
        ) : (
          <p className={styles.note}>No other cell around this one is at Watch or above.</p>
        )}
      </div>
    </div>
  )
}
