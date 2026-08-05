// ============================================================================
// MatchList – FlashScore-style grouped list of match rows
// ============================================================================
'use client'

import { MatchRow, MatchRowSkeleton } from './MatchRow'
import { LeagueGroup } from './LeagueGroup'
import { EmptyState } from '@/components/shared/EmptyState'
import type { Match, LiveScore } from '@/lib/types'
import { useFilterStore } from '@/store/filterStore'
import { useBasketStore } from '@/store/basketStore'
import { usePreferences } from '@/hooks/usePreferences'
import { groupMatchesByLeague, sortLeagueGroups } from '@/lib/utils'

interface Props {
  matches: Match[]
  liveScores?: LiveScore[]
  isLoading?: boolean
  onSelect?: (match: Match) => void
}

function applyLocalFilters(matches: Match[], filters: ReturnType<typeof useFilterStore.getState>): Match[] {
  let result = matches

  // Gemini recommendation filter
  if (filters.geminiRecommendation && filters.geminiRecommendation !== 'all') {
    result = result.filter((m) => m.gemini?.recommendation === filters.geminiRecommendation)
  }

  if (filters.minConfidence > 0) {
    result = result.filter((m) => (m.gemini?.confidence ?? m.confidence ?? m.forebet?.probability ?? 0) >= filters.minConfidence)
  }
  if (filters.league) {
    result = result.filter((m) => m.league === filters.league)
  }
  if (filters.hasOdds) {
    result = result.filter((m) => m.odds?.home != null)
  }
  if (filters.hasPredictions) {
    result = result.filter((m) => m.forebet?.prediction != null || m.sofascore?.home != null)
  }
  if (filters.hasSofascore) {
    result = result.filter((m) => m.sofascore?.home != null)
  }
  if (filters.search) {
    const q = filters.search.toLowerCase()
    result = result.filter(
      (m) =>
        m.homeTeam.toLowerCase().includes(q) ||
        m.awayTeam.toLowerCase().includes(q) ||
        (m.league?.toLowerCase().includes(q) ?? false),
    )
  }

  // Sort – HIGH recommendations first, then by selected sort
  const recOrder: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }
  result.sort((a, b) => {
    // Recommendation priority first
    const recA = recOrder[a.gemini?.recommendation ?? ''] ?? 3
    const recB = recOrder[b.gemini?.recommendation ?? ''] ?? 3
    if (recA !== recB) return recA - recB

    let cmp = 0
    const confA = a.gemini?.confidence ?? a.confidence ?? a.forebet?.probability ?? 0
    const confB = b.gemini?.confidence ?? b.confidence ?? b.forebet?.probability ?? 0
    if (filters.sortBy === 'confidence') cmp = confB - confA
    else if (filters.sortBy === 'sport') cmp = a.sport.localeCompare(b.sport)
    else cmp = (a.time ?? '').localeCompare(b.time ?? '')
    return filters.sortOrder === 'desc' ? -cmp : cmp
  })

  return result
}

/**
 * Reorder league groups so followed ones come first, keeping the existing order
 * inside each tier. A followed league outranks a merely followed sport.
 */
function promoteFollowed(
  groups: [string, Match[]][],
  sports: string[],
  leagues: string[],
): [string, Match[]][] {
  if (sports.length === 0 && leagues.length === 0) return groups

  const followedSports = new Set(sports)
  const followedLeagues = new Set(leagues)

  const rank = ([league, groupMatches]: [string, Match[]]): number => {
    if (followedLeagues.has(league)) return 0
    if (groupMatches.some(m => followedSports.has(m.sport))) return 1
    return 2
  }

  // A stable sort keeps live-first and the rest of the existing ordering intact
  // within each tier.
  return groups
    .map((group, index) => ({ group, index, tier: rank(group) }))
    .sort((a, b) => a.tier - b.tier || a.index - b.index)
    .map(entry => entry.group)
}

export function MatchList({ matches, liveScores, isLoading, onSelect }: Props) {
  const filters = useFilterStore()
  const filtered = applyLocalFilters(matches, filters)
  const { sports: followedSports, leagues: followedLeagues } = usePreferences()

  // Subscribing here keeps the odds buttons in sync with the basket without
  // threading callbacks through every caller of MatchList.
  const basketItems = useBasketStore(s => s.items)
  const toggleOutcome = useBasketStore(s => s.toggle)
  const selectedByMatch = new Map<string, string[]>()
  for (const item of basketItems) {
    const existing = selectedByMatch.get(item.matchId)
    if (existing) existing.push(item.outcome)
    else selectedByMatch.set(item.matchId, [item.outcome])
  }

  // Build live score lookup by team names
  const liveMap = new Map<string, LiveScore>()
  const liveMatchIds = new Set<string | number>()
  if (liveScores) {
    for (const ls of liveScores) {
      const key = `${ls.homeTeam.toLowerCase()}|${ls.awayTeam.toLowerCase()}`
      liveMap.set(key, ls)
      if (ls.status === 'live' || ls.status === 'halftime') {
        liveMatchIds.add(ls.id)
      }
    }
  }

  function findLiveScore(m: Match): LiveScore | undefined {
    const key = `${m.homeTeam.toLowerCase()}|${m.awayTeam.toLowerCase()}`
    return liveMap.get(key)
  }

  if (isLoading) {
    return (
      <div className="rounded-xl border bg-card overflow-hidden">
        {/* Skeleton league header */}
        <div className="bg-muted/50 px-4 py-2 animate-pulse">
          <div className="h-3.5 w-40 bg-muted rounded" />
        </div>
        {Array.from({ length: 8 }).map((_, i) => (
          <MatchRowSkeleton key={i} />
        ))}
      </div>
    )
  }

  if (filtered.length === 0) {
    return (
      <EmptyState
        title="Brak zdarzeń"
        description="Zmień filtry lub wybierz inny dzień."
      />
    )
  }

  // Group matches by league, then lead with what this reader follows. A
  // newcomer meets 670 events in time order, which says nothing about what is
  // worth their attention; the questionnaire's answers reorder the board rather
  // than filter it, so nothing is hidden.
  const grouped = groupMatchesByLeague(filtered)
  const sortedGroups = promoteFollowed(
    sortLeagueGroups(grouped, liveMatchIds),
    followedSports,
    followedLeagues,
  )

  return (
    <div className="overflow-hidden rounded-md border border-border bg-card">
      {sortedGroups.map(([league, leagueMatches]) => {
        const hasLive = leagueMatches.some(m => {
          const ls = findLiveScore(m)
          return ls?.status === 'live' || ls?.status === 'halftime'
        })

        return (
          <LeagueGroup
            key={league}
            league={league}
            country={leagueMatches[0]?.country}
            sport={leagueMatches[0]?.sport}
            matchCount={leagueMatches.length}
            hasLive={hasLive}
            defaultOpen={true}
          >
            {leagueMatches.map((m) => (
              <MatchRow
                key={m.id}
                match={m}
                liveScore={findLiveScore(m)}
                onSelect={onSelect}
                onPick={toggleOutcome}
                selectedOutcomes={selectedByMatch.get(String(m.id)) ?? []}
              />
            ))}
          </LeagueGroup>
        )
      })}
    </div>
  )
}
