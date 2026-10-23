// ============================================================================
// TopHero – the first thing on the board: our settled record, then today's TOP
// picks. Visitors see the proof and a locked teaser; subscribers see the picks.
// ============================================================================
'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, Crown, Lock, Star, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { formatOdds } from '@/lib/format'
import { getSportConfig } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { getTopPicks, type TopPick } from '@/lib/api'

function signed(v: number | null | undefined, suffix = '%') {
  if (v === null || v === undefined) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}${suffix}`
}

function splitMatch(match: string): [string, string] {
  const [h, a] = match.split(/\s+vs\.?\s+/i)
  return [h ?? match, a ?? '']
}

function PickCard({ p }: { p: TopPick }) {
  const [home, away] = splitMatch(p.match)
  const st = p.result?.status
  return (
    <div className="flex min-w-[240px] flex-col gap-2 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <SportIcon sport={p.sport} className="h-3.5 w-3.5" />
          {getSportConfig(p.sport).name}
          {p.league && <span className="truncate">· {p.league}</span>}
        </span>
        <span className="tabular-nums">{p.time ?? ''}</span>
      </div>
      <div className="text-sm font-semibold leading-snug">
        {home} <span className="font-normal text-muted-foreground">–</span> {away}
      </div>
      <div className="mt-auto flex items-center justify-between">
        <span className="text-sm">
          Pick: <b>{p.pick}</b>
        </span>
        <span className="rounded-md bg-primary/15 px-2 py-0.5 text-sm font-bold tabular-nums text-primary">
          {p.odds ? formatOdds(p.odds) : '—'}
        </span>
      </div>
      {st === 'won' && (
        <span className="flex items-center gap-1 text-xs font-medium text-emerald-500">
          <CheckCircle2 className="h-3.5 w-3.5" /> Won {p.result?.score}
        </span>
      )}
      {(st === 'lost' || st === 'draw') && (
        <span className="flex items-center gap-1 text-xs font-medium text-rose-500">
          <XCircle className="h-3.5 w-3.5" /> Lost {p.result?.score}
        </span>
      )}
    </div>
  )
}

export function TopHero() {
  const { data } = useQuery({ queryKey: ['top-picks'], queryFn: getTopPicks, staleTime: 60_000 })
  if (!data) return null

  const s = data.summary
  const today = data.days[0]
  const lockedToday = today?.locked ?? 0
  const openToday = (today?.picks ?? []).filter(p => !p.result?.status)
  // Recent wins are the proof: shown to everyone, newest first.
  const recentWins = data.days
    .flatMap(d => d.picks)
    .filter(p => p.result?.status === 'won')
    .slice(0, 6)

  return (
    <section className="border-b border-border bg-gradient-to-b from-primary/10 via-background to-background">
      <div className="mx-auto max-w-[1700px] space-y-4 px-3 py-5 sm:px-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight sm:text-2xl">
              <Star className="h-5 w-5 text-primary" /> Top Picks
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              The day’s strongest picks. Every settled pick stays public, so you can check for yourself.
            </p>
          </div>
          <dl className="grid grid-cols-3 gap-2 sm:gap-3">
            {[
              { k: 'Hit rate', v: s.hitRate != null ? `${s.hitRate.toFixed(0)}%` : '—', sub: `${s.won}/${s.settled} picks` },
              { k: 'ROI', v: signed(s.roi), sub: '1-unit stake', tone: s.roi },
              { k: 'Profit', v: signed(s.profitUnits, ' u'), sub: 'all time', tone: s.profitUnits },
            ].map(t => (
              <div key={t.k} className="rounded-lg border border-border bg-card px-3 py-2 sm:px-4">
                <dt className="text-[11px] text-muted-foreground">{t.k}</dt>
                <dd className={cn(
                  'text-lg font-bold tabular-nums sm:text-xl',
                  typeof t.tone === 'number' && t.tone > 0 && 'text-emerald-500',
                  typeof t.tone === 'number' && t.tone < 0 && 'text-rose-500',
                )}>{t.v}</dd>
                <dd className="text-[10px] text-muted-foreground">{t.sub}</dd>
              </div>
            ))}
          </dl>
        </div>

        {data.isSubscriber && openToday.length > 0 ? (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {openToday.map((p, i) => <PickCard key={`${p.match}-${i}`} p={p} />)}
          </div>
        ) : lockedToday > 0 ? (
          <div className="flex flex-col items-start justify-between gap-3 rounded-lg border border-primary/40 bg-primary/5 p-4 sm:flex-row sm:items-center">
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-primary/15 p-2"><Lock className="h-5 w-5 text-primary" /></div>
              <div>
                <div className="font-semibold">{lockedToday} Top Picks today before kick-off</div>
                <div className="text-sm text-muted-foreground">Unlock for $5 / €5 per week. Cancel anytime.</div>
              </div>
            </div>
            <Button asChild>
              <Link href="/pricing"><Crown className="mr-1.5 h-4 w-4" /> Get Premium – $5/week</Link>
            </Button>
          </div>
        ) : null}

        {recentWins.length > 0 && (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Recent winners</h2>
              <Link href="/top" className="flex items-center gap-1 text-xs text-primary hover:underline">
                Full history <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-1">
              {recentWins.map((p, i) => <PickCard key={`${p.match}-${i}`} p={p} />)}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
