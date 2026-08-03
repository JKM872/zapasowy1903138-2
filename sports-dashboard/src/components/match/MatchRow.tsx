// ============================================================================
// MatchRow – bookmaker-style event row with odds in aligned market columns
// ============================================================================
'use client'

import Link from 'next/link'
import { ChevronRight, Gem, Lock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { PREDICTION_LABELS } from '@/lib/constants'
import { formatMatchTime, formatOdds, formatPct } from '@/lib/format'
import { LiveScoreBadge } from './LiveScoreBadge'
import { TeamLogo } from './TeamLogo'
import { GradeBadge } from './GradeBadge'
import { marketLayout } from './marketGrid'
import { RadialProgress } from '@/components/charts/RadialProgress'
import { FormTimeline } from '@/components/charts/FormTimeline'
import type { Match, LiveScore } from '@/lib/types'

interface Props {
  match: Match
  liveScore?: LiveScore | null
  onSelect?: (match: Match) => void
  /** Called when an odds button is used, to add the outcome to the basket. */
  onPick?: (match: Match, outcome: string, odds: number) => void
  /** Outcomes already in the basket for this event, to show them as selected. */
  selectedOutcomes?: readonly string[]
}

/** Odds for one outcome of a match, or null when the market is missing. */
function outcomeOdds(match: Match, outcome: string): number | null {
  if (!match.odds) return null
  if (outcome === '1') return match.odds.home ?? null
  if (outcome === 'X') return match.odds.draw ?? null
  if (outcome === '2') return match.odds.away ?? null
  return null
}

export function MatchRow({
  match,
  liveScore,
  onSelect,
  onPick,
  selectedOutcomes = [],
}: Props) {
  const conf =
    match.gemini?.confidence ??
    match.scoring?.confidence ??
    match.confidence ??
    match.forebet?.probability ??
    0
  const isLive = liveScore?.status === 'live' || liveScore?.status === 'halftime'
  const isFinished = liveScore?.status === 'finished'
  const forebetPred = match.forebet?.prediction

  // SofaScore majority vote
  const sofaH = match.sofascore?.home ?? 0
  const sofaD = match.sofascore?.draw ?? 0
  const sofaA = match.sofascore?.away ?? 0
  const sofaMax = Math.max(sofaH, sofaD, sofaA)
  const sofaPred = sofaMax > 0 ? (sofaMax === sofaH ? '1' : sofaMax === sofaD ? 'X' : '2') : null

  // Our own engine drives the highlight: it is what the emails act on.
  const pick = match.scoring?.pick ?? forebetPred ?? sofaPred ?? null
  const { gridClass, columns } = marketLayout(match.sport)

  return (
    /* The row itself is not a button: it contains odds buttons and a paywall
       link, and nesting interactive elements is invalid. Clicking anywhere opens
       the details for convenience, while the chevron is a real button so the row
       stays reachable by keyboard. */
    <div
      onClick={() => onSelect?.(match)}
      className={cn(
        'group cursor-pointer items-stretch border-b border-border/40 transition-colors last:border-b-0',
        gridClass,
        'hover:bg-panel-hover',
        isLive && 'bg-red-500/5',
      )}
    >
      {/* ─── Time ─── */}
      <div className="flex flex-col items-center justify-center gap-0.5 border-r border-border/30 py-2 text-muted-foreground">
        {isLive ? (
          <LiveScoreBadge liveScore={liveScore} className="px-1 py-0 text-[10px]" />
        ) : isFinished ? (
          <span className="text-[11px] font-medium">KOŃ</span>
        ) : (
          <span className="text-[11px] font-medium tabular-nums">
            {formatMatchTime(match.time)}
          </span>
        )}
      </div>

      {/* ─── Teams, form, model verdict ─── */}
      <div className="flex min-w-0 flex-col justify-center gap-1 px-2 py-2 text-left">
        {(['home', 'away'] as const).map(side => {
          const name = side === 'home' ? match.homeTeam : match.awayTeam
          const logo = side === 'home' ? match.homeLogo : match.awayLogo
          const form = side === 'home' ? match.homeForm : match.awayForm
          const score = side === 'home' ? liveScore?.homeScore : liveScore?.awayScore
          const won =
            isFinished &&
            liveScore &&
            (side === 'home'
              ? liveScore.homeScore > liveScore.awayScore
              : liveScore.awayScore > liveScore.homeScore)
          return (
            <div
              key={side}
              className="grid grid-cols-[18px_minmax(0,1fr)_auto_auto] items-center gap-2"
            >
              <TeamLogo name={name} size="xs" badgeUrl={logo} />
              <span
                className={cn(
                  'truncate text-[13px] leading-tight',
                  pick === (side === 'home' ? '1' : '2')
                    ? 'font-semibold text-foreground'
                    : 'text-foreground/85',
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
              <span
                className={cn(
                  'w-4 text-right text-[13px] font-bold tabular-nums',
                  isLive ? 'text-red-500' : 'text-muted-foreground',
                )}
              >
                {(isLive || isFinished) && score != null ? score : ''}
              </span>
            </div>
          )
        })}

        {/* Model verdict line: grade, pick, probability, paywall notice. Detailed
            breakdowns live in the match dialog, not here. */}
        <div className="flex min-w-0 items-center gap-1.5 overflow-hidden pt-0.5">
          <GradeBadge grade={match.predictionGrade} />

          {pick && (
            <span className="shrink-0 text-[11px] text-muted-foreground">
              Typ:{' '}
              <span className="font-semibold text-foreground">
                {PREDICTION_LABELS[pick] ?? pick}
              </span>
            </span>
          )}

          {match.scoring?.prob != null && match.scoring.prob > 0 && (
            <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
              {formatPct(match.scoring.prob)}
            </span>
          )}

          {match.value_bet && (
            <Badge
              variant="secondary"
              className="shrink-0 gap-0.5 border-amber-400/30 px-1 py-0 text-[9px] text-amber-400"
            >
              <Gem className="h-2.5 w-2.5" />
              <span className="hidden sm:inline">Wartość</span>
            </Badge>
          )}

          {match.locked && (
            <Link
              href="/pricing"
              onClick={e => e.stopPropagation()}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0 text-[10px] font-semibold text-amber-400 transition-colors hover:bg-amber-500/20"
            >
              <Lock className="h-2.5 w-2.5" />
              Premium
            </Link>
          )}
        </div>

        {/* Odds below the teams on narrow screens, where the market columns of
            the desktop grid are not rendered. */}
        <div className="mt-1 flex items-center gap-1 lg:hidden">
          {columns.map(outcome => (
            <OddsButton
              key={outcome}
              match={match}
              outcome={outcome}
              odds={outcomeOdds(match, outcome)}
              isPick={pick === outcome}
              isSelected={selectedOutcomes.includes(outcome)}
              onPick={onPick}
              compact
            />
          ))}
        </div>
      </div>

      {/* ─── Market columns (desktop) ─── */}
      {columns.map(outcome => (
        <div key={outcome} className="hidden items-center justify-center p-1 lg:flex">
          <OddsButton
            match={match}
            outcome={outcome}
            odds={outcomeOdds(match, outcome)}
            isPick={pick === outcome}
            isSelected={selectedOutcomes.includes(outcome)}
            onPick={onPick}
          />
        </div>
      ))}

      {/* ─── Confidence + the row's keyboard-accessible trigger ─── */}
      <div className="hidden items-center justify-end gap-0.5 border-l border-border/30 pr-1 lg:flex">
        {conf > 0 ? <RadialProgress value={conf} size={30} strokeWidth={3} /> : <span className="w-[30px]" />}
        <button
          type="button"
          onClick={e => { e.stopPropagation(); onSelect?.(match) }}
          aria-label={`Szczegóły: ${match.homeTeam} - ${match.awayTeam}`}
          className="rounded p-0.5 text-muted-foreground/30 transition-colors group-hover:text-foreground/60 hover:bg-accent"
        >
          <ChevronRight className="h-4 w-4 shrink-0" />
        </button>
      </div>
    </div>
  )
}

/**
 * One market cell. Sized like a bookmaker's odds button so the eye can scan a
 * whole column, and disabled when the market is missing rather than hidden, so
 * the columns never shift.
 */
function OddsButton({
  match,
  outcome,
  odds,
  isPick,
  isSelected,
  onPick,
  compact = false,
}: {
  match: Match
  outcome: string
  odds: number | null
  isPick: boolean
  isSelected: boolean
  onPick?: (match: Match, outcome: string, odds: number) => void
  compact?: boolean
}) {
  const label = PREDICTION_LABELS[outcome] ?? outcome
  const disabled = odds == null || !onPick

  return (
    <button
      type="button"
      disabled={odds == null}
      aria-label={`${label}: ${odds != null ? formatOdds(odds) : 'brak kursu'}`}
      aria-pressed={isSelected}
      onClick={e => {
        e.stopPropagation()
        if (odds != null) onPick?.(match, outcome, odds)
      }}
      className={cn(
        'flex flex-col items-center justify-center rounded border font-mono tabular-nums transition-colors',
        compact ? 'h-7 min-w-[46px] px-1 text-[11px]' : 'h-9 w-full text-xs',
        odds == null
          ? 'cursor-default border-transparent bg-transparent text-muted-foreground/40'
          : isSelected
            ? 'border-primary bg-primary text-primary-foreground font-bold'
            : cn(
                'border-odds-border bg-odds text-foreground hover:bg-odds-hover',
                isPick && 'border-primary/60 text-primary',
              ),
        disabled && odds != null && 'cursor-default',
      )}
    >
      <span className="text-[8px] font-sans uppercase leading-none opacity-60 lg:hidden">
        {outcome}
      </span>
      <span className="leading-none">{odds != null ? formatOdds(odds) : '—'}</span>
    </button>
  )
}

// ── Skeleton for loading state ──
export function MatchRowSkeleton() {
  return (
    <div className="flex animate-pulse items-stretch border-b border-border/40">
      <div className="flex w-[46px] shrink-0 items-center justify-center border-r border-border/30 p-2">
        <div className="h-3 w-7 rounded bg-muted" />
      </div>
      <div className="flex-1 space-y-2 px-2 py-2">
        <div className="h-3 w-44 rounded bg-muted" />
        <div className="h-3 w-36 rounded bg-muted" />
        <div className="h-3 w-24 rounded bg-muted" />
      </div>
      <div className="hidden items-center gap-1 p-1 lg:flex">
        <div className="h-9 w-[54px] rounded bg-muted" />
        <div className="h-9 w-[54px] rounded bg-muted" />
        <div className="h-9 w-[54px] rounded bg-muted" />
      </div>
    </div>
  )
}
