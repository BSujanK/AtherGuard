import type { ShapFactor } from '../data/types'
import EChart from './EChart'
import { buildShapOption, shapSummary, topFactors } from './shapOption'

/** The inputs that moved a cell's risk most; orange raised it, cyan lowered it. */
export default function ShapBars({ shap }: { shap: readonly ShapFactor[] }) {
  return (
    <EChart
      option={buildShapOption(shap)}
      height={Math.max(120, 40 * topFactors(shap).length + 38)}
      label={`Top inputs behind this risk: ${shapSummary(shap)}`}
    />
  )
}
