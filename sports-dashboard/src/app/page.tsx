// ============================================================================
// Home – bookmaker-style event board: sports tree / events / analysis basket
// ============================================================================
'use client'

import { useState } from 'react'
import { MatchList } from '@/components/match/MatchList'
import { MatchDetails } from '@/components/match/MatchDetails'
import { EventsShell } from '@/components/layout/EventsShell'
import { SportTabs } from '@/components/navigation/SportTabs'
import { DateCarousel } from '@/components/navigation/DateCarousel'
import { CompactFilters } from '@/components/filters/CompactFilters'
import { PromoBanner } from '@/components/shared/PromoBanner'
import { useMatches, useLiveScores } from '@/hooks/useMatches'
import type { Match } from '@/lib/types'

export default function HomePage() {
  const { data, isLoading, isError, error } = useMatches()
  const { data: liveScores } = useLiveScores()
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null)

  const matches = data?.data ?? []
  const sportCounts = data?.sportCounts ?? {}

  return (
    <>
      <DateCarousel />

      {/* Sports live in the sidebar on desktop; these tabs cover narrow screens. */}
      <SportTabs sportCounts={sportCounts} className="lg:hidden" />

      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-[1700px] px-2 py-1.5 sm:px-4">
          <CompactFilters />
        </div>
      </div>

      <PromoBanner />

      <EventsShell sportCounts={sportCounts} matches={matches}>
        {isError && (
          <div className="mb-3 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            Nie udało się pobrać zdarzeń: {(error as Error)?.message ?? 'nieznany błąd'}
          </div>
        )}

        <MatchList
          matches={matches}
          liveScores={liveScores ?? []}
          isLoading={isLoading}
          onSelect={setSelectedMatch}
        />
      </EventsShell>

      <MatchDetails
        match={selectedMatch}
        open={!!selectedMatch}
        onOpenChange={(open) => !open && setSelectedMatch(null)}
      />
    </>
  )
}
