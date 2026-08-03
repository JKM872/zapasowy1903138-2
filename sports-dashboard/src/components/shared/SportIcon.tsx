// ============================================================================
// SportIcon – Google Material Design icon for a sport key, as inline SVG
// ============================================================================
import { cn } from '@/lib/utils'
import { getSportConfig } from '@/lib/constants'

interface Props {
  /** Raw sport key from the API. Unknown keys fall back to a generic icon. */
  sport: string | null | undefined
  className?: string
  /** Apply the sport's accent colour. */
  colored?: boolean
  /**
   * Accessible name. Omit when the sport is already named in adjacent text —
   * the icon is then decorative and hidden from screen readers.
   */
  label?: string
}

export function SportIcon({ sport, className, colored = false, label }: Props) {
  const { icon: Icon, color } = getSportConfig(sport)
  return (
    <Icon
      className={cn('shrink-0', colored && color, className ?? 'h-4 w-4')}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    />
  )
}
