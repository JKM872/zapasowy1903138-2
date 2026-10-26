'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getTopPicks, type TopBankroll } from '@/lib/api'

const W = 600
const H = 180

function toPath(vals: number[], min: number, max: number) {
  const span = max - min || 1
  const step = vals.length > 1 ? W / (vals.length - 1) : 0
  return vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(H - ((v - min) / span) * H).toFixed(1)}`)
    .join(' ')
}

/**
 * Simulated bankroll (start 100 units, suggested stake % of the current
 * bankroll) next to the flat 1-unit curve, as an inline SVG – no chart library.
 */
export function BankrollChart({ bankroll }: { bankroll?: TopBankroll | null }) {
  const points = bankroll?.points ?? []
  const start = bankroll?.start ?? 100
  const final = bankroll?.final ?? (points.length ? points[points.length - 1].value : null)
  const values = [start, ...points.map(p => p.value)]
  const flat = [start, ...points.map(p => p.flat)]
  const min = Math.min(...values, ...flat)
  const max = Math.max(...values, ...flat)
  const baseY = H - ((start - min) / (max - min || 1)) * H
  const first = points[0]?.t?.slice(0, 10)
  const last = points[points.length - 1]?.t?.slice(0, 10)
  const change = final != null ? final - start : null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2 text-base">
          <span>Bankroll</span>
          <span className="text-sm font-normal text-muted-foreground tabular-nums">
            {final != null ? (
              <>
                {start} → <b className={cn(
                  change != null && change > 0 && 'text-emerald-600 dark:text-emerald-400',
                  change != null && change < 0 && 'text-red-600 dark:text-red-400',
                )}>{final.toFixed(2)}</b> units
              </>
            ) : '—'}
            {bankroll?.maxDrawdownPct != null && <> · max drawdown {bankroll.maxDrawdownPct.toFixed(1)}%</>}
          </span>
        </CardTitle>
        <CardDescription>
          Start 100 units, each settled pick staked at its suggested % of the current bankroll, in kick-off order.
          Withdrawn and pending picks are skipped.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {points.length === 0 ? (
          <p className="text-sm text-muted-foreground">No settled picks yet.</p>
        ) : (
          <>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              className="h-44 w-full overflow-visible"
              role="img"
              aria-label={`Bankroll from ${start} to ${final?.toFixed(2)} units over ${points.length} settled picks`}
            >
              <title>Bankroll curve</title>
              <line x1="0" x2={W} y1={baseY} y2={baseY} className="stroke-border" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
              <path d={toPath(flat, min, max)} fill="none" className="stroke-muted-foreground/60" strokeWidth="1.5" strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />
              <path d={toPath(values, min, max)} fill="none" className="stroke-primary" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
            </svg>
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span className="tabular-nums">{first}</span>
              <span className="flex items-center gap-3">
                <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-primary" /> Suggested stakes</span>
                <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 border-t border-dashed border-muted-foreground" /> Flat 1 unit</span>
              </span>
              <span className="tabular-nums">{last}</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/** Live max drawdown of the public record, for the "expect losing streaks" section of /how-to-use. */
export function DrawdownNote() {
  const { data } = useQuery({ queryKey: ['top-picks'], queryFn: getTopPicks, staleTime: 60_000 })
  const b = data?.summary.bankroll
  if (!b || b.maxDrawdownPct == null) {
    return <p>Our live record shows its own largest drop on the <Link href="/top">Top Picks</Link> page.</p>
  }
  return (
    <p>
      Our own public record so far: largest drop from a peak <strong>{b.maxDrawdownPct.toFixed(1)}%</strong> of the
      bankroll, over {b.points.length} settled picks (now {b.final?.toFixed(2) ?? '—'} units from a start of {b.start}).
    </p>
  )
}
