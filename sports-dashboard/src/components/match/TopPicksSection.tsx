// ============================================================================
// TopPicksSection – Horizontal scroll hero for AI HIGH picks (SofaScore style)
// ============================================================================
'use client'

import { Flame, Sparkles, Zap } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { PREDICTION_COLORS } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatMatchTime, formatOdds } from '@/lib/format'
import { TeamLogo } from '@/components/match/TeamLogo'
import { RadialProgress } from '@/components/charts/RadialProgress'
import type { Match } from '@/lib/types'

interface Props {
  matches: Match[]
  onSelect?: (match: Match) => void
  isLoading?: boolean
}

function TopPickCard({ match, onSelect }: { match: Match; onSelect?: (m: Match) => void }) {
  const geminiConf = match.gemini?.confidence ?? match.forebet?.probability ?? 0

  return (
    <Card
      className={cn(
        'relative overflow-hidden cursor-pointer transition-all duration-200',
        'hover:shadow-2xl hover:-translate-y-1',
        'min-w-[260px] max-w-[300px] shrink-0',
        'border-red-500/20 bg-gradient-to-br from-background via-background to-red-500/5',
      )}
      onClick={() => onSelect?.(match)}
    >
      {/* Accent gradient top */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-red-500 via-orange-500 to-amber-500" />

      <CardContent className="p-3.5 space-y-3">
        {/* Header: sport + time */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <SportIcon sport={match.sport} colored className="text-[14px]" />
            <span className="text-[10px] text-muted-foreground truncate max-w-[120px]">
              {match.league ?? match.sport}
            </span>
          </div>
          <span className="text-[10px] text-muted-foreground tabular-nums">
            {formatMatchTime(match.time)}
          </span>
        </div>

        {/* Teams vs layout */}
        <div className="flex items-center gap-3">
          <div className="flex-1 space-y-2 min-w-0">
            <div className="flex items-center gap-2">
              <TeamLogo name={match.homeTeam} size="sm" badgeUrl={match.homeLogo} />
              <span className="font-bold text-sm truncate">{match.homeTeam}</span>
            </div>
            <div className="flex items-center gap-2">
              <TeamLogo name={match.awayTeam} size="sm" badgeUrl={match.awayLogo} />
              <span className="font-bold text-sm truncate">{match.awayTeam}</span>
            </div>
          </div>
          <RadialProgress value={geminiConf} size={44} strokeWidth={3} color="#ef4444" />
        </div>

        {/* Bottom row: prediction + odds */}
        <div className="flex items-center justify-between pt-1.5 border-t border-border/30">
          <div className="flex items-center gap-1.5">
            {match.forebet?.prediction && (
              <Badge className={cn('text-[9px] px-1 py-0', PREDICTION_COLORS[match.forebet.prediction] ?? '')}>
                {match.forebet.prediction}
              </Badge>
            )}
            {match.forebet?.probability != null && (
              <span className="text-[10px] font-medium">{match.forebet.probability}%</span>
            )}
          </div>
          {match.odds && (
            <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
              {formatOdds(match.odds.home)} / {match.odds.draw != null ? `${formatOdds(match.odds.draw)} / ` : ''}{formatOdds(match.odds.away)}
            </span>
          )}
        </div>

        {/* Gemini reasoning */}
        {match.gemini?.reasoning && (
          <p className="text-[10px] text-muted-foreground line-clamp-2 leading-relaxed">
            {match.gemini.reasoning}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function TopPicksSection({ matches, onSelect, isLoading }: Props) {
  const topPicks = matches
    .filter((m) => m.gemini?.recommendation === 'HIGH')
    .sort((a, b) => (b.gemini?.confidence ?? 0) - (a.gemini?.confidence ?? 0))
    .slice(0, 6)

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Flame className="h-5 w-5 text-red-500" />
          <h2 className="text-lg font-bold">AI Top Picks</h2>
        </div>
        <div className="flex gap-3 overflow-hidden">
          {[1, 2, 3].map((i) => (
            <div key={i} className="min-w-[260px] h-40 rounded-xl animate-pulse bg-muted shrink-0" />
          ))}
        </div>
      </div>
    )
  }

  if (topPicks.length === 0) {
    return (
      <Card className="border-dashed border border-muted-foreground/15 bg-muted/30">
        <CardContent className="flex items-center gap-3 py-5 px-4">
          <Sparkles className="h-6 w-6 text-muted-foreground/40 shrink-0" />
          <div>
            <p className="text-sm font-medium text-muted-foreground">
              No top AI picks available
            </p>
            <p className="text-xs text-muted-foreground/60 mt-0.5">
              Gemini AI highlights the best opportunities when data is ready.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-red-500/10">
            <Zap className="h-4 w-4 text-red-500" />
          </div>
          <h2 className="text-lg font-bold">AI Top Picks</h2>
          <Badge className="bg-red-500 text-white text-[10px] font-bold">{topPicks.length}</Badge>
        </div>
        <span className="text-[11px] text-muted-foreground flex items-center gap-1">
          Powered by Gemini AI
        </span>
      </div>

      {/* Horizontal scroll container */}
      <div className="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-thin scrollbar-track-transparent scrollbar-thumb-muted-foreground/20">
        {topPicks.map((m) => (
          <div key={m.id} className="snap-start">
            <TopPickCard match={m} onSelect={onSelect} />
          </div>
        ))}
      </div>
    </div>
  )
}
