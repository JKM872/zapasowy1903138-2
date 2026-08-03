// ============================================================================
// Home Page – FlashScore-style layout: SportTabs → DateCarousel → Filters → Grouped Matches
// ============================================================================
'use client'

import { useState } from 'react'
import { MatchList } from '@/components/match/MatchList'
import { MatchDetails } from '@/components/match/MatchDetails'
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
      {/* Sport navigation tabs – sticky below header */}
      <SportTabs sportCounts={sportCounts} />

      {/* Date carousel – sticky below sport tabs */}
      <DateCarousel />

      {/* Compact filters bar */}
      <div className="border-b bg-background">
        <div className="mx-auto max-w-5xl px-4 py-2">
          <CompactFilters />
        </div>
      </div>

      {/* Freemium upsell banner (hidden for subscribers) */}
      <PromoBanner />

      {/* Main content */}
      <main className="mx-auto max-w-5xl px-4 py-4">
        {isError && (
          <div className="mb-4 rounded-xl border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            Failed to load matches: {(error as Error)?.message ?? 'Unknown error'}
          </div>
        )}

        <MatchList
          matches={matches}
          liveScores={liveScores ?? []}
          isLoading={isLoading}
          onSelect={setSelectedMatch}
        />
      </main>

      {/* Match Details Dialog */}
      <MatchDetails
        match={selectedMatch}
        open={!!selectedMatch}
        onOpenChange={(open) => !open && setSelectedMatch(null)}
      />
    </>
  )
}
