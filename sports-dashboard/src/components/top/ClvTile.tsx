import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { TopClv } from '@/lib/api'

function signed(v: number) {
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

/**
 * Closing line value tile: average CLV vs the Pinnacle closing price, share of
 * picks that beat the close, and the sample size. OddsSafari closes are shown
 * separately because they are not a sharp closing line.
 */
export function ClvTile({ clv }: { clv?: TopClv | null }) {
  const n = clv?.n ?? 0
  const avg = clv?.avgPct
  const nOs = clv?.nOddsSafari ?? 0
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground" title="Closing line value: how our published price compares with the price just before kick-off. Beating the close regularly is the best sign of a real edge.">
          Closing line value
        </div>
        {n > 0 && typeof avg === 'number' ? (
          <>
            <div className={cn(
              'mt-1 text-xl font-bold tabular-nums',
              avg > 0 && 'text-emerald-600 dark:text-emerald-400',
              avg < 0 && 'text-red-600 dark:text-red-400',
            )}>{signed(avg)}</div>
            <div className="text-[11px] text-muted-foreground">
              {clv?.beatClosePct != null ? `${clv.beatClosePct.toFixed(0)}% beat the close · ` : ''}
              n={n} vs Pinnacle{clv?.since ? ` since ${clv.since}` : ''}
            </div>
          </>
        ) : (
          <>
            <div className="mt-1 text-xl font-bold tabular-nums text-muted-foreground">—</div>
            <div className="text-[11px] text-muted-foreground">No Pinnacle closing prices yet (n=0)</div>
          </>
        )}
        {nOs > 0 && (
          <div className="text-[11px] text-muted-foreground">
            OddsSafari close: {typeof clv?.avgPctOddsSafari === 'number' ? signed(clv.avgPctOddsSafari) : '—'} (n={nOs})
          </div>
        )}
        {(clv?.nApprox ?? 0) > 0 && (
          <div className="text-[11px] text-muted-foreground">{clv?.nApprox} approximate closes</div>
        )}
      </CardContent>
    </Card>
  )
}
