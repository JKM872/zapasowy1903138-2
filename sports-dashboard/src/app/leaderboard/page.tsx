// ============================================================================
// Leaderboard Page – Prediction source performance ranking
// ============================================================================
'use client'

import { Trophy, Medal, Target, Brain, BarChart3, TrendingUp, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { getSportConfig } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { useStats, useBetStats } from '@/hooks/useMatches'

function getRankIcon(rank: number) {
  if (rank === 1) return <Trophy className="h-5 w-5 text-yellow-500" />
  if (rank === 2) return <Medal className="h-5 w-5 text-gray-400" />
  if (rank === 3) return <Medal className="h-5 w-5 text-amber-700" />
  return <span className="text-sm font-mono text-muted-foreground w-5 text-center">{rank}</span>
}

interface SourceEntry {
  rank: number
  name: string
  icon: typeof Target
  color: string
  /** Null when the API does not report coverage for this source. */
  coverage: number | null
  matchesTracked: number | null
  description: string
}

export default function LeaderboardPage() {
  const { data: stats, isLoading: statsLoading } = useStats(30)
  const { data: betStats, isLoading: betsLoading } = useBetStats()

  const isLoading = statsLoading || betsLoading
  const totalMatches = stats?.total_matches ?? 0

  const sources: SourceEntry[] = [
    {
      rank: 1,
      name: 'Forebet AI',
      icon: Target,
      color: 'text-blue-500',
      coverage: totalMatches > 0 ? Math.round(((stats?.matches_with_predictions ?? 0) / totalMatches) * 100) : 0,
      matchesTracked: stats?.matches_with_predictions ?? 0,
      description: 'Przewidywania algorytmiczne z prawdopodobieństwem wyniku',
    },
    {
      rank: 2,
      name: 'SofaScore Votes',
      icon: BarChart3,
      color: 'text-orange-500',
      coverage: totalMatches > 0 ? Math.round(((stats?.matches_with_sofascore ?? 0) / totalMatches) * 100) : 0,
      matchesTracked: stats?.matches_with_sofascore ?? 0,
      description: 'Głosy kibiców z serwisu SofaScore',
    },
    {
      rank: 3,
      name: 'Gemini AI',
      icon: Brain,
      color: 'text-violet-500',
      // The stats endpoint reports no Gemini coverage. This used to reuse the
      // Forebet count, so both sources always showed an identical figure that was
      // never measured. Unknown is reported as unknown.
      coverage: null,
      matchesTracked: null,
      description: 'Pogłębiona analiza Google Gemini z uzasadnieniem',
    },
    {
      rank: 4,
      name: 'Bookmaker Odds',
      icon: TrendingUp,
      color: 'text-emerald-500',
      coverage: totalMatches > 0 ? Math.round(((stats?.matches_with_odds ?? 0) / totalMatches) * 100) : 0,
      matchesTracked: stats?.matches_with_odds ?? 0,
      description: 'Kursy przedmeczowe od bukmacherów, przez FlashScore',
    },
    // Sources without a measured coverage sort last rather than as zero.
  ].sort((a, b) => (b.coverage ?? -1) - (a.coverage ?? -1))
    .map((s, i) => ({ ...s, rank: i + 1 }))

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-3 py-6 sm:px-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Źródła danych</h1>
        <p className="text-muted-foreground mt-1">
          Skąd pochodzą dane i jaka część zdarzeń jest nimi objęta. Podstawa:{' '}
          {totalMatches.toLocaleString('pl-PL')} zdarzeń z ostatnich 30 dni.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {/* Podium – top 3 sources */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {sources.slice(0, 3).map((entry) => {
              const Icon = entry.icon
              return (
                <Card
                  key={entry.name}
                  className={cn(
                    'relative overflow-hidden',
                    entry.rank === 1 && 'border-yellow-500/50 bg-yellow-500/5',
                    entry.rank === 2 && 'border-gray-400/50 bg-gray-400/5',
                    entry.rank === 3 && 'border-amber-700/50 bg-amber-700/5',
                  )}
                >
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      {getRankIcon(entry.rank)}
                      <Badge variant="secondary" className="text-xs">
                        {entry.matchesTracked} zdarzeń
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-center gap-3">
                      <div className={cn('rounded-full bg-muted p-2', entry.color)}>
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="font-semibold">{entry.name}</p>
                        <p className="text-xs text-muted-foreground line-clamp-1">{entry.description}</p>
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="text-muted-foreground">Pokrycie</span>
                        <span className="font-mono font-semibold">
                          {entry.coverage != null ? `${entry.coverage}%` : 'brak danych'}
                        </span>
                      </div>
                      <Progress value={entry.coverage ?? 0} className="h-2" />
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>

          {/* Full source table */}
          <Card>
            <CardHeader>
              <CardTitle>Wszystkie źródła</CardTitle>
              <CardDescription>Pokrycie wszystkich śledzonych zdarzeń z ostatnich 30 dni</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {sources.map((entry) => {
                  const Icon = entry.icon
                  return (
                    <div key={entry.name} className="flex items-center gap-4 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors">
                      <div className="w-8 flex justify-center shrink-0">
                        {getRankIcon(entry.rank)}
                      </div>
                      <div className={cn('rounded-full bg-muted p-1.5 shrink-0', entry.color)}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{entry.name}</p>
                        <p className="text-xs text-muted-foreground truncate">{entry.description}</p>
                      </div>
                      <div className="hidden sm:flex items-center gap-2 w-32">
                        <Progress value={entry.coverage ?? 0} className="h-1.5 flex-1" />
                        <span className="w-14 text-right font-mono text-sm">
                          {entry.coverage != null ? `${entry.coverage}%` : '—'}
                        </span>
                      </div>
                      <div className="w-24 text-right">
                        <span className="text-xs text-muted-foreground">
                          {entry.matchesTracked != null
                            ? `${entry.matchesTracked} zdarzeń`
                            : 'brak danych'}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Sport breakdown */}
          {stats?.sport_breakdown && stats.sport_breakdown.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Pokrycie według dyscypliny</CardTitle>
                <CardDescription>Dostępność predykcji w poszczególnych dyscyplinach</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {stats.sport_breakdown.map((sp) => {
                    const pct = sp.total > 0 ? Math.round((sp.with_predictions / sp.total) * 100) : 0
                    return (
                      <div key={sp.sport} className="flex items-center gap-3 rounded-lg border p-3">
                        <SportIcon sport={sp.sport} colored className="h-4 w-4" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium">{getSportConfig(sp.sport).name}</p>
                          <p className="text-xs text-muted-foreground">
                            {sp.total.toLocaleString('pl-PL')} zdarzeń &middot;{' '}
                            {sp.with_predictions.toLocaleString('pl-PL')} z predykcją
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <Progress value={pct} className="h-1.5 w-16" />
                          <span className="w-9 text-right font-mono text-xs tabular-nums">{pct}%</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Your betting stats */}
          {betStats && betStats.total_bets > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Twoje wyniki</CardTitle>
                <CardDescription>Statystyki z zapisanych przez Ciebie typów</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div className="text-center">
                    <p className="text-2xl font-bold">{betStats.total_bets}</p>
                    <p className="text-xs text-muted-foreground">Typy</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-bold text-emerald-500">
                      {betStats.win_rate != null ? `${betStats.win_rate.toFixed(1)}%` : '—'}
                    </p>
                    <p className="text-xs text-muted-foreground">Skuteczność</p>
                  </div>
                  <div className="text-center">
                    <p className={cn('text-2xl font-bold tabular-nums', betStats.total_profit >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                      {betStats.total_profit >= 0 ? '+' : ''}{betStats.total_profit.toFixed(2)}
                    </p>
                    <p className="text-xs text-muted-foreground">Zysk / strata</p>
                  </div>
                  <div className="text-center">
                    <p className={cn('text-2xl font-bold tabular-nums', (betStats.roi ?? 0) >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                      {betStats.roi != null ? `${betStats.roi.toFixed(1)}%` : '—'}
                    </p>
                    <p className="text-xs text-muted-foreground">ROI</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
