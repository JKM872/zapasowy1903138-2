import { Ban } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatOdds } from '@/lib/format'
import { topStatus, type TopDay, type TopWithdrawn } from '@/lib/api'

const KIND: Record<string, string> = {
  availability: 'Line-up',
  price: 'Price',
}

/**
 * Every withdrawn pick with its reason. Withdrawn picks are not counted in the
 * record or the bankroll; their selection stays hidden until kick-off.
 */
export function WithdrawnList({ days, totals }: { days: TopDay[]; totals: TopWithdrawn }) {
  const rows = days.flatMap(d => d.picks.filter(p => topStatus(p) === 'withdrawn'))
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Ban className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Withdrawn picks
        </CardTitle>
        <CardDescription>
          {totals.n} withdrawn ({totals.availability} line-up, {totals.price} price) – not counted in the record or the bankroll.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No withdrawn picks.</p>
        ) : (
          <ul className="divide-y text-sm">
            {rows.map((p, i) => (
              <li key={`${p.date}-${p.match}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <SportIcon sport={p.sport} className="h-4 w-4 shrink-0" />
                <span className="w-24 tabular-nums text-muted-foreground">{p.date}</span>
                <span className="min-w-0 flex-1 font-medium">{p.match}</span>
                <span className="text-muted-foreground">
                  {p.selectionLocked || !p.pick
                    ? 'Selection hidden until kick-off'
                    : <>Pick: <b className="text-foreground">{p.pick}</b>{p.odds ? ` @ ${formatOdds(p.odds)}` : ''}</>}
                </span>
                <span className="rounded bg-muted px-2 py-0.5 text-xs">{KIND[p.withdrawKind ?? 'availability'] ?? 'Line-up'}</span>
                <span className="basis-full pl-7 text-xs text-muted-foreground">
                  Reason: {p.withdrawReason ?? p.result?.reason ?? 'not recorded'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
