import type { SVGProps } from 'react'

/** One stroke style for every icon: 24 grid, 1.75 stroke, round caps and joins, no fills. */
function Icon({ children, size = 22, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

type IconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & { size?: number }

/** Ridge line with a contour beneath it: the live terrain map. */
export function MapIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 16.5 9 6l4 6.5 2.5-3.5L21 16.5" />
      <path d="M3 20.5c3-1.6 5.5-1.6 9 0s6 1.6 9 0" />
    </Icon>
  )
}

/** Warning triangle: alerts. */
export function AlertIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12 3.5 21.5 19.5h-19z" />
      <path d="M12 10v4.5" />
      <path d="M12 17.2v.1" />
    </Icon>
  )
}

/** A gauge reporting over the air: sensors and data sources. */
export function SensorIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="14" r="2" />
      <path d="M7.8 9.8a6 6 0 0 1 8.4 0" />
      <path d="M4.9 6.9a10 10 0 0 1 14.2 0" />
      <path d="M12 16v4.5" />
    </Icon>
  )
}

/** Peak outline for empty states. */
export function PeakIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2.5 19.5 9.5 7l3.5 6 2-3 6.5 9.5z" />
      <path d="M9.5 7l1.8 3.2" />
    </Icon>
  )
}
