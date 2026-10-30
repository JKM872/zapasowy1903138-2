// ============================================================================
// Weekend Slip – 2-3 suggested Fri-Sun accumulators (max 3 legs) built from
// TOP picks + Fan Favourites whose price passes our standard odds limit.
// Pending legs are returned only to subscribers; settled legs, finished slips
// and the slip record are public.
// ============================================================================
'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { CalendarDays, CheckCircle2, Circle, Crown, Loader2, Lock, MinusCircle, TriangleAlert, XCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getSportConfig } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatOdds } from '@/lib/format'
import { getWeekendSlip, type WeekendLeg, type WeekendSlip } from '@/lib/api'
import { RiskDisclaimer } from '@/components/top/RiskDisclaimer'

function pct(v: number | null | undefined, signed = false) {
  if (v === null || v === undefined) return '—'
  return `${signed && v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

function kickoff(l: WeekendLeg) {
  if (!l.kickoff) return l.date
  return new Date(l.kickoff).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })
}

const LEG_STATUS = {
  won: { icon: CheckCircle2, label: 'Won', cls: 'text-emerald-600 dark:text-emerald-400' },
  lost: { icon: XCircle, label: 'Lost', cls: 'text-red-600 dark:text-red-400' },
  pending: { icon: Circle, label: 'Pending', cls: 'text-muted-foreground' },
  withdrawn: { icon: MinusCircle, label: 'Withdrawn', cls: 'text-amber-600 dark:text-amber-400' },
} as const

const SLIP_STATUS: Record<WeekendSlip['status'], { label: string; cls: string }> = {
  pending: { label: 'Pending', cls: 'bg-muted text-muted-foreground' },
  adjusted: { label: 'Adjusted', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  won: { label: 'Won', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  lost: { label: 'Lost', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  void: { label: 'Void', cls: 'bg-muted text-muted-foreground' },
}

function LegRow({ l }: { l: WeekendLeg }) {
  const st = LEG_STATUS[l.status] ?? LEG_STATUS.pending
  const Icon = st.icon
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border p-2.5 text-sm', l.status === 'withdrawn' && 'opacity-70')}>
      <Icon className={cn('h-4 w-4 shrink-0', st.cls)} aria-label={st.label} />
      <SportIcon sport={l.sport} className="h-4 w-4 shrink-0" />
      <span className="w-24 shrink-0 tabular-nums text-muted-foreground">{kickoff(l)}</span>
      {l.locked ? (
        <span className="flex flex-1 items-center gap-1 text-muted-foreground">
          <Lock className="h-3.5 w-3.5" /> {getSportConfig(l.sport).name} leg · Premium
          {l.status === 'withdrawn' && l.withdrawnReason && <span className="ml-2 text-amber-600">withdrawn: {l.withdrawnReason}</span>}
        </span>
      ) : (
        <>
          <span className="min-w-0 flex-1">
            <span className={cn(l.status === 'withdrawn' && 'line-through')}>{l.match}</span>
            {l.league && <span className="ml-2 text-xs text-muted-foreground">{l.league}</span>}
            <span className="block text-xs text-muted-foreground">
              Pick <b className="text-foreground">{l.pick}</b>
              {' · '}{l.source === 'top+fan' ? 'TOP + Fan Favourite' : l.source === 'top' ? 'TOP pick' : 'Fan Favourite'}
              {l.fanPct != null && ` · fans ${l.fanPct.toFixed(0)}%`}
              {l.modelProb != null && ` · model ${(l.modelProb * 100).toFixed(0)}%`}
              {` · implied ${pct(l.impliedPct)}`}
              {l.edgePct != null && <span className={cn(l.edgePct > 0 ? 'text-emerald-600' : 'text-red-600')}>{` · edge ${pct(l.edgePct, true)}`}</span>}
              {l.availability && l.availability !== 'unknown' && ` · line-up ${l.availability}`}
              {l.status === 'withdrawn' && l.withdrawnReason && <span className="text-amber-600">{` · withdrawn: ${l.withdrawnReason}`}</span>}
            </span>
          </span>
          <span className="text-right tabular-nums">
            <b>{l.price ? formatOdds(l.price) : '—'}</b>
            {l.bookmaker && <span className="block text-xs text-muted-foreground">{l.bookmaker}</span>}
            {l.limit && <span className="block text-xs text-muted-foreground">limit ≥ {l.limit.min.toFixed(2)} ({l.limit.source})</span>}
          </span>
          <span className={cn('w-20 text-right text-xs font-medium', st.cls)}>{st.label}{l.score ? ` ${l.score}` : ''}</span>
        </>
      )}
    </div>
  )
}

function SlipCard({ s, stakePct }: { s: WeekendSlip; stakePct: number }) {
  const st = SLIP_STATUS[s.status] ?? SLIP_STATUS.pending
  const live = s.legs.filter(l => l.status !== 'withdrawn').length
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            Slip {s.id.replace(/^S/, '')}
            <span className={cn('rounded px-2 py-0.5 text-xs font-medium', st.cls)}>{st.label}</span>
            <span className="text-sm font-normal text-muted-foreground">{live} legs{s.adjusted ? ' (after withdrawal)' : ''}</span>
          </span>
          <span className="flex flex-wrap items-center gap-3 text-sm font-normal tabular-nums">
            <span>Combined odds <b>{s.combinedOdds ? formatOdds(s.combinedOdds) : '—'}</b></span>
            <span className="text-muted-foreground">implied {pct(s.combinedImpliedPct)}</span>
            {s.combinedModelProb != null && (
              <span className="text-muted-foreground" title="Product of leg model probabilities; the model is not calibrated and overstates confidence">
                model {pct(s.combinedModelProb * 100)} (uncalibrated)
              </span>
            )}
            <Badge variant="outline">Stake {stakePct}% bankroll</Badge>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {s.legs.map(l => <LegRow key={l.id} l={l} />)}
      </CardContent>
    </Card>
  )
}

export default function WeekendPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['weekend-slip'],
    queryFn: getWeekendSlip,
    staleTime: 60_000,
    refetchInterval: 300_000,
  })
  const current = data?.weekends.find(w => w.friday === data.current)
  const past = data?.weekends.filter(w => w.friday !== data.current) ?? []
  const locked = current?.slips.reduce((n, s) => n + (s.locked ?? 0), 0) ?? 0
  const r = data?.record

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <CalendarDays className="h-6 w-6 text-primary" /> Weekend Slip
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Up to three Friday–Sunday accumulators of at most {data?.maxLegs ?? 3} legs, combining the weekend’s strongest TOP picks
          and Fan Favourites. Every leg passes our standard odds limit, comes from a different match and league, and is
          re-checked before kick-off: a leg whose key players are out is withdrawn and the slip is shown as adjusted.
        </p>
      </div>

      <div className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <span>{data?.note ?? 'Accumulators multiply the bookmaker margin with every leg and lose more often than singles.'}</span>
      </div>

      <RiskDisclaimer />

      {isLoading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>}
      {isError && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 p-3 text-sm text-red-600" role="alert">
          <TriangleAlert className="h-4 w-4" /> Couldn’t load the Weekend Slip.
        </div>
      )}

      {data && (
        <>
          {current && current.slips.length > 0 && (
            <Card>
              <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-4 text-sm">
                <span>
                  <b className="text-lg">{current.slips.length}</b> slips this weekend
                  {' · '}{current.slips.reduce((n, s) => n + s.legs.length, 0)} legs
                  {(() => {
                    const odds = current.slips.map(s => s.combinedOdds).filter((o): o is number => !!o)
                    return odds.length ? ` · combined odds ${formatOdds(Math.min(...odds))}–${formatOdds(Math.max(...odds))}` : ''
                  })()}
                  {!data.isSubscriber && locked > 0 && <span> · <b>{locked}</b> legs locked until settled</span>}
                </span>
                {!data.isSubscriber && locked > 0 && (
                  <Button asChild size="sm"><Link href="/pricing"><Crown className="mr-1.5 h-4 w-4" /> Get Premium</Link></Button>
                )}
              </CardContent>
            </Card>
          )}
          {(r?.slips ?? 0) === 0 && (
            <p className="text-xs text-muted-foreground">
              The slip record is building up since the first Weekend Slip ({data.weekends.at(-1)?.friday ?? data.current}).
              Legs become public with teams, picks and results as soon as they are settled.
            </p>
          )}
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">Public record of past slips (flat 1 unit on combined odds)</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-x-8 gap-y-2 text-sm tabular-nums">
              <span>Slips won <b>{r?.won ?? 0}/{r?.slips ?? 0}</b></span>
              <span>Hit rate <b>{pct(r?.hitPct)}</b></span>
              <span>ROI <b className={cn((r?.roiPct ?? 0) > 0 ? 'text-emerald-600' : (r?.roiPct ?? 0) < 0 ? 'text-red-600' : '')}>{pct(r?.roiPct, true)}</b></span>
              <span>Legs won <b>{r?.legsWon ?? 0}/{r?.legs ?? 0}</b></span>
              {(r?.void ?? 0) > 0 && <span className="text-muted-foreground">{r?.void} void</span>}
            </CardContent>
          </Card>

          <h2 className="text-lg font-semibold">This weekend{current ? ` · from ${current.friday}` : ''}</h2>
          {current && current.slips.length > 0 ? (
            <>
              {current.slips.map(s => <SlipCard key={s.id} s={s} stakePct={data.stakePct} />)}
              {locked > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted/50 p-3 text-sm">
                  <span>{locked} pending legs are available in Premium; settled legs are public.</span>
                  <Button asChild size="sm"><Link href="/pricing"><Crown className="mr-1.5 h-4 w-4" /> Unlock</Link></Button>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              No slip yet. Slips are built on Friday, Saturday and Sunday mornings when enough legs pass the odds limits.
            </p>
          )}

          {past.length > 0 && <h2 className="text-lg font-semibold">Past weekends</h2>}
          {past.map(w => (
            <div key={w.friday} className="space-y-2">
              <h3 className="text-sm font-medium text-muted-foreground">Weekend from {w.friday}</h3>
              {w.slips.map(s => <SlipCard key={s.id} s={s} stakePct={data.stakePct} />)}
            </div>
          ))}
        </>
      )}
    </div>
  )
}
