// ============================================================================
// Stats Page – analytics & accuracy breakdowns
// ============================================================================
'use client'

import { Loader2 } from 'lucide-react'
import { StatsOverview } from '@/components/stats/StatsOverview'
import { AccuracyChart } from '@/components/stats/AccuracyChart'
import { SportBreakdown } from '@/components/stats/SportBreakdown'
import { useStats } from '@/hooks/useMatches'

export default function StatsPage() {
  const { data, isLoading, isError, error } = useStats()

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-3 py-6 sm:px-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Statystyki</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pokrycie danymi i skuteczność predykcji w podziale na dyscypliny.
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {isError && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Nie udało się pobrać statystyk: {(error as Error)?.message ?? 'nieznany błąd'}
        </div>
      )}

      {data && (
        <>
          <StatsOverview data={data} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <AccuracyChart sportStats={data.sport_breakdown ?? []} />
            <SportBreakdown sportStats={data.sport_breakdown ?? []} />
          </div>
        </>
      )}
    </div>
  )
}
