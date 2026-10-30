// ============================================================================
// Fan Favourites – SofaScore Fan Vote favourites (football >= 60%, others
// >= 70%, at least 100 votes) whose price passes our standard odds limit.
// Pending picks are returned only to subscribers; settled picks and the
// record (hit rate + flat-stake ROI per sport and per Fan Vote band) are public.
// ============================================================================
'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Crown, ExternalLink, Loader2, Lock, TriangleAlert, Users } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getSportConfig } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatOdds } from '@/lib/format'
import { getFanFavourites, teamHref, type FanPick, type FanRecord } from '@/lib/api'
import { RiskDisclaimer } from '@/components/top/RiskDisclaimer'

const SPORTS = ['football', 'basketball', 'hockey', 'tennis', 'volleyball', 'handball', 'baseball', 'rugby', 'table_tennis']
const BANDS = ['60-70', '70-80', '80-90', '90+']

function pct(v: number | null | undefined, signed = false) {
  if (v === null || v === undefined) return '—'
  return `${signed && v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

function tone(v: number | null | undefined) {
  return cn((v ?? 0) > 0 && 'text-emerald-600 dark:text-emerald-400', (v ?? 0) < 0 && 'text-red-600 dark:text-red-400')
}

function kickoff(p: FanPick) {
  if (!p.kickoff) return p.time ?? ''
  const d = new Date(p.kickoff)
  return d.toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })
}

function Form({ s }: { s?: string }) {
  if (!s) return <span className="text-muted-foreground">—</span>
  return (
    <span className="inline-flex gap-0.5">
      {s.split('').slice(0, 6).map((c, i) => (
        <span key={i} className={cn('inline-flex h-4 w-4 items-center justify-center rounded-sm text-[10px] font-bold text-white',
          c === 'W' ? 'bg-emerald-500' : c === 'L' ? 'bg-red-500' : 'bg-zinc-400')}>{c}</span>
      ))}
    </span>
  )
}

const AVAIL: Record<string, { label: string; cls: string }> = {
  ok: { label: 'Line-up OK', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  warn: { label: 'Absences', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  out: { label: 'Key players out', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  unknown: { label: 'Line-ups unverified', cls: 'bg-muted text-muted-foreground' },
}

function ResultBadge({ p }: { p: FanPick }) {
  const st = p.result?.status
  if (!st) return <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">Pending</span>
  return (
    <span className={cn('rounded px-2 py-0.5 text-xs font-medium', st === 'won'
      ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/15 text-red-600 dark:text-red-400')}>
      {st === 'won' ? 'Won' : p.result?.draw ? 'Draw (lost)' : 'Lost'}{p.result?.score ? ` ${p.result.score}` : ''}
    </span>
  )
}

function LockedCard({ p }: { p: FanPick }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-dashed p-3 text-sm">
      <SportIcon sport={p.sport} className="h-4 w-4" />
      <span className="tabular-nums text-muted-foreground">{kickoff(p)}</span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">{p.league}</span>
      <Badge variant="outline">Fans {p.band}%</Badge>
      <span className="flex items-center gap-1 text-muted-foreground"><Lock className="h-3.5 w-3.5" /> Premium</span>
    </div>
  )
}

function PickCard({ p }: { p: FanPick }) {
  const av = AVAIL[p.availability?.verdict ?? 'unknown'] ?? AVAIL.unknown
  const sideOdds = p.side ? p.odds?.[p.side] : null
  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <SportIcon sport={p.sport} className="h-4 w-4 shrink-0" />
        <span className="tabular-nums text-muted-foreground">{kickoff(p)}</span>
        <span className="min-w-0 flex-1 font-medium">
          {[p.home, p.away].map((name, i) => (
            <span key={i}>
              {i > 0 && <span className="text-muted-foreground"> vs </span>}
              <Link href={teamHref(name ?? '', p.sport)} className={cn('hover:underline', name === p.team && 'text-primary')}>{name}</Link>
            </span>
          ))}
          {p.league && <span className="ml-2 text-xs font-normal text-muted-foreground">{p.league}</span>}
        </span>
        {p.status === 'watch' && <Badge variant="outline" title="No settled record for this sport yet – not staked">Watch only</Badge>}
        <ResultBadge p={p} />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="text-lg font-bold tabular-nums">{p.fanPct?.toFixed(0)}%</span>
        <span>fans back <b>{p.team}</b></span>
        <Badge variant="secondary">{p.band}%</Badge>
        <span className="text-xs text-muted-foreground">{p.votes?.toLocaleString()} votes</span>
        {p.sofascoreUrl && (
          <a href={p.sofascoreUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary">
            SofaScore <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      <div className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="text-muted-foreground">1 / X / 2</div>
          <div className="tabular-nums">
            {p.odds?.home ? formatOdds(p.odds.home) : '—'} / {p.odds?.draw ? formatOdds(p.odds.draw) : '—'} / {p.odds?.away ? formatOdds(p.odds.away) : '—'}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Best price ({p.team})</div>
          <div className="tabular-nums">
            <b>{p.bestPrice?.price ? formatOdds(p.bestPrice.price) : '—'}</b>
            {p.bestPrice?.bookmaker && <span className="text-muted-foreground"> · {p.bestPrice.bookmaker}</span>}
            {p.bestPrice?.pinnacle && p.bestPrice.bookmaker !== 'pinnacle' && <span className="text-muted-foreground"> · Pinnacle {formatOdds(p.bestPrice.pinnacle)}</span>}
            {p.oddsMarket === '2way_equiv' && sideOdds && <span className="text-muted-foreground"> (incl. OT)</span>}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Fans vs implied</div>
          <div className="tabular-nums">{pct(p.fanPct)} vs {pct(p.impliedPct)} · <span className={tone(p.edgePct)}>edge {pct(p.edgePct, true)}</span></div>
        </div>
        <div>
          <div className="text-muted-foreground">Odds limit</div>
          <div className="tabular-nums">≥ {p.limit?.min.toFixed(2)} <span className="text-muted-foreground">({p.limit?.source})</span></div>
        </div>
        <div>
          <div className="text-muted-foreground">Form {p.team} (all / venue)</div>
          <div className="flex gap-2"><Form s={p.form?.overall} /><Form s={p.form?.venue} /></div>
        </div>
        <div>
          <div className="text-muted-foreground">Form opponent (all / venue)</div>
          <div className="flex gap-2"><Form s={p.form?.opponentOverall} /><Form s={p.form?.opponentVenue} /></div>
        </div>
        <div>
          <div className="text-muted-foreground">H2H ({p.team})</div>
          <div className="tabular-nums">{p.h2h ? `${p.h2h.wins}W–${p.h2h.losses}L of ${p.h2h.total}${p.h2h.lastScore ? ` · last ${p.h2h.lastScore}` : ''}` : '—'}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Forebet · model · grade</div>
          <div className="tabular-nums">
            {pct(p.forebet?.prob)} · {p.modelProb != null ? pct(p.modelProb * 100) : '—'} · {p.grade ?? '—'}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={cn('rounded px-2 py-0.5', av.cls)}>{av.label}</span>
        {p.availability?.note && <span className="text-muted-foreground">{p.availability.note}</span>}
      </div>
    </div>
  )
}

function RecordTable({ title, rows }: { title: string; rows: [string, FanRecord | undefined][] }) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent>
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs text-muted-foreground">
            <tr><th className="text-left font-normal" /><th className="text-right font-normal">Settled</th><th className="text-right font-normal">Hit rate</th><th className="text-right font-normal">ROI</th><th className="text-right font-normal">Avg odds</th></tr>
          </thead>
          <tbody>
            {rows.map(([k, r]) => (
              <tr key={k} className="border-t">
                <td className="py-1">{k}</td>
                <td className="text-right">{r ? `${r.won}/${r.n}` : '0'}</td>
                <td className="text-right">{pct(r?.hitPct)}</td>
                <td className={cn('text-right', tone(r?.roiPct))}>{pct(r?.roiPct, true)}</td>
                <td className="text-right">{r?.avgOdds ? formatOdds(r.avgOdds) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

export default function FanFavouritesPage() {
  const [sport, setSport] = useState('football')
  const { data, isLoading, isError } = useQuery({
    queryKey: ['fan-favourites'],
    queryFn: getFanFavourites,
    staleTime: 60_000,
    refetchInterval: 300_000,
  })

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const d of data?.days ?? []) for (const [s, b] of Object.entries(d.sports)) c[s] = (c[s] ?? 0) + b.picks.length
    return c
  }, [data])

  // Teaser like TOP: how many picks today/tomorrow, how many are locked, and
  // the latest settled picks (public) so a visitor never sees an empty page.
  const teaser = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    let total = 0, locked = 0
    const bySport: Record<string, number> = {}
    const settled: FanPick[] = []
    for (const d of data?.days ?? []) {
      for (const [s, b] of Object.entries(d.sports)) {
        if (d.date >= today) {
          total += b.picks.length
          locked += b.locked ?? 0
          if (b.picks.length) bySport[s] = (bySport[s] ?? 0) + b.picks.length
        }
        for (const p of b.picks) if (p.result?.status && !p.locked) settled.push(p)
      }
    }
    return { total, locked, bySport, settled: settled.slice(0, 5) }
  }, [data])

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <Users className="h-6 w-6 text-primary" /> Fan Favourites
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Matches where SofaScore fans clearly back one side (football ≥ 60%, other sports ≥ 70%, at least 100 votes),
          listed only when the price passes our standard odds limit, sorted by Fan Vote. A strong crowd favourite is
          often a short price, so judge the record by ROI, not only by hit rate.
        </p>
      </div>

      <RiskDisclaimer />

      {isLoading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>}
      {isError && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 p-3 text-sm text-red-600" role="alert">
          <TriangleAlert className="h-4 w-4" /> Couldn’t load Fan Favourites.
        </div>
      )}

      {data && (
        <>
          <Card>
            <CardContent className="space-y-3 pt-4 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span>
                  <b className="text-lg">{teaser.total}</b> Fan Favourites today and tomorrow
                  {Object.keys(teaser.bySport).length > 0 && (
                    <span className="text-muted-foreground">
                      {' '}({Object.entries(teaser.bySport).map(([s, n]) => `${getSportConfig(s).name} ${n}`).join(' · ')})
                    </span>
                  )}
                  {!data.isSubscriber && teaser.locked > 0 && <span> · <b>{teaser.locked}</b> locked before kick-off</span>}
                </span>
                {!data.isSubscriber && teaser.locked > 0 && (
                  <Button asChild size="sm"><Link href="/pricing"><Crown className="mr-1.5 h-4 w-4" /> Get Premium</Link></Button>
                )}
              </div>
              {data.historySince && (
                <p className="text-xs text-muted-foreground">
                  History is building up since {data.historySince}: picks become public with full details once they are settled.
                </p>
              )}
              {teaser.settled.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">Latest settled picks</div>
                  {teaser.settled.map(p => <PickCard key={`s-${p.id}`} p={p} />)}
                </div>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            <RecordTable title="Record by sport (flat 1 unit at best price)"
              rows={SPORTS.filter(s => data.record.bySport[s]).map(s => [getSportConfig(s).name, data.record.bySport[s]])} />
            <RecordTable title="Record by Fan Vote band" rows={BANDS.map(b => [`${b}%`, data.record.byBand[b]])} />
          </div>
          <p className="text-xs text-muted-foreground">
            Only staked picks count (not “Watch only” sports without a record yet). A draw on a football pick counts as a loss.
            Overall: {data.record.all.won}/{data.record.all.n} won, ROI {pct(data.record.all.roiPct, true)}.
          </p>

          <div className="flex flex-wrap gap-2" role="tablist">
            {SPORTS.map(s => (
              <Button key={s} role="tab" aria-selected={sport === s} size="sm" variant={sport === s ? 'default' : 'outline'} onClick={() => setSport(s)}>
                <SportIcon sport={s} className="mr-1.5 h-3.5 w-3.5" />
                {getSportConfig(s).name}
                <span className="ml-1.5 text-xs opacity-70">{counts[s] ?? 0}</span>
              </Button>
            ))}
          </div>

          {data.days.map(day => {
            const blk = day.sports[sport]
            if (!blk) return null
            if (blk.picks.length === 0) {
              const st = blk.stats
              if (!st) return null
              return (
                <Card key={day.date}>
                  <CardHeader className="pb-2"><CardTitle className="text-base">{day.date}</CardTitle></CardHeader>
                  <CardContent className="text-sm text-muted-foreground">
                    {st.rows === 0
                      ? 'No match data for this day yet. Fan Favourites appear after the morning scrape (about 05:00–07:00 UTC).'
                      : `No pick passed the filters: ${st.rows} matches, ${st.withVote} with Fan Vote, ${st.fanOk} above the fan threshold, ${st.belowLimit} below the odds limit, ${st.noOdds} without odds.`}
                  </CardContent>
                </Card>
              )
            }
            const open = blk.picks.filter(p => !p.locked)
            const locked = blk.picks.filter(p => p.locked)
            return (
              <Card key={day.date}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex flex-wrap items-baseline justify-between gap-2 text-base">
                    <span>{day.date}</span>
                    <span className="text-sm font-normal text-muted-foreground">
                      {blk.picks.length} picks{blk.watch ? ' · watch only (no record yet)' : ''}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {open.map(p => <PickCard key={p.id} p={p} />)}
                  {locked.map(p => <LockedCard key={p.id} p={p} />)}
                  {locked.length > 0 && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted/50 p-3 text-sm">
                      <span>{locked.length} Fan Favourites before kick-off, available in Premium</span>
                      <Button asChild size="sm"><Link href="/pricing"><Crown className="mr-1.5 h-4 w-4" /> Unlock</Link></Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
          {!data.days.some(d => (d.sports[sport]?.picks.length ?? 0) > 0) && (
            <p className="text-sm text-muted-foreground">No {getSportConfig(sport).name} fan favourites pass the thresholds and odds limit right now.</p>
          )}
        </>
      )}
    </div>
  )
}
