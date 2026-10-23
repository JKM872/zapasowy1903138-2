// ============================================================================
// TOP – our best picks with a public, settled track record.
// Settled picks are visible to everyone (the proof); today's open picks are
// returned by the API only to subscribers, everyone else sees a locked count.
// ============================================================================
'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Crown, Loader2, Lock, Star, TriangleAlert } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getSportConfig } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatOdds } from '@/lib/format'
import { getTopPicks, type TopPick, type TopSummary } from '@/lib/api'

function fmtPct(v: number | null | undefined, signed = false) {
  if (v === null || v === undefined) return '—'
  const s = v.toFixed(1)
  return `${signed && v > 0 ? '+' : ''}${s}%`
}

const STATUS: Record<string, { label: string; cls: string }> = {
  won: { label: 'Wygrany', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  lost: { label: 'Przegrany', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  draw: { label: 'Remis (przegrany)', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
}

function StatusBadge({ pick }: { pick: TopPick }) {
  const st = pick.result?.status
  const meta = st ? STATUS[st] : undefined
  if (!meta) {
    return <span className="rounded px-2 py-0.5 text-xs bg-muted text-muted-foreground">Oczekuje</span>
  }
  return <span className={cn('rounded px-2 py-0.5 text-xs font-medium', meta.cls)}>{meta.label}</span>
}

function SummaryTiles({ s }: { s: TopSummary }) {
  const tiles = [
    { label: 'Rozliczone typy', value: `${s.settled} / ${s.picks}` },
    { label: 'Trafność', value: fmtPct(s.hitRate) },
    { label: 'ROI (stawka 1 j.)', value: fmtPct(s.roi, true), tone: s.roi },
    { label: 'Zysk', value: s.profitUnits === null ? '—' : `${s.profitUnits > 0 ? '+' : ''}${s.profitUnits.toFixed(2)} j.`, tone: s.profitUnits },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map(t => (
        <Card key={t.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{t.label}</div>
            <div className={cn(
              'mt-1 text-xl font-bold tabular-nums',
              typeof t.tone === 'number' && t.tone > 0 && 'text-emerald-600 dark:text-emerald-400',
              typeof t.tone === 'number' && t.tone < 0 && 'text-red-600 dark:text-red-400',
            )}>{t.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

export default function TopPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['top-picks'],
    queryFn: getTopPicks,
    staleTime: 60_000,
    refetchInterval: 300_000,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <Star className="h-6 w-6 text-primary" />
          Typy TOP
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Nasze najmocniejsze typy dnia. Każdy rozliczony typ zostaje tu na stałe —
          z wynikiem, kursem i zyskiem — żebyś mógł sam sprawdzić, jak działają.
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie…
        </div>
      )}
      {isError && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 p-3 text-sm text-red-600" role="alert">
          <TriangleAlert className="h-4 w-4" /> Nie udało się pobrać typów TOP.
        </div>
      )}

      {data && (
        <>
          <SummaryTiles s={data.summary} />
          <p className="text-xs text-muted-foreground">
            ROI liczone przy stałej stawce 1 jednostki na typ, po kursie z chwili publikacji.
            Remis przy typie na zwycięzcę liczymy jako przegraną. Mała próba — wyniki z kilku dni mogą się mocno wahać.
          </p>

          {Object.keys(data.bySport).length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Według dyscypliny</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {Object.entries(data.bySport)
                  .sort((a, b) => b[1].picks - a[1].picks)
                  .map(([sport, s]) => (
                    <Badge key={sport} variant="outline" className="gap-1.5 py-1">
                      <SportIcon sport={sport} className="h-3.5 w-3.5" />
                      {getSportConfig(sport).name}: {s.won}/{s.settled}
                      <span className={cn(
                        (s.roi ?? 0) > 0 && 'text-emerald-600 dark:text-emerald-400',
                        (s.roi ?? 0) < 0 && 'text-red-600 dark:text-red-400',
                      )}>{fmtPct(s.roi, true)}</span>
                    </Badge>
                  ))}
              </CardContent>
            </Card>
          )}

          {data.days.map(day => (
            <Card key={day.date}>
              <CardHeader className="pb-2">
                <CardTitle className="flex flex-wrap items-baseline justify-between gap-2 text-base">
                  <span>{day.date}</span>
                  <span className="text-sm font-normal text-muted-foreground">
                    {day.summary.won}/{day.summary.settled} trafionych · ROI {fmtPct(day.summary.roi, true)}
                  </span>
                </CardTitle>
                {day.summary.pending > 0 && (
                  <CardDescription>{day.summary.pending} typów czeka na rozliczenie</CardDescription>
                )}
              </CardHeader>
              <CardContent className="space-y-2">
                {day.picks.length > 0 && (
                  <ul className="divide-y">
                    {day.picks.map((p, i) => (
                      <li key={`${p.match}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                        <SportIcon sport={p.sport} className="h-4 w-4 shrink-0" />
                        <span className="w-12 tabular-nums text-muted-foreground">{p.time ?? ''}</span>
                        <span className="min-w-0 flex-1">
                          <span className="font-medium">{p.match}</span>
                          {p.league && <span className="ml-2 text-xs text-muted-foreground">{p.league}</span>}
                        </span>
                        <span>Typ: <b>{p.pick}</b></span>
                        <span className="tabular-nums">@ {p.odds ? formatOdds(p.odds) : '—'}</span>
                        {p.grade && <Badge variant="secondary">{p.grade}</Badge>}
                        {p.result?.score && <span className="tabular-nums text-muted-foreground">{p.result.score}</span>}
                        <StatusBadge pick={p} />
                      </li>
                    ))}
                  </ul>
                )}
                {day.locked > 0 && (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed p-3">
                    <span className="flex items-center gap-2 text-sm">
                      <Lock className="h-4 w-4 text-muted-foreground" />
                      {day.locked} typów TOP przed meczem — dostępne w Premium
                    </span>
                    <Button asChild size="sm">
                      <Link href="/pricing"><Crown className="mr-1.5 h-4 w-4" /> Odblokuj</Link>
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  )
}
