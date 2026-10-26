import Link from 'next/link'
import { ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/utils'

/** The one wording of the risk disclaimer (design K8), shared by /top, /how-to-use and the footer. */
export const RISK_DISCLAIMER =
  'Pickly provides statistical analysis, not guarantees. Past results do not predict future results. ' +
  'Bet only what you can afford to lose. 18+.'

/**
 * Risk disclaimer with links to help resources. `compact` is the footer variant
 * (plain text line), the default is a bordered note for content pages.
 */
export function RiskDisclaimer({ compact = false, className }: { compact?: boolean; className?: string }) {
  const links = (
    <>
      {' '}
      <Link href="/how-to-use" className="underline hover:text-foreground">How to use our picks</Link>
      {' · '}
      <Link href="/responsible-gambling" className="underline hover:text-foreground">Get help</Link>
      {' · '}
      <a href="https://www.begambleaware.org/" target="_blank" rel="noopener noreferrer"
        className="underline hover:text-foreground">BeGambleAware</a>
    </>
  )
  if (compact) {
    return (
      <p className={cn('leading-relaxed', className)}>
        <strong className="text-foreground">Risk:</strong> {RISK_DISCLAIMER}{links}
      </p>
    )
  }
  return (
    <aside
      aria-label="Risk disclaimer"
      className={cn(
        'flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-relaxed text-muted-foreground',
        className,
      )}
    >
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden="true" />
      <p>
        <strong className="text-foreground">{RISK_DISCLAIMER}</strong>{links}
      </p>
    </aside>
  )
}
