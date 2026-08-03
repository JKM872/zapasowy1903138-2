// ============================================================================
// SportIcon – Material Symbols glyph for a sport key
// ============================================================================
import { cn } from '@/lib/utils'
import { getSportConfig } from '@/lib/constants'

interface Props {
  /** Raw sport key from the API. Unknown keys fall back to a generic glyph. */
  sport: string | null | undefined
  className?: string
  /** Apply the sport's accent colour. */
  colored?: boolean
  /**
   * Accessible name. Omit when the sport is already named in adjacent text —
   * the glyph is then decorative and hidden from screen readers.
   */
  label?: string
}

export function SportIcon({ sport, className, colored = false, label }: Props) {
  const cfg = getSportConfig(sport)
  return (
    <span
      className={cn('material-symbol select-none', colored && cfg.color, className)}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    >
      {cfg.glyph}
    </span>
  )
}
