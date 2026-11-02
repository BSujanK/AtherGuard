import { LEAD_LABELS } from '../../data/summary'
import styles from './LeadSwitch.module.css'

interface LeadSwitchProps {
  value: number
  /** The leads the run published; the others are shown but cannot be chosen. */
  available: readonly number[]
  onChange: (lead: number) => void
  /** Radio group name, unique per place the switch appears. */
  name: string
}

/** D0, D+1, D+2, D+3 as native radio buttons, so arrow keys and screen readers just work. */
export default function LeadSwitch({ value, available, onChange, name }: LeadSwitchProps) {
  return (
    <fieldset className={styles.switch}>
      <legend className={styles.legend}>Forecast lead</legend>
      {LEAD_LABELS.map((text, lead) => {
        const enabled = available.includes(lead)
        return (
          <label key={text} className={styles.option} title={enabled ? (lead > 0 ? 'Forecast: each cell says whether its level is firm or depends on the rain forecast' : undefined) : `${text} was not published for this date`}>
            <input type="radio" name={name} checked={value === lead} disabled={!enabled} onChange={() => onChange(lead)} />
            <span>{text}</span>
          </label>
        )
      })}
    </fieldset>
  )
}
