// ============================================================================
// MatchRow – Expanded FlashScore-style row with full AI data
// ============================================================================
'use client'

import Link from 'next/link'
import { Clock, ChevronRight, Gem, BarChart3, Lock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { PREDICTION_COLORS } from '@/lib/constants'
import { formatMatchTime, formatOdds, formatPct } from '@/lib/format'
import { LiveScoreBadge } from './LiveScoreBadge'
import { RecommendationBadge } from './RecommendationBadge'
import { TeamLogo } from './TeamLogo'
import { GradeBadge } from './GradeBadge'
import { RadialProgress } from '@/components/charts/RadialProgress'
import { FormTimeline } from '@/components/charts/FormTimeline'
import type { Match, LiveScore } from '@/lib/types'

interface Props {
  match: Match
  liveScore?: LiveScore | null
  onSelect?: (match: Match) => void
}

/** Calculate data completeness as % (0-100) */
function calcCompleteness(m: Match): number {
  let filled = 0
  const total = 7
  if (m.time) filled++
  if (m.forebet?.prediction) filled++
  if (m.sofascore?.home != null) filled++
  if (m.odds?.home != null) filled++
  if (m.homeForm?.length > 0) filled++
  if (m.h2h && m.h2h.total > 0 && (m.h2h.home > 0 || m.h2h.away > 0)) filled++
  if (m.gemini?.prediction) filled++
  return Math.round((filled / total) * 100)
}

export function MatchRow({ match, liveScore, onSelect }: Props) {
  const conf = match.gemini?.confidence ?? match.scoring?.confidence ?? match.confidence ?? match.forebet?.probability ?? 0
  const isLive = liveScore?.status === 'live' || liveScore?.status === 'halftime'
  const isFinished = liveScore?.status === 'finished'
  const recommendation = match.gemini?.recommendation
  const forebetPred = match.forebet?.prediction
  const completeness = calcCompleteness(match)

  // Derive SofaScore majority prediction
  const sofaH = match.sofascore?.home ?? 0
  const sofaD = match.sofascore?.draw ?? 0
  const sofaA = match.sofascore?.away ?? 0
  const sofaMax = Math.max(sofaH, sofaD, sofaA)
  const sofaPred = sofaMax > 0 ? (sofaMax === sofaH ? '1' : sofaMax === sofaD ? 'X' : '2') : null

  return (
    <div
      onClick={() => onSelect?.(match)}
      className={cn(
        'group flex items-stretch cursor-pointer transition-colors',
        'border-b border-border/40 last:border-b-0',
        'hover:bg-accent/50',
        isLive && 'bg-red-500/5 hover:bg-red-500/10',
        recommendation === 'HIGH' && !isLive && 'bg-amber-500/5',
      )}
    >
      {/* ─── Left: Time / Status column ─── */}
      <div className="flex flex-col items-center justify-center w-[56px] shrink-0 border-r border-border/30 py-2">
        {isLive ? (
          <LiveScoreBadge liveScore={liveScore} className="text-[10px] px-1.5 py-0" />
        ) : isFinished ? (
          <span className="text-[11px] text-muted-foreground font-medium">FT</span>
        ) : (
          <span className="flex flex-col items-center gap-0.5 text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span className="text-[11px] tabular-nums font-medium">
              {formatMatchTime(match.time)}
            </span>
          </span>
        )}
        {/* Recommendation badge below time */}
        {recommendation && recommendation !== 'SKIP' && recommendation !== 'LOW' && (
          <div className="mt-1">
            <RecommendationBadge recommendation={recommendation} size="sm" showLabel={false} />
          </div>
        )}
      </div>

      {/* ─── Center: Teams + Form + Predictions ─── */}
      <div className="flex-1 min-w-0 px-3 py-2 flex flex-col justify-center gap-1.5">
        {/* Teams row */}
        <div className="flex items-start gap-3">
          {/* Team names + logos */}
          <div className="flex-1 min-w-0 space-y-1">
            {/* Home team */}
            <div className="flex items-center gap-2 min-w-0">
              <TeamLogo name={match.homeTeam} size="xs" badgeUrl={match.homeLogo} />
              <span className={cn(
                'text-sm font-medium truncate leading-tight',
                forebetPred === '1' && 'text-emerald-600 dark:text-emerald-400',
                isFinished && liveScore && liveScore.homeScore > liveScore.awayScore && 'font-bold',
              )}>
                {match.homeTeam}
              </span>
              {/* Home form inline */}
              {match.homeForm?.length > 0 && (
                <FormTimeline form={match.homeForm} teamName={match.homeTeam} maxItems={3} className="ml-auto shrink-0" />
              )}
            </div>
            {/* Away team */}
            <div className="flex items-center gap-2 min-w-0">
              <TeamLogo name={match.awayTeam} size="xs" badgeUrl={match.awayLogo} />
              <span className={cn(
                'text-sm font-medium truncate leading-tight',
                forebetPred === '2' && 'text-rose-600 dark:text-rose-400',
                isFinished && liveScore && liveScore.awayScore > liveScore.homeScore && 'font-bold',
              )}>
                {match.awayTeam}
              </span>
              {/* Away form inline */}
              {match.awayForm?.length > 0 && (
                <FormTimeline form={match.awayForm} teamName={match.awayTeam} maxItems={3} className="ml-auto shrink-0" />
              )}
            </div>
          </div>

          {/* Score column (only when live/finished) */}
          {(isLive || isFinished) && liveScore && (
            <div className="flex flex-col items-center w-[36px] shrink-0 gap-1">
              <span className={cn(
                'text-sm font-bold tabular-nums',
                isLive && 'text-red-600',
              )}>
                {liveScore.homeScore}
              </span>
              <span className={cn(
                'text-sm font-bold tabular-nums',
                isLive && 'text-red-600',
              )}>
                {liveScore.awayScore}
              </span>
            </div>
          )}
        </div>

        {/* Predictions + Odds row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Prediction grade */}
          <GradeBadge grade={match.predictionGrade} />

          {/* Premium lock — Grade A masked for non-subscribers */}
          {match.locked && (
            <Link
              href="/pricing"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0 text-[10px] font-semibold text-amber-700 dark:text-amber-400 hover:bg-amber-500/20 transition-colors"
            >
              <Lock className="h-2.5 w-2.5" /> Premium — unlock $5/wk
            </Link>
          )}

          {/* Forebet prediction + all 3 probabilities */}
          {forebetPred && (
            <div className="flex items-center gap-1">
              <Badge className={cn('text-[9px] px-1.5 py-0 font-bold', PREDICTION_COLORS[forebetPred] ?? 'bg-zinc-500 text-white')}>
                {forebetPred}
              </Badge>
              {/* Show all 3 probabilities if available, otherwise just max */}
              {match.forebet?.homeProb != null && match.forebet?.awayProb != null ? (
                <span className="text-[9px] text-muted-foreground tabular-nums font-mono">
                  <span className={cn(forebetPred === '1' && 'text-emerald-600 dark:text-emerald-400 font-semibold')}>
                    {match.forebet.homeProb}
                  </span>
                  {match.forebet.drawProb != null && (
                    <>
                      <span className="text-muted-foreground/40">-</span>
                      <span className={cn(forebetPred === 'X' && 'text-amber-600 dark:text-amber-400 font-semibold')}>
                        {match.forebet.drawProb}
                      </span>
                    </>
                  )}
                  <span className="text-muted-foreground/40">-</span>
                  <span className={cn(forebetPred === '2' && 'text-rose-600 dark:text-rose-400 font-semibold')}>
                    {match.forebet.awayProb}
                  </span>
                  <span className="text-muted-foreground/50">%</span>
                </span>
              ) : match.forebet?.probability != null ? (
                <span className="text-[10px] text-muted-foreground tabular-nums">
                  {match.forebet.probability}%
                </span>
              ) : null}
              <span className="text-[9px] text-muted-foreground/60">FB</span>
            </div>
          )}

          {/* Forebet exact score */}
          {match.forebet?.exactScore && (
            <span className="text-[10px] text-muted-foreground tabular-nums bg-muted rounded px-1 py-0.5">
              {match.forebet.exactScore}
            </span>
          )}

          {/* Forebet Over/Under */}
          {match.forebet?.overUnder && (
            <span className="text-[10px] text-muted-foreground tabular-nums bg-muted rounded px-1 py-0.5">
              {match.forebet.overUnder}
            </span>
          )}

          {/* Forebet BTTS */}
          {match.forebet?.btts && (
            <span className="text-[10px] text-muted-foreground tabular-nums bg-muted rounded px-1 py-0.5">
              BTTS: {match.forebet.btts}
            </span>
          )}

          {/* Separator if both sources present */}
          {forebetPred && sofaPred && (
            <span className="text-muted-foreground/30">│</span>
          )}

          {/* SofaScore prediction */}
          {sofaPred && (
            <div className="flex items-center gap-1">
              <Badge variant="outline" className="text-[9px] px-1.5 py-0 font-bold border-blue-400/50 text-blue-600 dark:text-blue-400">
                {sofaPred}
              </Badge>
              {sofaMax > 0 && (
                <span className="text-[10px] text-blue-500/80 tabular-nums">
                  {sofaMax}%
                </span>
              )}
              <span className="text-[9px] text-muted-foreground/60">SS</span>
            </div>
          )}

          {/* Scoring engine pick (when no forebet/sofascore) */}
          {!forebetPred && !sofaPred && match.scoring && (
            <div className="flex items-center gap-1">
              <Badge variant="outline" className="text-[9px] px-1.5 py-0 font-bold border-violet-400/50 text-violet-600 dark:text-violet-400">
                {match.scoring.pick}
              </Badge>
              {match.scoring.prob > 0 && (
                <span className="text-[10px] text-violet-500/80 tabular-nums">
                  {formatPct(match.scoring.prob)}
                </span>
              )}
              {match.scoring.ev > 0 && (
                <span className="text-[9px] text-emerald-600 dark:text-emerald-400 tabular-nums">
                  EV+{match.scoring.ev.toFixed(2)}
                </span>
              )}
              <span className="text-[9px] text-muted-foreground/60">SE</span>
            </div>
          )}

          {/* Value bet indicator */}
          {match.value_bet && (
            <Badge variant="secondary" className="text-[9px] px-1 py-0 gap-0.5 text-amber-600 dark:text-amber-400 border-amber-400/30">
              <Gem className="h-2.5 w-2.5" /> Value
            </Badge>
          )}

          {/* Data completeness indicator */}
          {completeness < 100 && !forebetPred && !sofaPred && (
            <div className="flex items-center gap-0.5 text-muted-foreground/50" title={`Data completeness: ${completeness}%`}>
              <BarChart3 className="h-3 w-3" />
              <span className="text-[9px] tabular-nums">{completeness}%</span>
            </div>
          )}

          {/* Odds inline (all screen sizes) */}
          {match.odds && (match.odds.home != null || match.odds.away != null) && (
            <div className="flex items-center gap-0.5 ml-auto">
              <span className={cn(
                'inline-flex items-center justify-center rounded px-1 py-0.5',
                'bg-muted text-[10px] font-mono font-medium tabular-nums min-w-[32px]',
                forebetPred === '1' && 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
              )}>
                {formatOdds(match.odds.home)}
              </span>
              {match.odds.draw != null && (
                <span className={cn(
                  'inline-flex items-center justify-center rounded px-1 py-0.5',
                  'bg-muted text-[10px] font-mono font-medium tabular-nums min-w-[32px]',
                  forebetPred === 'X' && 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
                )}>
                  {formatOdds(match.odds.draw)}
                </span>
              )}
              <span className={cn(
                'inline-flex items-center justify-center rounded px-1 py-0.5',
                'bg-muted text-[10px] font-mono font-medium tabular-nums min-w-[32px]',
                forebetPred === '2' && 'bg-rose-500/15 text-rose-700 dark:text-rose-400',
              )}>
                {formatOdds(match.odds.away)}
              </span>
            </div>
          )}
        </div>

        {/* Gemini reasoning (truncated, only if HIGH/MEDIUM) */}
        {match.gemini?.reasoning && (recommendation === 'HIGH' || recommendation === 'MEDIUM') && (
          <p className="text-[10px] text-muted-foreground/70 leading-tight line-clamp-1 italic">
            AI: {match.gemini.reasoning}
          </p>
        )}
      </div>

      {/* ─── Right: Confidence ring + arrow ─── */}
      <div className="flex items-center gap-1 pr-2 shrink-0 border-l border-border/30 pl-2">
        {conf > 0 ? (
          <RadialProgress value={conf} size={38} strokeWidth={3} />
        ) : (
          <div className="w-[38px]" />
        )}
        <ChevronRight className="h-4 w-4 text-muted-foreground/30 group-hover:text-foreground/60 transition-colors shrink-0" />
      </div>
    </div>
  )
}

// ── Skeleton for loading state ──
export function MatchRowSkeleton() {
  return (
    <div className="flex items-stretch border-b border-border/40 animate-pulse">
      <div className="w-[56px] shrink-0 border-r border-border/30 p-2 flex items-center justify-center">
        <div className="h-4 w-8 bg-muted rounded" />
      </div>
      <div className="flex-1 px-3 py-2 space-y-2">
        <div className="space-y-1">
          <div className="h-3.5 w-40 bg-muted rounded" />
          <div className="h-3.5 w-36 bg-muted rounded" />
        </div>
        <div className="flex gap-2">
          <div className="h-4 w-12 bg-muted rounded" />
          <div className="h-4 w-10 bg-muted rounded" />
          <div className="h-4 w-8 bg-muted rounded" />
          <div className="h-4 w-20 bg-muted rounded ml-auto" />
        </div>
      </div>
      <div className="flex items-center pr-2 pl-2 border-l border-border/30">
        <div className="h-[38px] w-[38px] rounded-full bg-muted" />
      </div>
    </div>
  )
}
