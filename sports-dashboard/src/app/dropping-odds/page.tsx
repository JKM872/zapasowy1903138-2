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

  const { data, isLoading, isError } = useQuery({
    queryKey: ['dropping-odds', date ?? 'latest', sport],
    queryFn: () => getDroppingOdds({ date, sport }),
    staleTime: 60_000,
    // The workflow runs three times a day; this keeps an open tab current
    // without a reload, like the main board.
    refetchInterval: 300_000,
  })

  const events = data?.events ?? []
  const summary = data?.summary
  const sportEntries = Object.entries(data?.sportCounts ?? {})
    .sort((a, b) => b[1] - a[1])

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <TrendingDown className="h-6 w-6 text-primary" />
          Spadki kursów
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Zdarzenia, na których kurs wyraźnie spadł od otwarcia. Spadek oznacza,
          że pieniądze poszły na tę stronę — pokazujemy ruch i to, co o tym
          zdarzeniu już wiemy.
        </p>
      </div>

      {/* The honest caveat, stated before the data rather than under it. */}
      <div className="flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-relaxed text-muted-foreground">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <p>
          <strong className="text-foreground">Nie wiemy, dlaczego kurs spadł.</strong>{' '}
          Powodem bywa kontuzja, skład, pogoda albo duży zakład — nic z tego nie
          znajduje się w naszych danych. Pokazujemy sam ruch i dołączone analizy,
          bez zgadywania przyczyny. Spadek kursu nie jest rekomendacją.
        </p>
      </div>

      {/* What the verdicts rest on, stated once above the list. */}
      {data?.model?.settled ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Przy każdym zdarzeniu podajemy, jak historycznie wypadały podobne ruchy
          (ta sama dyscyplina i strona), na podstawie {data.model.settled.toLocaleString('pl-PL')}{' '}
          rozstrzygniętych spadków
          {data.model.dateRange && <> z okresu {data.model.dateRange.from} – {data.model.dateRange.to}</>}.
          Ocena „zarabiało” wymaga zysku w obu połowach okresu i po obniżeniu kursu o 5%,
          bo realnie łapie się gorszą cenę niż w chwili odczytu. Ogólnie stawianie na stronę,
          na którą spadł kurs, traciło.
        </p>
      ) : null}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={date ?? data?.date ?? ''}
          onValueChange={value => setDate(value)}
        >
          <SelectTrigger className="w-[170px]">
            <SelectValue placeholder="Wybierz dzień" />
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
          Wszystkie
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
          <Stat label="Zdarzenia" value={String(summary.count)} />
          <Stat
            label="Mediana spadku"
            value={summary.medianDrop != null ? `${summary.medianDrop}%` : '—'}
          />
          <Stat
            label="Największy spadek"
            value={summary.maxDrop != null ? `${summary.maxDrop}%` : '—'}
          />
          <Stat
            label="Spadki ≥ 20%"
            value={String(summary.bigMoves ?? 0)}
            hint="tu rozkład się przerzedza"
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
          Nie udało się pobrać spadków kursów.
        </div>
      )}

      {!isLoading && events.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            Brak zdarzeń dla wybranego dnia i dyscypliny.
          </CardContent>
        </Card>
      )}

      {events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Lista spadków</CardTitle>
            <CardDescription>
              Największy ruch na górze. Dane z trzech przebiegów dziennie —
              pokazujemy najświeższy odczyt każdego zdarzenia.
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
  warto: { label: 'Historycznie zarabiało', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500' },
  nie_warto: { label: 'Historycznie traciło', cls: 'border-rose-500/40 bg-rose-500/10 text-rose-500' },
  za_malo_danych: { label: 'Za mało danych', cls: 'border-border bg-muted text-muted-foreground' },
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
          {v.n} podobnych ruchów
          {v.hitRate != null && <> · trafność {v.hitRate}%</>}
          {v.roiRealistic != null && (
            <> · ROI po realnym kursie{' '}
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
              <span className="text-muted-foreground">Forma</span>
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
              {e.h2hCount > 0 && <span className="opacity-70"> z {e.h2hCount}</span>}
              {e.h2hWinRate != null && (
                <span className="opacity-70">
                  {' '}· faworyt {(e.h2hWinRate * 100).toFixed(0)}%
                </span>
              )}
            </span>
          )}

          {e.lastH2hScore && (
            <span className="text-muted-foreground">
              Ostatni: <span className="font-semibold text-foreground">{e.lastH2hScore}</span>
              {e.lastH2hDate && <span className="opacity-70"> ({e.lastH2hDate})</span>}
            </span>
          )}

          {e.advancedScore != null && (
            <span className="text-muted-foreground">
              Ocena modelu{' '}
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
              przewaga formy
            </Badge>
          )}
        </div>
      )}

      {!hasAnalysis && (
        <p className="mt-1.5 text-[10px] text-muted-foreground">
          Brak dołączonej analizy dla tego zdarzenia.
        </p>
      )}
    </div>
  )
}
