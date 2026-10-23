// ============================================================================
// Dropping odds – price moves the market made, with the analysis we already had
// ============================================================================
'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, TrendingDown, TriangleAlert } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { getSportConfig, PREDICTION_LABELS } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { FormTimeline } from '@/components/charts/FormTimeline'
import { formatOdds } from '@/lib/format'
import { getDroppingOdds, type DroppingOddsEvent, type DropVerdict } from '@/lib/api'

export default function DroppingOddsPage() {
  const [date, setDate] = useState<string | undefined>()
  const [sport, setSport] = useState('all')
  // Off by default: on a typical day only ~1 in 7 moves sits in a segment that
  // held up, and hiding the rest without being asked would look like missing data.
  const [onlyWorth, setOnlyWorth] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['dropping-odds', date ?? 'latest', sport],
    queryFn: () => getDroppingOdds({ date, sport }),
    staleTime: 60_000,
    // The workflow runs three times a day; this keeps an open tab current
    // without a reload, like the main board.
    refetchInterval: 300_000,
  })

  const allEvents = data?.events ?? []
  const worthCount = allEvents.filter(e => e.verdict?.verdict === 'warto').length
  const events = onlyWorth
    ? allEvents.filter(e => e.verdict?.verdict === 'warto')
    : allEvents
  const summary = data?.summary
  const sportEntries = Object.entries(data?.sportCounts ?? {})
    .sort((a, b) => b[1] - a[1])

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <TrendingDown className="h-6 w-6 text-primary" />
          Dropping Odds
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Events where the odds have dropped sharply since opening. A drop means
          money came in on that side. We show the move and what we already know
          about the event.
        </p>
      </div>

      {/* The honest caveat, stated before the data rather than under it. */}
      <div className="flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-relaxed text-muted-foreground">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <p>
          <strong className="text-foreground">We don’t know why the odds dropped.</strong>{' '}
          It may be an injury, a line-up change, the weather or a big bet. None of
          that is in our data. We show the move and the attached analysis without
          guessing the cause. A drop in odds is not a recommendation.
        </p>
      </div>

      {/* What the verdicts rest on, stated once above the list. */}
      {data?.model?.settled ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          For each event we show how similar moves (same sport and side) have performed
          historically, based on {data.model.settled.toLocaleString('en-GB')}{' '}
          settled drops
          {data.model.dateRange && <> from {data.model.dateRange.from} – {data.model.dateRange.to}</>}.
          A “profitable” rating requires a profit in both halves of the period, even with odds
          cut by 5%, because in practice you get a worse price than at the time of reading.
          Overall, backing the side whose odds dropped has lost money.
        </p>
      ) : null}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={date ?? data?.date ?? ''}
          onValueChange={value => setDate(value)}
        >
          <SelectTrigger className="w-[170px]">
            <SelectValue placeholder="Select day" />
          </SelectTrigger>
          <SelectContent>
            {(data?.availableDates ?? []).map(d => (
              <SelectItem key={d} value={d}>{d}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <button
          onClick={() => setSport('all')}
          className={cn(
            'rounded-md px-2.5 py-1.5 text-sm transition-colors',
            sport === 'all'
              ? 'bg-primary text-primary-foreground font-semibold'
              : 'text-muted-foreground hover:bg-accent',
          )}
        >
          All
        </button>
        {sportEntries.map(([key, count]) => {
          const cfg = getSportConfig(key)
          const active = sport === key
          return (
            <button
              key={key}
              onClick={() => setSport(key)}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors',
                active
                  ? 'bg-primary text-primary-foreground font-semibold'
                  : 'text-muted-foreground hover:bg-accent',
              )}
            >
              <SportIcon sport={key} className={cn('h-4 w-4', !active && cfg.color)} />
              {cfg.name}
              <span className="text-[10px] tabular-nums opacity-70">{count}</span>
            </button>
          )
        })}
      </div>

      {/* Headline numbers */}
      {summary && summary.count > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Events" value={String(summary.count)} />
          <Stat
            label="Median drop"
            value={summary.medianDrop != null ? `${summary.medianDrop}%` : '—'}
          />
          <Stat
            label="Largest drop"
            value={summary.maxDrop != null ? `${summary.maxDrop}%` : '—'}
          />
          <Stat
            label="Drops ≥ 20%"
            value={String(summary.bigMoves ?? 0)}
            hint="where the data thins out"
          />
        </div>
      )}

      {isLoading && (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {isError && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn’t load dropping odds.
        </div>
      )}

      {/* Filter by verdict. The count is shown up front so the reader knows
          what the toggle will leave before pressing it. */}
      {allEvents.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setOnlyWorth(false)}
            aria-pressed={!onlyWorth}
            className={cn(
              'rounded-md border px-3 py-1.5 text-sm transition-colors',
              !onlyWorth
                ? 'border-primary bg-primary text-primary-foreground font-semibold'
                : 'border-border text-muted-foreground hover:bg-accent',
            )}
          >
            All drops
            <span className="ml-1.5 text-[10px] tabular-nums opacity-70">{allEvents.length}</span>
          </button>
          <button
            onClick={() => setOnlyWorth(true)}
            aria-pressed={onlyWorth}
            disabled={worthCount === 0}
            className={cn(
              'rounded-md border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              onlyWorth
                ? 'border-emerald-500 bg-emerald-500 text-white font-semibold'
                : 'border-emerald-500/40 text-emerald-500 hover:bg-emerald-500/10',
            )}
          >
            Historically profitable only
            <span className="ml-1.5 text-[10px] tabular-nums opacity-80">{worthCount}</span>
          </button>
        </div>
      )}

      {!isLoading && events.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            {onlyWorth
              ? 'No drop today falls into a historically profitable segment. That is a common, honest result. Not every day has an edge.'
              : 'No events for the selected day and sport.'}
          </CardContent>
        </Card>
      )}

      {events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              {onlyWorth ? 'Drops in profitable segments' : 'All drops'}
            </CardTitle>
            <CardDescription>
              {onlyWorth
                ? 'History, not a guarantee. Each event shows how many moves the rating is based on.'
                : 'Largest move first. Data from three runs a day; we show the latest reading for each event.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {events.map(e => (
              <DropRow key={`${e.matchId}-${e.outcome}`} event={e} />
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border bg-panel p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-2xl font-bold tabular-nums">{value}</p>
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

const VERDICT_STYLE: Record<DropVerdict['verdict'], { label: string; cls: string }> = {
  warto: { label: 'Historically profitable', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500' },
  nie_warto: { label: 'Historically unprofitable', cls: 'border-rose-500/40 bg-rose-500/10 text-rose-500' },
  za_malo_danych: { label: 'Not enough data', cls: 'border-border bg-muted text-muted-foreground' },
}

/**
 * The verdict always travels with the number of settled moves behind it, so a
 * reader can see how much evidence a "zarabiało" actually rests on.
 */
function VerdictLine({ verdict: v }: { verdict: DropVerdict }) {
  const style = VERDICT_STYLE[v.verdict] ?? VERDICT_STYLE.za_malo_danych
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
      <span className={cn('rounded border px-1.5 py-0.5 font-semibold', style.cls)}>
        {style.label}
      </span>
      {v.n != null && v.n > 0 && (
        <span className="text-muted-foreground tabular-nums">
          {v.n} similar moves
          {v.hitRate != null && <> · hit rate {v.hitRate}%</>}
          {v.roiRealistic != null && (
            <> · ROI at realistic odds{' '}
              <span className={cn('font-semibold', v.roiRealistic >= 0 ? 'text-emerald-500' : 'text-rose-500')}>
                {v.roiRealistic > 0 ? '+' : ''}{v.roiRealistic}%
              </span>
            </>
          )}
        </span>
      )}
      {v.reason && <span className="text-muted-foreground/70">({v.reason})</span>}
    </div>
  )
}

function DropRow({ event: e }: { event: DroppingOddsEvent }) {
  const drop = e.dropPct ?? 0
  // 20% is where the archive thins out, so it is the line worth marking.
  const severe = drop >= 20
  const hasAnalysis = e.homeForm.length > 0 || e.h2hCount != null

  return (
    <div className="rounded-md border border-border bg-panel p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SportIcon sport={e.sport} colored className="h-4 w-4" />
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {e.eventTime}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {e.homeTeam} <span className="text-muted-foreground">vs</span> {e.awayTeam}
        </span>

        <Badge
          variant="outline"
          className="shrink-0 border-primary/50 text-[10px] font-semibold text-primary"
        >
          {PREDICTION_LABELS[e.outcome] ?? e.outcome}
        </Badge>

        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
          {formatOdds(e.openOdds)} → <span className="font-bold text-foreground">
            {formatOdds(e.currentOdds)}
          </span>
        </span>

        <Badge
          className={cn(
            'shrink-0 gap-0.5 text-[10px] font-bold tabular-nums',
            severe ? 'bg-rose-500 text-white' : 'bg-amber-500/80 text-white',
          )}
        >
          <TrendingDown className="h-2.5 w-2.5" />
          {drop.toFixed(0)}%
        </Badge>
      </div>

      {e.league && (
        <p className="mt-1 truncate text-[10px] text-muted-foreground">{e.league}</p>
      )}

      {e.verdict && <VerdictLine verdict={e.verdict} />}

      {/* Everything the pipeline already knew about this event. Absent on about
          half the archive, so it is shown only when present. */}
      {hasAnalysis && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/60 pt-2 text-[11px]">
          {e.homeForm.length > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Form</span>
              <FormTimeline form={e.homeForm} teamName={e.homeTeam} maxItems={5} />
              <span className="text-muted-foreground/50">/</span>
              <FormTimeline form={e.awayForm} teamName={e.awayTeam} maxItems={5} />
            </span>
          )}

          {e.h2hCount != null && (
            <span className="text-muted-foreground">
              H2H{' '}
              <span className="font-semibold text-foreground tabular-nums">
                {e.h2hHomeWins ?? 0}–{e.h2hAwayWins ?? 0}
              </span>
              {e.h2hCount > 0 && <span className="opacity-70"> of {e.h2hCount}</span>}
              {e.h2hWinRate != null && (
                <span className="opacity-70">
                  {' '}· favourite {(e.h2hWinRate * 100).toFixed(0)}%
                </span>
              )}
            </span>
          )}

          {e.lastH2hScore && (
            <span className="text-muted-foreground">
              Last: <span className="font-semibold text-foreground">{e.lastH2hScore}</span>
              {e.lastH2hDate && <span className="opacity-70"> ({e.lastH2hDate})</span>}
            </span>
          )}

          {e.advancedScore != null && (
            <span className="text-muted-foreground">
              Model score{' '}
              <span className="font-semibold text-foreground tabular-nums">
                {e.advancedScore.toFixed(0)}/100
              </span>
            </span>
          )}

          {e.forebetPrediction && (
            <span className="text-muted-foreground">
              Forebet <span className="font-semibold text-foreground">
                {e.forebetPrediction}
              </span>
              {e.forebetProbability != null && (
                <span className="opacity-70"> {e.forebetProbability.toFixed(0)}%</span>
              )}
            </span>
          )}

          {e.formAdvantage && (
            <Badge variant="secondary" className="px-1 py-0 text-[9px]">
              form edge
            </Badge>
          )}
        </div>
      )}

      {!hasAnalysis && (
        <p className="mt-1.5 text-[10px] text-muted-foreground">
          No analysis attached to this event.
        </p>
      )}
    </div>
  )
}
