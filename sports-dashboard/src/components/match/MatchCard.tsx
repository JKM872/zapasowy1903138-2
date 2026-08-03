// ============================================================================
// MatchCard – SofaScore-style premium card
// ============================================================================
'use client'

import { Clock, TrendingUp, ChevronRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { PREDICTION_COLORS } from '@/lib/constants'
import { SportIcon } from '@/components/shared/SportIcon'
import { formatMatchTime, formatOdds, formatPct } from '@/lib/format'
import { RecommendationBadge } from './RecommendationBadge'
import { LiveScoreBadge } from './LiveScoreBadge'
import { TeamLogo } from './TeamLogo'
import { AIPredictionBadge } from './AIPredictionPanel'
import { RadialProgress } from '@/components/charts/RadialProgress'
import { FormTimeline } from '@/components/charts/FormTimeline'
import type { Match, LiveScore } from '@/lib/types'

interface Props {
  match: Match
  liveScore?: LiveScore | null
  onSelect?: (match: Match) => void
}

export function MatchCard({ match, liveScore, onSelect }: Props) {
  const conf = match.aiPrediction?.compositeConfidence ?? match.gemini?.confidence ?? match.scoring?.confidence ?? match.confidence ?? match.forebet?.probability ?? 0
  const recommendation = match.gemini?.recommendation
  const isHighPick = recommendation === 'HIGH'
  const isLive = liveScore?.status === 'live' || liveScore?.status === 'halftime'
  const forebetPred = match.forebet?.prediction

  return (
    <Card
      className={cn(
        'group relative overflow-hidden cursor-pointer transition-all duration-200',
        'hover:shadow-xl hover:-translate-y-0.5',
        'border-border/60',
        isHighPick && 'ring-1 ring-red-500/30 shadow-red-500/10 shadow-lg',
        isLive && 'ring-1 ring-emerald-500/40',
        !isHighPick && match.value_bet && 'ring-1 ring-amber-400/30',
      )}
      onClick={() => onSelect?.(match)}
    >
      {/* ── Header bar ── */}
      <div className={cn(
        'flex items-center justify-between px-3.5 py-2 border-b border-border/40',
        'bg-muted/30',
      )}>
        <div className="flex items-center gap-1.5 min-w-0">
          <SportIcon sport={match.sport} colored className="shrink-0 text-[16px]" />
          <span className="text-[11px] text-muted-foreground truncate">
            {match.league ?? match.sport}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <LiveScoreBadge liveScore={liveScore} />
          {match.aiPrediction && <AIPredictionBadge prediction={match.aiPrediction} />}
          <RecommendationBadge recommendation={recommendation} />
          {!liveScore && (
            <span className="flex items-center gap-0.5 text-[11px] text-muted-foreground tabular-nums">
              <Clock className="h-3 w-3" />
              {formatMatchTime(match.time)}
            </span>
          )}
        </div>
      </div>

      {/* ── Teams section ── */}
      <div className="px-3.5 py-3">
        <div className="flex items-center gap-3">
          {/* Left: team logos + names */}
          <div className="flex-1 space-y-2.5 min-w-0">
            {/* Home team */}
            <div className="flex items-center gap-2.5">
              <TeamLogo name={match.homeTeam} size="sm" badgeUrl={match.homeLogo} />
              <span className={cn(
                'font-semibold text-sm leading-tight truncate',
                forebetPred === '1' && 'text-emerald-600 dark:text-emerald-400',
              )}>
                {match.homeTeam}
              </span>
              {forebetPred === '1' && (
                <Badge className={cn('text-[9px] px-1 py-0 shrink-0', PREDICTION_COLORS['1'])}>W</Badge>
              )}
            </div>
            {/* Away team */}
            <div className="flex items-center gap-2.5">
              <TeamLogo name={match.awayTeam} size="sm" badgeUrl={match.awayLogo} />
              <span className={cn(
                'font-semibold text-sm leading-tight truncate',
                forebetPred === '2' && 'text-rose-600 dark:text-rose-400',
              )}>
                {match.awayTeam}
              </span>
              {forebetPred === '2' && (
                <Badge className={cn('text-[9px] px-1 py-0 shrink-0', PREDICTION_COLORS['2'])}>W</Badge>
              )}
            </div>
          </div>

          {/* Right: confidence ring */}
          {conf > 0 && (
            <RadialProgress value={conf} size={48} strokeWidth={3.5} />
          )}
        </div>

        {/* ── Form timeline ── */}
        {(match.homeForm?.length > 0 || match.awayForm?.length > 0) && (
          <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-border/30">
            <FormTimeline form={match.homeForm} teamName={match.homeTeam} maxItems={5} />
            <span className="text-[9px] text-muted-foreground/60 px-1">FORM</span>
            <FormTimeline form={match.awayForm} teamName={match.awayTeam} maxItems={5} />
          </div>
        )}
      </div>

      {/* ── Footer: odds + prediction ── */}
      <div className={cn(
        'flex items-center justify-between px-3.5 py-2 border-t border-border/40',
        'bg-muted/20',
      )}>
        {/* Odds row */}
        {match.odds ? (
          <div className="flex gap-1">
            <span className={cn(
              'inline-flex items-center justify-center rounded px-1.5 py-0.5',
              'bg-muted text-[10px] font-mono font-medium tabular-nums',
              forebetPred === '1' && 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
            )}>
              {formatOdds(match.odds.home)}
            </span>
            {match.odds.draw != null && (
              <span className={cn(
                'inline-flex items-center justify-center rounded px-1.5 py-0.5',
                'bg-muted text-[10px] font-mono font-medium tabular-nums',
                forebetPred === 'X' && 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
              )}>
                {formatOdds(match.odds.draw)}
              </span>
            )}
            <span className={cn(
              'inline-flex items-center justify-center rounded px-1.5 py-0.5',
              'bg-muted text-[10px] font-mono font-medium tabular-nums',
              forebetPred === '2' && 'bg-rose-500/15 text-rose-700 dark:text-rose-400',
            )}>
              {formatOdds(match.odds.away)}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground/50">
            {match.forebet?.prediction ? (
              <>
                <Badge className={cn('text-[9px] px-1 py-0', PREDICTION_COLORS[match.forebet.prediction] ?? 'bg-zinc-500 text-white')}>
                  {match.forebet.prediction}
                </Badge>
                {match.forebet?.probability != null && (
                  <span className="font-medium">{match.forebet.probability}%</span>
                )}
              </>
            ) : match.scoring ? (
              <>
                <Badge variant="outline" className="text-[9px] px-1 py-0 font-bold border-violet-400/50 text-violet-600 dark:text-violet-400">
                  {match.scoring.pick}
                </Badge>
                {match.scoring.prob > 0 && (
                  <span className="font-medium text-violet-500/80">
                    {formatPct(match.scoring.prob)}
                  </span>
                )}
                {match.scoring.ev > 0 && (
                  <span className="text-emerald-600 dark:text-emerald-400">
                    EV+{match.scoring.ev.toFixed(2)}
                  </span>
                )}
              </>
            ) : null}
          </div>
        )}

        <div className="flex items-center gap-1.5">
          {match.value_bet && (
            <Badge variant="secondary" className="gap-0.5 text-amber-600 border-amber-300/50 text-[9px] px-1.5 py-0">
              <TrendingUp className="h-2.5 w-2.5" /> Value
            </Badge>
          )}
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-foreground transition-colors" />
        </div>
      </div>
    </Card>
  )
}
