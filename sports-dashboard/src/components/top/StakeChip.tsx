import Link from 'next/link'
import { Coins } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Suggested stake as % of bankroll (1–2 %). Links to /how-to-use, which explains
 * the staking rule. Missing stake (very old picks) falls back to the default 1 %.
 */
export function StakeChip({ stakePct, className }: { stakePct?: number | null; className?: string }) {
  const pct = typeof stakePct === 'number' && stakePct > 0 ? stakePct : 1.0
  const example = (pct * 10).toFixed(0) // stake on a 1 000 $/€ bankroll
  return (
    <Link
      href="/how-to-use#stake"
      title={`Suggested stake: ${pct.toFixed(1)}% of your bankroll (${example} $/€ on a 1 000 $/€ bankroll). How we size stakes →`}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20',
        className,
      )}
    >
      <Coins className="h-3 w-3" aria-hidden="true" />
      Stake {pct.toFixed(1)}% of bankroll
    </Link>
  )
}
