// ============================================================================
// MatchRow – compact match row with a deterministic, non-overlapping layout
// ============================================================================
'use client'

import Link from 'next/link'
import { Clock, ChevronRight, Gem, Lock } from 'lucide-react'
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

/**
 * Three fixed odds slots. Rendered at most once per breakpoint so the block has
 * a predictable width and never competes with the market chips for space.
 */
function OddsBlock({
  match,
  pick,
  className,
}: {
  match: Match
  pick: string | null
  className?: string
}) {
  if (!match.odds || (match.odds.home == null && match.odds.away == null)) return null
  const cell = 'inline-flex items-center justify-center rounded bg-muted px-1 py-0.5 text-[10px] font-mono font-medium tabular-nums min-w-[34px]'
  return (
    <div className={cn('flex items-center gap-0.5', className)}>
      <span className={cn(cell, pick === '1' && 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400')}>
        {formatOdds(match.odds.home)}
      </span>
      {match.odds.draw != null && (
        <span className={cn(cell, pick === 'X' && 'bg-amber-500/15 text-amber-700 dark:text-amber-400')}>
          {formatOdds(match.odds.draw)}
        </span>
      )}
      <span className={cn(cell, pick === '2' && 'bg-rose-500/15 text-rose-700 dark:text-rose-400')}>
        {formatOdds(match.odds.away)}
      </span>
    </div>
  )
}

/** A single source's pick: badge + probability + source tag. */
function PickChip({
  pick,
  prob,
  source,
  tone,
  className,
}: {
  pick: string
  prob: string | null
  source: string
  tone: 'forebet' | 'sofascore' | 'engine'
  className?: string
}) {
  const badgeClass =
    tone === 'forebet'
      ? cn('font-bold', PREDICTION_COLORS[pick] ?? 'bg-zinc-500 text-white')
      : tone === 'sofascore'
        ? 'border-blue-400/50 text-blue-600 dark:text-blue-400 font-bold'
        : 'border-violet-400/50 text-violet-600 dark:text-violet-400 font-bold'
  return (
    <div className={cn('flex shrink-0 items-center gap-1', className)}>
      <Badge
        variant={tone === 'forebet' ? 'default' : 'outline'}
        className={cn('px-1.5 py-0 text-[9px]', badgeClass)}
      >
        {pick}
      </Badge>
      {prob && <span className="text-[10px] tabular-nums text-muted-foreground">{prob}</span>}
      <span className="text-[9px] text-muted-foreground/60">{source}</span>
    </div>
  )
}

export function MatchRow({ match, liveScore, onSelect }: Props) {
  const conf =
    match.gemini?.confidence ??
    match.scoring?.confidence ??
    match.confidence ??
    match.forebet?.probability ??
    0
  const isLive = liveScore?.status === 'live' || liveScore?.status === 'halftime'
  const isFinished = liveScore?.status === 'finished'
  const recommendation = match.gemini?.recommendation
  const forebetPred = match.forebet?.prediction

  // SofaScore majority vote
  const sofaH = match.sofascore?.home ?? 0
  const sofaD = match.sofascore?.draw ?? 0
  const sofaA = match.sofascore?.away ?? 0
  const sofaMax = Math.max(sofaH, sofaD, sofaA)
  const sofaPred = sofaMax > 0 ? (sofaMax === sofaH ? '1' : sofaMax === sofaD ? 'X' : '2') : null

  // The pick that drives odds highlighting: our own engine first, then Forebet.
  const highlightPick = match.scoring?.pick ?? forebetPred ?? sofaPred ?? null

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
      {/* ─── Time / status ─── */}
      <div className="flex w-[52px] shrink-0 flex-col items-center justify-center border-r border-border/30 py-2">
        {isLive ? (
          <LiveScoreBadge liveScore={liveScore} className="px-1.5 py-0 text-[10px]" />
        ) : isFinished ? (
          <span className="text-[11px] font-medium text-muted-foreground">FT</span>
        ) : (
          <span className="flex flex-col items-center gap-0.5 text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span className="text-[11px] font-medium tabular-nums">{formatMatchTime(match.time)}</span>
          </span>
        )}
        {recommendation && recommendation !== 'SKIP' && recommendation !== 'LOW' && (
          <div className="mt-1">
            <RecommendationBadge recommendation={recommendation} size="sm" showLabel={false} />
          </div>
        )}
      </div>

      {/* ─── Teams + markets ─── */}
      <div className="flex min-w-0 flex-1 flex-col justify-center gap-1.5 px-2 py-2 sm:px-3">
        {/* Teams: each side gets dedicated tracks so names truncate instead of
            colliding with the form timeline. */}
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1 space-y-1">
            {(['home', 'away'] as const).map(side => {
              const name = side === 'home' ? match.homeTeam : match.awayTeam
              const logo = side === 'home' ? match.homeLogo : match.awayLogo
              const form = side === 'home' ? match.homeForm : match.awayForm
              const won =
                isFinished &&
                liveScore &&
                (side === 'home'
                  ? liveScore.homeScore > liveScore.awayScore
                  : liveScore.awayScore > liveScore.homeScore)
              return (
                <div
                  key={side}
                  className="grid grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-2"
                >
                  <TeamLogo name={name} size="xs" badgeUrl={logo} />
                  <span
                    className={cn(
                      'truncate text-sm font-medium leading-tight',
                      forebetPred === (side === 'home' ? '1' : '2') &&
                        (side === 'home'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-rose-600 dark:text-rose-400'),
                      won && 'font-bold',
                    )}
                  >
                    {name}
                  </span>
                  {form && form.length > 0 ? (
                    <FormTimeline
                      form={form}
                      teamName={name}
                      maxItems={3}
                      className="hidden shrink-0 sm:flex"
                    />
                  ) : (
                    <span />
                  )}
                </div>
              )
            })}
          </div>

          {/* Live / final score */}
          {(isLive || isFinished) && liveScore && (
            <div className="flex w-[32px] shrink-0 flex-col items-center gap-1">
              <span className={cn('text-sm font-bold tabular-nums', isLive && 'text-red-600')}>
                {liveScore.homeScore}
              </span>
              <span className={cn('text-sm font-bold tabular-nums', isLive && 'text-red-600')}>
                {liveScore.awayScore}
              </span>
            </div>
          )}
        </div>

        {/* Markets: a single non-wrapping line. Lower-priority chips drop out on
            narrow screens rather than reflowing on top of each other. Exact
            score, over/under, BTTS, 3-way splits and H2H live in the details
            panel. */}
        <div className="flex min-w-0 items-center gap-1.5 overflow-hidden">
          <GradeBadge grade={match.predictionGrade} />

          {match.locked && (
            <Link
              href="/pricing"
              onClick={e => e.stopPropagation()}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0 text-[10px] font-semibold text-amber-700 transition-colors hover:bg-amber-500/20 dark:text-amber-400"
            >
              <Lock className="h-2.5 w-2.5" />
              <span className="hidden sm:inline">Premium — unlock $5/wk</span>
              <span className="sm:hidden">Premium</span>
            </Link>
          )}

          {/* Our engine's pick takes precedence — it is what the emails act on. */}
          {match.scoring?.pick && (
            <PickChip
              pick={match.scoring.pick}
              prob={match.scoring.prob > 0 ? formatPct(match.scoring.prob) : null}
              source="SE"
              tone="engine"
            />
          )}

          {forebetPred && (
            <PickChip
              pick={forebetPred}
              prob={match.forebet?.probability != null ? `${match.forebet.probability}%` : null}
              source="FB"
              tone="forebet"
              className={match.scoring?.pick ? 'hidden md:flex' : undefined}
            />
          )}

          {sofaPred && (
            <PickChip
              pick={sofaPred}
              prob={`${sofaMax}%`}
              source="SS"
              tone="sofascore"
              className={match.scoring?.pick || forebetPred ? 'hidden lg:flex' : undefined}
            />
          )}

          {match.value_bet && (
            <Badge
              variant="secondary"
              className="shrink-0 gap-0.5 border-amber-400/30 px-1 py-0 text-[9px] text-amber-600 dark:text-amber-400"
            >
              <Gem className="h-2.5 w-2.5" />
              <span className="hidden sm:inline">Value</span>
            </Badge>
          )}

          {/* Odds pinned to the end of the markets line on narrow screens. */}
          <OddsBlock match={match} pick={highlightPick} className="ml-auto shrink-0 lg:hidden" />
        </div>
      </div>

      {/* ─── Odds + confidence ─── */}
      <div className="flex shrink-0 items-center gap-2 border-l border-border/30 pl-2 pr-2">
        <OddsBlock match={match} pick={highlightPick} className="hidden lg:flex" />
        {conf > 0 ? <RadialProgress value={conf} size={38} strokeWidth={3} /> : <div className="w-[38px]" />}
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/30 transition-colors group-hover:text-foreground/60" />
      </div>
    </div>
  )
}

// ── Skeleton for loading state ──
export function MatchRowSkeleton() {
  return (
    <div className="flex animate-pulse items-stretch border-b border-border/40">
      <div className="flex w-[52px] shrink-0 items-center justify-center border-r border-border/30 p-2">
        <div className="h-4 w-8 rounded bg-muted" />
      </div>
      <div className="flex-1 space-y-2 px-3 py-2">
        <div className="space-y-1">
          <div className="h-3.5 w-40 rounded bg-muted" />
          <div className="h-3.5 w-36 rounded bg-muted" />
        </div>
        <div className="flex gap-2">
          <div className="h-4 w-12 rounded bg-muted" />
          <div className="h-4 w-10 rounded bg-muted" />
          <div className="h-4 w-8 rounded bg-muted" />
        </div>
      </div>
      <div className="flex items-center border-l border-border/30 pl-2 pr-2">
        <div className="h-[38px] w-[38px] rounded-full bg-muted" />
      </div>
    </div>
  )
}
